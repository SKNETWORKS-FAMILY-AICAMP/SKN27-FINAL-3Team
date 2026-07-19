"""Persistence boundary for versioned traffic-dispute consultation cases."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from app.services.case_evidence_service import (
    build_case_evidence,
    case_evidence_readiness,
    material_fact_values,
)
from app.services.consultation_v2_service import CORE_FACT_QUESTIONS
from chatbot.models import (
    AgentWorkItemStatus,
    AnalysisJob,
    AnalysisJobStatus,
    Case,
    CaseStatus,
    ChatSession,
    ConfirmedFactVersion,
    UploadedFileStatus,
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


class CaseAnalysisInProgress(CaseConflict):
    code = "case_analysis_in_progress"


def create_case(
    *,
    owner_id: str,
    payload: dict[str, Any],
    guest_id: str = "",
) -> dict[str, Any]:
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
        if not session.owner_id:
            session_guest_id = _session_guest_id(session)
            if not session_guest_id:
                raise CaseOwnerMismatch("guest session binding is required")
            if session_guest_id != _text(guest_id):
                raise CaseOwnerMismatch("guest session belongs to another guest identity")
        if session.case_id:
            if session.case.owner_id != owner_id:
                raise CaseOwnerMismatch("case belongs to another user")
            return case_to_api(session.case)

        active_job = (
            session.analysis_jobs.filter(
                Q(status=AnalysisJobStatus.RUNNING.value)
                | Q(metadata__source="canonical_analysis_job_reservation")
            )
            .order_by("created_at")
            .values_list("job_id", flat=True)
            .first()
        )
        active_work_job = (
            session.analysis_jobs.filter(
                work_items__status__in=[
                    AgentWorkItemStatus.QUEUED.value,
                    AgentWorkItemStatus.RUNNING.value,
                    AgentWorkItemStatus.RETRYING.value,
                ]
            )
            .order_by("created_at")
            .values_list("job_id", flat=True)
            .first()
        )
        blocking_job_id = active_job or active_work_job
        if blocking_job_id:
            raise CaseAnalysisInProgress(
                "case creation must wait for the active session analysis to finish",
                details={"job_id": blocking_job_id, "retryable": True},
            )

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
        _validate_promotable_session_records(session, owner_id=owner_id)
        session.owner_id = owner_id
        session.case = case
        session.save(update_fields=["owner_id", "case", "updated_at"])
        session.analysis_jobs.update(case=case, owner_id=owner_id)
        reports = list(session.reports.select_for_update().order_by("created_at", "id"))
        for version_no, report in enumerate(reports, start=1):
            old_version = report.version_no
            metadata = dict(report.metadata or {})
            metadata["guest_promotion"] = {
                "guest_id": _text(guest_id),
                "owner_id": owner_id,
                "old_version": old_version,
                "new_version": version_no,
            }
            report.owner_id = owner_id
            report.case = case
            report.version_no = version_no
            report.metadata = metadata
            report.save(
                update_fields=[
                    "owner_id",
                    "case",
                    "version_no",
                    "metadata",
                    "updated_at",
                ]
            )
        case.current_report_version = len(reports)
        if reports:
            case.save(update_fields=["current_report_version", "updated_at"])
        for uploaded_file in session.uploaded_files.filter(deleted_at__isnull=True):
            uploaded_file.owner_id = owner_id
            uploaded_file.case = case
            uploaded_file.retention_expires_at = upload_retention_expires_at(
                owner_id=owner_id,
                file_type=uploaded_file.file_type,
                content_type=uploaded_file.content_type,
            )
            uploaded_file.save(
                update_fields=[
                    "owner_id",
                    "case",
                    "retention_expires_at",
                    "updated_at",
                ]
            )
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
    fact_versions = list(case.fact_versions.all())
    facts = [fact_version_to_api(version) for version in fact_versions]
    latest_fact_version = max(fact_versions, key=lambda version: version.version_no, default=None)
    case_evidence = (
        build_case_evidence(
            facts=_dict(latest_fact_version.facts),
            sources=_dict_list(latest_fact_version.sources),
            conflicts=_dict_list(latest_fact_version.conflicts),
            material_source_refs=_ready_case_attachment_ids(case),
        )
        if latest_fact_version is not None
        else build_case_evidence(facts={}, sources=[], conflicts=[])
    )
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
        "case_evidence": case_evidence,
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
    sources = _dict_list(payload.get("sources"))
    conflicts = _dict_list(payload.get("conflicts"))
    user_edit_history = _dict_list(payload.get("user_edit_history"))
    request_fingerprint = _confirmed_fact_payload_fingerprint(
        facts=facts,
        sources=sources,
        conflicts=conflicts,
        user_edit_history=user_edit_history,
    )

    with transaction.atomic():
        case = Case.objects.select_for_update().filter(case_id=case_id, deleted_at__isnull=True).first()
        if case is None:
            raise CaseNotFound("case was not found")
        if case.owner_id != owner_id:
            raise CaseOwnerMismatch("case belongs to another user")
        case_metadata = _dict(case.metadata)
        confirmation = _dict(case_metadata.get("fact_confirmation"))
        if confirmation.get("request_fingerprint") == request_fingerprint:
            existing_version = case.fact_versions.filter(
                fact_version_id=_text(confirmation.get("fact_version_id")),
                status="confirmed",
            ).first()
            if existing_version is not None:
                return fact_version_to_api(existing_version)
        latest_version = case.fact_versions.filter(status="confirmed").order_by(
            "-version_no"
        ).first()
        if latest_version is not None and request_fingerprint == _confirmed_fact_payload_fingerprint(
            facts=_dict(latest_version.facts),
            sources=_dict_list(latest_version.sources),
            conflicts=_dict_list(latest_version.conflicts),
            user_edit_history=_dict_list(latest_version.user_edit_history),
        ):
            case_metadata["fact_confirmation"] = {
                "contract_version": "confirmed_facts_idempotency.v1",
                "request_fingerprint": request_fingerprint,
                "fact_version_id": latest_version.fact_version_id,
            }
            case.metadata = case_metadata
            case.save(update_fields=["metadata", "updated_at"])
            return fact_version_to_api(latest_version)
        next_version = case.current_fact_version + 1
        fact_version = ConfirmedFactVersion.objects.create(
            fact_version_id=f"fact_{uuid4().hex[:20]}",
            case=case,
            version_no=next_version,
            status="confirmed",
            facts=facts,
            sources=sources,
            conflicts=conflicts,
            user_edit_history=user_edit_history,
            confirmed_by=owner_id,
            confirmed_at=timezone.now(),
        )
        case.current_fact_version = next_version
        case.status = CaseStatus.INTAKE
        case.metadata = {
            **case_metadata,
            "active_analysis_job_id": "",
            "active_fact_version_id": fact_version.fact_version_id,
            "fact_confirmation": {
                "contract_version": "confirmed_facts_idempotency.v1",
                "request_fingerprint": request_fingerprint,
                "fact_version_id": fact_version.fact_version_id,
            },
        }
        case.save(
            update_fields=[
                "current_fact_version",
                "status",
                "metadata",
                "updated_at",
            ]
        )
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
        case_evidence = build_case_evidence(
            facts=_dict(fact_version.facts),
            sources=_dict_list(fact_version.sources),
            conflicts=_dict_list(fact_version.conflicts),
            material_source_refs=_ready_case_attachment_ids(case),
        )
        readiness = case_evidence_readiness(case_evidence)
        if not readiness["ready"]:
            raise FactReadinessNotMet(
                "material evidence does not meet the analysis readiness gate",
                details={
                    **readiness,
                    "conflict_count": len(fact_version.conflicts),
                },
            )

        session = case.chat_sessions.order_by("created_at").first()
        if session is None:
            raise CaseConflict("case has no chat session")
        case_metadata = _dict(case.metadata)
        active_job_id = _text(case_metadata.get("active_analysis_job_id"))
        reusable_jobs = case.analysis_jobs.filter(
            metadata__fact_version_id=fact_version.fact_version_id,
            status__in=[
                "queued",
                "running",
                "success",
                "partial",
            ],
            work_items__isnull=False,
        )
        if active_job_id:
            reusable_jobs = reusable_jobs.filter(job_id=active_job_id)
        reusable_job = reusable_jobs.order_by("-created_at").distinct().first()
        if reusable_job is not None:
            reusable_work_item = reusable_job.work_items.order_by("created_at").first()
            if reusable_work_item is not None:
                return _case_analysis_job_response(reusable_job, reusable_work_item)

        plan_id = f"plan_{uuid4().hex[:16]}"
        job_id = f"job_{uuid4().hex[:16]}"
        node_codes = [
            "text_ml_case_search",
            "law_ground_search",
            "objection_report_generation",
        ]
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
                    "required_inputs": ["confirmed_facts.v1", "case_evidence.v1"],
                }
                for index, node_code in enumerate(node_codes, start=1)
            ],
        }
        material_user_facts = json.dumps(
            material_fact_values(case_evidence),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        request_payload = {
            "owner_id": owner_id,
            "user_id": owner_id,
            "session_id": session.session_id,
            "case_id": case.case_id,
            "user_text": material_user_facts,
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
                    "report_type": "fault_ratio_analysis",
                    "case_id": case.case_id,
                    "fact_version_id": fact_version.fact_version_id,
                },
            },
            "node_execution": {},
        }
        queue = enqueue_analysis_job_work(
            request_payload,
            job_payload,
            server_execution_context={
                "user_facts": material_user_facts,
                "case_evidence": case_evidence,
            },
        )
        job = AnalysisJob.objects.get(job_id=queue["job_id"])
        job.case = case
        job.metadata = {
            **_dict(job.metadata),
            "case_id": case.case_id,
            "fact_version_id": fact_version.fact_version_id,
            "confirmed_facts_schema": "confirmed_facts.v1",
            "case_evidence_schema": "case_evidence.v1",
        }
        job.save(update_fields=["case", "metadata", "updated_at"])
        case.status = CaseStatus.QUEUED
        case.metadata = {
            **case_metadata,
            "active_analysis_job_id": job.job_id,
            "active_fact_version_id": fact_version.fact_version_id,
        }
        case.save(update_fields=["status", "metadata", "updated_at"])

    return {
        "contract_version": "case_analysis_job.v2",
        "job": {"job_id": job.job_id, "status": job.status},
        "work_item": {
            "work_item_id": queue["work_item_id"],
            "status": queue["work_item_status"],
        },
        "analysis_plan": {"plan_id": plan_id, "node_codes": node_codes},
    }


def _case_analysis_job_response(job: AnalysisJob, work_item: Any) -> dict[str, Any]:
    analysis_plan = _dict(_dict(job.metadata).get("analysis_plan"))
    node_codes = [
        _text(step.get("node_code"))
        for step in analysis_plan.get("steps") or []
        if isinstance(step, dict) and _text(step.get("node_code"))
    ]
    return {
        "contract_version": "case_analysis_job.v2",
        "job": {"job_id": job.job_id, "status": job.status},
        "work_item": {
            "work_item_id": work_item.work_item_id,
            "status": work_item.status,
        },
        "analysis_plan": {
            "plan_id": job.analysis_plan_id or _text(analysis_plan.get("plan_id")),
            "node_codes": node_codes,
        },
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


def _ready_case_attachment_ids(case: Case) -> set[str]:
    return {
        _text(attachment_id)
        for attachment_id in case.uploaded_files.filter(
            status=UploadedFileStatus.READY.value,
            deleted_at__isnull=True,
        ).values_list("attachment_id", flat=True)
        if _text(attachment_id)
    }


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value or [] if isinstance(item, dict)]


def _confirmed_fact_payload_fingerprint(
    *,
    facts: dict[str, Any],
    sources: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    user_edit_history: list[dict[str, Any]],
) -> str:
    encoded = json.dumps(
        {
            "facts": facts,
            "sources": sources,
            "conflicts": conflicts,
            "user_edit_history": user_edit_history,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _session_guest_id(session: ChatSession) -> str:
    metadata = session.metadata if isinstance(session.metadata, dict) else {}
    auth_context = (
        metadata.get("auth_context")
        if isinstance(metadata.get("auth_context"), dict)
        else {}
    )
    return _text(auth_context.get("guest_id"))


def _validate_promotable_session_records(session: ChatSession, *, owner_id: str) -> None:
    related_querysets = (
        session.analysis_jobs.all(),
        session.reports.all(),
        session.uploaded_files.filter(deleted_at__isnull=True),
    )
    for queryset in related_querysets:
        if queryset.exclude(owner_id__in=["", owner_id]).exists():
            raise CaseOwnerMismatch("session contains data owned by another user")
        if queryset.exclude(case_id__isnull=True).exists():
            raise CaseOwnerMismatch("session contains data linked to another case")
