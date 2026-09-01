"""Application boundary for the canonical GetCurrentAuthIdentity route."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from django.db import DatabaseError

from app.services.auth_error_contract import build_auth_error
from app.services.auth_session_service import (
    get_current_auth_subject,
    normalize_guest_identity_sources,
)
from app.services.history_event_contract import actor_from_payload, subject_from_payload
from chatbot.repositories import AuthSessionStateError, SessionBindingError


GuestStateResolver = Callable[[str | None], dict[str, Any] | None]
PersistenceWriter = Callable[..., dict[str, Any]]
HistoryRecorder = Callable[..., object]


PUBLIC_AUTH_IDENTITY_FIELDS = (
    "auth_state",
    "user",
    "guest",
    "subject",
    "auth_session",
    "session_binding",
    "rate_limit",
    "merge_policy",
    "limitations",
    "persistence",
)
PUBLIC_AUTH_IDENTITY_NESTED_FIELDS = {
    "user": (
        "user_id",
        "email",
        "display_name",
        "picture",
        "status",
        "auth_provider",
        "provider_subject",
        "policy_status",
    ),
    "guest": (
        "guest_id",
        "status",
        "issued_at",
        "expires_at",
        "ttl_seconds",
        "policy_status",
    ),
    "subject": (
        "subject_id",
        "subject_type",
        "user_id",
        "guest_id",
        "auth_session_id",
        "is_authenticated",
    ),
    "auth_session": (
        "auth_session_id",
        "jwt_jti",
        "status",
        "verification",
        "provider",
    ),
    "session_binding": (
        "session_id",
        "can_bind_to_chat_session",
        "binding_policy",
    ),
    "rate_limit": ("subject_id", "policy_status", "keys", "notes"),
    "merge_policy": ("guest_to_user_merge", "auto_merge", "reason"),
    "persistence": (
        "backend",
        "tables",
        "user_table",
        "guest_identity_table",
        "auth_session_table",
        "auth_events_table",
        "chat_session_table",
        "social_account_table",
        "oauth_connection_table",
        "user_id",
        "guest_id",
        "auth_session_id",
        "social_account_id",
        "oauth_connection_id",
        "event_id",
        "session_id",
        "status",
    ),
}


@dataclass(frozen=True)
class GetCurrentAuthIdentityQuery:
    authorization_header: str | None
    header_guest_id: str | None
    query_guest_id: str | None
    guest_credential: str | None
    session_id: str | None
    canonical_request: bool
    audit_source: Mapping[str, Any]
    guest_state_resolver: GuestStateResolver
    persistence_writer: PersistenceWriter
    history_recorder: HistoryRecorder


@dataclass(frozen=True)
class GetCurrentAuthIdentityResult:
    payload: dict[str, Any]


class CurrentAuthIdentityInvalid(Exception):
    def __init__(self, payload: Mapping[str, Any]) -> None:
        super().__init__("current auth identity is invalid")
        self.payload = dict(payload)


class CurrentAuthIdentityAccessDenied(Exception):
    def __init__(self, payload: Mapping[str, Any]) -> None:
        super().__init__("current auth identity access is denied")
        self.payload = dict(payload)


class CurrentAuthIdentityPersistenceUnavailable(Exception):
    def __init__(self, payload: Mapping[str, Any]) -> None:
        super().__init__("current auth identity persistence is unavailable")
        self.payload = dict(payload)


def execute_get_current_auth_identity(
    query: GetCurrentAuthIdentityQuery,
) -> GetCurrentAuthIdentityResult:
    """Validate, persist, audit, and project one current auth identity."""

    guest_id, guest_source_error = normalize_guest_identity_sources(
        query.header_guest_id,
        query.query_guest_id,
    )
    if guest_source_error:
        raise CurrentAuthIdentityInvalid(
            build_auth_error("token_invalid", reason=guest_source_error)
        )

    status, auth_payload = get_current_auth_subject(
        authorization_header=query.authorization_header,
        guest_id=guest_id,
        guest_credential=query.guest_credential,
        session_id=query.session_id,
    )
    if status >= 400:
        raise CurrentAuthIdentityInvalid(auth_payload)

    subject = _mapping(auth_payload.get("subject"))
    if subject.get("subject_type") == "anonymous":
        raise CurrentAuthIdentityInvalid(build_auth_error("auth_required"))

    try:
        guest_violation = query.guest_state_resolver(
            _text_or_none(subject.get("guest_id"))
        )
    except DatabaseError as error:
        raise CurrentAuthIdentityPersistenceUnavailable(
            _persistence_unavailable_payload()
        ) from error
    if guest_violation:
        raise CurrentAuthIdentityInvalid(
            build_auth_error(
                "token_invalid",
                reason=str(guest_violation.get("reason") or "guest_inactive"),
            )
        )

    try:
        persistence = query.persistence_writer(
            auth_payload,
            session_id=query.session_id,
        )
    except AuthSessionStateError as error:
        raise CurrentAuthIdentityInvalid(
            build_auth_error("token_invalid", reason=error.reason)
        ) from error
    except SessionBindingError as error:
        raise CurrentAuthIdentityAccessDenied(
            build_auth_error("forbidden", reason=error.reason)
        ) from error
    except DatabaseError as error:
        raise CurrentAuthIdentityPersistenceUnavailable(
            _persistence_unavailable_payload()
        ) from error

    payload = project_current_auth_identity_public(
        {**auth_payload, "persistence": persistence}
    )
    _record_history_best_effort(query, payload)
    return GetCurrentAuthIdentityResult(payload=payload)


def project_current_auth_identity_public(
    auth_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the explicit public allow-list for the auth/me response."""

    payload: dict[str, Any] = {}
    for field in PUBLIC_AUTH_IDENTITY_FIELDS:
        if field not in auth_payload:
            continue
        value = auth_payload[field]
        if field in PUBLIC_AUTH_IDENTITY_NESTED_FIELDS:
            payload[field] = _project_mapping(
                value,
                PUBLIC_AUTH_IDENTITY_NESTED_FIELDS[field],
            )
        elif field == "limitations" and isinstance(value, list):
            payload[field] = list(value)
        elif field == "auth_state":
            payload[field] = value
    return payload


def _record_history_best_effort(
    query: GetCurrentAuthIdentityQuery,
    payload: Mapping[str, Any],
) -> None:
    subject = _mapping(payload.get("subject"))
    try:
        query.history_recorder(
            event_type="auth_me_checked",
            status="success",
            summary="현재 인증 주체 상태를 확인했습니다.",
            actor=actor_from_payload(
                {
                    "auth_context": {
                        "auth_state": payload.get("auth_state"),
                        "user_id": subject.get("user_id"),
                        "guest_id": subject.get("guest_id"),
                        "auth_session_id": subject.get("auth_session_id"),
                    }
                }
            ),
            subject=subject_from_payload({"session_id": query.session_id}),
            source=dict(query.audit_source),
            metadata={
                "http_status": 200,
                "auth_state": payload.get("auth_state"),
                "subject_type": subject.get("subject_type"),
                "is_authenticated": subject.get("is_authenticated"),
                "canonical_request": query.canonical_request,
            },
        )
    except (DatabaseError, OSError):
        return


def _persistence_unavailable_payload() -> dict[str, Any]:
    payload = build_auth_error(
        "provider_unavailable",
        reason="auth_me_persistence_unavailable",
    )
    payload["error"]["required_action"] = "retry"
    return payload


def _project_mapping(value: object, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if value is None:
        return None
    record = _mapping(value)
    return {field: record[field] for field in fields if field in record}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None

