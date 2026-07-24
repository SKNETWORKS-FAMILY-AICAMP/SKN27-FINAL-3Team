"""Exercise the public Supervisor chat path through the canonical worker."""

from __future__ import annotations

import json
import time
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from django.test import RequestFactory

from app.services.guest_credential_service import issue_guest_credential
from chatbot.management.commands.smoke_non_dl_analysis_reporting_pipeline import (
    _fine_notice_fixture,
)
from chatbot.models import (
    AgentResult,
    AgentWorkItem,
    AgentWorkItemStatus,
    AnalysisDisplayResult,
    AnalysisJob,
    ChatSession,
    ChatSessionStatus,
    Report,
    UploadedFile,
    UploadedFileStatus,
)
from chatbot.views import analysis_result, submit_chat_message


SYNC_AGENT_NODE_CODES = {
    "appeal_decision_flow",
    "fine_notice_analysis",
    "law_ground_search",
    "objection_report_generation",
    "text_ml_case_search",
    "traffic_accident_confirmation_ocr",
}


class Command(BaseCommand):
    help = (
        "Run one public Supervisor conversation through queue, Worker, and Reporting. "
        "Provider-capable execution requires explicit paid-call consent."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--allow-paid-provider-call",
            action="store_true",
            help="Explicitly authorize one provider-capable Supervisor runtime smoke.",
        )
        parser.add_argument(
            "--fine-notice-fixture-s3-uri",
            default="",
            help=(
                "S3 URI of an operator-reviewed fixture under canonical/acceptance/. "
                "Required before any provider-capable work."
            ),
        )
        parser.add_argument("--require-llm-used", action="store_true")
        parser.add_argument("--require-real-agent-results", action="store_true")
        parser.add_argument("--require-persisted-handoff", action="store_true")
        parser.add_argument("--require-report", action="store_true")
        parser.add_argument(
            "--timeout-seconds",
            type=int,
            default=600,
            help="Bounded wait for the deployed Agent worker to finish.",
        )
        parser.add_argument("--format", choices=("json", "text"), default="json")

    def handle(self, *args, **options) -> None:
        if not options["allow_paid_provider_call"]:
            raise CommandError(
                "Refusing provider-capable smoke run without --allow-paid-provider-call."
            )
        fixture = _fine_notice_fixture(str(options["fine_notice_fixture_s3_uri"] or ""))
        result = _run_smoke(
            fixture,
            timeout_seconds=max(30, min(int(options["timeout_seconds"]), 1800)),
        )
        failed_checks = _failed_checks(result, options)
        result["failed_checks"] = failed_checks
        result["status"] = "pass" if not failed_checks else "fail"
        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        else:
            self.stdout.write(_text_result(result))
        if failed_checks:
            raise CommandError("Supervisor conversation runtime smoke failed: " + ", ".join(failed_checks))


