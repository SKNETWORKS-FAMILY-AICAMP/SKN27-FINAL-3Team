"""Persistence boundary for the additive consultation Case API."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from chatbot.models import (
    AnalysisJob,
    Case,
    CaseNotificationPreference,
    CaseStatus,
    ChatSession,
    ConfirmedFactVersion,
    MediaArtifact,
    Report,
    UploadedFile,
    UploadedFileStatus,
)


STAGING_NEW_CASES_PER_DAY = 3
STAGING_ANALYSIS_ATTEMPTS_PER_CASE = 3
RAW_MEDIA_RETENTION_DAYS = 30


class CaseQuotaExceeded(ValueError):
    pass


class CaseConflict(ValueError):
    pass


def create_case(payload: dict[str, Any], *, owner_id: str) -> dict[str, Any]:
    if not owner_id:
        raise ValueError("authenticated owner_id is required")
    _enforce_daily_case_quota(owner_id)

    session_id = str(payload.get("session_id") or "").strip()
    session = ChatSession.objects.filter(session_id=session_id).first() if session_id else None
    if session is not None and session.owner_id and session.owner_id != owner_id:
        raise PermissionError("session owner does not match authenticated owner")

    consultation_state = _dict(payload.get("consultation_state"))
    state_v2 = _dict(consultation_state.get("v2") or consultation_state)
    risk_gate = _dict(state_v2.get("risk_gate"))
    high_risk = risk_gate.get("decision") == "high_risk_handoff"
    now = timezone.now()

    with transaction.atomic():
        case = Case.objects.create(
            case_id=f"case_{uuid4().hex[:20]}",
            owner_id=owner_id,
            title=str(payload.get("title") or (session.title if session else "") or "교통사고 과실 초기상담")[:200],
            case_type=str(payload.get("case_type") or "fault_ratio")[:64],
            status=(
                CaseStatus.HIGH_RISK_HANDOFF.value
                if high_risk
                else CaseStatus.AWAITING_FACT_CONFIRMATION.value
            ),
            risk_level="high" if high_risk else str(risk_gate.get("level") or "standard"),
            location=_dict(payload.get("location")),
            metadata={
                "contract_version": "case.v2",
                "source_session_id": session_id or None,
                "consultation_state": state_v2,
                "created_from_guest_consultation": bool(session_id),
            },
        )
        CaseNotificationPreference.objects.create(
            case=case,
            email_enabled=bool(payload.get("email_notification_enabled", False)),
            email_address=str(payload.get("notification_email") or "")[:254],
            consented_at=now if payload.get("email_notification_enabled") else None,
        )
        if session is not None:
            if not session.owner_id:
                session.owner_id = owner_id
            session.case = case
            session.save(update_fields=["owner_id", "case", "updated_at"])
            UploadedFile.objects.filter(session=session).update(
                case=case,
                owner_id=owner_id,
                retention_expires_at=now + timedelta(days=RAW_MEDIA_RETENTION_DAYS),
            )
            AnalysisJob.objects.filter(session=session).update(case=case, owner_id=owner_id)
            Report.objects.filter(session=session).update(case=case, owner_id=owner_id)

    return case_to_api(case)


def list_cases(*, owner_id: str) -> list[dict[str, Any]]:
    return [
        case_to_api(case)
        for case in Case.objects.filter(owner_id=owner_id)
        .exclude(status=CaseStatus.DELETED.value)
        .order_by("-updated_at")
    ]


def get_case_access_metadata(case_id: str) -> dict[str, Any] | None:
    case = Case.objects.filter(case_id=case_id).first()
    if case is None:
        return None
    return {"type": "case", "case_id": case.case_id, "owner_id": case.owner_id}


def get_case_workspace(case_id: str) -> dict[str, Any] | None:
    case = Case.objects.filter(case_id=case_id).first()
    if case is None or case.status == CaseStatus.DELETED.value:
        return None

    latest_fact = case.fact_versions.order_by("-version_no").first()
    jobs = case.analysis_jobs.order_by("-created_at")
    latest_job = jobs.first()
    reports = case.reports.exclude(status="deleted").order_by("-version_no", "-created_at")
    files = case.uploaded_files.filter(deleted_at__isnull=True).order_by("-created_at")
    artifacts = case.media_artifacts.filter(deleted_at__isnull=True).order_by("created_at")
    state = _dict(_dict(case.metadata).get("consultation_state"))
    readiness = _dict(state.get("readiness"))
    immediate_actions = list(_dict(state.get("risk_gate")).get("immediate_actions") or [])

    return {
        "schema_version": "case_workspace.v2",
        "case": case_to_api(case),
        "summary": {
            "immediate_actions": immediate_actions,
            "current_assessment": _current_assessment(case, reports.first()),
            "evidence_readiness": readiness,
            "analysis_status": _analysis_status(case, latest_job),
        },
        "confirmed_facts": confirmed_fact_to_api(latest_fact) if latest_fact else None,
        "fact_cards": list(state.get("fact_cards") or []),
        "annotated_frames": [media_artifact_to_api(item) for item in artifacts[:3]],
        "accident_diagram": {
            "format": "svg",
            "generated_from": "confirmed_facts",
            "svg": _accident_svg(),
            "is_generative_image": False,
        },
        "fault_assessment": _fault_assessment(latest_job, readiness),
        "external_evidence": _external_evidence(latest_job),
        "missing_materials": _missing_materials(readiness),
        "files": [uploaded_file_to_case_api(item) for item in files],
        "analysis_jobs": [analysis_job_to_case_api(item) for item in jobs[:10]],
        "reports": [report_to_case_api(item) for item in reports],
        "report_generation": "automatic_after_analysis",
    }


def confirm_case_facts(case_id: str, payload: dict[str, Any], *, confirmed_by: str) -> dict[str, Any]:
    facts = payload.get("facts")
    if not isinstance(facts, dict) or not facts:
        raise ValueError("facts must be a non-empty object")

    with transaction.atomic():
        case = Case.objects.select_for_update().filter(case_id=case_id).first()
        if case is None:
            raise LookupError("case not found")
        latest = case.fact_versions.aggregate(value=Max("version_no"))["value"] or 0
        version = ConfirmedFactVersion.objects.create(
            fact_version_id=f"fact_{uuid4().hex[:20]}",
            case=case,
            version_no=latest + 1,
            status="confirmed",
            facts=facts,
            sources=list(payload.get("sources") or []),
            conflicts=list(payload.get("conflicts") or []),
            user_edit_history=list(payload.get("user_edit_history") or []),
            confirmed_by=confirmed_by,
            confirmed_at=timezone.now(),
        )
        case.current_fact_version = version.version_no
        case.status = (
            CaseStatus.NEEDS_INPUT.value
            if version.conflicts
            else CaseStatus.QUEUED.value
        )
        case.save(update_fields=["current_fact_version", "status", "updated_at"])
    return confirmed_fact_to_api(version)


def start_case_analysis(case_id: str, payload: dict[str, Any], *, owner_id: str) -> dict[str, Any]:
    from chatbot.repositories import enqueue_analysis_job_work

    case = Case.objects.filter(case_id=case_id).first()
    if case is None:
        raise LookupError("case not found")
    fact = case.fact_versions.order_by("-version_no").first()
    if fact is None:
        raise CaseConflict("confirmed facts are required before analysis")
    attempt_count = case.analysis_jobs.count()
    if attempt_count >= STAGING_ANALYSIS_ATTEMPTS_PER_CASE:
        raise CaseQuotaExceeded("case analysis quota exceeded")
    session = case.chat_sessions.order_by("-updated_at").first()
    if session is None:
        session = ChatSession.objects.create(
            session_id=f"ses_{uuid4().hex[:20]}",
            owner_id=owner_id,
            case=case,
            title=case.title,
            status="active",
            current_intent="fault_ratio",
            metadata={"source": "case_analysis"},
        )

    job_id = f"job_{uuid4().hex[:20]}"
    work_payload = {
        "user_id": owner_id,
        "owner_id": owner_id,
        "session_id": session.session_id,
        "case_id": case.case_id,
        "confirmed_fact_version_id": fact.fact_version_id,
        "idempotency_key": str(payload.get("idempotency_key") or f"{case.case_id}:{fact.version_no}:{attempt_count + 1}"),
    }
    job_payload = {
        "job_id": job_id,
        "session_id": session.session_id,
        "routing_intent": "fault_ratio",
        "mock_scenario": "fault_ratio",
        "analysis_plan": _case_analysis_plan(case, fact),
        "analysis_plan_id": f"plan_{job_id}",
        "active_node": "risk_gate",
        "progress_message": "안전·고위험 사건 확인을 시작합니다.",
        "attachments": [uploaded_file_to_case_api(item) for item in case.uploaded_files.filter(deleted_at__isnull=True)],
        "chat_response": {
            "case_status": CaseStatus.QUEUED.value,
            "cards": [],
            "pending_questions": [],
            "report_links": [],
            "reporting_payload": {},
        },
    }
    queued = enqueue_analysis_job_work(work_payload, job_payload, max_attempts=3)
    AnalysisJob.objects.filter(job_id=job_id).update(
        case=case,
        metadata={
            "source": "case_analysis_v2",
            "source_fact_version": fact.fact_version_id,
            "idempotency_key": work_payload["idempotency_key"],
            "work_item_id": queued["work_item_id"],
        },
    )
    case.status = CaseStatus.QUEUED.value
    case.save(update_fields=["status", "updated_at"])
    return {
        "schema_version": "case_analysis_job.v2",
        "case_id": case.case_id,
        "source_fact_version": fact.fact_version_id,
        "analysis_attempt": attempt_count + 1,
        "quota": {"used": attempt_count + 1, "limit": STAGING_ANALYSIS_ATTEMPTS_PER_CASE},
        **queued,
    }


def soft_delete_uploaded_file(attachment_id: str) -> dict[str, Any] | None:
    uploaded_file = UploadedFile.objects.filter(attachment_id=attachment_id).first()
    if uploaded_file is None:
        return None
    now = timezone.now()
    uploaded_file.status = UploadedFileStatus.DELETED.value
    uploaded_file.deleted_at = now
    metadata = _dict(uploaded_file.metadata)
    metadata["deletion"] = {
        "requested_at": now.isoformat(),
        "object_delete_status": "pending_storage_adapter",
        "reason": "user_request",
    }
    uploaded_file.metadata = metadata
    uploaded_file.save(update_fields=["status", "deleted_at", "metadata", "updated_at"])
    uploaded_file.media_artifacts.filter(deleted_at__isnull=True).update(deleted_at=now)
    return uploaded_file_to_case_api(uploaded_file)


def list_reports(*, owner_id: str, case_id: str | None = None) -> list[dict[str, Any]]:
    queryset = Report.objects.filter(owner_id=owner_id).exclude(status="deleted")
    if case_id:
        queryset = queryset.filter(case__case_id=case_id)
    return [report_to_case_api(report) for report in queryset.order_by("-created_at")]


def get_report(report_id: str) -> dict[str, Any] | None:
    report = Report.objects.filter(report_id=report_id).first()
    return report_to_case_api(report, include_content=True) if report else None


def get_report_access_metadata(report_id: str) -> dict[str, Any] | None:
    report = Report.objects.filter(report_id=report_id).first()
    if report is None:
        return None
    return {"type": "report", "report_id": report.report_id, "owner_id": report.owner_id}


def case_to_api(case: Case) -> dict[str, Any]:
    return {
        "schema_version": "case.v2",
        "case_id": case.case_id,
        "title": case.title,
        "case_type": case.case_type,
        "status": case.status,
        "risk_level": case.risk_level,
        "location": case.location,
        "current_fact_version": case.current_fact_version,
        "current_report_version": case.current_report_version,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
    }


def confirmed_fact_to_api(version: ConfirmedFactVersion) -> dict[str, Any]:
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
        "confirmed_at": version.confirmed_at,
    }


def media_artifact_to_api(artifact: MediaArtifact) -> dict[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type,
        "storage_uri": artifact.storage_uri,
        "source_timestamp_ms": artifact.source_timestamp_ms,
        "metadata": artifact.metadata,
        "retention_expires_at": artifact.retention_expires_at,
    }


def uploaded_file_to_case_api(uploaded_file: UploadedFile) -> dict[str, Any]:
    return {
        "attachment_id": uploaded_file.attachment_id,
        "purpose": uploaded_file.purpose,
        "file_type": uploaded_file.file_type,
        "original_filename": uploaded_file.original_filename,
        "content_type": uploaded_file.content_type,
        "size_bytes": uploaded_file.size_bytes,
        "status": uploaded_file.status,
        "scan_status": uploaded_file.scan_status,
        "retention_expires_at": uploaded_file.retention_expires_at,
        "deleted_at": uploaded_file.deleted_at,
    }


def analysis_job_to_case_api(job: AnalysisJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "stage": _public_stage(job.active_node),
        "progress_message": job.progress_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def report_to_case_api(report: Report, *, include_content: bool = False) -> dict[str, Any]:
    payload = {
        "schema_version": "consultation_report.v2",
        "report_id": report.report_id,
        "case_id": report.case.case_id if report.case_id else None,
        "version_no": report.version_no,
        "source_fact_version": report.source_fact_version.fact_version_id if report.source_fact_version_id else None,
        "report_type": report.report_type,
        "status": report.status,
        "title": report.title,
        "content_summary": report.content_summary,
        "download_url": f"/api/reports/{report.report_id}/download/" if report.status == "ready" else None,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }
    if include_content:
        payload["content"] = report.content
        payload["metadata"] = report.metadata
    return payload


def _enforce_daily_case_quota(owner_id: str) -> None:
    now = timezone.localtime()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if Case.objects.filter(owner_id=owner_id, created_at__gte=day_start).count() >= STAGING_NEW_CASES_PER_DAY:
        raise CaseQuotaExceeded("daily new case quota exceeded")


def _case_analysis_plan(case: Case, fact: ConfirmedFactVersion) -> dict[str, Any]:
    has_media = case.uploaded_files.filter(deleted_at__isnull=True).exists()
    node_codes = ["risk_gate", "input_context_validation"]
    if has_media:
        node_codes.append("vision_media_analysis")
    node_codes.extend(
        [
            "road_context_analysis",
            "fact_confirmation",
            "text_ml_case_search",
            "law_ground_search",
            "agent_result_validation",
            "initial_consultation_report_generation",
        ]
    )
    return {
        "contract_version": "analysis_plan.v2",
        "plan_id": f"plan_{uuid4().hex[:16]}",
        "case_id": case.case_id,
        "source_fact_version": fact.fact_version_id,
        "steps": [
            {"node_code": code, "status": "ready", "sequence": index + 1}
            for index, code in enumerate(node_codes)
        ],
    }


def _analysis_status(case: Case, job: AnalysisJob | None) -> dict[str, Any]:
    if job is None:
        return {"status": case.status, "stage": "자료 확인", "message": "분석을 시작하기 전입니다."}
    return {"status": job.status, "stage": _public_stage(job.active_node), "message": job.progress_message}


def _public_stage(node_code: str) -> str:
    if node_code in {"risk_gate", "input_context_validation", "fact_confirmation"}:
        return "자료 확인"
    if node_code in {"vision_media_analysis", "road_context_analysis"}:
        return "장면 분석"
    if node_code in {"text_ml_case_search", "law_ground_search"}:
        return "사례·근거 확인"
    return "요약서 준비"


def _current_assessment(case: Case, report: Report | None) -> dict[str, Any]:
    if case.status == CaseStatus.HIGH_RISK_HANDOFF.value:
        return {"label": "전문가 이관 권장", "fault_range": None, "reason": "high_risk_handoff"}
    if report and isinstance(report.content, dict):
        return _dict(report.content.get("fault_assessment")) or {"label": report.content_summary}
    return {"label": "분석 전", "fault_range": None, "reason": "analysis_not_completed"}


def _fault_assessment(job: AnalysisJob | None, readiness: dict[str, Any]) -> dict[str, Any]:
    if not readiness.get("fault_range_allowed"):
        return {
            "schema_version": "fault_assessment.v2",
            "fault_range": None,
            "unavailable_reason": readiness.get("reason") or "insufficient_confirmed_facts",
            "change_factors": [],
            "evidence_readiness": readiness,
        }
    return {
        "schema_version": "fault_assessment.v2",
        "fault_range": None,
        "unavailable_reason": "analysis_in_progress" if job and job.status in {"queued", "running"} else "validated_result_not_available",
        "change_factors": [],
        "evidence_readiness": readiness,
    }


def _external_evidence(job: AnalysisJob | None) -> list[dict[str, Any]]:
    if job is None:
        return []
    evidence = []
    for result in job.agent_results.all():
        for item in result.evidence or []:
            if not isinstance(item, dict):
                continue
            evidence.append(
                {
                    "schema_version": "external_evidence.v1",
                    "provider": item.get("provider") or result.node_code,
                    "source_url": item.get("source_url") or item.get("source_ref"),
                    "retrieved_at": item.get("retrieved_at") or result.created_at,
                    "data_revision": item.get("data_revision") or "unknown",
                    "limitation": item.get("limitation") or "원문과 사건 사실을 함께 검토해야 합니다.",
                    **item,
                }
            )
    return evidence


def _missing_materials(readiness: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"field": code, "label": str(_dict(readiness.get("core_elements")).get(code, {}).get("label") or code)}
        for code in readiness.get("missing_elements") or []
    ]


def _accident_svg() -> str:
    return (
        '<svg viewBox="0 0 640 360" role="img" aria-label="확정 사실 기반 사고 도식" '
        'xmlns="http://www.w3.org/2000/svg"><rect width="640" height="360" fill="#f7f8fa"/>'
        '<path d="M0 140h640v80H0z" fill="#dfe4ea"/><path d="M280 0h80v360h-80z" fill="#dfe4ea"/>'
        '<path d="M30 180h230" stroke="#2563eb" stroke-width="8" marker-end="url(#a)"/>'
        '<path d="M320 330V235" stroke="#ef4444" stroke-width="8" marker-end="url(#b)"/>'
        '<defs><marker id="a" markerWidth="10" markerHeight="10" refX="5" refY="3" orient="auto">'
        '<path d="M0 0L0 6L6 3z" fill="#2563eb"/></marker><marker id="b" markerWidth="10" markerHeight="10" '
        'refX="5" refY="3" orient="auto"><path d="M0 0L0 6L6 3z" fill="#ef4444"/></marker></defs>'
        '<text x="24" y="165" font-size="16">사용자 차량</text><text x="370" y="330" font-size="16">상대 차량</text>'
        '<circle cx="320" cy="180" r="14" fill="#f59e0b"/></svg>'
    )


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
