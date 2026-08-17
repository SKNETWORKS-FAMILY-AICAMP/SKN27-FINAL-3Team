"""Application orchestration for starting consultation case analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.contracts.consultation_case import StartCaseAnalysisRequest
from chatbot.case_repository import get_case_access_metadata, start_case_analysis
from chatbot.repositories import access_subject_from_payload, authorize_resource_access


@dataclass(frozen=True)
class StartCaseAnalysisCommand:
    case_id: str
    identity_payload: Mapping[str, Any]
    raw_payload: Mapping[str, Any]


@dataclass(frozen=True)
class StartCaseAnalysisResult:
    response: dict[str, Any]


class CaseAnalysisAccessDenied(Exception):
    def __init__(self, access: dict[str, Any]) -> None:
        super().__init__("case analysis access denied")
        self.access = access


def execute_start_case_analysis(
    command: StartCaseAnalysisCommand,
) -> StartCaseAnalysisResult:
    """Authorize, validate, then delegate the unchanged analysis transaction."""

    identity_payload = dict(command.identity_payload)
    metadata = get_case_access_metadata(command.case_id)
    if metadata is None:
        metadata = {"type": "case", "case_id": command.case_id}
    access = authorize_resource_access(metadata, identity_payload)
    if not access["allowed"]:
        raise CaseAnalysisAccessDenied(access)

    subject = access_subject_from_payload(identity_payload)["subject"]
    owner_id = str(subject.get("user_id") or "")
    validated = StartCaseAnalysisRequest.model_validate(dict(command.raw_payload))
    response = start_case_analysis(
        command.case_id,
        owner_id=owner_id,
        payload=validated.model_dump(mode="python"),
    )
    return StartCaseAnalysisResult(response=response)
