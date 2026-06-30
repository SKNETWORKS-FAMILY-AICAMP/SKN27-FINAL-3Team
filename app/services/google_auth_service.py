"""Google login boundary and app JWT helpers for the Django auth MVP."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.auth_error_contract import build_auth_error

APP_JWT_ALGORITHM = "HS256"
APP_JWT_ISSUER = "skn27-demo-auth"
APP_JWT_AUDIENCE = "skn27-demo-api"
APP_JWT_TTL_SECONDS = 60 * 60
GOOGLE_AUTH_CONTRACT_VERSION = "google_auth.v1"


def create_google_login(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Create an app auth session from a Google identity payload."""

    provider = _text(payload.get("provider") or "google")
    if provider != "google":
        return 401, build_auth_error("token_invalid", reason="unsupported_auth_provider")

    google_profile = _google_profile_from_payload(payload)
    if google_profile is None:
        return 401, build_auth_error("token_invalid", reason="google_identity_missing")

    user_id = _user_id_for_google_subject(google_profile["sub"])
    auth_session_id = _auth_session_id_for_google_subject(
        google_profile["sub"],
        payload.get("session_id"),
    )
    issued_at = _now()
    expires_at = issued_at + timedelta(seconds=APP_JWT_TTL_SECONDS)
    token, claims = issue_access_token(
        user_id=user_id,
        auth_session_id=auth_session_id,
        email=google_profile.get("email", ""),
        display_name=google_profile.get("display_name", ""),
        provider_subject=google_profile["sub"],
        issued_at=issued_at,
        expires_at=expires_at,
    )
    guest_id = _normalize_guest_id(payload.get("guest_id"))
    session_id = _text(payload.get("session_id")) or None

    return 200, {
        "contract_version": GOOGLE_AUTH_CONTRACT_VERSION,
        "auth_state": "authenticated",
        "provider": "google",
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": APP_JWT_TTL_SECONDS,
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "user": {
            "user_id": user_id,
            "email": google_profile.get("email"),
            "display_name": google_profile.get("display_name"),
            "picture": google_profile.get("picture"),
            "status": "active",
            "auth_provider": "google",
            "provider_subject": google_profile["sub"],
            "policy_status": google_profile["verification"],
        },
        "guest": _guest_snapshot(guest_id),
        "subject": {
            "subject_id": f"user:{user_id}",
            "subject_type": "user",
            "user_id": user_id,
            "guest_id": guest_id,
            "auth_session_id": auth_session_id,
            "is_authenticated": True,
        },
        "auth_session": {
            "auth_session_id": auth_session_id,
            "jwt_jti": auth_session_id,
            "status": "active",
            "verification": google_profile["verification"],
            "provider": "google",
            "id_token_audience": google_profile.get("aud"),
            "app_jwt_claims": {
                "iss": claims["iss"],
                "aud": claims["aud"],
                "sub": claims["sub"],
                "jti": claims["jti"],
                "exp": claims["exp"],
            },
        },
        "session_binding": {
            "session_id": session_id,
            "can_bind_to_chat_session": bool(session_id),
            "binding_policy": "Google login may bind future chat sessions to the user account; guest merge remains user-confirmed.",
        },
        "rate_limit": _rate_limit_policy(subject_id=f"user:{user_id}"),
        "merge_policy": _merge_policy(),
        "limitations": [
            "Local Google login accepts mock Google profile fields while GOOGLE_AUTH_ALLOW_MOCK=1.",
            "Set GOOGLE_AUTH_ALLOW_MOCK=0 and install google-auth to require real Google ID token verification.",
        ],
    }


