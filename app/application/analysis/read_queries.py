"""Application queries for the canonical AnalysisRead surface."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.services.analysis_job_query_service import (
    load_analysis_job_detail,
    load_analysis_result,
)
from app.services.chat_orchestration_service import compose_agent_response
from chatbot.progress_cache import read_analysis_job_progress
from chatbot.repositories import (
    access_subject_from_payload,
    authorize_resource_access,
    get_analysis_job_access_metadata,
    get_analysis_job_record,
    get_chat_session_access_metadata,
    list_analysis_job_records,
    list_analysis_job_records_for_session,
)


GuestViolationResolver = Callable[[Mapping[str, Any]], dict[str, Any] | None]


@dataclass(frozen=True)
class ListAnalysisJobsQuery:
    identity_payload: Mapping[str, Any]
    session_id: str | None
    canonical_request: bool
    guest_violation_resolver: GuestViolationResolver


@dataclass(frozen=True)
class GetAnalysisJobDetailQuery:
    job_id: str
    identity_payload: Mapping[str, Any]
    canonical_request: bool
    guest_violation_resolver: GuestViolationResolver


@dataclass(frozen=True)
class GetAnalysisResultQuery:
    job_id: str
    identity_payload: Mapping[str, Any]
    canonical_request: bool
    guest_violation_resolver: GuestViolationResolver


@dataclass(frozen=True)
class ListAnalysisJobsResult:
    payload: dict[str, Any]


@dataclass(frozen=True)
class GetAnalysisJobDetailResult:
    payload: dict[str, Any]


@dataclass(frozen=True)
class GetAnalysisResultResult:
    payload: dict[str, Any]
    pending: bool


class AnalysisReadGuestIdentityInvalid(Exception):
    def __init__(self, violation: Mapping[str, Any]) -> None:
        super().__init__("analysis read guest identity is invalid")
        self.violation = dict(violation)


class AnalysisReadAccessDenied(Exception):
    def __init__(self, access: Mapping[str, Any]) -> None:
        super().__init__("analysis read access denied")
        self.access = dict(access)


class AnalysisJobNotFound(Exception):
    """The requested AnalysisJob does not exist."""


class AnalysisResultNotFound(Exception):
    """The requested AnalysisJob result does not exist."""


class AnalysisJobAccessMetadataMissing(Exception):
    """The requested job cannot be exposed without access metadata."""


def execute_list_analysis_jobs(
    query: ListAnalysisJobsQuery,
) -> ListAnalysisJobsResult:
    """Authorize one list scope and return the existing public job summaries."""

    trusted_identity = _trusted_identity(query.identity_payload, query.session_id)
    subject = _subject_with_guest_policy(
        trusted_identity,
        canonical_request=query.canonical_request,
        guest_violation_resolver=query.guest_violation_resolver,
    )
    if query.session_id:
        session_access = get_chat_session_access_metadata(query.session_id)
        if session_access is None:
            raise AnalysisReadAccessDenied(_unknown_session_access())
        access = authorize_resource_access(session_access, trusted_identity)
        if not access["allowed"]:
            raise AnalysisReadAccessDenied(access)

    if str(subject.get("subject_type") or "") == "guest":
        if not query.session_id:
            jobs: list[Mapping[str, Any]] = []
        else:
            jobs = _authorized_analysis_job_summaries(
                list_analysis_job_records_for_session(session_id=query.session_id),
                trusted_identity,
            )
    else:
        jobs = list_analysis_job_records(
            owner_id=str(subject.get("user_id") or ""),
            session_id=query.session_id,
        )

    return ListAnalysisJobsResult(payload={"jobs": list(jobs)})


def execute_get_analysis_job_detail(
    query: GetAnalysisJobDetailQuery,
) -> GetAnalysisJobDetailResult:
    """Authorize and load a public AnalysisJob detail projection."""

    trusted_identity = _trusted_identity(query.identity_payload)
    _subject_with_guest_policy(
        trusted_identity,
        canonical_request=query.canonical_request,
        guest_violation_resolver=query.guest_violation_resolver,
    )
    try:
        _authorize_analysis_job(query.job_id, trusted_identity)
    except AnalysisJobAccessMetadataMissing:
        raise AnalysisJobNotFound()
    outcome = load_analysis_job_detail(
        query.job_id,
        load_job=get_analysis_job_record,
        load_progress=read_analysis_job_progress,
    )
    if outcome.kind == "not_found":
        raise AnalysisJobNotFound()
    return GetAnalysisJobDetailResult(payload=outcome.payload)


def execute_get_analysis_result(
    query: GetAnalysisResultQuery,
) -> GetAnalysisResultResult:
    """Authorize and load the persisted pending or terminal result state."""

    trusted_identity = _trusted_identity(query.identity_payload)
    _subject_with_guest_policy(
        trusted_identity,
        canonical_request=query.canonical_request,
        guest_violation_resolver=query.guest_violation_resolver,
    )
    try:
        _authorize_analysis_job(query.job_id, trusted_identity)
    except AnalysisJobAccessMetadataMissing:
        raise AnalysisResultNotFound()
    outcome = load_analysis_result(
        query.job_id,
        load_job=get_analysis_job_record,
        compose_response=compose_agent_response,
    )
    if outcome.kind == "not_found":
        raise AnalysisResultNotFound()
    return GetAnalysisResultResult(
        payload=outcome.payload,
        pending=outcome.kind == "pending",
    )


def _subject_with_guest_policy(
    identity_payload: Mapping[str, Any],
    *,
    canonical_request: bool,
    guest_violation_resolver: GuestViolationResolver,
) -> dict[str, Any]:
    subject = access_subject_from_payload(dict(identity_payload))["subject"]
    if canonical_request:
        violation = guest_violation_resolver(subject)
        if violation:
            raise AnalysisReadGuestIdentityInvalid(violation)
    return subject


def _trusted_identity(
    identity_payload: Mapping[str, Any],
    session_id: str | None = None,
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


def _authorize_analysis_job(
    job_id: str,
    identity_payload: dict[str, Any],
) -> None:
    metadata = get_analysis_job_access_metadata(job_id)
    if metadata is None:
        raise AnalysisJobAccessMetadataMissing()
    access = _authorize_analysis_job_metadata(metadata, identity_payload)
    if not access["allowed"]:
        raise AnalysisReadAccessDenied(access)


def _authorized_analysis_job_summaries(
    summaries: list[Mapping[str, Any]],
    identity_payload: dict[str, Any],
) -> list[Mapping[str, Any]]:
    """Return only session candidates individually authorized for this subject."""

    authorized: list[Mapping[str, Any]] = []
    for summary in summaries:
        job_id = str(summary.get("job_id") or "").strip()
        if not job_id:
            continue
        metadata = get_analysis_job_access_metadata(job_id)
        if metadata is None:
            continue
        access = _authorize_analysis_job_metadata(metadata, identity_payload)
        if access["allowed"]:
            authorized.append(summary)
    return authorized


def _authorize_analysis_job_metadata(
    metadata: Mapping[str, Any],
    identity_payload: dict[str, Any],
) -> dict[str, Any]:
    """Apply explicit job ownership before legacy session compatibility."""

    owner_id = str(metadata.get("owner_id") or "").strip()
    if owner_id:
        return authorize_resource_access(dict(metadata), identity_payload)
    session_id = str(metadata.get("session_id") or "").strip()
    return _authorize_session_query(
        session_id,
        identity_payload,
        resource_type="analysis_result",
    )


def _authorize_session_query(
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


def _unknown_session_access() -> dict[str, Any]:
    return {
        "contract_version": "object_access.v1",
        "allowed": False,
        "reason": "not_found_or_forbidden",
        "resource": {"type": "chat_session"},
    }
