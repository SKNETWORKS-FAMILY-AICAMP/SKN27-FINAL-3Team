"""Application query for restoring an authenticated user's latest consultation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.services.analysis_job_query_service import load_analysis_job_detail
from app.services.resume_manifest_service import build_resume_manifest
from chatbot.progress_cache import read_analysis_job_progress
from chatbot.repositories import (
    access_subject_from_payload,
    get_analysis_job_record,
    get_latest_owned_chat_session_record,
)


@dataclass(frozen=True)
class ResumeLatestConsultationQuery:
    identity_payload: Mapping[str, Any]


@dataclass(frozen=True)
class ResumeLatestConsultationResult:
    payload: dict[str, Any]


class ResumeLatestConsultationLoginRequired(Exception):
    def __init__(self, subject: Mapping[str, Any]) -> None:
        super().__init__("resume latest consultation requires an authenticated user")
        self.subject = dict(subject)


def execute_resume_latest_consultation(
    query: ResumeLatestConsultationQuery,
) -> ResumeLatestConsultationResult:
    """Restore only the newest session and newest analysis owned by one user."""

    subject = access_subject_from_payload(dict(query.identity_payload))["subject"]
    if subject.get("subject_type") != "user":
        raise ResumeLatestConsultationLoginRequired(subject)

    session_record = get_latest_owned_chat_session_record(
        str(subject.get("user_id") or "")
    )
    analysis_detail = None
    latest_job_id = (
        str(session_record.get("latest_job_id") or "")
        if isinstance(session_record, dict)
        else ""
    )
    if latest_job_id:
        outcome = load_analysis_job_detail(
            latest_job_id,
            load_job=get_analysis_job_record,
            load_progress=read_analysis_job_progress,
        )
        if outcome.kind == "detail":
            analysis_detail = outcome.payload

    return ResumeLatestConsultationResult(
        payload=build_resume_manifest(
            session_record=session_record,
            analysis_detail=analysis_detail,
        )
    )
