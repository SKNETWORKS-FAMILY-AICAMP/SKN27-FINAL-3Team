"""Ephemeral progress cache helpers for canonical analysis flows."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.cache import cache

from chatbot.models import AnalysisJob, ChatSession

PROGRESS_CACHE_POLICY_VERSION = "progress_cache.v1"
ANALYSIS_JOB_PROGRESS_KEY_PREFIX = "analysis_job_progress"
CHAT_SESSION_STATE_KEY_PREFIX = "chat_session_state"
PROGRESS_CACHE_FALLBACK = "postgresql"
DEFAULT_PROGRESS_CACHE_TTL_SECONDS = 300


def analysis_job_progress_key(job_id: str) -> str:
    return f"{ANALYSIS_JOB_PROGRESS_KEY_PREFIX}:{job_id}"


def chat_session_state_key(session_id: str) -> str:
    return f"{CHAT_SESSION_STATE_KEY_PREFIX}:{session_id}"


def progress_cache_ttl_seconds() -> int:
    raw_ttl = getattr(
        settings,
        "PROGRESS_CACHE_TTL_SECONDS",
        DEFAULT_PROGRESS_CACHE_TTL_SECONDS,
    )
    try:
        ttl = int(raw_ttl)
    except (TypeError, ValueError):
        return DEFAULT_PROGRESS_CACHE_TTL_SECONDS
    return ttl if ttl > 0 else DEFAULT_PROGRESS_CACHE_TTL_SECONDS


def progress_cache_backend() -> str:
    backend_path = ""
    caches = getattr(settings, "CACHES", {})
    if isinstance(caches, dict):
        default_cache = caches.get("default", {})
        if isinstance(default_cache, dict):
            backend_path = str(default_cache.get("BACKEND", ""))

    backend_path = backend_path.lower()
    if "redis" in backend_path:
        return "redis"
    if "locmem" in backend_path:
        return "locmem"
    if backend_path:
        return backend_path.rsplit(".", 1)[-1]
    return "unknown"


def progress_cache_policy() -> dict[str, Any]:
    return {
        "policy_version": PROGRESS_CACHE_POLICY_VERSION,
        "backend": progress_cache_backend(),
        "ttl_seconds": progress_cache_ttl_seconds(),
        "fallback": PROGRESS_CACHE_FALLBACK,
        "key_patterns": {
            "analysis_job_progress": f"{ANALYSIS_JOB_PROGRESS_KEY_PREFIX}:{{job_id}}",
            "chat_session_state": f"{CHAT_SESSION_STATE_KEY_PREFIX}:{{session_id}}",
        },
        "cache_role": "ephemeral_progress_state",
        "stores_raw_user_input": False,
        "stores_agent_reasoning": False,
    }


def build_analysis_job_progress_snapshot(job: AnalysisJob) -> dict[str, Any]:
    return {
        "policy_version": PROGRESS_CACHE_POLICY_VERSION,
        "key": analysis_job_progress_key(job.job_id),
        "cache_role": "ephemeral_analysis_job_progress",
        "fallback": PROGRESS_CACHE_FALLBACK,
        "job_id": job.job_id,
        "session_id": job.session.session_id if job.session_id else None,
        "owner_id": job.owner_id or None,
        "status": job.status,
        "active_node": job.active_node,
        "progress_message": job.progress_message,
        "analysis_plan_id": job.analysis_plan_id,
        "status_counts": job.status_counts or {},
        "updated_at": job.updated_at.isoformat(),
        "source_tables": ["analysis_jobs", "analysis_job_events"],
    }


def build_chat_session_state_snapshot(
    session: ChatSession,
    *,
    latest_job: AnalysisJob | None = None,
) -> dict[str, Any]:
    if latest_job is None:
        latest_job = (
            AnalysisJob.objects.filter(session=session)
            .order_by("-updated_at")
            .first()
        )

    return {
        "policy_version": PROGRESS_CACHE_POLICY_VERSION,
        "key": chat_session_state_key(session.session_id),
        "cache_role": "ephemeral_chat_session_state",
        "fallback": PROGRESS_CACHE_FALLBACK,
        "session_id": session.session_id,
        "owner_id": session.owner_id or None,
        "status": session.status,
        "current_intent": session.current_intent or (latest_job.routing_intent if latest_job else ""),
        "latest_job_id": latest_job.job_id if latest_job else None,
        "latest_job_status": latest_job.status if latest_job else None,
        "updated_at": session.updated_at.isoformat(),
        "source_tables": ["chat_sessions", "analysis_jobs"],
    }


def write_analysis_job_progress(job: AnalysisJob) -> dict[str, Any]:
    snapshot = build_analysis_job_progress_snapshot(job)
    return _write_snapshot(snapshot)


def write_chat_session_state(
    session: ChatSession,
    *,
    latest_job: AnalysisJob | None = None,
) -> dict[str, Any]:
    snapshot = build_chat_session_state_snapshot(session, latest_job=latest_job)
    return _write_snapshot(snapshot)


def read_analysis_job_progress(job_id: str) -> dict[str, Any]:
    key = analysis_job_progress_key(job_id)
    cached = _safe_cache_get(key)
    if cached["status"] == "hit":
        return _read_result(key=key, status="hit", snapshot=cached["snapshot"])

    job = (
        AnalysisJob.objects.select_related("session")
        .filter(job_id=job_id)
        .first()
    )
    if job is None:
        status = "not_found"
        if cached["status"] == "unavailable":
            status = "unavailable_not_found"
        return _read_result(key=key, status=status, snapshot=None, error=cached.get("error"))

    snapshot = build_analysis_job_progress_snapshot(job)
    write_result = _write_snapshot(snapshot)
    status = "miss_fallback"
    error = cached.get("error")
    if cached["status"] == "unavailable" or write_result["status"] == "unavailable":
        status = "unavailable_fallback"
        error = error or write_result.get("error")
    return _read_result(key=key, status=status, snapshot=snapshot, error=error)


def read_chat_session_state(session_id: str) -> dict[str, Any]:
    key = chat_session_state_key(session_id)
    cached = _safe_cache_get(key)
    if cached["status"] == "hit":
        return _read_result(key=key, status="hit", snapshot=cached["snapshot"])

    session = ChatSession.objects.filter(session_id=session_id).first()
    if session is None:
        status = "not_found"
        if cached["status"] == "unavailable":
            status = "unavailable_not_found"
        return _read_result(key=key, status=status, snapshot=None, error=cached.get("error"))

    latest_job = (
        AnalysisJob.objects.filter(session=session)
        .order_by("-updated_at")
        .first()
    )
    snapshot = build_chat_session_state_snapshot(session, latest_job=latest_job)
    write_result = _write_snapshot(snapshot)
    status = "miss_fallback"
    error = cached.get("error")
    if cached["status"] == "unavailable" or write_result["status"] == "unavailable":
        status = "unavailable_fallback"
        error = error or write_result.get("error")
    return _read_result(key=key, status=status, snapshot=snapshot, error=error)


def _write_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    key = str(snapshot["key"])
    result = _base_result(key=key)
    try:
        cache.set(key, snapshot, timeout=progress_cache_ttl_seconds())
    except Exception as exc:  # pragma: no cover - depends on external Redis availability.
        result["status"] = "unavailable"
        result["error"] = exc.__class__.__name__
        return result

    result["status"] = "cached"
    result["snapshot"] = snapshot
    return result


def _safe_cache_get(key: str) -> dict[str, Any]:
    try:
        snapshot = cache.get(key)
    except Exception as exc:  # pragma: no cover - depends on external Redis availability.
        return {
            "status": "unavailable",
            "snapshot": None,
            "error": exc.__class__.__name__,
        }
    if snapshot is None:
        return {"status": "miss", "snapshot": None}
    return {"status": "hit", "snapshot": snapshot}


def _read_result(
    *,
    key: str,
    status: str,
    snapshot: dict[str, Any] | None,
    error: str | None = None,
) -> dict[str, Any]:
    result = _base_result(key=key)
    result["status"] = status
    result["snapshot"] = snapshot
    if error:
        result["error"] = error
    return result


def _base_result(*, key: str) -> dict[str, Any]:
    return {
        "policy_version": PROGRESS_CACHE_POLICY_VERSION,
        "backend": progress_cache_backend(),
        "key": key,
        "ttl_seconds": progress_cache_ttl_seconds(),
        "fallback": PROGRESS_CACHE_FALLBACK,
    }
