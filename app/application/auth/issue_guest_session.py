"""Application boundary for the canonical IssueGuestSession route."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from django.db import DatabaseError

from app.services.auth_error_contract import build_auth_error
from app.services.auth_session_service import create_guest_session
from app.services.history_event_contract import subject_from_payload
from chatbot.repositories import (
    GuestIdentityStateError,
    SessionBindingError,
    persist_guest_session_identity,
)


GuestSessionCreator = Callable[..., dict[str, Any]]
PersistenceWriter = Callable[[dict[str, Any]], dict[str, Any]]
HistoryRecorder = Callable[..., object]


PUBLIC_ISSUE_GUEST_SESSION_FIELDS: Final = (
    "auth_state",
    "guest",
    "subject",
    "session_binding",
    "guest_credential",
    "rate_limit",
    "merge_policy",
    "limitations",
    "persistence",
)
PUBLIC_ISSUE_GUEST_SESSION_NESTED_FIELDS: Final = {
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
    "session_binding": (
        "session_id",
        "can_bind_to_chat_session",
        "binding_policy",
    ),
    "rate_limit": (
        "subject_id",
        "policy_status",
        "keys",
        "notes",
    ),
    "merge_policy": (
        "guest_to_user_merge",
        "auto_merge",
        "reason",
    ),
    "persistence": (
        "backend",
        "tables",
        "guest_identity_table",
        "auth_events_table",
        "chat_session_table",
        "guest_id",
        "event_id",
        "session_id",
        "status",
    ),
}
PUBLIC_ISSUE_GUEST_SESSION_LIST_FIELDS: Final = {
    "limitations": (),
    "rate_limit": ("keys", "notes"),
    "persistence": ("tables",),
}


@dataclass(frozen=True)
class IssueGuestSessionCommand:
    payload: Mapping[str, Any]
    guest_credential: str | None
    audit_source: Mapping[str, Any]
    guest_session_creator: GuestSessionCreator = create_guest_session
    persistence_writer: PersistenceWriter = persist_guest_session_identity
    history_recorder: HistoryRecorder | None = None


@dataclass(frozen=True)
class IssueGuestSessionResult:
    payload: dict[str, Any]


class IssueGuestSessionInvalid(Exception):
    def __init__(self, payload: Mapping[str, Any]) -> None:
        super().__init__("guest session is invalid")
        self.payload = dict(payload)


class IssueGuestSessionAccessDenied(Exception):
    def __init__(self, payload: Mapping[str, Any]) -> None:
        super().__init__("guest session access is denied")
        self.payload = dict(payload)


class IssueGuestSessionPersistenceUnavailable(Exception):
    def __init__(self, payload: Mapping[str, Any]) -> None:
        super().__init__("guest session persistence is unavailable")
        self.payload = dict(payload)


def execute_issue_guest_session(
    command: IssueGuestSessionCommand,
) -> IssueGuestSessionResult:
    """Issue, persist, and audit a guest session without retaining request secrets."""

    auth_payload = command.guest_session_creator(
        dict(command.payload),
        guest_credential=command.guest_credential,
    )
    try:
        persistence = command.persistence_writer(auth_payload)
    except GuestIdentityStateError as error:
        raise IssueGuestSessionInvalid(
            build_auth_error("token_invalid", reason=error.reason)
        ) from error
    except SessionBindingError as error:
        raise IssueGuestSessionAccessDenied(
            build_auth_error("forbidden", reason=error.reason)
        ) from error
    except DatabaseError as error:
        raise IssueGuestSessionPersistenceUnavailable(
            _persistence_unavailable_payload()
        ) from error

    payload = project_issue_guest_session_public(
        {**auth_payload, "persistence": persistence}
    )
    _record_history_best_effort(command, payload)
    return IssueGuestSessionResult(payload=payload)


def project_issue_guest_session_public(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the explicit public contract for the IssueGuestSession route."""

    source = _mapping(payload)
    projected: dict[str, Any] = {}
    for field in PUBLIC_ISSUE_GUEST_SESSION_FIELDS:
        if field not in source:
            continue
        if field in PUBLIC_ISSUE_GUEST_SESSION_NESTED_FIELDS:
            projected[field] = _project_public_mapping(
                source[field],
                PUBLIC_ISSUE_GUEST_SESSION_NESTED_FIELDS[field],
                list_fields=PUBLIC_ISSUE_GUEST_SESSION_LIST_FIELDS.get(field, ()),
            )
        elif field == "limitations":
            projected[field] = _public_string_list(source[field])
        else:
            projected[field] = _public_scalar(source[field])
    return projected


def _record_history_best_effort(
    command: IssueGuestSessionCommand,
    payload: Mapping[str, Any],
) -> None:
    if command.history_recorder is None:
        return

    guest = _mapping(payload.get("guest"))
    subject = _mapping(payload.get("subject"))
    session_binding = _mapping(payload.get("session_binding"))
    try:
        command.history_recorder(
            event_type="guest_session_created",
            status="success",
            summary="비회원 상담 세션을 생성했습니다.",
            actor={
                "guest_id": guest.get("guest_id"),
                "auth_state": "guest",
            },
            subject=subject_from_payload(
                {
                    "auth_context": {
                        "guest_id": subject.get("guest_id"),
                        "subject_id": subject.get("subject_id"),
                        "subject_type": "guest",
                    }
                },
                session_id=_text_or_none(session_binding.get("session_id")),
            ),
            source=dict(command.audit_source),
            metadata={
                "ttl_seconds": guest.get("ttl_seconds"),
                "rate_limit_keys": _mapping(payload.get("rate_limit")).get("keys", []),
                "merge_policy": _mapping(payload.get("merge_policy")),
            },
        )
    except (DatabaseError, OSError):
        return


def _persistence_unavailable_payload() -> dict[str, Any]:
    payload = build_auth_error(
        "provider_unavailable",
        reason="guest_session_store_unavailable",
    )
    payload["error"]["required_action"] = "retry"
    return payload


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _project_public_mapping(
    value: object,
    fields: tuple[str, ...],
    *,
    list_fields: tuple[str, ...],
) -> dict[str, Any]:
    source = _mapping(value)
    return {
        field: (
            _public_string_list(source[field])
            if field in list_fields
            else _public_scalar(source[field])
        )
        for field in fields
        if field in source
    }


def _public_string_list(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _public_scalar(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return None


def _text_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
