"""Database-backed validity checks for app JWT auth sessions."""

from __future__ import annotations

from typing import Any

from django.db import DatabaseError
from django.utils import timezone

from chatbot.models import AuthSession, AuthSessionStatus, UserAccountStatus


def validate_persisted_auth_session(claims: dict[str, Any]) -> tuple[bool, str]:
    """Require a signed JWT to reference the matching active persisted session."""

    auth_session_id = str(claims.get("jti") or "").strip()
    user_id = str(claims.get("sub") or "").strip()
    if not auth_session_id or not user_id:
        return False, "auth_session_claims_missing"

    try:
        auth_session = (
            AuthSession.objects.select_related("user")
            .filter(auth_session_id=auth_session_id)
            .first()
        )
    except DatabaseError:
        return False, "auth_session_store_unavailable"

    if auth_session is None:
        return False, "auth_session_not_persisted"
    if auth_session.status != AuthSessionStatus.ACTIVE or auth_session.revoked_at is not None:
        return False, "auth_session_revoked"
    if auth_session.expires_at and auth_session.expires_at <= timezone.now():
        return False, "auth_session_expired"
    if auth_session.subject_type != "user" or auth_session.subject_id != f"user:{user_id}":
        return False, "auth_session_subject_mismatch"
    if auth_session.user is None:
        return False, "auth_session_user_missing"
    if auth_session.user.user_id != user_id:
        return False, "auth_session_subject_mismatch"
    if auth_session.user.status != UserAccountStatus.ACTIVE:
        return False, "user_account_inactive"
    return True, ""
