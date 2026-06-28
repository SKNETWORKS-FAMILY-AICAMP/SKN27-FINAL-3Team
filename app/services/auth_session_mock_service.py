"""Mock auth/session identity helpers for guest and JWT boundary tests."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.services.auth_error_contract import is_valid_mock_bearer_header


MOCK_GUEST_TTL_SECONDS = 7 * 24 * 60 * 60


def create_guest_session(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create or refresh a mock guest identity without binding it to login."""

    payload = payload or {}
    now = _now()
    guest_id = _normalize_guest_id(payload.get("guest_id")) or f"gst_{uuid4().hex[:12]}"
    session_id = _text(payload.get("session_id")) or None
    issued_at = now.isoformat()
    expires_at = (now + timedelta(seconds=MOCK_GUEST_TTL_SECONDS)).isoformat()

    return {
        "auth_state": "guest",
        "guest": {
            "guest_id": guest_id,
            "status": "active",
            "issued_at": issued_at,
            "expires_at": expires_at,
            "ttl_seconds": MOCK_GUEST_TTL_SECONDS,
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
            "binding_policy": "guest_id may start chat sessions, but account merge requires explicit user confirmation.",
        },
        "rate_limit": _rate_limit_policy(subject_id=f"guest:{guest_id}"),
        "merge_policy": _merge_policy(),
        "limitations": [
            "Mock guest identity only; no durable guest identity table is created yet.",
            "Guest TTL and quota values are review-required and not production policy.",
        ],
    }


def get_current_auth_subject(
    *,
    authorization_header: str | None,
    guest_id: str | None = None,
    session_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Return current mock auth subject or an auth error envelope."""

    if authorization_header:
        valid, error_body = is_valid_mock_bearer_header(authorization_header)
        if not valid:
            return int(error_body["error"]["status"]), error_body

        token = authorization_header.strip().split()[1]
        auth_session_id = _auth_session_id_for_token(token)
        user_id = _user_id_for_token(token)
        return 200, {
            "auth_state": "authenticated",
            "user": {
                "user_id": user_id,
                "display_name": "Mock user",
                "status": "active",
                "policy_status": "mock_only",
            },
            "guest": _guest_snapshot(guest_id),
            "subject": {
                "subject_id": f"user:{user_id}",
                "subject_type": "user",
                "user_id": user_id,
                "guest_id": _normalize_guest_id(guest_id),
                "auth_session_id": auth_session_id,
                "is_authenticated": True,
            },
            "auth_session": {
                "auth_session_id": auth_session_id,
                "jwt_jti": auth_session_id,
                "status": "active",
                "verification": "mock_bearer_shape_only",
            },
            "session_binding": {
                "session_id": _text(session_id) or None,
                "can_bind_to_chat_session": bool(session_id),
            },
            "rate_limit": _rate_limit_policy(subject_id=f"user:{user_id}"),
            "merge_policy": _merge_policy(),
            "limitations": [
                "Mock Bearer token validation checks token shape only, not JWT signature.",
                "auth_session_id is derived from the mock token until a real auth session table exists.",
            ],
        }

    normalized_guest_id = _normalize_guest_id(guest_id)
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
                "Guest subject is accepted for identity preview only; protected APIs still require Bearer auth in the current mock middleware.",
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
            "Exact quota numbers are intentionally not fixed in this mock contract.",
            "File upload limits should also consider IP-based protection.",
        ],
    }


def _merge_policy() -> dict[str, Any]:
    return {
        "guest_to_user_merge": "user_confirmation_required",
        "auto_merge": False,
        "reason": "Traffic dispute consultations may contain sensitive case details.",
    }


def _auth_session_id_for_token(token: str) -> str:
    if token == "dev-mock-token":
        return "auth_dev_mock"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    return f"auth_{digest}"


def _user_id_for_token(token: str) -> str:
    if token.startswith("usr_"):
        return token.split(":", 1)[0]
    return "usr_mock"


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
