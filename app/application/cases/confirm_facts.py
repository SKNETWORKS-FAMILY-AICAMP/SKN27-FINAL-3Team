"""Application orchestration for confirming consultation case facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import ValidationError

from app.contracts.consultation_case import ConfirmCaseFactsRequest
from chatbot.case_repository import confirm_case_facts, get_case_access_metadata
from chatbot.repositories import authorize_resource_access


@dataclass(frozen=True)
class ConfirmCaseFactsCommand:
    case_id: str
    owner_id: str
    identity_payload: Mapping[str, Any]
    raw_payload: Mapping[str, Any]


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

    metadata = get_case_access_metadata(command.case_id)
    if metadata is None:
        metadata = {"type": "case", "case_id": command.case_id}
    access = authorize_resource_access(metadata, dict(command.identity_payload))
    if not access["allowed"]:
        raise CaseFactConfirmationAccessDenied(access)

    validated = ConfirmCaseFactsRequest.model_validate(dict(command.raw_payload))
    fact_version = confirm_case_facts(
        command.case_id,
        owner_id=command.owner_id,
        payload=validated.model_dump(mode="python"),
    )
    return ConfirmCaseFactsResult(fact_version=fact_version)