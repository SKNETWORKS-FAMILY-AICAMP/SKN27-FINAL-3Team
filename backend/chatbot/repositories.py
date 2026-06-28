"""Repository helpers for canonical API persistence boundaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.db import transaction

from app.services.attachment_mock_service import (
    register_attachment as register_mock_attachment,
)
from chatbot.models import (
    AnalysisJob,
    AnalysisJobEvent,
    AnalysisJobStatus,
    ChatMessage,
    ChatSession,
    ChatSessionStatus,
    MessageRole,
    UploadedFile,
    UploadedFileStatus,
)


def register_uploaded_file(
    payload: dict[str, Any],
    upload_file: Any | None = None,
) -> dict[str, Any]:
    """Register a canonical file upload and persist its metadata in Django DB.

    The byte/object storage path still goes through the mock local storage
    service until the object-storage adapter is introduced.
    """

    attachment = register_mock_attachment(payload, upload_file=upload_file)
    owner_id = _owner_id(payload)
    return persist_uploaded_file_metadata(attachment, owner_id=owner_id, raw_payload=payload)


def persist_uploaded_file_metadata(
    attachment: dict[str, Any],
    *,
    owner_id: str = "",
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = _get_or_create_session(attachment.get("session_id"), owner_id=owner_id)
    metadata = _metadata_snapshot(attachment, raw_payload=raw_payload)

    with transaction.atomic():
        uploaded_file, _created = UploadedFile.objects.update_or_create(
            attachment_id=_text(attachment.get("attachment_id")),
            defaults={
                "owner_id": owner_id or (session.owner_id if session else ""),
                "session": session,
                "purpose": _text(attachment.get("purpose")) or "unknown",
                "file_type": _text(attachment.get("type")),
                "original_filename": _text(attachment.get("original_filename")),
                "content_type": _text(attachment.get("content_type")),
                "size_bytes": _positive_int_or_none(attachment.get("size_bytes")),
                "storage_uri": _text(attachment.get("storage_uri")),
                "privacy_risk": True,
                "status": _model_status(attachment.get("status")),
                "scan_status": "not_started",
                "agent_handoff": attachment.get("agent_handoff") or {},
                "metadata": metadata,
            },
        )

    return uploaded_file_to_api(uploaded_file)


def list_uploaded_files(session_id: str | None = None) -> list[dict[str, Any]]:
    queryset = UploadedFile.objects.select_related("session").order_by("-created_at")
    if session_id:
        queryset = queryset.filter(session__session_id=session_id)
    return [uploaded_file_to_api(uploaded_file) for uploaded_file in queryset]


def get_uploaded_file(attachment_id: str) -> dict[str, Any] | None:
    uploaded_file = (
        UploadedFile.objects.select_related("session")
        .filter(attachment_id=attachment_id)
        .first()
    )
    if uploaded_file is None:
        return None
    return uploaded_file_to_api(uploaded_file)


def persist_chat_message_analysis_boundary(
    payload: dict[str, Any],
    chat_response: dict[str, Any],
) -> dict[str, Any]:
    """Persist the canonical chat message and its analysis-job boundary."""

    owner_id = _owner_id(payload)
    session = _get_or_create_session(chat_response.get("session_id"), owner_id=owner_id)
    if session is None:
        raise ValueError("chat_response must include session_id")

    message_id = _text(chat_response.get("message_id"))
    analysis_plan = chat_response.get("analysis_plan") or {}
    progress = chat_response.get("progress") or {}
    job_id = _analysis_job_id(payload, chat_response)

    with transaction.atomic():
        message, _message_created = ChatMessage.objects.update_or_create(
            message_id=message_id,
            defaults={
                "session": session,
                "role": MessageRole.USER,
                "content": _message_content(payload),
                "routing_intent": _text(chat_response.get("routing_intent")),
                "metadata": {
                    "source": "canonical_chat_message",
                    "analysis_job_id": job_id,
                    "mock_scenario": chat_response.get("mock_scenario"),
                    "mock_status": payload.get("mock_status"),
                    "response_status": chat_response.get("status"),
                    "attachments": chat_response.get("attachments", []),
                    "attachment_resolution": chat_response.get("attachment_resolution", {}),
                    "raw_payload": _safe_payload(payload),
                },
            },
        )
        job, _job_created = AnalysisJob.objects.update_or_create(
            job_id=job_id,
            defaults={
                "session": session,
                "message": message,
                "owner_id": owner_id or session.owner_id,
                "routing_intent": _text(chat_response.get("routing_intent")),
                "mock_scenario": _text(chat_response.get("mock_scenario")),
                "status": _analysis_job_status(chat_response.get("status")),
                "active_node": _text(progress.get("active_node")),
                "progress_message": _text(progress.get("message")),
                "analysis_plan_id": _text(analysis_plan.get("plan_id")),
                "status_counts": _analysis_plan_status_counts(analysis_plan),
                "metadata": {
                    "source": "canonical_chat_message",
                    "analysis_plan": analysis_plan,
                    "assistant_message": chat_response.get("assistant_message"),
                    "case_status": chat_response.get("case_status"),
                    "cards": chat_response.get("cards", []),
                    "pending_questions": chat_response.get("pending_questions", []),
                    "report_links": chat_response.get("report_links", []),
                    "attachments": chat_response.get("attachments", []),
                    "attachment_resolution": chat_response.get("attachment_resolution", {}),
                    "limitations": chat_response.get("limitations", []),
                },
            },
        )
        _upsert_initial_job_event(job, progress=progress)

    return {
        "message_id": message.message_id,
        "job_id": job.job_id,
        "session_id": session.session_id,
    }


def uploaded_file_to_api(uploaded_file: UploadedFile) -> dict[str, Any]:
    metadata = uploaded_file.metadata or {}
    checks = dict(metadata.get("checks") or {})
    checks.setdefault("metadata_repository", UploadedFile._meta.db_table)
    limitations = list(metadata.get("limitations") or [])
    session_id = (
        uploaded_file.session.session_id
        if uploaded_file.session_id
        else metadata.get("session_id")
    )
    filename = metadata.get("filename") or Path(uploaded_file.original_filename).name

    attachment = {
        "attachment_id": uploaded_file.attachment_id,
        "session_id": session_id,
        "message_id": metadata.get("message_id"),
        "purpose": uploaded_file.purpose,
        "type": uploaded_file.file_type,
        "original_filename": uploaded_file.original_filename,
        "filename": filename,
        "content_type": uploaded_file.content_type,
        "size_bytes": uploaded_file.size_bytes or 0,
        "storage_uri": uploaded_file.storage_uri,
        "status": uploaded_file.status,
        "created_at": uploaded_file.created_at.isoformat(),
        "checks": checks,
        "agent_handoff": uploaded_file.agent_handoff or {},
        "limitations": limitations,
        "persistence": {
            "backend": "postgresql",
            "table": UploadedFile._meta.db_table,
            "status": "metadata_saved",
        },
    }
    return {key: value for key, value in attachment.items() if value is not None}


def _get_or_create_session(session_id: Any, *, owner_id: str) -> ChatSession | None:
    normalized_session_id = _text(session_id)
    if not normalized_session_id:
        return None

    session, _created = ChatSession.objects.get_or_create(
        session_id=normalized_session_id,
        defaults={
            "owner_id": owner_id,
            "status": ChatSessionStatus.ACTIVE,
            "metadata": {"created_by": "canonical_file_upload"},
        },
    )
    if owner_id and not session.owner_id:
        session.owner_id = owner_id
        session.save(update_fields=["owner_id", "updated_at"])
    return session


def _metadata_snapshot(
    attachment: dict[str, Any],
    *,
    raw_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "session_id": attachment.get("session_id"),
        "message_id": attachment.get("message_id"),
        "filename": attachment.get("filename"),
        "mock_status": attachment.get("status"),
        "checks": attachment.get("checks") or {},
        "limitations": attachment.get("limitations") or [],
        "raw_payload": _safe_payload(raw_payload or {}),
    }


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }


def _owner_id(payload: dict[str, Any]) -> str:
    return _text(payload.get("owner_id") or payload.get("user_id"))


def _message_content(payload: dict[str, Any]) -> str:
    return _text(payload.get("user_text") or payload.get("message") or payload.get("content"))


def _analysis_job_id(payload: dict[str, Any], chat_response: dict[str, Any]) -> str:
    explicit_job_id = _text(payload.get("job_id"))
    if explicit_job_id:
        return explicit_job_id
    message_id = _text(chat_response.get("message_id"))
    if message_id.startswith("msg_"):
        return f"job_{message_id.removeprefix('msg_')}"
    return f"job_{message_id}"


def _analysis_job_status(status: Any) -> str:
    status_text = _text(status)
    if status_text in {choice.value for choice in AnalysisJobStatus}:
        return status_text
    if status_text == "pending":
        return AnalysisJobStatus.RUNNING
    return AnalysisJobStatus.RUNNING


def _analysis_plan_status_counts(analysis_plan: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    steps = analysis_plan.get("steps") or []
    for step in steps:
        if not isinstance(step, dict):
            continue
        status = _text(step.get("status")) or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return counts


def _upsert_initial_job_event(
    job: AnalysisJob,
    *,
    progress: dict[str, Any],
) -> None:
    status = job.status
    active_node = _text(progress.get("active_node"))
    message = _text(progress.get("message")) or "canonical chat message에서 분석 job 경계를 생성했습니다."
    first_event = job.events.order_by("created_at").first()
    if first_event is None:
        AnalysisJobEvent.objects.create(
            job=job,
            status=status,
            active_node=active_node,
            message=message,
            metadata={"source": "canonical_chat_message"},
        )
        return

    first_event.status = status
    first_event.active_node = active_node
    first_event.message = message
    first_event.metadata = {"source": "canonical_chat_message"}
    first_event.save(update_fields=["status", "active_node", "message", "metadata"])


def _model_status(status: Any) -> str:
    status_text = _text(status)
    if status_text in {choice.value for choice in UploadedFileStatus}:
        return status_text
    if status_text == "metadata_registered":
        return UploadedFileStatus.UPLOADED
    return UploadedFileStatus.UPLOADED


def _positive_int_or_none(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
