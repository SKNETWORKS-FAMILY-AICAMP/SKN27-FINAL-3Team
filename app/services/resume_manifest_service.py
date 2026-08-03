"""Safe public projection for restoring an authenticated user's latest chat."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


RESUME_MANIFEST_VERSION = "resume_manifest.v1"
_SESSION_FIELDS = ("session_id", "status", "current_intent", "updated_at")
_MESSAGE_FIELDS = ("message_id", "role", "content", "routing_intent", "created_at")
_ATTACHMENT_FIELDS = (
    "attachment_id",
    "purpose",
    "filename",
    "status",
    "scan_status",
)
_REPORT_FIELDS = (
    "report_id",
    "report_type",
    "status",
    "title",
    "content_summary",
    "created_at",
    "updated_at",
)
_SENSITIVE_KEY_FRAGMENTS = (
    "authorization",
    "credential",
    "ocrtext",
    "prompt",
    "rawocr",
    "rawtext",
    "reasoning",
    "secret",
    "signedurl",
    "storageuri",
    "token",
    "transcript",
    "uri",
)


def build_resume_manifest(
    *,
    session_record: Mapping[str, Any] | None,
    analysis_detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the latest owned session without internal storage or model data."""

    if not isinstance(session_record, Mapping):
        return _empty_manifest()

    followup_state = _mapping(session_record.get("followup_state"))
    session = _project_mapping(session_record.get("session"), _SESSION_FIELDS)
    messages = _project_messages(session_record.get("conversation_messages"))
    attachments = _project_attachments(session_record.get("attachments"))
    reports = _project_reports(session_record.get("reports"))
    latest_analysis = (
        deepcopy(dict(analysis_detail))
        if isinstance(analysis_detail, Mapping)
        else None
    )
    return {
        "contract_version": RESUME_MANIFEST_VERSION,
        "has_resume": bool(
            session
            and (
                messages
                or attachments
                or reports
                or latest_analysis
                or followup_state
            )
        ),
        "session": session or None,
        "conversation_messages": messages,
        "pending_questions": _project_pending_questions(
            followup_state.get("pending_questions")
        ),
        "facts": _safe_fact_mapping(followup_state.get("facts")),
        "fine_notice_intake": _project_fine_notice_intake(
            followup_state.get("fine_notice_intake")
        ),
        "attachments": attachments,
        "latest_analysis": latest_analysis,
        "reports": reports,
    }


def _empty_manifest() -> dict[str, Any]:
    return {
        "contract_version": RESUME_MANIFEST_VERSION,
        "has_resume": False,
        "session": None,
        "conversation_messages": [],
        "pending_questions": [],
        "facts": {},
        "fine_notice_intake": None,
        "attachments": [],
        "latest_analysis": None,
        "reports": [],
    }


def _project_messages(value: Any) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        projected = _project_mapping(item, _MESSAGE_FIELDS)
        projected["role"] = role
        projected["content"] = content
        messages.append(projected)
    return messages


def _project_pending_questions(value: Any) -> list[dict[str, str]]:
    questions: list[dict[str, str]] = []
    for item in value or []:
        if not isinstance(item, Mapping):
            continue
        field = str(item.get("field") or "").strip()
        question = str(item.get("question") or "").strip()
        if not field or not question:
            continue
        questions.append({"field": field, "question": question})
    return questions


def _project_attachments(value: Any) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, Mapping):
            continue
        projected = _project_mapping(item, _ATTACHMENT_FIELDS)
        if "filename" not in projected:
            filename = str(item.get("original_filename") or "").strip()
            if filename:
                projected["filename"] = filename
        if projected.get("attachment_id"):
            attachments.append(projected)
    return attachments


def _project_reports(value: Any) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, Mapping):
            continue
        projected = _project_mapping(item, _REPORT_FIELDS)
        if projected.get("report_id"):
            reports.append(projected)
    return reports


def _project_fine_notice_intake(value: Any) -> dict[str, Any] | None:
    intake = _mapping(value)
    slots = _safe_fact_mapping(intake.get("slots"))
    if not slots:
        return None
    return {
        "contract_version": str(intake.get("contract_version") or "").strip()
        or "fine_notice_intake.v1",
        "slots": slots,
    }


def _safe_fact_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    projected: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = str(key or "").strip()
        if not normalized_key or _is_sensitive_key(normalized_key):
            continue
        safe_value = _safe_fact_value(item)
        if safe_value is not None:
            projected[normalized_key] = safe_value
    return projected


def _safe_fact_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return deepcopy(value)
    if isinstance(value, Mapping):
        return _safe_fact_mapping(value)
    if isinstance(value, list):
        return [
            safe
            for item in value
            if (safe := _safe_fact_value(item)) is not None
        ]
    return None


def _is_sensitive_key(value: str) -> bool:
    normalized = "".join(character for character in value.lower() if character.isalnum())
    return any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _project_mapping(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        field: deepcopy(value[field])
        for field in fields
        if field in value and _is_public_scalar(value[field])
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _is_public_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))
