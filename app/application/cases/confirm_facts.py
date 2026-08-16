"""Application orchestration for confirming consultation case facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.contracts.consultation_case import ConfirmCaseFactsRequest
from chatbot.case_repository import confirm_case_facts, get_case_access_metadata
from chatbot.repositories import access_subject_from_payload, authorize_resource_access


@dataclass(frozen=True)
class ConfirmCaseFactsCommand:
    case_id: str
    identity_payload: Mapping[str, Any]
    raw_payload: Mapping[str, Any]


ConfirmCaseFactsCommand.dataclass_fields = ConfirmCaseFactsCommand.__dataclass_fields__


@dataclass(frozen=True)
class ConfirmCaseFactsResult:
    fact_version: dict[str, Any]


class CaseFactConfirmationAccessDenied(Exception):
    def __init__(self, access: dict[str, Any]) -> None:
        super().__init__("case fact confirmation access denied")
        self.access = access


def execute_confirm_case_facts(
    command: ConfirmCaseFactsCommand,
) -> ConfirmCaseFactsResult:
    """Authorize, validate, then delegate the unchanged confirmation transaction."""

    identity_payload = dict(command.identity_payload)
    metadata = get_case_access_metadata(command.case_id)
    if metadata is None:
        metadata = {"type": "case", "case_id": command.case_id}
    access = authorize_resource_access(metadata, identity_payload)
    if not access["allowed"]:
        raise CaseFactConfirmationAccessDenied(access)

    subject = access_subject_from_payload(identity_payload)["subject"]
    owner_id = str(subject.get("user_id") or "")

    validated = ConfirmCaseFactsRequest.model_validate(dict(command.raw_payload))
    fact_version = confirm_case_facts(
        command.case_id,
        owner_id=owner_id,
        payload=validated.model_dump(mode="python"),
    )
    return ConfirmCaseFactsResult(fact_version=fact_version)