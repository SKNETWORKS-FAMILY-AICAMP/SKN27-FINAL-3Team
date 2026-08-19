"""Application query for the canonical MyPage summary surface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from chatbot.progress_cache import read_chat_session_state
from chatbot.repositories import (
    access_subject_from_payload,
    authorize_resource_access,
    get_chat_session_access_metadata,
    get_mycase_summary,
)


@dataclass(frozen=True)
class GetMyPageSummaryQuery:
    identity_payload: Mapping[str, Any]
    session_id: str | None
    owner_id: str | None
    user_id: str | None
    limit: object | None
    canonical_request: bool


@dataclass(frozen=True)
class GetMyPageSummaryResult:
    payload: dict[str, Any]


class MyPageSummaryAccessDenied(Exception):
    def __init__(self, access: Mapping[str, Any]) -> None:
        super().__init__("mypage summary access denied")
        self.access = dict(access)


def execute_get_mypage_summary(
    query: GetMyPageSummaryQuery,
) -> GetMyPageSummaryResult:
    """Authorize and compose the existing MyPage public summary unchanged."""

    identity_payload = dict(query.identity_payload)
    if query.canonical_request:
        _authorize_mypage_query(query, identity_payload)

    subject = access_subject_from_payload(identity_payload)["subject"]
    owner_id = query.owner_id or query.user_id or subject.get("user_id")
    summary = get_mycase_summary(
        session_id=query.session_id,
        owner_id=owner_id,
        limit=_positive_int(query.limit, default=10),
    )
    if query.canonical_request and query.session_id:
        summary["session_cache"] = read_chat_session_state(query.session_id)
    return GetMyPageSummaryResult(payload=summary)


def _authorize_mypage_query(
    query: GetMyPageSummaryQuery,
    identity_payload: dict[str, Any],
) -> None:
    requested_owner = query.owner_id or query.user_id
    if requested_owner:
        owner_access = authorize_resource_access(
            {"type": "mypage", "owner_id": requested_owner},
            identity_payload,
        )
        if not owner_access["allowed"]:
            raise MyPageSummaryAccessDenied(owner_access)

    if query.session_id:
        session_access = _session_access(
            query.session_id,
            identity_payload,
            resource_type="mypage",
        )
        if not session_access["allowed"]:
            raise MyPageSummaryAccessDenied(session_access)
    elif not requested_owner:
        access = _session_access(None, identity_payload, resource_type="mypage")
        if not access["allowed"]:
            raise MyPageSummaryAccessDenied(access)


def _session_access(
    session_id: str | None,
    identity_payload: dict[str, Any],
    *,
    resource_type: str,
) -> dict[str, Any]:
    if not session_id:
        return authorize_resource_access({"type": resource_type}, identity_payload)
    session_access = get_chat_session_access_metadata(session_id)
    if session_access is None:
        return authorize_resource_access(
            {"type": resource_type, "session_id": session_id},
            identity_payload,
        )
    session_access["type"] = resource_type
    return authorize_resource_access(session_access, identity_payload)


def _positive_int(value: object | None, *, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default