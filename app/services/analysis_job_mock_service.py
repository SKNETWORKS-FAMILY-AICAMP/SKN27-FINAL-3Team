"""Mock analysis job lifecycle for the Django integration phase."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.agent_node_service import execute_mock_plan
from app.services.chatbot_mock_service import submit_message


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
            "중간발표용 mock analysis job이며 실제 비동기 queue, Redis, DB 저장은 사용하지 않습니다."
        ],
    }
    _write_job(job)
    return job


def get_analysis_job(job_id: str) -> dict[str, Any] | None:
    return _read_job(_job_path(job_id))


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
