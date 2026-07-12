"""Persistence boundary for versioned traffic-dispute consultation cases."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from app.services.consultation_v2_service import CORE_FACT_QUESTIONS
from chatbot.models import (
    AnalysisJob,
    Case,
    CaseStatus,
    ChatSession,
    ConfirmedFactVersion,
)
from chatbot.retention_policy import upload_retention_expires_at
from chatbot.repositories import enqueue_analysis_job_work


class CaseRepositoryError(Exception):
    code = "case_repository_error"
    status = 400

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class CaseNotFound(CaseRepositoryError):
    code = "case_not_found"
    status = 404


class CaseConflict(CaseRepositoryError):
    code = "case_conflict"
    status = 409


class CaseOwnerMismatch(CaseRepositoryError):
    code = "case_owner_mismatch"
    status = 403


class ConfirmedFactsRequired(CaseConflict):
    code = "confirmed_facts_required"


class FactReadinessNotMet(CaseConflict):
    code = "fact_readiness_not_met"


def create_case(*, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not _text(owner_id):
        raise CaseOwnerMismatch("authenticated owner_id is required")
    session_id = _text(payload.get("session_id"))
    if not session_id:
        raise CaseConflict("session_id is required")

    with transaction.atomic():
        session = ChatSession.objects.select_for_update().filter(session_id=session_id).first()
        if session is None:
            raise CaseNotFound("chat session was not found")
        if session.owner_id and session.owner_id != owner_id:
            raise CaseOwnerMismatch("chat session belongs to another user")
        if session.case_id:
            if session.case.owner_id != owner_id:
                raise CaseOwnerMismatch("case belongs to another user")
            return case_to_api(session.case)

        consultation_state = _dict(payload.get("consultation_state"))
        risk_level = _text(_dict(consultation_state.get("risk_gate")).get("level")) or "standard"
        status = (
            CaseStatus.HIGH_RISK_HANDOFF
            if risk_level == "high_risk"
            else CaseStatus.AWAITING_FACT_CONFIRMATION
        )
        case = Case.objects.create(
            case_id=f"case_{uuid4().hex[:20]}",
            owner_id=owner_id,
            title=_text(payload.get("title")) or session.title or "교통사고 초기상담",
            case_type=_text(payload.get("case_type")) or "accident_fault",
            status=status,
            risk_level=risk_level,
            location=_dict(payload.get("location")),
            metadata={
                "contract_version": "consultation_case.v2",
                "source_session_id": session.session_id,
                "consultation_state": consultation_state,
            },
        )
        session.owner_id = owner_id
        session.case = case
        session.save(update_fields=["owner_id", "case", "updated_at"])
        session.analysis_jobs.update(case=case)
        session.reports.update(case=case)
        for uploaded_file in session.uploaded_files.filter(deleted_at__isnull=True):
            uploaded_file.case = case
            uploaded_file.retention_expires_at = upload_retention_expires_at(
                owner_id=owner_id,
                file_type=uploaded_file.file_type,
                content_type=uploaded_file.content_type,
            )
            uploaded_file.save(update_fields=["case", "retention_expires_at", "updated_at"])
    return case_to_api(case)


def list_cases(*, owner_id: str) -> list[dict[str, Any]]:
    return [case_to_api(case) for case in Case.objects.filter(owner_id=owner_id, deleted_at__isnull=True)]


def get_case_access_metadata(case_id: str) -> dict[str, Any] | None:
    case = Case.objects.filter(case_id=case_id, deleted_at__isnull=True).first()
    if case is None:
        return None
    return {"type": "case", "case_id": case.case_id, "owner_id": case.owner_id}


def get_case_workspace(case_id: str) -> dict[str, Any]:
    case = Case.objects.filter(case_id=case_id, deleted_at__isnull=True).first()
    if case is None:
        raise CaseNotFound("case was not found")
    facts = [fact_version_to_api(version) for version in case.fact_versions.all()]
    jobs = [
        {
            "job_id": job.job_id,
            "status": job.status,
            "active_node": job.active_node,
            "updated_at": job.updated_at.isoformat(),
        }
        for job in case.analysis_jobs.all().order_by("-created_at")
    ]
    reports = [
        {
            "report_id": report.report_id,
            "report_type": report.report_type,
            "version_no": report.version_no,
            "status": report.status,
        }
        for report in case.reports.all().order_by("-version_no", "-created_at")
    ]
    return {
        "contract_version": "case_workspace.v2",
        "case": case_to_api(case),
        "consultation_state": _dict(case.metadata).get("consultation_state") or {},
        "confirmed_facts": facts,
        "analysis_jobs": jobs,
        "reports": reports,
        "attachments": [
            {
                "attachment_id": item.attachment_id,
                "status": item.status,
                "purpose": item.purpose,
                "retention_expires_at": (
                    item.retention_expires_at.isoformat() if item.retention_expires_at else None
                ),
            }
            for item in case.uploaded_files.filter(deleted_at__isnull=True)
        ],
    }


def confirm_case_facts(
    case_id: str,
    *,
    owner_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    facts = _dict(payload.get("facts"))
    if not facts:
        raise CaseConflict("facts are required")

    with transaction.atomic():
        case = Case.objects.select_for_update().filter(case_id=case_id, deleted_at__isnull=True).first()
        if case is None:
            raise CaseNotFound("case was not found")
        if case.owner_id != owner_id:
            raise CaseOwnerMismatch("case belongs to another user")
        next_version = case.current_fact_version + 1
        fact_version = ConfirmedFactVersion.objects.create(
            fact_version_id=f"fact_{uuid4().hex[:20]}",
            case=case,
            version_no=next_version,
            status="confirmed",
            facts=facts,
            sources=_dict_list(payload.get("sources")),
            conflicts=_dict_list(payload.get("conflicts")),
            user_edit_history=_dict_list(payload.get("user_edit_history")),
            confirmed_by=owner_id,
            confirmed_at=timezone.now(),
        )
        case.current_fact_version = next_version
        case.status = CaseStatus.INTAKE
        case.save(update_fields=["current_fact_version", "status", "updated_at"])
    return fact_version_to_api(fact_version)


def start_case_analysis(
    case_id: str,
    *,
    owner_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    with transaction.atomic():
        case = Case.objects.select_for_update().filter(
            case_id=case_id,
            deleted_at__isnull=True,
        ).first()
        if case is None:
            raise CaseNotFound("case was not found")
        if case.owner_id != owner_id:
            raise CaseOwnerMismatch("case belongs to another user")
        if case.risk_level == "high_risk":
            raise CaseConflict("high-risk cases require expert handoff")

        requested_fact_version_id = _text(payload.get("fact_version_id"))
        fact_query = case.fact_versions.filter(status="confirmed")
        if requested_fact_version_id:
            fact_query = fact_query.filter(fact_version_id=requested_fact_version_id)
        fact_version = fact_query.order_by("-version_no").first()
        if fact_version is None:
            raise ConfirmedFactsRequired("confirmed facts are required before analysis")
        required_fields = [field for field, _question in CORE_FACT_QUESTIONS]
        missing_fields = [field for field in required_fields if not _text(fact_version.facts.get(field))]
        if missing_fields or fact_version.conflicts:
            raise FactReadinessNotMet(
                "confirmed facts do not meet the analysis readiness gate",
                details={
                    "required_fields": required_fields,
                    "missing_fields": missing_fields,
                    "conflict_count": len(fact_version.conflicts),
                },
            )

        session = case.chat_sessions.order_by("created_at").first()
        if session is None:
            raise CaseConflict("case has no chat session")
        plan_id = f"plan_{uuid4().hex[:16]}"
        job_id = f"job_{uuid4().hex[:16]}"
        node_codes = ["text_ml_case_search", "law_ground_search"]
        analysis_plan = {
            "contract_version": "analysis_plan.v2",
            "plan_id": plan_id,
            "routing_intent": "fault_ratio_text",
            "case_id": case.case_id,
            "fact_version_id": fact_version.fact_version_id,
            "steps": [
                {
                    "order": index,
                    "node_code": node_code,
                    "status": "ready",
                    "execution_mode": "sync",
                    "depends_on": [node_codes[index - 2]] if index > 1 else [],
                    "required_inputs": ["confirmed_facts.v1"],
                }
                for index, node_code in enumerate(node_codes, start=1)
            ],
        }
        request_payload = {
            "owner_id": owner_id,
            "user_id": owner_id,
            "session_id": session.session_id,
            "case_id": case.case_id,
            "confirmed_facts": fact_version_to_api(fact_version),
        }
        job_payload = {
            "job_id": job_id,
            "session_id": session.session_id,
            "routing_intent": "fault_ratio_text",
            "status": "queued",
            "active_node": node_codes[0],
            "progress_message": "Confirmed facts queued for case analysis.",
            "analysis_plan_id": plan_id,
            "analysis_plan": analysis_plan,
            "chat_response": {
                "case_status": CaseStatus.QUEUED,
                "reporting_payload": {
                    "contract_version": "reporting_payload.v2",
                    "report_type": "initial_consultation",
                    "case_id": case.case_id,
                    "fact_version_id": fact_version.fact_version_id,
                },
            },
            "node_execution": {},
        }
        queue = enqueue_analysis_job_work(request_payload, job_payload)
        job = AnalysisJob.objects.get(job_id=queue["job_id"])
        job.case = case
        job.metadata = {
            **_dict(job.metadata),
            "case_id": case.case_id,
            "fact_version_id": fact_version.fact_version_id,
            "confirmed_facts_schema": "confirmed_facts.v1",
        }
        job.save(update_fields=["case", "metadata", "updated_at"])
        case.status = CaseStatus.QUEUED
        case.save(update_fields=["status", "updated_at"])

    return {
        "contract_version": "case_analysis_job.v2",
        "job": {"job_id": job.job_id, "status": job.status},
        "work_item": {
            "work_item_id": queue["work_item_id"],
            "status": queue["work_item_status"],
        },
        "analysis_plan": {"plan_id": plan_id, "node_codes": node_codes},
    }


def case_to_api(case: Case) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "owner_id": case.owner_id,
        "title": case.title,
        "case_type": case.case_type,
        "status": case.status,
        "risk_level": case.risk_level,
        "location": case.location,
        "current_fact_version": case.current_fact_version,
        "current_report_version": case.current_report_version,
        "created_at": case.created_at.isoformat(),
        "updated_at": case.updated_at.isoformat(),
    }


def fact_version_to_api(version: ConfirmedFactVersion) -> dict[str, Any]:
    return {
        "schema_version": "confirmed_facts.v1",
        "fact_version_id": version.fact_version_id,
        "case_id": version.case.case_id,
        "version_no": version.version_no,
        "status": version.status,
        "facts": version.facts,
        "sources": version.sources,
        "conflicts": version.conflicts,
        "user_edit_history": version.user_edit_history,
        "confirmed_by": version.confirmed_by,
        "confirmed_at": version.confirmed_at.isoformat() if version.confirmed_at else None,
    }


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value or [] if isinstance(item, dict)]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""
