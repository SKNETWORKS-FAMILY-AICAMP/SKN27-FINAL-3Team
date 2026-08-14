"""Application orchestration for reading a consultation case workspace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from chatbot.case_repository import (
    get_case_access_metadata,
    get_case_workspace as load_case_workspace,
)
from chatbot.repositories import authorize_resource_access


@dataclass(frozen=True)
class GetCaseWorkspaceQuery:
    case_id: str
    identity_payload: Mapping[str, Any]


@dataclass(frozen=True)
class GetCaseWorkspaceResult:
    workspace: dict[str, Any]


class CaseWorkspaceAccessDenied(Exception):
    def __init__(self, access: dict[str, Any]) -> None:
        super().__init__("case workspace access denied")
        self.access = access


def execute_get_case_workspace(
    query: GetCaseWorkspaceQuery,
) -> GetCaseWorkspaceResult:
    if not isinstance(query.case_id, str) or not query.case_id:
        raise ValueError("case_id is required")

    case_id = query.case_id
    metadata = get_case_access_metadata(case_id)
    if metadata is None:
        metadata = {"type": "case", "case_id": case_id}
    access = authorize_resource_access(metadata, query.identity_payload)
    if not access["allowed"]:
        raise CaseWorkspaceAccessDenied(access)

    return GetCaseWorkspaceResult(workspace=load_case_workspace(case_id))
