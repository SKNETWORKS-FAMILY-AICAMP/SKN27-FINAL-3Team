"""Google login boundary and app JWT helpers for the Django auth MVP."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from app.services.auth_error_contract import build_auth_error

APP_JWT_ALGORITHM = "HS256"
APP_JWT_ISSUER = "skn27-demo-auth"
APP_JWT_AUDIENCE = "skn27-demo-api"
APP_JWT_TTL_SECONDS = 60 * 60
GOOGLE_AUTH_CONTRACT_VERSION = "google_auth.v1"
GOOGLE_AUTH_CODE_CONTRACT_VERSION = "google_auth_code.v1"
AUTH_TOKEN_REFRESH_CONTRACT_VERSION = "auth_token_refresh.v1"
AUTH_LOGOUT_CONTRACT_VERSION = "auth_logout.v1"
GOOGLE_DEFAULT_LOGIN_SCOPE = "openid email profile"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


def create_google_login(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Create an app auth session from a Google identity payload."""

    provider = _text(payload.get("provider") or "google")
    if provider != "google":
        return 401, build_auth_error("token_invalid", reason="unsupported_auth_provider")

    google_profile = _google_profile_from_payload(payload)
    if google_profile is None:
        return 401, build_auth_error("token_invalid", reason="google_identity_missing")

    allow_mock = _google_auth_allow_mock()

    return 200, _build_google_auth_payload(
        payload=payload,
        google_profile=google_profile,
        contract_version=GOOGLE_AUTH_CONTRACT_VERSION,
        auth_mode="mock_allowed" if allow_mock else "google_id_token_required",
        google={
            "connected": False,
            "purpose": "LOGIN",
            "granted_scopes": [],
            "connection_policy": "legacy_id_token_login_only",
        },
        limitations=_google_login_limitations(google_profile["verification"], allow_mock=allow_mock),
    )


