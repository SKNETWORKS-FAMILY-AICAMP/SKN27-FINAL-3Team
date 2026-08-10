"""Canonical history event payload contract without sidecar persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.security.pii_masking import mask_text, sanitize_pii


HISTORY_EVENT_VERSION = "history_event.v1"
DEFAULT_RETENTION_POLICY = "review_required"
SENSITIVE_METADATA_KEYS = {
    "answer", "content", "completion", "full_text", "message", "ocr_raw", "ocr_result",
    "ocr_text", "prompt", "raw_output", "raw_payload", "reasoning", "transcript", "user_text",
}
CANONICAL_MOCK_MARKERS = {"mock_scenario", "mock_status", "canonical_mock"}


def build_history_event(*, event_type: str, status: str, summary: str, actor: dict[str, Any] | None = None, subject: dict[str, Any] | None = None, source: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None, privacy: dict[str, Any] | None = None) -> dict[str, Any]:
    occurred_at = _now_iso()
    return {
        "event_id": f"evt_{uuid4().hex[:16]}",
        "event_type": _text(event_type),
        "event_version": HISTORY_EVENT_VERSION,
        "occurred_at": occurred_at,
        "actor": _normalize_actor(actor),
        "subject": _normalize_subject(subject),
        "source": _normalize_source(source),
        "status": _text(status) or "success",
        "summary": _safe_summary(summary),
        "metadata": sanitize_metadata(metadata or {}),
        "privacy": _normalize_privacy(privacy),
        "created_at": occurred_at,
    }


def build_agent_execution_events(executions: list[dict[str, Any]], *, actor: dict[str, Any], source: dict[str, Any], subject: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for execution in executions:
        if not isinstance(execution, dict):
            continue
        agent_output = execution.get("agent_output") if isinstance(execution.get("agent_output"), dict) else {}
        node_code = _text(agent_output.get("node_code") or execution.get("node_code"))
        status = _text(agent_output.get("status") or execution.get("execution_status")) or "success"
        event_subject = {**subject, "job_id": subject.get("job_id") or execution.get("job_id") or agent_output.get("job_id")}
        event_source = {**source, "node_code": node_code or source.get("node_code")}
        structured = agent_output.get("structured_result") if isinstance(agent_output.get("structured_result"), dict) else {}
        events.append(build_history_event(
            event_type={"failed": "agent_call_failed", "partial": "agent_call_partial"}.get(status, "agent_call_completed"),
            status=status,
            summary=_safe_summary(agent_output.get("summary") or f"{node_code or 'agent'} execution recorded."),
            actor=actor,
            subject=event_subject,
            source=event_source,
            metadata={
                "execution_id": execution.get("execution_id"), "execution_status": execution.get("execution_status"),
                "node_code": node_code, "node_name": agent_output.get("node_name"),
                "missing_fields": structured.get("missing_fields", []), "evidence_count": len(agent_output.get("evidence", [])),
                "limitation_count": len(agent_output.get("limitations", [])),
            },
            privacy={"risk_level": "medium" if status != "success" else "low", "contains_model_output": True},
        ))
    return events


def actor_from_payload(payload: dict[str, Any] | None = None, *, authorization_header: str | None = None, guest_id_header: str | None = None, auth_session_id_header: str | None = None) -> dict[str, Any]:
    payload = payload or {}
    auth_context = payload.get("auth_context") if isinstance(payload.get("auth_context"), dict) else {}
    guest_id = _text(guest_id_header or auth_context.get("guest_id") or payload.get("guest_id")) or None
    user_id = _text(auth_context.get("user_id") or payload.get("user_id") or payload.get("owner_id")) or None
    auth_session_id = _text(auth_session_id_header or auth_context.get("auth_session_id")) or None
    auth_state = _text(auth_context.get("auth_state")) or ("authenticated" if user_id or auth_session_id or authorization_header else "guest" if guest_id else "anonymous")
    return {"user_id": user_id, "guest_id": guest_id, "auth_session_id": auth_session_id, "auth_state": auth_state}


def subject_from_payload(payload: dict[str, Any] | None = None, *, session_id: str | None = None, message_id: str | None = None, job_id: str | None = None, report_id: str | None = None) -> dict[str, Any]:
    payload = payload or {}
    auth_context = payload.get("auth_context") if isinstance(payload.get("auth_context"), dict) else {}
    return {"session_id": _text(session_id or payload.get("session_id") or auth_context.get("session_id")) or None, "message_id": _text(message_id or payload.get("message_id")) or None, "job_id": _text(job_id or payload.get("job_id")) or None, "report_id": _text(report_id or payload.get("report_id")) or None}


def source_from_request(*, api_path: str, execution_mode: str = "canonical", surface: str = "api", node_code: str | None = None) -> dict[str, Any]:
    return {"surface": surface, "api_path": api_path, "execution_mode": execution_mode, "node_code": node_code}


def sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize_metadata(item) for key, item in value.items() if str(key).lower() not in SENSITIVE_METADATA_KEYS | CANONICAL_MOCK_MARKERS}
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    return sanitize_pii(value if isinstance(value, (str, int, float, bool)) or value is None else str(value))


def _normalize_actor(actor: dict[str, Any] | None) -> dict[str, Any]:
    actor = actor or {}
    return {"user_id": _text(actor.get("user_id")) or None, "guest_id": _text(actor.get("guest_id")) or None, "auth_session_id": _text(actor.get("auth_session_id")) or None, "auth_state": _text(actor.get("auth_state")) or "anonymous"}


def _normalize_subject(subject: dict[str, Any] | None) -> dict[str, Any]:
    subject = subject or {}
    return {key: _text(subject.get(key)) or None for key in ("session_id", "message_id", "job_id", "report_id")}


def _normalize_source(source: dict[str, Any] | None) -> dict[str, Any]:
    source = source or {}
    return {"surface": _text(source.get("surface")) or "api", "api_path": _text(source.get("api_path")) or None, "execution_mode": _text(source.get("execution_mode")) or "canonical", "node_code": _text(source.get("node_code")) or None}


def _normalize_privacy(privacy: dict[str, Any] | None) -> dict[str, Any]:
    privacy = privacy or {}
    return {"risk_level": _text(privacy.get("risk_level")) or "low", "contains_user_text": bool(privacy.get("contains_user_text", False)), "contains_file_uri": bool(privacy.get("contains_file_uri", False)), "contains_model_output": bool(privacy.get("contains_model_output", False)), "retention_policy": _text(privacy.get("retention_policy")) or DEFAULT_RETENTION_POLICY}


def _safe_summary(value: Any) -> str:
    summary = mask_text(_text(value))
    return summary[:280] if summary else "history event recorded"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
