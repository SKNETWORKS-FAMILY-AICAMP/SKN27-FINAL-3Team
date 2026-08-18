"""Application queries for the canonical Report read surface."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.services.report_query_service import (
    WORKER_REPORT_SOURCE,
    compose_report_detail_response,
    compose_report_list_response,
    report_api_surface,
    report_execution_mode,
)
from chatbot.repositories import (
    access_subject_from_payload,
    authorize_report_download_metadata,
    get_report_access_metadata,
    get_report_record_detail,
    list_report_records,
)


GuestViolationResolver = Callable[[Mapping[str, Any]], dict[str, Any] | None]


@dataclass(frozen=True)
class ListReportsQuery:
    identity_payload: Mapping[str, Any]
    session_id: str | None
    guest_violation_resolver: GuestViolationResolver


@dataclass(frozen=True)
class ListReportsResult:
    payload: dict[str, Any]


@dataclass(frozen=True)
class GetReportDetailQuery:
    report_id: str
    identity_payload: Mapping[str, Any]
    guest_violation_resolver: GuestViolationResolver


@dataclass(frozen=True)
class GetReportDetailResult:
    payload: dict[str, Any]


class ReportReadGuestIdentityInvalid(Exception):
    def __init__(self, violation: Mapping[str, Any]) -> None:
        super().__init__("report read guest identity is invalid")
        self.violation = dict(violation)


class ReportReadLoginRequired(Exception):
    def __init__(self, subject: Mapping[str, Any]) -> None:
        super().__init__("report read requires an authenticated user")
        self.subject = dict(subject)


class ReportReadAccessDenied(Exception):
    def __init__(self, access: Mapping[str, Any]) -> None:
        super().__init__("report read access denied")
        self.access = dict(access)


class ReportReadNotFound(Exception):
    """The requested Report detail does not exist."""


def execute_list_reports(query: ListReportsQuery) -> ListReportsResult:
    """List summaries owned by the trusted authenticated user."""

    subject = _authenticated_report_subject(
        query.identity_payload,
        query.guest_violation_resolver,
    )
    reports = list_report_records(
        session_id=query.session_id,
        owner_id=str(subject.get("user_id") or ""),
    )
    has_worker_reports = any(
        report.get("source") == WORKER_REPORT_SOURCE
        for report in reports
    )
    return ListReportsResult(
        payload=compose_report_list_response(
            reports,
            api_surface=report_api_surface(
                canonical=True,
                source=WORKER_REPORT_SOURCE if has_worker_reports else "",
            ),
        )
    )


def execute_get_report_detail(
    query: GetReportDetailQuery,
) -> GetReportDetailResult:
    """Authorize and project one Report detail for the trusted owner."""

    trusted_identity = _trusted_identity(query.identity_payload)
    _authenticated_report_subject(
        trusted_identity,
        query.guest_violation_resolver,
    )
    access_metadata = get_report_access_metadata(query.report_id)
    if access_metadata is not None:
        access = authorize_report_download_metadata(access_metadata, trusted_identity)
        if not access["allowed"]:
            raise ReportReadAccessDenied(access)

    report = get_report_record_detail(query.report_id)
    if report is None:
        raise ReportReadNotFound()
    return GetReportDetailResult(
        payload=compose_report_detail_response(
            report,
            api_surface=report_api_surface(
                canonical=True,
                source=report.get("source"),
            ),
            execution_mode=report_execution_mode(source=report.get("source")),
        )
    )


def _authenticated_report_subject(
    identity_payload: Mapping[str, Any],
    guest_violation_resolver: GuestViolationResolver,
) -> dict[str, Any]:
    trusted_identity = _trusted_identity(identity_payload)
    subject = access_subject_from_payload(trusted_identity)["subject"]
    violation = guest_violation_resolver(subject)
    if violation:
        raise ReportReadGuestIdentityInvalid(violation)
    if subject.get("subject_type") != "user":
        raise ReportReadLoginRequired(subject)
    return subject


def _trusted_identity(identity_payload: Mapping[str, Any]) -> dict[str, Any]:
    auth_context = identity_payload.get("auth_context")
    return {"auth_context": dict(auth_context)} if isinstance(auth_context, Mapping) else {}
