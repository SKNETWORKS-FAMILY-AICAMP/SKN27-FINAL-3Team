"""Application orchestration for promoting a consultation session to a Case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from chatbot.case_repository import create_case
from chatbot.repositories import access_subject_from_payload


@dataclass(frozen=True)
class CreateConsultationCaseCommand:
    identity_payload: Mapping[str, Any]
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class CreateConsultationCaseResult:
    case: dict[str, Any]


def execute_create_consultation_case(
    command: CreateConsultationCaseCommand,
) -> CreateConsultationCaseResult:
    """Delegate validated case promotion using only the trusted auth context."""

    auth_context = command.identity_payload.get("auth_context")
    trusted_identity = (
        {"auth_context": dict(auth_context)}
        if isinstance(auth_context, Mapping)
        else {}
    )
    subject = access_subject_from_payload(trusted_identity)["subject"]
    case = create_case(
        owner_id=str(subject.get("user_id") or ""),
        guest_id=str(subject.get("guest_id") or ""),
        payload=dict(command.payload),
    )
    return CreateConsultationCaseResult(case=case)