def create_google_code_login(
    payload: dict[str, Any],
    *,
    request_headers: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Create an app auth session from a Google authorization code."""

    provider = _text(payload.get("provider") or "google")
    if provider != "google":
        return 401, build_auth_error("token_invalid", reason="unsupported_auth_provider")

    requested_with = _header_value(request_headers, "X-Requested-With")
    if requested_with != "XmlHttpRequest":
        return 403, build_auth_error("forbidden", reason="invalid_google_code_request_header")

    code = _text(payload.get("code"))
    if not code:
        return 401, build_auth_error("token_invalid", reason="authorization_code_missing")

    token_status, token_payload = _google_token_response_from_code(payload, code)
    if token_status >= 400:
        return token_status, token_payload

    google_profile = _google_profile_from_code_tokens(token_payload, payload)
    if google_profile is None:
        return 401, build_auth_error("token_invalid", reason="google_code_identity_missing")

    issued_at = _now()
    expires_at = _google_token_expires_at(token_payload, issued_at=issued_at)
    granted_scopes = _scope_list(token_payload.get("scope") or payload.get("scope") or GOOGLE_DEFAULT_LOGIN_SCOPE)
    purpose = _text(payload.get("purpose")) or "LOGIN"

    private_oauth_tokens = {
        "provider": "google",
        "access_token": _text(token_payload.get("access_token")),
        "refresh_token": _text(token_payload.get("refresh_token")),
        "token_type": _text(token_payload.get("token_type")) or "Bearer",
        "expires_at": expires_at.isoformat() if expires_at else None,
        "granted_scopes": granted_scopes,
        "purpose": purpose,
    }

    response = _build_google_auth_payload(
        payload=payload,
        google_profile=google_profile,
        contract_version=GOOGLE_AUTH_CODE_CONTRACT_VERSION,
        auth_mode="authorization_code_mock" if token_payload.get("mock") else "authorization_code",
        google={
            "connected": True,
            "purpose": purpose,
            "granted_scopes": granted_scopes,
            "has_refresh_token": bool(private_oauth_tokens["refresh_token"]),
            "token_expires_at": private_oauth_tokens["expires_at"],
            "connection_policy": "backend_token_exchange",
            "social_account": {
                "provider": "google",
                "provider_user_id": google_profile["sub"],
                "email": google_profile.get("email"),
                "email_verified": bool(google_profile.get("email_verified")),
            },
            "oauth_connection": {
                "provider": "google",
                "granted_scopes": granted_scopes,
                "expires_at": private_oauth_tokens["expires_at"],
                "revoked_at": None,
                "token_storage": "backend_only",
            },
        },
        limitations=[
            "Frontend receives only the authorization code and this app JWT; Google access and refresh tokens stay on the backend.",
            "Feature-specific Google API scopes must be requested only when the user starts that feature.",
        ],
    )
    response["_private_oauth_tokens"] = private_oauth_tokens
    return 200, response


def _build_google_auth_payload(
    *,
    payload: dict[str, Any],
    google_profile: dict[str, Any],
    contract_version: str,
    auth_mode: str,
    google: dict[str, Any],
    limitations: list[str],
) -> dict[str, Any]:
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
        email=_text(google_profile.get("email")),
        display_name=_text(google_profile.get("display_name")),
        provider_subject=google_profile["sub"],
        issued_at=issued_at,
        expires_at=expires_at,
    )
    guest_id = _normalize_guest_id(payload.get("guest_id"))
    session_id = _text(payload.get("session_id")) or None

    return {
        "contract_version": contract_version,
        "auth_state": "authenticated",
        "provider": "google",
        "auth_mode": auth_mode,
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
        "google": google,
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
        "limitations": limitations,
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
    extra_claims: dict[str, Any] | None = None,
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
    if extra_claims:
        claims.update(extra_claims)
    header = {"alg": APP_JWT_ALGORITHM, "typ": "JWT"}
    signing_input = f"{_b64_json(header)}.{_b64_json(claims)}"
    signature = _b64_bytes(
        hmac.new(_jwt_secret().encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    )
    return f"{signing_input}.{signature}", claims


def create_token_refresh(
    *,
    authorization_header: str | None,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Refresh a valid app JWT into a new app JWT for the same auth session."""

    header_value = _text(authorization_header)
    token = _bearer_token_from_header(authorization_header)
    if header_value and not token:
        return 401, build_auth_error("token_invalid", reason="malformed_authorization_header")
    token = token or _text((payload or {}).get("access_token"))
    if not token:
        return 401, build_auth_error("auth_required")

    valid, claims = decode_access_token(token)
    if not valid:
        return _auth_error_from_decode_reason(claims)

    issued_at = _now()
    expires_at = issued_at + timedelta(seconds=APP_JWT_TTL_SECONDS)
    refreshed_token, refreshed_claims = issue_access_token(
        user_id=_text(claims.get("sub")),
        auth_session_id=_text(claims.get("jti")),
        email=_text(claims.get("email")),
        display_name=_text(claims.get("name")),
        provider_subject=_text(claims.get("provider_subject")),
        issued_at=issued_at,
        expires_at=expires_at,
        extra_claims={
            "refresh_nonce": _digest(f"{token}:{issued_at.isoformat()}", length=12),
        },
    )
    guest_id = _normalize_guest_id((payload or {}).get("guest_id"))
    session_id = _text((payload or {}).get("session_id")) or None

    return 200, {
        "contract_version": AUTH_TOKEN_REFRESH_CONTRACT_VERSION,
        "auth_state": "authenticated",
        "provider": _text(claims.get("auth_provider")) or "google",
        "access_token": refreshed_token,
        "token_type": "Bearer",
        "expires_in": APP_JWT_TTL_SECONDS,
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "user": {
            "user_id": _text(claims.get("sub")),
            "email": _text(claims.get("email")),
            "display_name": _text(claims.get("name")) or "Google user",
            "status": "active",
            "auth_provider": _text(claims.get("auth_provider")) or "google",
            "provider_subject": _text(claims.get("provider_subject")),
            "policy_status": "app_jwt_refreshed",
        },
        "guest": _guest_snapshot(guest_id),
        "subject": {
            "subject_id": f"user:{_text(claims.get('sub'))}",
            "subject_type": "user",
            "user_id": _text(claims.get("sub")),
            "guest_id": guest_id,
            "auth_session_id": _text(claims.get("jti")),
            "is_authenticated": True,
        },
        "auth_session": {
            "auth_session_id": _text(claims.get("jti")),
            "jwt_jti": _text(claims.get("jti")),
            "status": "active",
            "verification": "app_jwt_hmac",
            "provider": _text(claims.get("auth_provider")) or "google",
            "refresh_policy": "valid_app_jwt_required",
            "app_jwt_claims": {
                "iss": refreshed_claims["iss"],
                "aud": refreshed_claims["aud"],
                "sub": refreshed_claims["sub"],
                "jti": refreshed_claims["jti"],
                "exp": refreshed_claims["exp"],
            },
        },
        "session_binding": {
            "session_id": session_id,
            "can_bind_to_chat_session": bool(session_id),
        },
        "rate_limit": _rate_limit_policy(subject_id=f"user:{_text(claims.get('sub'))}"),
        "merge_policy": _merge_policy(),
        "limitations": [
            "MVP refresh requires a valid app JWT; separate refresh tokens and silent expired-token refresh are not enabled.",
        ],
    }


def create_logout(
    *,
    authorization_header: str | None,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Build a logout contract from a valid app JWT."""

    header_value = _text(authorization_header)
    token = _bearer_token_from_header(authorization_header)
    if header_value and not token:
        return 401, build_auth_error("token_invalid", reason="malformed_authorization_header")
    token = token or _text((payload or {}).get("access_token"))
    if not token:
        return 401, build_auth_error("auth_required")

    valid, claims = decode_access_token(token)
    if not valid:
        return _auth_error_from_decode_reason(claims)

    revoked_at = _now()
    guest_id = _normalize_guest_id((payload or {}).get("guest_id"))
    session_id = _text((payload or {}).get("session_id")) or None
    user_id = _text(claims.get("sub"))
    auth_session_id = _text(claims.get("jti"))

    return 200, {
        "contract_version": AUTH_LOGOUT_CONTRACT_VERSION,
        "auth_state": "anonymous",
        "provider": _text(claims.get("auth_provider")) or "google",
        "revoked_at": revoked_at.isoformat(),
        "user": {
            "user_id": user_id,
            "email": _text(claims.get("email")),
            "display_name": _text(claims.get("name")) or "Google user",
            "auth_provider": _text(claims.get("auth_provider")) or "google",
            "provider_subject": _text(claims.get("provider_subject")),
        },
        "guest": _guest_snapshot(guest_id),
        "subject": {
            "subject_id": f"user:{user_id}",
            "subject_type": "user",
            "user_id": user_id,
            "guest_id": guest_id,
            "auth_session_id": auth_session_id,
            "is_authenticated": False,
        },
        "auth_session": {
            "auth_session_id": auth_session_id,
            "jwt_jti": auth_session_id,
            "status": "revoked",
            "verification": "app_jwt_hmac",
            "provider": _text(claims.get("auth_provider")) or "google",
        },
        "session_binding": {
            "session_id": session_id,
            "can_bind_to_chat_session": bool(session_id),
        },
        "client_action": {
            "clear_access_token": True,
            "clear_google_profile": True,
            "next_auth_state": "guest" if guest_id else "anonymous",
        },
        "limitations": [
            "Stateless JWTs cannot be invalidated client-side after issuance; backend marks auth_session revoked and clients must clear the token.",
        ],
    }


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


def _bearer_token_from_header(header_value: str | None) -> str:
    value = _text(header_value)
    if not value:
        return ""
    parts = value.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()


def _auth_error_from_decode_reason(decoded: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    reason = _text(decoded.get("reason")) or "invalid_app_jwt"
    if reason == "expired_token":
        body = build_auth_error("token_expired")
        return int(body["error"]["status"]), body
    if reason == "not_app_jwt":
        body = build_auth_error("token_invalid", reason="app_jwt_required")
        return int(body["error"]["status"]), body
    body = build_auth_error("token_invalid", reason=reason)
    return int(body["error"]["status"]), body


def _google_token_response_from_code(payload: dict[str, Any], code: str) -> tuple[int, dict[str, Any]]:
    if _google_auth_allow_mock() and code.startswith("mock_google_code:"):
        return 200, _mock_google_code_token_response(payload, code)

    client_id = _text(_django_setting("GOOGLE_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_ID"))
    client_secret = _text(_django_setting("GOOGLE_CLIENT_SECRET") or os.environ.get("GOOGLE_CLIENT_SECRET"))
    redirect_uri = _google_redirect_uri(payload)
    if not client_id:
        return 401, build_auth_error("token_invalid", reason="google_client_id_missing")
    if not client_secret:
        return 401, build_auth_error("token_invalid", reason="google_client_secret_missing")
    if not redirect_uri:
        return 401, build_auth_error("token_invalid", reason="google_redirect_uri_missing")

    form = urllib_parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = urllib_request.Request(
        _google_token_endpoint(),
        data=form,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
    except urllib_error.HTTPError as error:
        return 401, build_auth_error(
            "token_invalid",
            reason=f"google_token_exchange_failed:{error.code}",
        )
    except (urllib_error.URLError, TimeoutError):
        return 401, build_auth_error("token_invalid", reason="google_token_exchange_unavailable")

    try:
        token_payload = json.loads(body)
    except ValueError:
        return 401, build_auth_error("token_invalid", reason="google_token_response_invalid")

    if not _text(token_payload.get("access_token")):
        return 401, build_auth_error("token_invalid", reason="google_access_token_missing")
    return 200, token_payload


def _mock_google_code_token_response(payload: dict[str, Any], code: str) -> dict[str, Any]:
    suffix = _text(code.split(":", 1)[1]) or _text(payload.get("guest_id")) or "guest"
    google_sub = _text(payload.get("google_sub") or payload.get("sub") or f"mock-code-{suffix}")
    email = _text(payload.get("email")) or f"driver.{_digest(google_sub, length=8)}@example.com"
    display_name = _text(payload.get("display_name") or payload.get("name")) or "Google Demo User"
    granted_scope = _text(payload.get("scope")) or GOOGLE_DEFAULT_LOGIN_SCOPE
    return {
        "mock": True,
        "access_token": f"mock_google_access_{_digest(google_sub)}",
        "refresh_token": f"mock_google_refresh_{_digest(google_sub, length=24)}",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": granted_scope,
        "profile": {
            "sub": google_sub,
            "email": email,
            "email_verified": True,
            "display_name": display_name,
            "picture": _text(payload.get("picture")),
            "aud": _text(payload.get("aud")),
            "verification": "mock_google_authorization_code",
        },
    }


def _google_profile_from_code_tokens(
    token_payload: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    profile = token_payload.get("profile")
    if isinstance(profile, dict) and _text(profile.get("sub")):
        return {
            "sub": _text(profile.get("sub")),
            "email": _text(profile.get("email")),
            "email_verified": bool(profile.get("email_verified")),
            "display_name": _text(profile.get("display_name") or profile.get("name")) or "Google user",
            "picture": _text(profile.get("picture")),
            "aud": _text(profile.get("aud")),
            "verification": _text(profile.get("verification")) or "mock_google_authorization_code",
        }

    id_token = _text(token_payload.get("id_token"))
    if id_token:
        verified = _verified_google_profile(id_token)
        if verified is not None:
            verified["email_verified"] = True
            return verified

    access_token = _text(token_payload.get("access_token"))
    if access_token:
        userinfo = _fetch_google_userinfo(access_token)
        if userinfo is not None:
            return userinfo

    if _google_auth_allow_mock():
        return _mock_google_profile(payload, id_token)
    return None


def _fetch_google_userinfo(access_token: str) -> dict[str, Any] | None:
    request = urllib_request.Request(
        _google_userinfo_endpoint(),
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
    except (urllib_error.HTTPError, urllib_error.URLError, TimeoutError):
        return None
    try:
        userinfo = json.loads(body)
    except ValueError:
        return None
    google_sub = _text(userinfo.get("sub"))
    if not google_sub:
        return None
    return {
        "sub": google_sub,
        "email": _text(userinfo.get("email")),
        "email_verified": bool(userinfo.get("email_verified")),
        "display_name": _text(userinfo.get("name")) or "Google user",
        "picture": _text(userinfo.get("picture")),
        "aud": "",
        "verification": "google_userinfo_verified",
    }


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


def _google_redirect_uri(payload: dict[str, Any]) -> str:
    return (
        _text(payload.get("redirect_uri"))
        or _text(_django_setting("GOOGLE_POPUP_REDIRECT_URI"))
        or os.environ.get("GOOGLE_POPUP_REDIRECT_URI", "")
    )


def _google_token_endpoint() -> str:
    return (
        _text(_django_setting("GOOGLE_TOKEN_ENDPOINT"))
        or os.environ.get("GOOGLE_TOKEN_ENDPOINT")
        or GOOGLE_TOKEN_ENDPOINT
    )


def _google_userinfo_endpoint() -> str:
    return (
        _text(_django_setting("GOOGLE_USERINFO_ENDPOINT"))
        or os.environ.get("GOOGLE_USERINFO_ENDPOINT")
        or GOOGLE_USERINFO_ENDPOINT
    )


def _google_token_expires_at(
    token_payload: dict[str, Any],
    *,
    issued_at: datetime,
) -> datetime | None:
    try:
        expires_in = int(token_payload.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 0
    if expires_in <= 0:
        return None
    return issued_at + timedelta(seconds=expires_in)


def _scope_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    return [item for item in _text(value).split() if item]


def _header_value(headers: dict[str, Any] | None, name: str) -> str:
    if not headers:
        return ""
    direct = headers.get(name)
    if direct is not None:
        return _text(direct)
    lower_name = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lower_name:
            return _text(value)
    return ""


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


def _google_login_limitations(verification: str, *, allow_mock: bool) -> list[str]:
    if verification == "google_id_token_verified":
        return [
            "Google ID token was verified at the login boundary; the app JWT is issued by this backend.",
        ]
    if allow_mock:
        return [
            "Local Google login accepts mock Google profile fields while GOOGLE_AUTH_ALLOW_MOCK=1.",
            "Set GOOGLE_AUTH_ALLOW_MOCK=0 and GOOGLE_CLIENT_ID to require real Google ID token verification.",
        ]
    return [
        "Google ID token verification is required, but the provided credential could not be verified.",
    ]


def _normalize_guest_id(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    return text if text.startswith("gst_") else f"gst_{text}"


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _now() -> datetime:
    return datetime.now(timezone.utc)
