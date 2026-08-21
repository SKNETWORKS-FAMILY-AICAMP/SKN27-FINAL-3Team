"""Application orchestration for the draft chat-session boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.services.chat_orchestration_service import create_session
from app.services.history_event_contract import subject_from_payload
from chatbot.repositories import access_subject_from_payload


HistoryRecorder = Callable[..., Mapping[str, Any] | None]


@dataclass(frozen=True)
class CreateChatSessionCommand:
    identity_payload: Mapping[str, Any]
    history_actor: Mapping[str, Any]
    history_source: Mapping[str, Any]
    history_recorder: HistoryRecorder


@dataclass(frozen=True)
class CreateChatSessionResult:
    payload: dict[str, Any]


def _trusted_identity(identity_payload: Mapping[str, Any]) -> dict[str, Any]:
    auth_context = identity_payload.get("auth_context")
    return {"auth_context": dict(auth_context)} if isinstance(auth_context, Mapping) else {}


def execute_create_chat_session(
    command: CreateChatSessionCommand,
) -> CreateChatSessionResult:
    """Issue the existing draft DTO and record its best-effort history event."""

    trusted_identity = _trusted_identity(command.identity_payload)
    subject = access_subject_from_payload(trusted_identity)["subject"]
    payload = create_session(user_id=subject.get("user_id"))
    command.history_recorder(
        event_type="chat_session_created",
        status="success",
        summary="상담 세션을 생성했습니다.",
        actor=dict(command.history_actor),
        subject=subject_from_payload(
            trusted_identity,
            session_id=payload.get("session_id"),
        ),
        source=dict(command.history_source),
        metadata={"session_status": payload.get("status")},
    )
    return CreateChatSessionResult(payload=payload)
