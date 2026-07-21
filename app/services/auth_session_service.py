"""Guest and signed app-JWT identity helpers for the canonical auth boundary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.services.auth_error_contract import build_auth_error
from app.services.guest_credential_service import (
    decode_guest_credential,
    issue_guest_credential,
)
from app.services.google_auth_service import decode_access_token


GUEST_TTL_SECONDS = 7 * 24 * 60 * 60


def create_guest_session(
    payload: dict[str, Any] | None = None,
    *,
    guest_credential: str | None = None,
) -> dict[str, Any]:
    """Create or refresh a guest identity without binding it to a login."""

    payload = payload or {}
    now = _now()
    credential_valid, credential_claims = decode_guest_credential(guest_credential)
    guest_id = (
        _normalize_guest_id(credential_claims.get("sub"))
        if credential_valid
        else None
    ) or f"gst_{uuid4().hex}"
    session_id = _text(payload.get("session_id")) if credential_valid else ""
    session_id = session_id or None
    issued_at = now.isoformat()
    expires_at = (now + timedelta(seconds=GUEST_TTL_SECONDS)).isoformat()

    issued_credential, _credential_claims = issue_guest_credential(guest_id)
    return {
        "auth_state": "guest",
        "guest": {
            "guest_id": guest_id,
            "status": "active",
            "issued_at": issued_at,
            "expires_at": expires_at,
            "ttl_seconds": GUEST_TTL_SECONDS,
            "policy_status": "review_required",
        },
        "subject": {
            "subject_id": f"guest:{guest_id}",
            "subject_type": "guest",
            "user_id": None,
            "guest_id": guest_id,
            "auth_session_id": None,
            "is_authenticated": False,
        },
        "session_binding": {
            "session_id": session_id,
            "can_bind_to_chat_session": bool(session_id),
            "binding_policy": (
                "guest_id may start chat sessions, but account merge requires "
                "explicit user confirmation."
            ),
        },
        "rate_limit": _rate_limit_policy(subject_id=f"guest:{guest_id}"),
        "merge_policy": _merge_policy(),
        "guest_credential": issued_credential,
        "limitations": [
            "The canonical Django endpoint persists this guest identity.",
            "Guest TTL and quota values remain deployment policy inputs.",
        ],
    }


def get_current_auth_subject(
    *,
    authorization_header: str | None,
    guest_id: str | None = None,
    guest_credential: str | None = None,
    session_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Return the current guest or signature-verified app-JWT subject."""

    normalized_guest_id = _normalize_guest_id(guest_id)
    credential_valid, credential_claims = decode_guest_credential(guest_credential)
    credential_guest_id = (
        _normalize_guest_id(credential_claims.get("sub"))
        if credential_valid
        else None
    )

    if authorization_header:
        token = _bearer_token_from_header(authorization_header)
        if not token:
            return 401, build_auth_error(
                "token_invalid",
                reason="malformed_authorization_header",
            )
        app_jwt_valid, app_jwt_claims = decode_access_token(token)
        if not app_jwt_valid:
            reason = str(app_jwt_claims.get("reason") or "invalid_app_jwt")
            if reason == "expired_token":
                return 401, build_auth_error("token_expired")
            if reason == "not_app_jwt":
                reason = "app_jwt_required"
            return 401, build_auth_error("token_invalid", reason=reason)

        user_id = str(app_jwt_claims["sub"])
        auth_session_id = str(app_jwt_claims["jti"])
        return 200, {
            "auth_state": "authenticated",
            "user": {
                "user_id": user_id,
                "email": app_jwt_claims.get("email"),
                "display_name": app_jwt_claims.get("name") or "Google user",
                "status": "active",
                "auth_provider": app_jwt_claims.get("auth_provider") or "google",
                "provider_subject": app_jwt_claims.get("provider_subject"),
                "policy_status": "app_jwt_verified",
            },
            "guest": _guest_snapshot(credential_guest_id),
            "subject": {
                "subject_id": f"user:{user_id}",
                "subject_type": "user",
                "user_id": user_id,
                "guest_id": credential_guest_id,
                "auth_session_id": auth_session_id,
                "is_authenticated": True,
            },
            "auth_session": {
                "auth_session_id": auth_session_id,
                "jwt_jti": auth_session_id,
                "status": "active",
                "verification": "app_jwt_hmac",
                "provider": app_jwt_claims.get("auth_provider") or "google",
            },
            "session_binding": {
                "session_id": _text(session_id) or None,
                "can_bind_to_chat_session": bool(session_id),
            },
            "rate_limit": _rate_limit_policy(subject_id=f"user:{user_id}"),
            "merge_policy": _merge_policy(),
            "limitations": [
                "App JWT is verified locally; Google ID-token verification happens at login."
            ],
        }

    if guest_credential:
        if not credential_valid:
            reason = str(credential_claims.get("reason") or "invalid_guest_credential")
            if reason == "expired_guest_credential":
                return 401, build_auth_error("token_expired", reason=reason)
            return 401, build_auth_error("token_invalid", reason=reason)
        if normalized_guest_id and credential_guest_id != normalized_guest_id:
            return 401, build_auth_error(
                "token_invalid",
                reason="guest_credential_guest_mismatch",
            )
        normalized_guest_id = credential_guest_id
    elif normalized_guest_id:
        return 401, build_auth_error(
            "token_invalid",
            reason="missing_guest_credential",
        )

    if normalized_guest_id:
        return 200, {
            "auth_state": "guest",
            "user": None,
            "guest": _guest_snapshot(normalized_guest_id),
            "subject": {
                "subject_id": f"guest:{normalized_guest_id}",
                "subject_type": "guest",
                "user_id": None,
                "guest_id": normalized_guest_id,
                "auth_session_id": None,
                "is_authenticated": False,
            },
            "session_binding": {
                "session_id": _text(session_id) or None,
                "can_bind_to_chat_session": bool(session_id),
            },
            "rate_limit": _rate_limit_policy(subject_id=f"guest:{normalized_guest_id}"),
            "merge_policy": _merge_policy(),
            "limitations": [
                "Guest identity is available for preview endpoints; protected APIs require an app JWT."
            ],
        }

    return 200, {
        "auth_state": "anonymous",
        "user": None,
        "guest": None,
        "subject": {
            "subject_id": "anonymous",
            "subject_type": "anonymous",
            "user_id": None,
            "guest_id": None,
            "auth_session_id": None,
            "is_authenticated": False,
        },
        "rate_limit": _rate_limit_policy(subject_id="anonymous"),
        "merge_policy": _merge_policy(),
        "limitations": ["No Bearer token or guest_id was provided."],
    }


def _guest_snapshot(guest_id: str | None) -> dict[str, Any] | None:
    normalized_guest_id = _normalize_guest_id(guest_id)
    if not normalized_guest_id:
        return None
    return {
        "guest_id": normalized_guest_id,
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
        ],
        "notes": [
            "Quota values are supplied by the canonical usage policy.",
            "File-upload protection also applies deployment-level IP controls.",
        ],
    }


def _merge_policy() -> dict[str, Any]:
    return {
        "guest_to_user_merge": "user_confirmation_required",
        "auto_merge": False,
        "reason": "Traffic dispute consultations may contain sensitive case details.",
    }


def _bearer_token_from_header(value: str | None) -> str:
    parts = _text(value).split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1]


def _normalize_guest_id(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    if text.startswith("gst_"):
        return text
    return f"gst_{text}"


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)
