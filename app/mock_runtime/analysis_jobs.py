"""Mock analysis job lifecycle for the Django integration phase."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.mock_runtime.agent_execution import execute_mock_plan
from app.mock_runtime.chat import submit_message


JOB_STATUSES = {"queued", "running", "success", "partial", "failed"}


def create_analysis_job(payload: dict[str, Any]) -> dict[str, Any]:
    job_id = payload.get("job_id") or f"job_{uuid4().hex[:12]}"
    created_at = _now_iso()

    chat_response = submit_message(payload)
    execution_payload = deepcopy(payload)
    execution_payload.update(
        {
            "job_id": job_id,
            "session_id": chat_response["session_id"],
            "message_id": chat_response["message_id"],
            "attachments": chat_response.get("attachments", []),
        }
    )
    node_execution = execute_mock_plan(chat_response["analysis_plan"], execution_payload)

    status = _job_status(payload, chat_response)
    progress = chat_response.get("progress", {})
    job = {
        "job_id": job_id,
        "session_id": chat_response["session_id"],
        "message_id": chat_response["message_id"],
        "routing_intent": chat_response["routing_intent"],
        "mock_scenario": chat_response["mock_scenario"],
        "status": status,
        "active_node": progress.get("active_node"),
        "progress_message": progress.get("message") or _progress_message(status),
        "analysis_plan_id": chat_response["analysis_plan"]["plan_id"],
        "analysis_plan": chat_response["analysis_plan"],
        "attachment_resolution": chat_response.get("attachment_resolution", {}),
        "attachments": chat_response.get("attachments", []),
        "chat_response": chat_response,
        "node_execution": node_execution,
        "status_counts": node_execution.get("status_counts", {}),
        "history": _history_for_status(status, progress, created_at),
        "created_at": created_at,
        "updated_at": _now_iso(),
        "limitations": [
            "중간발표용 mock analysis job입니다. 명시적 mock API는 실제 비동기 queue/Redis/DB 저장을 사용하지 않으며, canonical API는 별도 persistence/cache envelope로 저장 상태를 표시합니다."
        ],
    }
    _write_job(job)
    return job


def get_analysis_job(job_id: str) -> dict[str, Any] | None:
    return _read_job(_job_path(job_id))


def get_analysis_result(job_id: str) -> dict[str, Any] | None:
    job = get_analysis_job(job_id)
    if not job:
        return None

    chat_response = job.get("chat_response") or {}
    limitations = _combined_limitations(job, chat_response)
    return {
        "result_id": f"res_{job['job_id']}",
        "job_id": job["job_id"],
        "session_id": job.get("session_id"),
        "message_id": job.get("message_id"),
        "routing_intent": job.get("routing_intent"),
        "mock_scenario": job.get("mock_scenario"),
        "status": job.get("status"),
        "assistant_message": _display_assistant_message(chat_response, job, limitations),
        "progress": _display_progress(job),
        "cards": deepcopy(chat_response.get("cards", [])),
        "pending_questions": deepcopy(chat_response.get("pending_questions", [])),
        "attachments": _display_attachments(job.get("attachments", [])),
        "report_links": _display_report_links(job, chat_response),
        "evidence": _display_evidence(job),
        "agent_results": _agent_result_summaries(job),
        "limitations": limitations,
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }


def list_analysis_jobs(session_id: str | None = None) -> list[dict[str, Any]]:
    root = _job_root()
    if not root.exists():
        return []

    jobs = []
    for job_path in sorted(root.glob("*/job.json")):
        job = _read_job(job_path)
        if not job:
            continue
        if session_id and job.get("session_id") != session_id:
            continue
        jobs.append(_job_summary(job))
    return jobs


def _job_status(payload: dict[str, Any], chat_response: dict[str, Any]) -> str:
    requested_status = payload.get("mock_job_status")
    if requested_status in JOB_STATUSES:
        return str(requested_status)

    return {
        "pending": "running",
        "success": "success",
        "partial": "partial",
        "failed": "failed",
    }.get(str(chat_response.get("status")), "running")


def _history_for_status(
    status: str,
    progress: dict[str, Any],
    created_at: str,
) -> list[dict[str, Any]]:
    history = [
        {
            "status": "queued",
            "active_node": None,
            "message": "분석 job이 생성되었습니다.",
            "created_at": created_at,
        }
    ]

    if status != "queued":
        history.append(
            {
                "status": "running",
                "active_node": progress.get("active_node"),
                "message": progress.get("message") or "분석 job을 실행 중입니다.",
                "created_at": _now_iso(),
            }
        )

    if status in {"success", "partial", "failed"}:
        history.append(
            {
                "status": status,
                "active_node": progress.get("active_node"),
                "message": _progress_message(status),
                "created_at": _now_iso(),
            }
        )

    return history


def _progress_message(status: str) -> str:
    return {
        "queued": "분석 요청을 대기열에 등록했습니다.",
        "running": "분석을 진행 중입니다.",
        "success": "분석이 완료되었습니다.",
        "partial": "일부 분석이 완료되었고 추가 입력이 필요합니다.",
        "failed": "분석을 완료하지 못했습니다.",
    }.get(status, "분석 상태를 확인 중입니다.")


def _job_summary(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "session_id": job.get("session_id"),
        "message_id": job.get("message_id"),
        "routing_intent": job.get("routing_intent"),
        "mock_scenario": job.get("mock_scenario"),
        "status": job.get("status"),
        "active_node": job.get("active_node"),
        "progress_message": job.get("progress_message"),
        "analysis_plan_id": job.get("analysis_plan_id"),
        "status_counts": job.get("status_counts", {}),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }


def _display_assistant_message(
    chat_response: dict[str, Any],
    job: dict[str, Any],
    limitations: list[str],
) -> dict[str, Any]:
    answer = str(chat_response.get("assistant_message") or job.get("progress_message") or "")
    return {
        "summary": _result_summary(chat_response, answer),
        "answer": answer,
        "limitations": limitations,
    }


def _result_summary(chat_response: dict[str, Any], fallback: str) -> str:
    for card in chat_response.get("cards", []):
        if isinstance(card, dict) and card.get("summary"):
            return str(card["summary"])
    return fallback


def _display_progress(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("analysis_plan", {}).get("steps", [])
    node_names = _node_names_by_code(job)
    if not steps:
        active_node = job.get("active_node")
        return [
            {
                "order": 1,
                "node_code": active_node,
                "label": active_node or "analysis",
                "status": _display_step_status(job.get("status")),
                "source_status": job.get("status"),
                "active": True,
            }
        ]

    return [
        {
            "order": step.get("order"),
            "node_code": step.get("node_code"),
            "label": node_names.get(step.get("node_code")) or step.get("node_code"),
            "status": _display_step_status(step.get("status")),
            "source_status": step.get("status"),
            "active": step.get("node_code") == job.get("active_node"),
        }
        for step in steps
        if isinstance(step, dict)
    ]


def _display_step_status(status: Any) -> str:
    if status == "success":
        return "done"
    if status in {"failed", "skipped"}:
        return "failed"
    return "waiting"


def _display_attachments(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    display_attachments = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        attachment_id = attachment.get("attachment_id")
        display_attachments.append(
            {
                "attachment_id": attachment_id,
                "label": attachment.get("original_filename")
                or attachment.get("filename")
                or attachment_id,
                "purpose": attachment.get("purpose"),
                "type": attachment.get("type"),
                "status": attachment.get("status"),
                "content_type": attachment.get("content_type"),
                "size_bytes": attachment.get("size_bytes"),
                "storage_uri": attachment.get("storage_uri"),
            }
        )
    return display_attachments


def _display_report_links(job: dict[str, Any], chat_response: dict[str, Any]) -> list[dict[str, Any]]:
    report_id = f"rep_{job['job_id']}"
    report_links = []
    for link in chat_response.get("report_links", []):
        if not isinstance(link, dict):
            continue
        display_link = deepcopy(link)
        display_link.setdefault("report_id", report_id)
        endpoint = display_link.get("endpoint")
        if endpoint == "/api/mock/reports":
            display_link["endpoint"] = "/api/mock/reports/"
        if display_link.get("action") == "download" and endpoint in {
            "/api/mock/reports/download",
            "/api/mock/reports/download/",
        }:
            display_link["endpoint"] = f"/api/mock/reports/{report_id}/download/"
        report_links.append(display_link)
    return report_links


def _display_evidence(job: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_items = []
    for execution in _executions(job):
        agent_output = execution.get("agent_output") or {}
        for evidence in agent_output.get("evidence", []):
            if not isinstance(evidence, dict):
                continue
            display_evidence = deepcopy(evidence)
            display_evidence.setdefault(
                "evidence_id",
                f"ev_{job['job_id']}_{len(evidence_items) + 1}",
            )
            display_evidence["node_code"] = agent_output.get("node_code")
            display_evidence["node_name"] = agent_output.get("node_name")
            evidence_items.append(display_evidence)
    return evidence_items


def _agent_result_summaries(job: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = []
    for execution in _executions(job):
        agent_output = execution.get("agent_output") or {}
        execution_id = execution.get("execution_id")
        node_code = agent_output.get("node_code") or execution.get("node_code")
        summaries.append(
            {
                "result_id": f"res_{execution_id or node_code}",
                "execution_id": execution_id,
                "node_code": node_code,
                "node_name": agent_output.get("node_name"),
                "status": agent_output.get("status"),
                "summary": agent_output.get("summary"),
                "next_actions": deepcopy(agent_output.get("next_actions", [])),
                "evidence_count": len(agent_output.get("evidence", [])),
                "limitation_count": len(agent_output.get("limitations", [])),
                "created_at": agent_output.get("created_at") or execution.get("created_at"),
            }
        )
    return summaries


def _combined_limitations(job: dict[str, Any], chat_response: dict[str, Any]) -> list[str]:
    limitations = []
    limitations.extend(job.get("limitations", []))
    limitations.extend(chat_response.get("limitations", []))
    limitations.extend(job.get("node_execution", {}).get("limitations", []))
    for execution in _executions(job):
        limitations.extend((execution.get("agent_output") or {}).get("limitations", []))
    return _dedupe_strings(limitations)


def _node_names_by_code(job: dict[str, Any]) -> dict[str, str]:
    node_names = {}
    for execution in _executions(job):
        agent_output = execution.get("agent_output") or {}
        node_code = agent_output.get("node_code") or execution.get("node_code")
        node_name = agent_output.get("node_name")
        if node_code and node_name:
            node_names[node_code] = node_name
    return node_names


def _executions(job: dict[str, Any]) -> list[dict[str, Any]]:
    executions = job.get("node_execution", {}).get("executions", [])
    return [execution for execution in executions if isinstance(execution, dict)]


def _dedupe_strings(values: list[Any]) -> list[str]:
    deduped = []
    seen = set()
    for value in values:
        if not isinstance(value, str) or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _job_root() -> Path:
    return Path(os.environ.get("MOCK_ANALYSIS_JOB_ROOT", "backend/media/mock_analysis_jobs"))


def _job_path(job_id: str) -> Path:
    return _job_root() / job_id / "job.json"


def _write_job(job: dict[str, Any]) -> None:
    job_path = _job_path(job["job_id"])
    job_path.parent.mkdir(parents=True, exist_ok=True)
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_job(job_path: Path) -> dict[str, Any] | None:
    if not job_path.exists():
        return None
    try:
        return json.loads(job_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
