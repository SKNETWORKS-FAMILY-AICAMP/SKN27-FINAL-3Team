"""Application boundary for the canonical IssueGuestSession route."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

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

    payload = {**auth_payload, "persistence": persistence}
    _record_history_best_effort(command, payload)
    return IssueGuestSessionResult(payload=payload)


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


def _text_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
