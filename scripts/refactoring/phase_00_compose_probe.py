"""Safe, no-provider probes run inside the Phase 0 Docker Compose backend container."""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any
from uuid import uuid4


EXPECTED_INTERNAL_NODE = "input_context_validation"
INTERNAL_NODE_CODES = {
    "input_context_validation",
    "consultation_fact_state_reducer",
    "case_promotion_gate",
    "agent_result_validation",
    "final_response_merge",
}
PRIVATE_KEYS = {
    "authorization",
    "oauth_code",
    "raw_user_text",
    "secret",
    "storage_uri",
    "token",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("seed-agent-work")
    verify_agent = subcommands.add_parser("verify-agent-work")
    verify_agent.add_argument("--job-id", required=True)
    verify_agent.add_argument("--work-item-id", required=True)
    verify_agent.add_argument("--timeout-seconds", type=int, default=120)
    verify_file = subcommands.add_parser("verify-file-scan")
    verify_file.add_argument("--attachment-id", required=True)
    verify_file.add_argument("--timeout-seconds", type=int, default=180)
    subcommands.add_parser("describe-runtime")
    return parser


def safe_projection(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): safe_projection(item)
            for key, item in value.items()
            if str(key).lower() not in PRIVATE_KEYS
        }
    if isinstance(value, list):
        return [safe_projection(item) for item in value]
    return value


def validate_internal_plan(node_codes: list[str]) -> str:
    if node_codes != [EXPECTED_INTERNAL_NODE]:
        for node_code in node_codes:
            if node_code not in INTERNAL_NODE_CODES:
                raise ValueError(f"provider_capable_node:{node_code}")
        raise ValueError("unexpected_internal_plan")
    return EXPECTED_INTERNAL_NODE


