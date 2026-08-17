"""Application orchestration for listing consultation cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from chatbot.case_repository import list_cases
from chatbot.repositories import access_subject_from_payload


@dataclass(frozen=True)
class ListConsultationCasesQuery:
    identity_payload: Mapping[str, Any]


@dataclass(frozen=True)
class ListConsultationCasesResult:
    cases: list[dict[str, Any]]


class CaseListAccessDenied(Exception):
    def __init__(self, access: dict[str, Any]) -> None:
        super().__init__("consultation case list access denied")
        self.access = access


def execute_list_consultation_cases(
    query: ListConsultationCasesQuery,
) -> ListConsultationCasesResult:
    """List only cases owned by the trusted authenticated user."""

    auth_context = query.identity_payload.get("auth_context")
    if not isinstance(auth_context, Mapping):
        raise CaseListAccessDenied(_case_list_access_denied())

    subject = access_subject_from_payload(
        {"auth_context": dict(auth_context)}
    )["subject"]
    owner_id = str(subject.get("user_id") or "")
    if subject.get("subject_type") != "user" or not owner_id:
        raise CaseListAccessDenied(_case_list_access_denied())

    return ListConsultationCasesResult(cases=list_cases(owner_id=owner_id))


def _case_list_access_denied() -> dict[str, Any]:
    return {
        "contract_version": "object_access.v1",
        "allowed": False,
        "reason": "authenticated_user_required",
        "resource": {"type": "consultation_case_list"},
    }
