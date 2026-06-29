"""Standard-light mock history event storage for the MVP workflow."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


HISTORY_EVENT_VERSION = "history_event.v1"
DEFAULT_RETENTION_POLICY = "review_required"
DEFAULT_HISTORY_LIMIT = 100

SENSITIVE_METADATA_KEYS = {
    "answer",
    "content",
    "completion",
    "full_text",
    "message",
    "ocr_raw",
    "ocr_result",
    "ocr_text",
    "prompt",
    "raw_output",
    "raw_payload",
    "reasoning",
    "transcript",
    "user_text",
}


def record_history_event(
    *,
    event_type: str,
    status: str,
    summary: str,
    actor: dict[str, Any] | None = None,
    subject: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    privacy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create and persist one standard-light history event."""

    event = build_history_event(
        event_type=event_type,
        status=status,
        summary=summary,
        actor=actor,
        subject=subject,
        source=source,
        metadata=metadata,
        privacy=privacy,
    )
    _write_event(event)
    return event


def build_history_event(
    *,
    event_type: str,
    status: str,
    summary: str,
    actor: dict[str, Any] | None = None,
    subject: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    privacy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one standard-light history event payload without choosing storage."""

    occurred_at = _now_iso()
    return {
        "event_id": f"evt_{uuid4().hex[:16]}",
        "event_type": str(event_type),
        "event_version": HISTORY_EVENT_VERSION,
        "occurred_at": occurred_at,
        "actor": _normalize_actor(actor),
        "subject": _normalize_subject(subject),
        "source": _normalize_source(source),
        "status": str(status or "success"),
        "summary": _safe_summary(summary),
        "metadata": sanitize_metadata(metadata or {}),
        "privacy": _normalize_privacy(privacy),
        "created_at": occurred_at,
    }


def list_history_events(
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    guest_id: str | None = None,
    job_id: str | None = None,
    event_type: str | None = None,
    limit: int = DEFAULT_HISTORY_LIMIT,
) -> list[dict[str, Any]]:
    """Read persisted mock history events and apply light filters."""

    events = []
    for event_path in sorted(_history_root().glob("*/*.json")):
        event = _read_event(event_path)
        if not event or not history_event_matches(
            event,
            session_id=session_id,
            user_id=user_id,
            guest_id=guest_id,
            job_id=job_id,
            event_type=event_type,
        ):
            continue
        events.append(event)

    events.sort(key=lambda item: (item.get("occurred_at") or "", item.get("event_id") or ""))
    return events[-max(limit, 1) :]


def actor_from_payload(
    payload: dict[str, Any] | None = None,
    *,
    authorization_header: str | None = None,
    guest_id_header: str | None = None,
    auth_session_id_header: str | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    auth_context = payload.get("auth_context") if isinstance(payload.get("auth_context"), dict) else {}
    guest_id = _text(guest_id_header or auth_context.get("guest_id") or payload.get("guest_id")) or None
    auth_session_id = _text(auth_session_id_header or auth_context.get("auth_session_id")) or None
    user_id = _text(auth_context.get("user_id") or payload.get("user_id") or payload.get("owner_id")) or None
    auth_state = _text(auth_context.get("auth_state"))
    if not auth_state:
        if user_id or auth_session_id or authorization_header:
            auth_state = "authenticated"
        elif guest_id:
            auth_state = "guest"
        else:
            auth_state = "anonymous"

    return {
        "user_id": user_id,
        "guest_id": guest_id,
        "auth_session_id": auth_session_id,
        "auth_state": auth_state,
    }


def source_from_request(
    *,
    api_path: str,
    execution_mode: str = "mock",
    surface: str = "api",
    node_code: str | None = None,
) -> dict[str, Any]:
    return {
        "surface": surface,
        "api_path": api_path,
        "execution_mode": execution_mode,
        "node_code": node_code,
    }


def subject_from_payload(
    payload: dict[str, Any] | None = None,
    *,
    session_id: str | None = None,
    message_id: str | None = None,
    job_id: str | None = None,
    report_id: str | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    auth_context = payload.get("auth_context") if isinstance(payload.get("auth_context"), dict) else {}
    return {
        "session_id": _text(session_id or payload.get("session_id") or auth_context.get("session_id")) or None,
        "message_id": _text(message_id or payload.get("message_id")) or None,
        "job_id": _text(job_id or payload.get("job_id")) or None,
        "report_id": _text(report_id or payload.get("report_id")) or None,
    }


def record_agent_execution_events(
    executions: list[dict[str, Any]],
    *,
    actor: dict[str, Any],
    source: dict[str, Any],
    subject: dict[str, Any],
) -> list[dict[str, Any]]:
    events = build_agent_execution_events(
        executions,
        actor=actor,
        source=source,
        subject=subject,
    )
    for event in events:
        _write_event(event)
    return events


def build_agent_execution_events(
    executions: list[dict[str, Any]],
    *,
    actor: dict[str, Any],
    source: dict[str, Any],
    subject: dict[str, Any],
) -> list[dict[str, Any]]:
    events = []
    for execution in executions:
        if not isinstance(execution, dict):
            continue
        agent_output = execution.get("agent_output") if isinstance(execution.get("agent_output"), dict) else {}
        node_code = _text(agent_output.get("node_code") or execution.get("node_code"))
        status = _text(agent_output.get("status") or execution.get("execution_status") or "success")
        event_type = {
            "failed": "agent_call_failed",
            "partial": "agent_call_partial",
        }.get(status, "agent_call_completed")
        structured_result = agent_output.get("structured_result") if isinstance(agent_output.get("structured_result"), dict) else {}
        event_subject = dict(subject)
        event_subject["job_id"] = event_subject.get("job_id") or execution.get("job_id") or agent_output.get("job_id")
        event_source = dict(source)
        event_source["node_code"] = node_code or event_source.get("node_code")
        events.append(
            build_history_event(
                event_type=event_type,
                status=status,
                summary=_safe_summary(agent_output.get("summary") or f"{node_code or 'agent'} mock 호출을 기록했습니다."),
                actor=actor,
                subject=event_subject,
                source=event_source,
                metadata={
                    "execution_id": execution.get("execution_id"),
                    "execution_status": execution.get("execution_status"),
                    "node_code": node_code,
                    "node_name": agent_output.get("node_name"),
                    "missing_fields": structured_result.get("missing_fields", []),
                    "evidence_count": len(agent_output.get("evidence", [])),
                    "limitation_count": len(agent_output.get("limitations", [])),
                },
                privacy={
                    "risk_level": "medium" if status != "success" else "low",
                    "contains_model_output": True,
                },
            )
        )
    return events


def sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            normalized_key = str(key)
            if normalized_key.lower() in SENSITIVE_METADATA_KEYS:
                continue
            sanitized[normalized_key] = sanitize_metadata(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _normalize_actor(actor: dict[str, Any] | None) -> dict[str, Any]:
    actor = actor or {}
    auth_state = _text(actor.get("auth_state")) or "anonymous"
    return {
        "user_id": _text(actor.get("user_id")) or None,
        "guest_id": _text(actor.get("guest_id")) or None,
        "auth_session_id": _text(actor.get("auth_session_id")) or None,
        "auth_state": auth_state,
    }


def _normalize_subject(subject: dict[str, Any] | None) -> dict[str, Any]:
    subject = subject or {}
    return {
        "session_id": _text(subject.get("session_id")) or None,
        "message_id": _text(subject.get("message_id")) or None,
        "job_id": _text(subject.get("job_id")) or None,
        "report_id": _text(subject.get("report_id")) or None,
    }


def _normalize_source(source: dict[str, Any] | None) -> dict[str, Any]:
    source = source or {}
    return {
        "surface": _text(source.get("surface")) or "api",
        "api_path": _text(source.get("api_path")) or None,
        "execution_mode": _text(source.get("execution_mode")) or "mock",
        "node_code": _text(source.get("node_code")) or None,
    }


def _normalize_privacy(privacy: dict[str, Any] | None) -> dict[str, Any]:
    privacy = privacy or {}
    return {
        "risk_level": _text(privacy.get("risk_level")) or "low",
        "contains_user_text": bool(privacy.get("contains_user_text", False)),
        "contains_file_uri": bool(privacy.get("contains_file_uri", False)),
        "contains_model_output": bool(privacy.get("contains_model_output", False)),
        "retention_policy": _text(privacy.get("retention_policy")) or DEFAULT_RETENTION_POLICY,
    }


def history_event_matches(
    event: dict[str, Any],
    *,
    session_id: str | None,
    user_id: str | None,
    guest_id: str | None,
    job_id: str | None,
    event_type: str | None,
) -> bool:
    actor = event.get("actor") or {}
    subject = event.get("subject") or {}
    return all(
        [
            not session_id or subject.get("session_id") == session_id,
            not user_id or actor.get("user_id") == user_id,
            not guest_id or actor.get("guest_id") == guest_id,
            not job_id or subject.get("job_id") == job_id,
            not event_type or event.get("event_type") == event_type,
        ]
    )


def _write_event(event: dict[str, Any]) -> None:
    event_path = _event_path(event)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event_path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_event(event_path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(event_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _event_path(event: dict[str, Any]) -> Path:
    subject = event.get("subject") or {}
    actor = event.get("actor") or {}
    bucket = (
        subject.get("session_id")
        or subject.get("job_id")
        or actor.get("user_id")
        or actor.get("guest_id")
        or "global"
    )
    return _history_root() / _safe_segment(bucket) / f"{event['event_id']}.json"


def _history_root() -> Path:
    return Path(os.environ.get("MOCK_HISTORY_EVENT_ROOT", "backend/media/mock_history_events"))


def _safe_segment(value: Any) -> str:
    text = _text(value) or "global"
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in text)


def _safe_summary(value: Any) -> str:
    summary = _text(value)
    return summary[:280] if summary else "history event recorded"


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