def _run_smoke(fixture: dict, *, timeout_seconds: int = 600) -> dict:
    suffix = uuid4().hex[:12]
    guest_id = f"gst_supervisor_smoke_{suffix}"
    guest_credential, _guest_credential_claims = issue_guest_credential(guest_id)
    session_id = f"ses_supervisor_smoke_{suffix}"
    attachment_id = f"att_supervisor_smoke_{suffix}"
    session = ChatSession.objects.create(
        session_id=session_id,
        status=ChatSessionStatus.ACTIVE.value,
        metadata={"guest_id": guest_id},
    )
    UploadedFile.objects.create(
        attachment_id=attachment_id,
        session=session,
        purpose="fine_notice",
        file_type="image",
        original_filename="sanitized-fine-notice.png",
        content_type=fixture["content_type"],
        size_bytes=1,
        storage_uri=fixture["storage_uri"],
        privacy_risk=False,
        status=UploadedFileStatus.READY.value,
        scan_status="clean",
        metadata={"object_storage": fixture["object_storage"]},
    )
    request = RequestFactory().post(
        "/api/chat/messages/",
        data=json.dumps(
            {
                "session_id": session_id,
                "user_text": "과태료 고지서에 대해 이의신청서와 분석 리포트를 작성해 주세요.",
                "attachments": [{"attachment_id": attachment_id}],
                "ocr_confirmation": {
                    "confirmed": True,
                    "fields": {
                        "fine_type": "과태료",
                        "notice_stage": "사전통지",
                    },
                },
            }
        ),
        content_type="application/json",
        HTTP_X_GUEST_ID=guest_id,
        HTTP_X_GUEST_CREDENTIAL=guest_credential,
    )
    chat_response = submit_chat_message(request)
    chat = json.loads(chat_response.content)
    result = {
        "contract_version": "supervisor_conversation_runtime_smoke.v1",
        "chat": {
            "http_status": chat_response.status_code,
            "status": chat.get("status"),
            "execution_mode": chat.get("execution_mode"),
        },
        "llm": _safe_llm(chat.get("supervisor_state")),
        "identifiers": {},
        "checks": {},
    }
    if chat_response.status_code != 202 or chat.get("status") != "queued":
        result["checks"] = _no_followup_checks(session)
        return result
    work_item_id = str((chat.get("work_item") or {}).get("work_item_id") or "")
    job_id = str((chat.get("work_item") or {}).get("job_id") or "")
    result["identifiers"] = {"job_id": job_id, "work_item_id": work_item_id}
    _wait_for_worker_completion(
        work_item_id,
        timeout_seconds=timeout_seconds,
    )
    result_request = RequestFactory().get(
        f"/api/analysis/results/{job_id}/",
        HTTP_X_GUEST_ID=guest_id,
        HTTP_X_GUEST_CREDENTIAL=guest_credential,
    )
    public_result = analysis_result(result_request, job_id)
    job = AnalysisJob.objects.filter(job_id=job_id).first()
    work_item = AgentWorkItem.objects.filter(work_item_id=work_item_id).first()
    report = Report.objects.filter(job=job).first() if job else None
    display = AnalysisDisplayResult.objects.filter(job=job).first() if job else None
    agent_results = list(AgentResult.objects.filter(job=job)) if job else []
    reporting_result = next(
        (
            item
            for item in agent_results
            if item.node_code == "objection_report_generation"
        ),
        None,
    )
    handoff = ((job.metadata if job else {}) or {}).get("supervisor_reporting_handoff")
    result["checks"] = {
        "queued": bool(job and work_item),
        "job_success": bool(job and job.status == "success"),
        "all_agent_results_success": bool(agent_results) and all(item.status == "success" for item in agent_results),
        "real_agent_results": _real_agent_results(agent_results),
        "persisted_handoff_consumed": _persisted_handoff_consumed(
            handoff,
            reporting_result,
        ),
        "report_ready": bool(report and report.status == "ready"),
        "analysis_display_persisted": display is not None,
        "public_result_loaded": public_result.status_code == 200,
        "worker_completed": bool(
            work_item and work_item.status == AgentWorkItemStatus.SUCCESS.value
        ),
        "worker_loop_consumed": bool(
            work_item
            and work_item.attempt_no >= 1
            and work_item.started_at is not None
            and work_item.completed_at is not None
            and work_item.status
            in {
                AgentWorkItemStatus.SUCCESS.value,
                AgentWorkItemStatus.FAILED.value,
                AgentWorkItemStatus.CANCELED.value,
            }
        ),
    }
    return result


def _wait_for_worker_completion(
    work_item_id: str,
    *,
    timeout_seconds: int,
    poll_interval_seconds: float = 2.0,
) -> AgentWorkItem | None:
    deadline = time.monotonic() + max(1, timeout_seconds)
    terminal_statuses = {
        AgentWorkItemStatus.SUCCESS.value,
        AgentWorkItemStatus.FAILED.value,
        AgentWorkItemStatus.CANCELED.value,
    }
    latest: AgentWorkItem | None = None
    while True:
        latest = AgentWorkItem.objects.filter(work_item_id=work_item_id).first()
        if latest is not None and latest.status in terminal_statuses:
            return latest
        if time.monotonic() >= deadline:
            return latest
        time.sleep(max(0.1, poll_interval_seconds))


SAFE_LLM_REASON_CODES = frozenset(
    {
        "ok",
        "disabled",
        "missing_config",
        "provider_unavailable",
        "provider_refusal",
        "provider_structured_output_error",
        "invalid_contract",
    }
)


