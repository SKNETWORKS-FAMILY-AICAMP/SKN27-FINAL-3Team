"""Exercise the persisted non-DL analysis-to-reporting worker pipeline."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError

from chatbot import repositories
from chatbot.object_storage import object_exists
from chatbot.models import (
    AgentInvocation,
    AgentResult,
    AgentResultStatus,
    AgentWorkItem,
    AgentWorkItemStatus,
    AnalysisDisplayResult,
    AnalysisJob,
    AnalysisJobStatus,
    ChatSession,
    ChatSessionStatus,
    Report,
    ReportStatus,
    UploadedFile,
    UploadedFileStatus,
)


ANALYSIS_NODE_CODES = (
    "fine_notice_analysis",
    "law_ground_search",
    "text_ml_case_search",
    "appeal_decision_flow",
)
REPORTING_NODE_CODE = "objection_report_generation"
PAID_GUARD_NODE_CODES = ("__paid_analysis_phase__", "__paid_reporting_phase__")
TERMINAL_WORK_ITEM_STATUSES = {
    AgentWorkItemStatus.SUCCESS.value,
    AgentWorkItemStatus.FAILED.value,
    AgentWorkItemStatus.CANCELED.value,
}
TERMINAL_JOB_STATUSES = {
    AnalysisJobStatus.SUCCESS.value,
    AnalysisJobStatus.PARTIAL.value,
    AnalysisJobStatus.FAILED.value,
}
EXPECTED_ADAPTERS = {
    "fine_notice_analysis": "ai.agents.fine_notice_analysis.graph",
    "law_ground_search": "ai.agents.law_ground_search.run_law_ground_search",
    "text_ml_case_search": "ai.agents.text_ml_case_search.run_text_ml_case_search",
    "appeal_decision_flow": "ai.agents.appeal_decision_flow.graph",
}

FINE_NOTICE_CONTENT_TYPES = {
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".webp": "image/webp",
}


class Command(BaseCommand):
    help = (
        "Run one unique canonical Supervisor-handoff smoke job through real non-DL "
        "analysis adapters and Reporting. No provider-capable work starts unless "
        "--allow-paid-provider-call is supplied."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--allow-paid-provider-call",
            action="store_true",
            help=(
                "Explicitly authorize this command to dispatch the configured non-DL "
                "analysis providers once for the unique smoke job."
            ),
        )
        parser.add_argument(
            "--require-real-agent-results",
            action="store_true",
            help="Fail unless every analysis row came from its registered sync adapter without a mock/heuristic fallback.",
        )
        parser.add_argument(
            "--require-persisted-handoff",
            action="store_true",
            help="Fail unless persisted analysis rows precede Reporting and the persisted handoff provenance is consumed.",
        )
        parser.add_argument(
            "--require-report",
            action="store_true",
            help="Fail unless one Report and one AnalysisDisplayResult are persisted.",
        )
        parser.add_argument(
            "--fine-notice-fixture-s3-uri",
            default="",
            help=(
                "S3 URI of an operator-reviewed, sanitized fine-notice acceptance "
                "fixture under canonical/acceptance/. Required before any paid work."
            ),
        )
        parser.add_argument(
            "--timeout-seconds",
            type=int,
            default=180,
            help="Bounded time to poll the canonical DB rows for a terminal result after worker dispatch (default: 180).",
        )
        parser.add_argument(
            "--poll-interval-seconds",
            type=float,
            default=1.0,
            help="DB polling interval in seconds (default: 1.0).",
        )
        parser.add_argument(
            "--format",
            choices=("json", "text"),
            default="json",
            help="Output format (default: json).",
        )

    def handle(self, *args, **options):
        if not options["allow_paid_provider_call"]:
            raise CommandError(
                "Refusing provider-capable smoke run without --allow-paid-provider-call."
            )

        fine_notice_fixture = _fine_notice_fixture(
            str(options.get("fine_notice_fixture_s3_uri") or "")
        )
        if not object_exists(fine_notice_fixture["object_storage"]):
            raise CommandError(
                "The operator-reviewed fine-notice fixture is not readable from object storage."
            )

        timeout_seconds = max(1, min(int(options["timeout_seconds"] or 1), 900))
        poll_interval_seconds = max(0.0, float(options["poll_interval_seconds"] or 0.0))
        identifiers = _unique_identifiers()
        _register_fine_notice_fixture(
            identifiers,
            fine_notice_fixture=fine_notice_fixture,
        )
        payload, job_payload, server_execution_context = _smoke_payloads(
            identifiers,
            fine_notice_fixture=fine_notice_fixture,
        )
        queued = repositories.enqueue_analysis_job_work(
            payload,
            job_payload,
            max_attempts=1,
            server_execution_context=server_execution_context,
        )

        worker_result = repositories.process_agent_work_item(queued["work_item_id"])
        if not AnalysisJob.objects.filter(job_id=queued["job_id"]).exists():
            raise CommandError(
                "Canonical worker returned without the queued AnalysisJob; "
                f"worker_status={worker_result.get('status')}, "
                f"worker_reason={worker_result.get('reason')}, "
                f"queued_job_id={queued['job_id']}, "
                f"remaining_job_count={AnalysisJob.objects.count()}."
            )
        job, work_item = _poll_terminal_rows(
            job_id=queued["job_id"],
            work_item_id=queued["work_item_id"],
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

        paid_guard_count_before_retry = _paid_guard_count(job)
        safe_retry_result = repositories.process_agent_work_item(work_item.work_item_id)
        paid_guard_count_after_retry = _paid_guard_count(job)
        result = _verification_result(
            job=job,
            work_item=work_item,
            worker_result=worker_result,
            safe_retry_result=safe_retry_result,
            paid_guard_count_before_retry=paid_guard_count_before_retry,
            paid_guard_count_after_retry=paid_guard_count_after_retry,
            requirements={
                "real_agent_results": bool(options["require_real_agent_results"]),
                "persisted_handoff": bool(options["require_persisted_handoff"]),
                "report": bool(options["require_report"]),
            },
        )

        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        else:
            self.stdout.write(_text_result(result))

        if result["status"] != "pass":
            raise CommandError(
                "Non-DL analysis/reporting smoke failed: "
                + ", ".join(result["failed_checks"])
            )


def _unique_identifiers() -> dict[str, str]:
    suffix = uuid4().hex[:12]
    return {
        "owner_id": f"usr_non_dl_smoke_{suffix}",
        "session_id": f"ses_non_dl_smoke_{suffix}",
        "message_id": f"msg_non_dl_smoke_{suffix}",
        "job_id": f"job_non_dl_smoke_{suffix}",
        "plan_id": f"plan_non_dl_smoke_{suffix}",
    }


def _fine_notice_fixture(storage_uri: str) -> dict[str, Any]:
    storage_uri = storage_uri.strip()
    parsed = urlsplit(storage_uri)
    key = unquote(parsed.path.lstrip("/"))
    suffix = "." + key.rsplit(".", 1)[-1].lower() if "." in key else ""
    if (
        parsed.scheme != "s3"
        or not parsed.netloc
        or not key.startswith("canonical/acceptance/")
        or not key.removeprefix("canonical/acceptance/")
        or any(part in {"", ".", ".."} for part in key.split("/"))
        or parsed.query
        or parsed.fragment
        or suffix not in FINE_NOTICE_CONTENT_TYPES
    ):
        raise CommandError(
            "--fine-notice-fixture-s3-uri must be an operator-reviewed s3:// URI "
            "under canonical/acceptance/ with a supported image or PDF extension."
        )
    attachment_id = f"att_non_dl_smoke_{uuid4().hex[:12]}"
    content_type = FINE_NOTICE_CONTENT_TYPES[suffix]
    return {
        "attachment_id": attachment_id,
        "purpose": "fine_notice",
        "status": "ready",
        "filename": key.rsplit("/", 1)[-1],
        "content_type": content_type,
        "storage_uri": storage_uri,
        "metadata_source": "operator_reviewed_acceptance_fixture",
        "object_storage": {
            "provider": "s3",
            "bucket": parsed.netloc,
            "key": key,
            "storage_uri": storage_uri,
            "resource_type": "acceptance_fixture",
            "resource_id": attachment_id,
            "filename": key.rsplit("/", 1)[-1],
            "content_type": content_type,
        },
    }


def _register_fine_notice_fixture(
    identifiers: dict[str, str],
    *,
    fine_notice_fixture: dict[str, Any],
) -> None:
    session = ChatSession.objects.create(
        session_id=identifiers["session_id"],
        owner_id=identifiers["owner_id"],
        status=ChatSessionStatus.ACTIVE.value,
        metadata={
            "auth_context": {
                "auth_state": "authenticated",
                "subject_id": identifiers["owner_id"],
                "subject_type": "user",
                "user_id": identifiers["owner_id"],
            }
        },
    )
    UploadedFile.objects.create(
        attachment_id=fine_notice_fixture["attachment_id"],
        owner_id=identifiers["owner_id"],
        session=session,
        purpose="fine_notice",
        file_type=(
            "document"
            if fine_notice_fixture["content_type"] == "application/pdf"
            else "image"
        ),
        original_filename=fine_notice_fixture["filename"],
        content_type=fine_notice_fixture["content_type"],
        size_bytes=1,
        storage_uri=fine_notice_fixture["storage_uri"],
        privacy_risk=False,
        status=UploadedFileStatus.READY.value,
        scan_status="clean",
        metadata={
            "metadata_source": "operator_reviewed_acceptance_fixture",
            "object_storage": fine_notice_fixture["object_storage"],
        },
    )


def _smoke_payloads(
    identifiers: dict[str, str],
    *,
    fine_notice_fixture: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    user_facts = (
        "At a signalized four-way intersection the smoke vehicle proceeded straight "
        "on green while the other vehicle turned left; review signal priority, "
        "comparable cases, and applicable traffic-law grounds."
    )
    steps = [
        {
            "order": 1,
            "node_code": "fine_notice_analysis",
            "status": "ready",
            "execution_mode": "sync",
            "depends_on": [],
        },
        {
            "order": 2,
            "node_code": "law_ground_search",
            "status": "ready",
            "execution_mode": "sync",
            "depends_on": ["fine_notice_analysis"],
        },
        {
            "order": 3,
            "node_code": "text_ml_case_search",
            "status": "ready",
            "execution_mode": "sync",
            "depends_on": ["law_ground_search"],
        },
        {
            "order": 4,
            "node_code": "appeal_decision_flow",
            "status": "ready",
            "execution_mode": "sync",
            "depends_on": ["fine_notice_analysis", "law_ground_search"],
        },
        {
            "order": 5,
            "node_code": REPORTING_NODE_CODE,
            "status": "ready",
            "execution_mode": "sync",
            "depends_on": list(ANALYSIS_NODE_CODES),
        },
    ]
    analysis_plan = {
        "contract_version": "analysis_plan.v2",
        "plan_id": identifiers["plan_id"],
        "session_id": identifiers["session_id"],
        "message_id": identifiers["message_id"],
        "routing_intent": "traffic_accident_objection",
        "steps": steps,
    }
    payload = {
        "owner_id": identifiers["owner_id"],
        "user_id": identifiers["owner_id"],
        "session_id": identifiers["session_id"],
        "message_id": identifiers["message_id"],
        "user_text": user_facts,
        "attachments": [fine_notice_fixture],
    }
    ocr_confirmation = {
        "confirmed": True,
        "fields": {
            "fine_type": "과태료",
            "notice_stage": "사전통지",
        },
    }
    server_execution_context = {
        "user_facts": user_facts,
        "raw_user_text": user_facts,
        "query_text": user_facts,
        "accident_context": user_facts,
        "user_appeal_reason": user_facts,
        "query": {
            "raw_text": user_facts,
            "search_query": user_facts,
        },
        "temporal_basis": {"mode": "current"},
        "scope": {"jurisdiction": "KR"},
        "law_graph": {"enabled": False},
        # This command bypasses the public chat endpoint, so the user-confirmed
        # OCR fields are supplied only through the trusted worker context.
        "ocr_confirmation": ocr_confirmation,
    }

    job_payload = {
        "job_id": identifiers["job_id"],
        "session_id": identifiers["session_id"],
        "message_id": identifiers["message_id"],
        "routing_intent": "traffic_accident_objection",
        "status": AnalysisJobStatus.QUEUED.value,
        "active_node": ANALYSIS_NODE_CODES[0],
        "progress_message": "Non-DL analysis/reporting smoke queued.",
        "analysis_plan_id": identifiers["plan_id"],
        "analysis_plan": analysis_plan,
        "chat_response": {},
        "node_execution": {},
        "attachments": [
            {"attachment_id": fine_notice_fixture["attachment_id"]}
        ],
    }
    return payload, job_payload, server_execution_context


def _poll_terminal_rows(
    *,
    job_id: str,
    work_item_id: str,
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> tuple[AnalysisJob, AgentWorkItem]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        job = AnalysisJob.objects.get(job_id=job_id)
        work_item = AgentWorkItem.objects.get(work_item_id=work_item_id)
        if (
            work_item.status in TERMINAL_WORK_ITEM_STATUSES
            and job.status in TERMINAL_JOB_STATUSES
        ):
            return job, work_item
        if time.monotonic() >= deadline:
            raise CommandError(
                f"Timed out waiting for smoke job {job_id} after {timeout_seconds}s."
            )
        time.sleep(poll_interval_seconds)


def _verification_result(
    *,
    job: AnalysisJob,
    work_item: AgentWorkItem,
    worker_result: dict[str, Any],
    safe_retry_result: dict[str, Any],
    paid_guard_count_before_retry: int,
    paid_guard_count_after_retry: int,
    requirements: dict[str, bool],
) -> dict[str, Any]:
    analysis_results = list(
        AgentResult.objects.filter(job=job, node_code__in=ANALYSIS_NODE_CODES)
        .order_by("created_at", "result_id")
    )
    reporting_results = list(
        AgentResult.objects.filter(job=job, node_code=REPORTING_NODE_CODE)
    )
    reporting_result = reporting_results[0] if len(reporting_results) == 1 else None
    handoff = job.metadata.get("supervisor_reporting_handoff")
    handoff = handoff if isinstance(handoff, dict) else {}
    reporting_guard = AgentInvocation.objects.filter(
        job=job,
        node_code="__paid_reporting_phase__",
    ).first()
    expected_result_ids = [
        result.result_id
        for node_code in ANALYSIS_NODE_CODES
        for result in analysis_results
        if result.node_code == node_code
    ]
    handoff_source = handoff.get("source") if isinstance(handoff.get("source"), dict) else {}
    reporting_trace = (
        reporting_result.structured_result.get("supervisor_handoff")
        if reporting_result is not None
        and isinstance(reporting_result.structured_result, dict)
        else {}
    )
    reporting_trace = reporting_trace if isinstance(reporting_trace, dict) else {}
    expected_trace = {
        "contract_version": handoff.get("contract_version"),
        "handoff_id": handoff.get("handoff_id"),
        "gate_status": (
            handoff.get("gate", {}).get("status")
            if isinstance(handoff.get("gate"), dict)
            else None
        ),
        "source_fingerprint": handoff_source.get("fingerprint"),
        "source_result_ids": handoff_source.get("result_ids"),
    }
    report_count = Report.objects.filter(job=job).count()
    report = Report.objects.filter(job=job).first() if report_count == 1 else None
    display_count = AnalysisDisplayResult.objects.filter(job=job).count()
    all_agent_results = list(AgentResult.objects.filter(job=job))

    checks = {
        "canonical_worker_completed": (
            work_item.status == AgentWorkItemStatus.SUCCESS.value
            and worker_result.get("status") == AgentWorkItemStatus.SUCCESS.value
        ),
        "job_success": job.status == AnalysisJobStatus.SUCCESS.value,
        "all_agent_results_success": bool(
            len(all_agent_results) == len(ANALYSIS_NODE_CODES) + 1
            and all(
                result.status == AgentResultStatus.SUCCESS.value
                for result in all_agent_results
            )
        ),
        "non_dl_plan_only": set(
            AgentResult.objects.filter(job=job).values_list("node_code", flat=True)
        ).issubset({*ANALYSIS_NODE_CODES, REPORTING_NODE_CODE}),
        "analysis_results_unique": (
            len(analysis_results) == len(ANALYSIS_NODE_CODES)
            and {result.node_code for result in analysis_results}
            == set(ANALYSIS_NODE_CODES)
        ),
        "real_agent_results": _real_analysis_results(analysis_results),
        "analysis_persisted_before_reporting": bool(
            reporting_guard
            and len(analysis_results) == len(ANALYSIS_NODE_CODES)
            and all(result.created_at <= reporting_guard.started_at for result in analysis_results)
        ),
        "persisted_handoff": bool(
            handoff.get("contract_version") == "supervisor_reporting_handoff.v1"
            and handoff_source.get("persisted") is True
            and handoff_source.get("persistence") == "agent_results"
            and handoff_source.get("result_ids") == expected_result_ids
        ),
        "persisted_handoff_consumed": bool(
            reporting_result is not None and reporting_trace == expected_trace
        ),
        "report_persisted": report_count == 1,
        "report_ready": bool(
            report is not None and report.status == ReportStatus.READY.value
        ),
        "general_report_download_unavailable": _general_report_download_unavailable(report),
        "analysis_display_persisted": display_count == 1,
        "paid_phase_guards_unique": (
            paid_guard_count_before_retry == len(PAID_GUARD_NODE_CODES)
            and all(
                AgentInvocation.objects.filter(job=job, node_code=node_code).count() == 1
                for node_code in PAID_GUARD_NODE_CODES
            )
        ),
        "safe_retry_no_new_paid_invocation": (
            safe_retry_result.get("status") == "skipped"
            and paid_guard_count_after_retry == paid_guard_count_before_retry
        ),
    }
    required_check_names = {
        "canonical_worker_completed",
        "job_success",
        "all_agent_results_success",
        "non_dl_plan_only",
        "analysis_results_unique",
        "paid_phase_guards_unique",
        "safe_retry_no_new_paid_invocation",
    }
    if requirements.get("real_agent_results"):
        required_check_names.add("real_agent_results")
    if requirements.get("persisted_handoff"):
        required_check_names.update(
            {
                "analysis_persisted_before_reporting",
                "persisted_handoff",
                "persisted_handoff_consumed",
            }
        )
    if requirements.get("report"):
        required_check_names.update(
            {
                "report_persisted",
                "report_ready",
                "general_report_download_unavailable",
                "analysis_display_persisted",
            }
        )
    failed_checks = sorted(
        check_name for check_name in required_check_names if not checks[check_name]
    )
    return {
        "contract_version": "non_dl_analysis_reporting_smoke.v1",
        "status": "fail" if failed_checks else "pass",
        "job_id": job.job_id,
        "session_id": job.session.session_id,
        "work_item_id": work_item.work_item_id,
        "job_status": job.status,
        "work_item_status": work_item.status,
        "analysis_node_codes": list(ANALYSIS_NODE_CODES),
        "all_node_codes": list(
            AgentResult.objects.filter(job=job)
            .order_by("created_at", "result_id")
            .values_list("node_code", flat=True)
        ),
        "requested_requirements": requirements,
        "checks": checks,
        "failed_checks": failed_checks,
        "paid_phase_guard_count_before_retry": paid_guard_count_before_retry,
        "paid_phase_guard_count_after_retry": paid_guard_count_after_retry,
        "safe_retry_status": safe_retry_result.get("status"),
        "report_count": report_count,
        "report_status": report.status if report is not None else None,
        "analysis_display_count": display_count,
        "supervisor_plan_source": "explicit_canonical_smoke_plan",
        "remaining_gap": (
            "This smoke isolates the persisted Supervisor handoff and worker pipeline; "
            "it does not exercise the optional conversational Supervisor LLM planner."
        ),
    }


def _real_analysis_results(results: list[AgentResult]) -> bool:
    if len(results) != len(ANALYSIS_NODE_CODES):
        return False
    for result in results:
        if result.status != AgentResultStatus.SUCCESS.value:
            return False
        raw_output = result.raw_output if isinstance(result.raw_output, dict) else {}
        structured = (
            result.structured_result
            if isinstance(result.structured_result, dict)
            else {}
        )
        adapter_trace = (
            structured.get("adapter_trace")
            if isinstance(structured.get("adapter_trace"), dict)
            else {}
        )
        adapter = str(adapter_trace.get("adapter") or "")
        retrieval = (
            structured.get("retrieval")
            if isinstance(structured.get("retrieval"), dict)
            else {}
        )
        if raw_output.get("execution_mode") != "sync":
            return False
        if adapter_trace.get("execution_mode") != "sync":
            return False
        if adapter != EXPECTED_ADAPTERS.get(result.node_code):
            return False
        if "mock" in adapter.lower():
            return False
        if retrieval.get("fallback_used") is True:
            return False
    return True


def _general_report_download_unavailable(report: Report | None) -> bool:
    if report is None or report.status != ReportStatus.READY.value:
        return False
    try:
        metadata = repositories.get_report_download_metadata(report.report_id)
    except Exception:
        return False
    return metadata is None


def _paid_guard_count(job: AnalysisJob) -> int:
    return AgentInvocation.objects.filter(
        job=job,
        node_code__in=PAID_GUARD_NODE_CODES,
    ).count()


def _text_result(result: dict[str, Any]) -> str:
    lines = [
        f"Non-DL analysis/reporting smoke: {result['status']}",
        f"- job_id: {result['job_id']}",
        f"- job_status: {result['job_status']}",
        f"- work_item_status: {result['work_item_status']}",
    ]
    lines.extend(
        f"- {name}: {passed}" for name, passed in result["checks"].items()
    )
    if result["failed_checks"]:
        lines.append(f"- failed_checks: {', '.join(result['failed_checks'])}")
    lines.append(f"- remaining_gap: {result['remaining_gap']}")
    return "\n".join(lines)
