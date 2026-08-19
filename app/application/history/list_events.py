"""Application query for the canonical History read surface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.services.history_event_contract import HISTORY_EVENT_VERSION
from chatbot.repositories import (
    access_subject_from_payload,
    authorize_resource_access,
    build_history_after_service_summary,
    get_analysis_job_access_metadata,
    get_chat_session_access_metadata,
    history_operating_policy,
    list_history_event_records,
)


@dataclass(frozen=True)
class ListHistoryEventsQuery:
    identity_payload: Mapping[str, Any]
    session_id: str | None
    user_id: str | None
    guest_id: str | None
    job_id: str | None
    event_type: str | None
    limit: object | None
    canonical_request: bool


@dataclass(frozen=True)
class ListHistoryEventsResult:
    payload: dict[str, Any]


class HistoryListAccessDenied(Exception):
    def __init__(self, access: Mapping[str, Any]) -> None:
        super().__init__("history list access denied")
        self.access = dict(access)


def execute_list_history_events(
    query: ListHistoryEventsQuery,
) -> ListHistoryEventsResult:
    """Authorize and project standard-light history for the trusted subject."""

    trusted_identity = _trusted_identity(query.identity_payload, query.session_id)
    if query.canonical_request:
        _authorize_job_query(query.job_id, trusted_identity)
        _authorize_history_query(query, trusted_identity)

    subject = access_subject_from_payload(trusted_identity)["subject"]
    filters = {
        "session_id": query.session_id,
        "user_id": query.user_id,
        "guest_id": query.guest_id,
        "job_id": query.job_id,
        "event_type": query.event_type,
        "limit": _positive_int(query.limit, default=100),
    }
    if not any(filters.get(key) for key in ("session_id", "user_id", "guest_id", "job_id")):
        if subject.get("user_id"):
            filters["user_id"] = subject["user_id"]
        elif subject.get("guest_id"):
            filters["guest_id"] = subject["guest_id"]
    filters["subject_type"] = subject.get("subject_type")

    events = list_history_event_records(**filters)
    return ListHistoryEventsResult(
        payload={
            "history_contract": HISTORY_EVENT_VERSION,
            "storage": {
                "backend": "postgresql",
                "policy": "standard_light",
                "table": "history_events",
            },
            "history_policy": history_operating_policy(subject.get("subject_type")),
            "after_service_summary": build_history_after_service_summary(events),
            "count": len(events),
            "events": events,
            "limitations": [
                "대화 원문, OCR 원문, 에이전트 추론 원문은 표준 경량 이력에 저장하지 않습니다.",
                "원본 이벤트의 DB 테이블 원문과 민감 필드는 이 응답에 포함하지 않습니다.",
            ],
        }
    )


def _trusted_identity(
    identity_payload: Mapping[str, Any],
    session_id: str | None,
) -> dict[str, Any]:
    auth_context = identity_payload.get("auth_context")
    trusted_identity = (
        {"auth_context": dict(auth_context)}
        if isinstance(auth_context, Mapping)
        else {}
    )
    if session_id:
        trusted_identity["session_id"] = session_id
    return trusted_identity


def _authorize_job_query(
    job_id: str | None,
    identity_payload: dict[str, Any],
) -> None:
    if not job_id:
        return
    metadata = get_analysis_job_access_metadata(job_id)
    if metadata is None:
        return
    access = _session_access(
        str(metadata.get("session_id") or ""),
        identity_payload,
        resource_type="history",
    )
    if not access["allowed"]:
        raise HistoryListAccessDenied(access)


def _authorize_history_query(
    query: ListHistoryEventsQuery,
    identity_payload: dict[str, Any],
) -> None:
    subject = access_subject_from_payload(identity_payload)["subject"]
    if query.user_id:
        access = authorize_resource_access(
            {"type": "history", "owner_id": query.user_id},
            identity_payload,
        )
    elif query.guest_id:
        access = authorize_resource_access(
            {"type": "history", "guest_id": query.guest_id},
            identity_payload,
        )
    else:
        access = _session_access(
            query.session_id,
            identity_payload,
            resource_type="history",
        )
        if not any((query.session_id, query.job_id, query.event_type)):
            if subject.get("user_id") or subject.get("guest_id"):
                return
            access = authorize_resource_access(
                {
                    "type": "history",
                    "owner_id": "__authenticated_subject_required__",
                },
                identity_payload,
            )

    if not access["allowed"]:
        raise HistoryListAccessDenied(access)


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
