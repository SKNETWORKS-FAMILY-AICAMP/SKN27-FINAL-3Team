"""Repository helpers for canonical API persistence boundaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.db import transaction

from app.services.attachment_mock_service import (
    register_attachment as register_mock_attachment,
)
from chatbot.models import ChatSession, ChatSessionStatus, UploadedFile, UploadedFileStatus


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