def issue_access_token(
    *,
    user_id: str,
    auth_session_id: str,
    email: str = "",
    display_name: str = "",
    provider_subject: str = "",
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    issued_at = issued_at or _now()
    expires_at = expires_at or (issued_at + timedelta(seconds=APP_JWT_TTL_SECONDS))
    claims = {
        "iss": APP_JWT_ISSUER,
        "aud": APP_JWT_AUDIENCE,
        "sub": user_id,
        "jti": auth_session_id,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "auth_provider": "google",
        "provider_subject": provider_subject,
        "email": email,
        "name": display_name,
    }
    header = {"alg": APP_JWT_ALGORITHM, "typ": "JWT"}
    signing_input = f"{_b64_json(header)}.{_b64_json(claims)}"
    signature = _b64_bytes(
        hmac.new(_jwt_secret().encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    )
    return f"{signing_input}.{signature}", claims


def decode_access_token(token: str) -> tuple[bool, dict[str, Any]]:
    parts = token.split(".")
    if len(parts) != 3:
        return False, {"reason": "not_app_jwt"}

    signing_input = f"{parts[0]}.{parts[1]}"
    expected_signature = _b64_bytes(
        hmac.new(_jwt_secret().encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(parts[2], expected_signature):
        return False, {"reason": "invalid_signature"}

    try:
        claims = json.loads(_b64_decode(parts[1]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False, {"reason": "invalid_claims"}

    if claims.get("iss") != APP_JWT_ISSUER or claims.get("aud") != APP_JWT_AUDIENCE:
        return False, {"reason": "invalid_issuer_or_audience"}
    try:
        expires_at = int(claims.get("exp") or 0)
    except (TypeError, ValueError):
        return False, {"reason": "invalid_exp"}
    if expires_at <= int(_now().timestamp()):
        return False, {"reason": "expired_token"}
    if not _text(claims.get("sub")) or not _text(claims.get("jti")):
        return False, {"reason": "missing_required_claim"}
    return True, claims


def _google_profile_from_payload(payload: dict[str, Any]) -> dict[str, str] | None:
    id_token = _text(payload.get("id_token") or payload.get("credential") or payload.get("google_id_token"))
    allow_mock = _google_auth_allow_mock()
    if allow_mock:
        profile = _mock_google_profile(payload, id_token)
        if profile is not None:
            return profile
    if not id_token:
        return None
    return _verified_google_profile(id_token)


def _mock_google_profile(payload: dict[str, Any], id_token: str) -> dict[str, str] | None:
    token_claims = _unverified_jwt_claims(id_token)
    google_sub = _text(
        payload.get("google_sub")
        or payload.get("sub")
        or token_claims.get("sub")
    )
    email = _text(payload.get("email") or token_claims.get("email"))
    display_name = _text(payload.get("display_name") or payload.get("name") or token_claims.get("name"))
    picture = _text(payload.get("picture") or token_claims.get("picture"))
    aud = _text(token_claims.get("aud"))
    if not google_sub and id_token.startswith("mock_google:"):
        google_sub = id_token.split(":", 1)[1]
    if not google_sub and email:
        google_sub = f"email:{email.lower()}"
    if not google_sub:
        return None
    return {
        "sub": google_sub,
        "email": email or f"{_digest(google_sub, length=8)}@example.local",
        "display_name": display_name or "Google user",
        "picture": picture,
        "aud": aud,
        "verification": "mock_google_subject",
    }


def _verified_google_profile(id_token: str) -> dict[str, str] | None:
    client_id = _text(_django_setting("GOOGLE_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_ID"))
    if not client_id:
        return None
    try:
        from google.auth.transport import requests as google_requests  # type: ignore
        from google.oauth2 import id_token as google_id_token  # type: ignore
    except ImportError:
        return None

    try:
        idinfo = google_id_token.verify_oauth2_token(
            id_token,
            google_requests.Request(),
            client_id,
        )
    except ValueError:
        return None

    google_sub = _text(idinfo.get("sub"))
    if not google_sub:
        return None
    return {
        "sub": google_sub,
        "email": _text(idinfo.get("email")),
        "display_name": _text(idinfo.get("name")),
        "picture": _text(idinfo.get("picture")),
        "aud": _text(idinfo.get("aud")),
        "verification": "google_id_token_verified",
    }


def _unverified_jwt_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        return json.loads(_b64_decode(parts[1]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _b64_json(value: dict[str, Any]) -> str:
    return _b64_bytes(json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _b64_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _jwt_secret() -> str:
    return (
        _text(_django_setting("APP_JWT_SECRET"))
        or os.environ.get("APP_JWT_SECRET")
        or os.environ.get("DJANGO_SECRET_KEY")
        or _text(_django_setting("SECRET_KEY"))
        or "dev-only-change-before-deploy"
    )


def _google_auth_allow_mock() -> bool:
    configured_value = _django_setting("GOOGLE_AUTH_ALLOW_MOCK", None)
    if configured_value is not None:
        return bool(configured_value)
    return os.environ.get("GOOGLE_AUTH_ALLOW_MOCK", "1") != "0"


def _django_setting(name: str, default: Any = "") -> Any:
    try:
        from django.conf import settings
    except Exception:
        return default
    if not settings.configured:
        return default
    return getattr(settings, name, default)


def _user_id_for_google_subject(google_sub: str) -> str:
    return f"usr_google_{_digest(google_sub)}"


def _auth_session_id_for_google_subject(google_sub: str, session_id: Any) -> str:
    return f"auth_google_{_digest(f'{google_sub}:{_text(session_id)}')}"


def _digest(value: str, *, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _guest_snapshot(guest_id: str | None) -> dict[str, Any] | None:
    if not guest_id:
        return None
    return {
        "guest_id": guest_id,
        "status": "active",
        "policy_status": "review_required",
    }


def _rate_limit_policy(*, subject_id: str) -> dict[str, Any]:
    return {
        "subject_id": subject_id,
        "policy_status": "review_required",
        "keys": [
            f"rate_limit:{subject_id}:chat_message",
            f"rate_limit:{subject_id}:agent_run",
            f"rate_limit:{subject_id}:report_action",
        ],
    }


def _merge_policy() -> dict[str, Any]:
    return {
        "guest_to_user_merge": "user_confirmation_required",
        "auto_merge": False,
        "reason": "Traffic dispute consultations may contain sensitive case details.",
    }


def _normalize_guest_id(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    return text if text.startswith("gst_") else f"gst_{text}"


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _now() -> datetime:
    return datetime.now(timezone.utc)
