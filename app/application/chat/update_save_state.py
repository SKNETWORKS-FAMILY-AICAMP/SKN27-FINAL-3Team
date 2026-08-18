"""Application orchestration for the conversation save-state boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from chatbot.repositories import (
    access_subject_from_payload,
    authorize_resource_access,
    conversation_save_state_from_payload,
    get_chat_session_access_metadata,
    mark_conversation_save_state,
)


HistoryRecorder = Callable[..., Mapping[str, Any] | None]
HistoryEventFactory = Callable[[], Mapping[str, Any]]
GuestViolationResolver = Callable[[dict[str, Any]], Mapping[str, Any] | None]


@dataclass(frozen=True)
class UpdateConversationSaveStateCommand:
    identity_payload: Mapping[str, Any]
    session_id: str
    raw_payload: Mapping[str, Any]
    canonical_request: bool
    guest_violation_resolver: GuestViolationResolver | None = None
    history_recorder: HistoryRecorder | None = None
    history_event_factory: HistoryEventFactory | None = None


UpdateConversationSaveStateCommand.dataclass_fields = (
    UpdateConversationSaveStateCommand.__dataclass_fields__
)


@dataclass(frozen=True)
class UpdateConversationSaveStateResult:
    conversation_save: dict[str, Any]


class ConversationSaveStateAccessDenied(Exception):
    def __init__(self, access: Mapping[str, Any]) -> None:
        super().__init__("conversation save-state access denied")
        self.access = dict(access)


class ConversationSaveStateGuestIdentityInvalid(Exception):
    def __init__(self, violation: Mapping[str, Any]) -> None:
        super().__init__("conversation save-state guest identity is invalid")
        self.violation = dict(violation)


class ConversationSaveStateLoginRequired(Exception):
    def __init__(self, subject: Mapping[str, Any]) -> None:
        super().__init__("conversation save-state requires an authenticated user")
        self.subject = dict(subject)


def _trusted_identity(identity_payload: Mapping[str, Any]) -> dict[str, Any]:
    auth_context = identity_payload.get("auth_context")
    return (
        {"auth_context": dict(auth_context)}
        if isinstance(auth_context, Mapping)
        else {}
    )


def _session_access(
    session_id: str,
    identity_payload: dict[str, Any],
) -> dict[str, Any]:
    if not session_id:
        return authorize_resource_access({"type": "chat_save_state"}, identity_payload)
    access_metadata = get_chat_session_access_metadata(session_id)
    if access_metadata is None:
        return authorize_resource_access(
            {"type": "chat_save_state", "session_id": session_id},
            identity_payload,
        )
    access_metadata["type"] = "chat_save_state"
    return authorize_resource_access(access_metadata, identity_payload)


def execute_update_conversation_save_state(
    command: UpdateConversationSaveStateCommand,
) -> UpdateConversationSaveStateResult:
    """Authorize and delegate the existing save-state transaction unchanged."""

    trusted_identity = _trusted_identity(command.identity_payload)
    if command.session_id:
        trusted_identity["session_id"] = command.session_id
    if command.canonical_request:
        access = _session_access(command.session_id, trusted_identity)
        if not access["allowed"]:
            raise ConversationSaveStateAccessDenied(access)

    subject = access_subject_from_payload(trusted_identity)["subject"]
    save_state = conversation_save_state_from_payload(
        dict(command.raw_payload),
        default="pending",
    )
    if command.canonical_request:
        violation = (
            command.guest_violation_resolver(subject)
            if command.guest_violation_resolver is not None
            else None
        )
        if violation:
            raise ConversationSaveStateGuestIdentityInvalid(violation)
        if save_state == "saved" and subject.get("subject_type") != "user":
            raise ConversationSaveStateLoginRequired(subject)

    conversation_save = mark_conversation_save_state(
        session_id=command.session_id,
        save_state=save_state,
        owner_id=str(subject.get("user_id") or ""),
        guest_id=str(subject.get("guest_id") or ""),
        raw_payload=dict(command.raw_payload),
    )
    if (
        conversation_save.get("conversation_save_state") == "saved"
        and command.history_recorder is not None
        and command.history_event_factory is not None
    ):
        command.history_recorder(**dict(command.history_event_factory()))
    return UpdateConversationSaveStateResult(conversation_save=conversation_save)
