"""Exercise the public Supervisor chat path through the canonical worker."""

from __future__ import annotations

import json
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from django.test import RequestFactory

from chatbot.management.commands.smoke_non_dl_analysis_reporting_pipeline import (
    _fine_notice_fixture,
)
from chatbot import repositories
from chatbot.models import (
    AgentResult,
    AgentWorkItem,
    AnalysisDisplayResult,
    AnalysisJob,
    ChatSession,
    ChatSessionStatus,
    Report,
    UploadedFile,
    UploadedFileStatus,
)
from chatbot.views import analysis_result, submit_chat_message


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
        parser.add_argument("--format", choices=("json", "text"), default="json")

    def handle(self, *args, **options) -> None:
        if not options["allow_paid_provider_call"]:
            raise CommandError(
                "Refusing provider-capable smoke run without --allow-paid-provider-call."
            )
        fixture = _fine_notice_fixture(str(options["fine_notice_fixture_s3_uri"] or ""))
        result = _run_smoke(fixture)
        failed_checks = _failed_checks(result, options)
        result["failed_checks"] = failed_checks
        result["status"] = "pass" if not failed_checks else "fail"
        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        else:
            self.stdout.write(_text_result(result))
        if failed_checks:
            raise CommandError("Supervisor conversation runtime smoke failed: " + ", ".join(failed_checks))


def _run_smoke(fixture: dict) -> dict:
    suffix = uuid4().hex[:12]
    guest_id = f"gst_supervisor_smoke_{suffix}"
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
            }
        ),
        content_type="application/json",
        HTTP_X_GUEST_ID=guest_id,
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
        result["checks"] = _no_followup_checks()
        return result
    work_item_id = str((chat.get("work_item") or {}).get("work_item_id") or "")
    job_id = str((chat.get("work_item") or {}).get("job_id") or "")
    result["identifiers"] = {"job_id": job_id, "work_item_id": work_item_id}
    worker_result = repositories.process_agent_work_item(work_item_id)
    result_request = RequestFactory().get(
        f"/api/analysis/results/{job_id}/", HTTP_X_GUEST_ID=guest_id
    )
    public_result = analysis_result(result_request, job_id)
    job = AnalysisJob.objects.filter(job_id=job_id).first()
    work_item = AgentWorkItem.objects.filter(work_item_id=work_item_id).first()
    report = Report.objects.filter(job=job).first() if job else None
    display = AnalysisDisplayResult.objects.filter(job=job).first() if job else None
    agent_results = list(AgentResult.objects.filter(job=job)) if job else []
    handoff = ((job.metadata if job else {}) or {}).get("supervisor_reporting_handoff")
    result["checks"] = {
        "queued": bool(job and work_item),
        "job_success": bool(job and job.status == "success"),
        "all_agent_results_success": bool(agent_results) and all(item.status == "success" for item in agent_results),
        "persisted_handoff_consumed": bool(handoff and report),
        "report_ready": bool(report and report.status == "ready"),
        "analysis_display_persisted": display is not None,
        "public_result_loaded": public_result.status_code == 200,
        "worker_completed": worker_result.get("status") in {"success", "skipped"},
    }
    return result


def _safe_llm(supervisor_state) -> dict:
    llm = supervisor_state.get("llm") if isinstance(supervisor_state, dict) else {}
    llm = llm if isinstance(llm, dict) else {}
    return {key: llm.get(key) for key in ("status", "reason", "provider", "model")}


def _no_followup_checks() -> dict:
    return {
        "planning_failure_has_no_followup_rows": not AnalysisJob.objects.exists()
        and not AgentWorkItem.objects.exists()
        and not Report.objects.exists(),
    }


def _failed_checks(result: dict, options: dict) -> list[str]:
    checks = result["checks"]
    failed = []
    if result["chat"]["status"] != "queued":
        return ["chat_queued"]
    if options["require_llm_used"] and result["llm"].get("status") != "used":
        failed.append("llm_used")
    requirement_checks = {
        "require_real_agent_results": ("job_success", "all_agent_results_success"),
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