def _safe_llm_reason(status: object, reason: object) -> str:
    if str(status or "").strip().lower() == "disabled":
        return "disabled"
    normalized_reason = str(reason or "").strip().lower()
    if normalized_reason in SAFE_LLM_REASON_CODES:
        return normalized_reason
    return "unspecified"


def _safe_llm(supervisor_state) -> dict:
    llm = supervisor_state.get("llm") if isinstance(supervisor_state, dict) else {}
    llm = llm if isinstance(llm, dict) else {}
    status = str(llm.get("status") or "")
    return {"status": status, "reason": _safe_llm_reason(status, llm.get("reason"))}


def _no_followup_checks(session: ChatSession) -> dict:
    return {
        "planning_failure_has_no_followup_rows": not AnalysisJob.objects.filter(
            session=session
        ).exists()
        and not AgentWorkItem.objects.filter(job__session=session).exists()
        and not Report.objects.filter(job__session=session).exists(),
    }


def _real_agent_results(agent_results: list[AgentResult]) -> bool:
    sync_results = [
        result for result in agent_results if result.node_code in SYNC_AGENT_NODE_CODES
    ]
    if not sync_results:
        return False
    for result in sync_results:
        raw_output = result.raw_output if isinstance(result.raw_output, dict) else {}
        structured = (
            result.structured_result
            if isinstance(result.structured_result, dict)
            else {}
        )
        adapter_trace = structured.get("adapter_trace")
        adapter_trace = adapter_trace if isinstance(adapter_trace, dict) else {}
        adapter = str(adapter_trace.get("adapter") or "")
        retrieval = structured.get("retrieval")
        retrieval = retrieval if isinstance(retrieval, dict) else {}
        if (
            result.status != "success"
            or raw_output.get("execution_mode") != "sync"
            or adapter_trace.get("execution_mode") != "sync"
            or not adapter
            or "mock" in adapter.lower()
            or retrieval.get("fallback_used") is True
        ):
            return False
    return True


def _persisted_handoff_consumed(handoff, reporting_result: AgentResult | None) -> bool:
    handoff = handoff if isinstance(handoff, dict) else {}
    source = handoff.get("source")
    source = source if isinstance(source, dict) else {}
    gate = handoff.get("gate")
    gate = gate if isinstance(gate, dict) else {}
    structured = (
        reporting_result.structured_result
        if reporting_result is not None and isinstance(reporting_result.structured_result, dict)
        else {}
    )
    trace = structured.get("supervisor_handoff")
    trace = trace if isinstance(trace, dict) else {}
    return bool(
        handoff.get("contract_version") == "supervisor_reporting_handoff.v1"
        and source.get("persistence") == "agent_results"
        and source.get("persisted") is True
        and gate.get("status") == "ready"
        and reporting_result is not None
        and reporting_result.status == "success"
        and trace
        and trace.get("contract_version") == handoff.get("contract_version")
        and trace.get("handoff_id") == handoff.get("handoff_id")
        and trace.get("gate_status") == gate.get("status")
        and trace.get("source_fingerprint") == source.get("fingerprint")
        and trace.get("source_result_ids") == source.get("result_ids")
    )


def _failed_checks(result: dict, options: dict) -> list[str]:
    checks = result["checks"]
    failed = []
    if result["chat"]["status"] != "queued":
        return ["chat_queued"]
    failed.extend(
        name
        for name in ("worker_loop_consumed", "worker_completed")
        if not checks.get(name)
    )
    if options["require_llm_used"] and result["llm"].get("status") != "used":
        failed.append("llm_used")
    requirement_checks = {
        "require_real_agent_results": (
            "job_success",
            "all_agent_results_success",
            "real_agent_results",
        ),
        "require_persisted_handoff": ("persisted_handoff_consumed",),
        "require_report": ("report_ready", "analysis_display_persisted", "public_result_loaded"),
    }
    for option, names in requirement_checks.items():
        if options[option]:
            failed.extend(name for name in names if not checks.get(name))
    return failed


def _text_result(result: dict) -> str:
    return "\n".join(
        [
            f"Supervisor conversation runtime smoke: {result['status']}",
            f"- chat: {result['chat'].get('http_status')} {result['chat'].get('status')}",
            f"- llm: {result['llm'].get('status')}",
            f"- failed_checks: {', '.join(result['failed_checks']) or '-'}",
        ]
    )