def agent_work_verdict(snapshot: dict[str, Any], *, expected_node_code: str) -> dict[str, Any]:
    checks = {
        "attempt": int(snapshot.get("attempt_no") or 0) >= 1,
        "started": bool(snapshot.get("started")),
        "completed": bool(snapshot.get("completed")),
        "work_item_status": snapshot.get("work_item_status") == "success",
        "job_status": snapshot.get("job_status") == "success",
        "node_code": snapshot.get("result_node_codes") == [expected_node_code],
        "error_code": not snapshot.get("error_code"),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {"status": "pass" if not failed_checks else "fail", "failed_checks": failed_checks}


def file_scan_verdict(snapshot: dict[str, Any]) -> dict[str, Any]:
    scanner = str(snapshot.get("scanner") or "").lower()
    checks = {
        "file_status": snapshot.get("file_status") == "ready",
        "scan_status": snapshot.get("scan_status") == "clean",
        "scanner": "clamav" in scanner,
        "error_code": not snapshot.get("error_code"),
        "retry_count": int(snapshot.get("retry_count") or 0) == 0,
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {"status": "pass" if not failed_checks else "fail", "failed_checks": failed_checks}


def _setup_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()


def _seed_agent_work() -> dict[str, Any]:
    _setup_django()
    from chatbot.models import ChatSession, ChatSessionStatus
    from chatbot.repositories import enqueue_analysis_job_work

    suffix = uuid4().hex
    owner_id = f"phase00_probe_{suffix}"
    session_id = f"ses_phase00_probe_{suffix}"
    message_id = f"msg_phase00_probe_{suffix}"
    job_id = f"job_phase00_probe_{suffix}"
    plan_id = f"plan_phase00_probe_{suffix}"
    ChatSession.objects.create(
        session_id=session_id,
        owner_id=owner_id,
        status=ChatSessionStatus.ACTIVE.value,
        metadata={"phase_00_probe": True},
    )
    plan = {
        "contract_version": "analysis_plan.v2",
        "plan_id": plan_id,
        "session_id": session_id,
        "message_id": message_id,
        "routing_intent": "phase_00_internal_probe",
        "steps": [
            {
                "order": 1,
                "node_code": validate_internal_plan([EXPECTED_INTERNAL_NODE]),
                "status": "ready",
                "depends_on": [],
            }
        ],
    }
    queued = enqueue_analysis_job_work(
        {
            "owner_id": owner_id,
            "user_id": owner_id,
            "session_id": session_id,
            "message_id": message_id,
            "user_text": "phase zero compose worker probe",
        },
        {
            "job_id": job_id,
            "session_id": session_id,
            "message_id": message_id,
            "routing_intent": "phase_00_internal_probe",
            "status": "queued",
            "active_node": EXPECTED_INTERNAL_NODE,
            "progress_message": "Phase 0 Compose probe queued.",
            "analysis_plan_id": plan_id,
            "analysis_plan": plan,
            "chat_response": {},
            "node_execution": {},
        },
    )
    return {
        "status": "queued",
        "job_id": queued["job_id"],
        "work_item_id": queued["work_item_id"],
        "expected_node_code": EXPECTED_INTERNAL_NODE,
    }


def _agent_snapshot(*, job_id: str, work_item_id: str) -> dict[str, Any]:
    from chatbot.models import AgentResult, AgentWorkItem, AnalysisJob

    work_item = AgentWorkItem.objects.filter(work_item_id=work_item_id).first()
    job = AnalysisJob.objects.filter(job_id=job_id).first()
    result_node_codes = (
        list(AgentResult.objects.filter(job=job).order_by("created_at", "result_id").values_list("node_code", flat=True))
        if job is not None
        else []
    )
    return {
        "attempt_no": work_item.attempt_no if work_item is not None else 0,
        "started": bool(work_item and work_item.started_at),
        "completed": bool(work_item and work_item.completed_at),
        "work_item_status": work_item.status if work_item is not None else "missing",
        "job_status": job.status if job is not None else "missing",
        "result_node_codes": result_node_codes,
        "error_code": work_item.error_code if work_item is not None else "missing_work_item",
    }


def _file_scan_snapshot(*, attachment_id: str) -> dict[str, Any]:
    from chatbot.models import UploadedFile

    uploaded_file = UploadedFile.objects.filter(attachment_id=attachment_id).first()
    metadata = uploaded_file.metadata if uploaded_file is not None and isinstance(uploaded_file.metadata, dict) else {}
    scan_result = metadata.get("scan_result") if isinstance(metadata.get("scan_result"), dict) else {}
    return {
        "file_status": uploaded_file.status if uploaded_file is not None else "missing",
        "scan_status": uploaded_file.scan_status if uploaded_file is not None else "missing",
        "scanner": scan_result.get("scanner"),
        "error_code": scan_result.get("error_code") or metadata.get("scan_error_code"),
        "retry_count": metadata.get("scan_retry_count") or 0,
    }


def _poll(*, timeout_seconds: int, snapshot, verdict) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + max(1, timeout_seconds)
    last_snapshot: dict[str, Any] = {}
    while True:
        last_snapshot = snapshot()
        current_verdict = verdict(last_snapshot)
        if current_verdict["status"] == "pass":
            return last_snapshot, current_verdict
        if time.monotonic() >= deadline:
            return last_snapshot, current_verdict
        time.sleep(1)


def _describe_runtime() -> dict[str, Any]:
    _setup_django()
    from django.conf import settings
    from django.core.cache import cache
    from django.db import connections

    return {
        "database_vendor": connections["default"].vendor,
        "cache_backend": f"{cache.__class__.__module__}.{cache.__class__.__name__}",
        "app_release_version": str(getattr(settings, "APP_RELEASE_VERSION", "")),
        "execution_environment": str(getattr(settings, "EXECUTION_ENVIRONMENT", "")),
        "providers": {
            "supervisor_llm_enabled": bool(getattr(settings, "SUPERVISOR_LLM_ENABLED", False)),
            "legal_rag_vector_enabled": bool(getattr(settings, "LEGAL_RAG_VECTOR_ENABLED", False)),
            "law_ground_search_enable_neo4j": bool(getattr(settings, "LAW_GROUND_SEARCH_ENABLE_NEO4J", False)),
        },
    }


def main(argv: list[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    if options.command == "seed-agent-work":
        result = _seed_agent_work()
    elif options.command == "verify-agent-work":
        _setup_django()
        snapshot, verdict = _poll(
            timeout_seconds=options.timeout_seconds,
            snapshot=lambda: _agent_snapshot(job_id=options.job_id, work_item_id=options.work_item_id),
            verdict=lambda current: agent_work_verdict(current, expected_node_code=EXPECTED_INTERNAL_NODE),
        )
        result = {**safe_projection(snapshot), **verdict, "job_id": options.job_id, "work_item_id": options.work_item_id}
    elif options.command == "verify-file-scan":
        _setup_django()
        snapshot, verdict = _poll(
            timeout_seconds=options.timeout_seconds,
            snapshot=lambda: _file_scan_snapshot(attachment_id=options.attachment_id),
            verdict=file_scan_verdict,
        )
        result = {**safe_projection(snapshot), **verdict, "attachment_id": options.attachment_id}
    else:
        result = _describe_runtime()
    print(json.dumps(safe_projection(result), ensure_ascii=False, sort_keys=True, default=str))
    return 0 if result.get("status", "pass") == "pass" or result.get("status") == "queued" else 1


if __name__ == "__main__":
    raise SystemExit(main())
