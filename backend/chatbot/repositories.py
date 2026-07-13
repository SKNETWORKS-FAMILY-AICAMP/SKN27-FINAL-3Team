"""Repository helpers for canonical API persistence boundaries."""

from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta, timezone as datetime_timezone
from io import BytesIO
from pathlib import Path
from threading import Event, Thread
from typing import Any

from django.conf import settings
from django.db import DatabaseError, close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from app.services.attachment_mock_service import (
    register_attachment as register_mock_attachment,
)
from app.services.history_event_mock_service import (
    SENSITIVE_METADATA_KEYS,
    build_agent_execution_events,
    build_history_event,
)
from chatbot.models import (
    AgentInvocation,
    AgentInvocationStatus,
    AgentNodeDefinition,
    AgentResult,
    AgentResultStatus,
    AgentWorkItem,
    AgentWorkItemStatus,
    AiSession,
    AnalysisDisplayResult,
    AnalysisJob,
    AnalysisJobEvent,
    AnalysisJobStatus,
    AuthEvent,
    AuthSession,
    AuthSessionStatus,
    Case,
    ConfirmedFactVersion,
    ChatMessage,
    ChatSession,
    ChatSessionStatus,
    CodeGroup,
    CodeItem,
    GuestIdentity,
    GuestIdentityStatus,
    HistoryEvent,
    MessageRole,
    RetrievalEvent,
    Report,
    ReportStatus,
    ReportType,
    Subscription,
    SubscriptionStatus,
    SocialAccount,
    UsageEvent,
    UsageQuota,
    UserAccount,
    UserAccountStatus,
    UploadedFile,
    UploadedFileStatus,
)
from chatbot.object_storage import (
    build_quarantine_upload_storage_reference,
    build_report_storage_reference,
    build_upload_storage_reference,
    copy_object,
    delete_object,
    delete_source_uri,
    object_storage_bucket,
    object_storage_policy,
    object_storage_prefix,
    storage_reference_from_uri,
    write_object,
    write_object_from_source_uri,
)
from chatbot.progress_cache import (
    progress_cache_policy,
    write_analysis_job_progress,
    write_chat_session_state,
)
from chatbot.retention_policy import upload_retention_expires_at

USAGE_POLICY_GROUP_CODE = "usage_quota_policy"
REPORT_PDF_CONTENT_TYPE = "application/pdf"
REPORT_DOWNLOAD_TYPE_REPORT = "report"
REPORT_DOWNLOAD_TYPE_OBJECTION_FORM = "objection_form"
ACCIDENT_OBJECTION_TEMPLATE_PATH = Path(__file__).resolve().parent / "traffic_objection_form_template.pdf"
ACCIDENT_OBJECTION_RENDERER_PATH = Path(__file__).resolve().parent / "pdf_template_renderer.py"
REPORT_PDF_RENDERER_PATH = Path(__file__).resolve().parent / "pdf_report_renderer.py"
UPLOAD_STORAGE_LIFECYCLE_VERSION = "upload_storage_lifecycle.v1"
REPORT_STAGING_CLEANUP_BATCH_VERSION = "report_staging_cleanup_batch.v1"
REPORT_STAGING_CLEANUP_PENDING = "staging_cleanup_pending"
SUCCESSFUL_STORAGE_DELETE_STATUSES = {"deleted", "not_found"}
DEFAULT_REPORT_STAGING_CLEANUP_LIMIT = 100


class ReportReferenceError(ValueError):
    """Stable report-reference error whose internal detail is log-only."""

    def __init__(self, reason: str, internal_message: str) -> None:
        super().__init__(internal_message)
        self.reason = reason


class AuthSessionStateError(ValueError):
    """Fail-closed auth-session persistence error safe to expose as a reason code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class UploadStorageUnavailableError(RuntimeError):
    """Retryable upload error raised when quarantine persistence did not finish."""

    def __init__(self, reason: str) -> None:
        super().__init__("quarantine object storage is unavailable")
        self.reason = reason or "quarantine_write_failed"


class AttachmentScanGateError(RuntimeError):
    """Queued work item no longer has access to every requested attachment."""

    def __init__(self) -> None:
        super().__init__("queued attachment is no longer available")
        self.reason = "attachment_scan_gate_blocked"


class UploadValidationError(ValueError):
    """Stable validation error for canonical upload boundary requirements."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def build_report_download_pdf_body(
    *,
    report_id: str,
    title: str,
    body_text: str,
) -> bytes:
    """Build a lightweight PDF report from the persisted report text body."""

    try:
        import fitz
    except Exception:
        reportlab_pdf = _reportlab_pdf_bytes(report_id=report_id, title=title, body_text=body_text)
        if reportlab_pdf:
            return reportlab_pdf
        return _minimal_pdf_bytes(title=title or report_id, body_text=body_text)

    doc = fitz.open()
    margin = 48
    page_width = 595
    page_height = 842
    line_height = 17
    font_file = _report_pdf_font_file()
    fontname = "reportfont" if font_file else "helv"

    page = doc.new_page(width=page_width, height=page_height)
    if font_file:
        page.insert_font(fontname=fontname, fontfile=font_file)
    y = margin

    def ensure_page(required_height: int = line_height):
        nonlocal page, y
        if y + required_height <= page_height - margin:
            return
        page = doc.new_page(width=page_width, height=page_height)
        if font_file:
            page.insert_font(fontname=fontname, fontfile=font_file)
        y = margin

    def write_line(text: str, *, size: int = 10, spacing: int = 0, indent: int = 0):
        nonlocal y
        ensure_page(line_height + spacing)
        page.insert_text(
            (margin + indent, y),
            text,
            fontsize=size,
            fontname=fontname,
            fontfile=font_file,
            color=(0, 0, 0),
        )
        y += line_height + spacing

    def write_wrapped(text: str, *, size: int = 10, width: int = 72, prefix: str = "", indent: int = 0):
        for chunk_index, chunk in enumerate(_wrap_report_pdf_line(text, width=width)):
            write_line(f"{prefix if chunk_index == 0 else '  '}{chunk}", size=size, indent=indent)

    title_text = title or "상담 분석 리포트"
    write_line(title_text, size=16, spacing=8)
    write_line(f"Report ID: {report_id}", size=9, spacing=8)
    write_line("본 문서는 Traffic Dispute AI 상담 결과를 바탕으로 생성한 검토용 리포트입니다.", size=9, spacing=10)

    for raw_line in str(body_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            y += 8
            continue
        if line.startswith("# "):
            write_line(line[2:], size=15, spacing=6)
            continue
        if line.startswith("## "):
            write_line(line[3:], size=13, spacing=5)
            continue
        if line.startswith("### "):
            write_line(line[4:], size=11, spacing=3)
            continue
        prefix = "- " if line.startswith("- ") else ""
        line_body = line[2:] if prefix else line
        write_wrapped(line_body, width=68 if prefix else 72, prefix=prefix, indent=10 if prefix else 0)

    metadata_title = title_text[:120]
    doc.set_metadata(
        {
            "title": metadata_title,
            "subject": "Traffic Dispute AI report",
            "creator": "Traffic Dispute AI",
        }
    )
    pdf_bytes = doc.tobytes(deflate=True)
    doc.close()
    return pdf_bytes


def _reportlab_pdf_bytes(*, report_id: str, title: str, body_text: str) -> bytes | None:
    modules = _reportlab_pdf_modules()
    if modules is None:
        return _reportlab_pdf_bytes_via_bundled_python(report_id=report_id, title=title, body_text=body_text)

    canvas_cls = modules["canvas"]
    pdfmetrics = modules["pdfmetrics"]
    ttfont = modules["ttfont"]

    font_file = _report_pdf_font_file()
    font_name = "ReportBody"
    try:
        if font_file and font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(ttfont(font_name, font_file))
    except Exception:
        return None

    if font_name not in pdfmetrics.getRegisteredFontNames():
        return None

    page_width = 595
    page_height = 842
    margin_x = 54
    margin_top = 58
    margin_bottom = 56
    max_width = page_width - (margin_x * 2)

    output = BytesIO()
    pdf_canvas = canvas_cls(output, pagesize=(page_width, page_height))
    pdf_canvas.setTitle((title or "Traffic Dispute AI report")[:120])
    pdf_canvas.setAuthor("Traffic Dispute AI")
    pdf_canvas.setCreator("Traffic Dispute AI")

    y = page_height - margin_top

    def ensure_page(required_height: float) -> None:
        nonlocal y
        if y - required_height >= margin_bottom:
            return
        pdf_canvas.showPage()
        y = page_height - margin_top

    def draw_line(text: str, *, size: float = 10.5, leading: float = 16, indent: float = 0) -> None:
        nonlocal y
        ensure_page(leading)
        pdf_canvas.setFont(font_name, size)
        pdf_canvas.drawString(margin_x + indent, y, text)
        y -= leading

    def draw_wrapped(
        text: str,
        *,
        size: float = 10.5,
        leading: float = 16,
        indent: float = 0,
        first_prefix: str = "",
        next_prefix: str = "",
    ) -> None:
        available_width = max_width - indent - pdfmetrics.stringWidth(next_prefix, font_name, size)
        lines = _wrap_reportlab_pdf_line(
            text,
            font_name=font_name,
            font_size=size,
            max_width=available_width,
            pdfmetrics=pdfmetrics,
        )
        for index, line in enumerate(lines):
            prefix = first_prefix if index == 0 else next_prefix
            draw_line(f"{prefix}{line}", size=size, leading=leading, indent=indent)

    title_text = title or "상담 분석 리포트"
    for line in _wrap_reportlab_pdf_line(
        title_text,
        font_name=font_name,
        font_size=17,
        max_width=max_width,
        pdfmetrics=pdfmetrics,
    ):
        draw_line(line, size=17, leading=23)
    y -= 4
    draw_line(f"Report ID: {report_id}", size=9.2, leading=14)
    draw_wrapped(
        "본 문서는 Traffic Dispute AI 상담 결과를 바탕으로 생성한 검토용 리포트입니다.",
        size=9.2,
        leading=14,
    )
    y -= 12

    for raw_line in str(body_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            y -= 8
            continue
        if line.startswith("# "):
            y -= 6
            draw_wrapped(line[2:], size=15, leading=21)
            y -= 4
            continue
        if line.startswith("## "):
            y -= 8
            draw_wrapped(line[3:], size=13, leading=19)
            y -= 3
            continue
        if line.startswith("### "):
            y -= 5
            draw_wrapped(line[4:], size=11.5, leading=17)
            continue
        if line.startswith("- "):
            draw_wrapped(line[2:], first_prefix="- ", next_prefix="  ", indent=8, size=10.2, leading=15.5)
            continue
        draw_wrapped(line, size=10.2, leading=15.5)

    pdf_canvas.save()
    return output.getvalue()


def _reportlab_pdf_bytes_via_bundled_python(*, report_id: str, title: str, body_text: str) -> bytes | None:
    if not REPORT_PDF_RENDERER_PATH.exists():
        return None

    bundled_python = _bundled_pdf_python_path()
    if bundled_python is None:
        return None

    payload = {
        "report_id": report_id,
        "title": title,
        "body_text": body_text,
        "font_file": _report_pdf_font_file(),
        "intro": "본 문서는 Traffic Dispute AI 상담 결과를 바탕으로 생성한 검토용 리포트입니다.",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="report-pdf-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            payload_path = temp_dir / "payload.json"
            output_path = temp_dir / "report.pdf"
            payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    str(bundled_python),
                    str(REPORT_PDF_RENDERER_PATH),
                    str(payload_path),
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if completed.returncode != 0 or not output_path.exists():
                return None
            return output_path.read_bytes()
    except Exception:
        return None
USAGE_POLICY_LIMITS = {
    "anonymous": {
        "chat_message": 2,
        "file_upload": 1,
        "agent_run": 1,
        "report_action": 1,
    },
    "guest": {
        "chat_message": 5,
        "file_upload": 3,
        "agent_run": 3,
        "report_action": 2,
    },
    "free": {
        "chat_message": 100,
        "file_upload": 30,
        "agent_run": 30,
        "report_action": 30,
    },
    "paid": {
        "chat_message": 500,
        "file_upload": 100,
        "agent_run": 120,
        "report_action": 100,
    },
}

HISTORY_POLICY_VERSION = "history_operating_policy.v1"
CONVERSATION_SAVE_POLICY_VERSION = "conversation_save_policy.v1"
CONVERSATION_SAVE_STATES = {"pending", "saved", "session_only"}
HISTORY_RETENTION_DAYS = {
    "anonymous": settings.ANONYMOUS_RETENTION_DAYS,
    "guest": settings.GUEST_RETENTION_DAYS,
    "user": settings.USER_RETENTION_DAYS,
    "authenticated": settings.USER_RETENTION_DAYS,
}
HISTORY_METADATA_ALLOWED_KEYS = {
    "action",
    "active_node",
    "analysis_plan_id",
    "attachment_count",
    "card_count",
    "conversation_save_policy",
    "conversation_save_state",
    "error_code",
    "evidence_count",
    "execution_id",
    "execution_status",
    "has_download_url",
    "http_status",
    "is_authenticated",
    "limitation_count",
    "merge_policy",
    "metadata_policy",
    "missing_fields",
    "mock_scenario",
    "mock_status",
    "node_code",
    "node_name",
    "pending_fields",
    "rate_limit_keys",
    "report_status",
    "response_status",
    "routing_intent",
    "session_status",
    "status_counts",
    "subject_type",
    "ttl_seconds",
}
HISTORY_AFTER_SERVICE_EVENT_TYPES = {
    "analysis_job_created",
    "agent_call_completed",
    "agent_call_failed",
    "agent_call_partial",
    "chat_message_created",
    "conversation_saved",
    "report_downloaded",
    "report_saved",
}


def register_uploaded_file(
    payload: dict[str, Any],
    upload_file: Any | None = None,
) -> dict[str, Any]:
    """Register a canonical file upload and persist its metadata in Django DB.

    The mock sidecar remains the local byte source, while the canonical
    metadata exposes the object-storage adapter URI and fallback envelope.
    """

    if not _text(payload.get("session_id")):
        raise UploadValidationError("session_id_required")
    owner_id = _owner_id(payload)
    guest_id = _payload_guest_id(payload)
    _get_or_create_session(
        payload.get("session_id"),
        owner_id=owner_id,
        guest_id=guest_id,
    )
    registration_payload = dict(payload)
    registration_payload.pop("attachment_id", None)
    attachment = register_mock_attachment(
        registration_payload,
        upload_file=upload_file,
        max_upload_bytes=int(getattr(settings, "FILE_UPLOAD_MAX_BYTES", 20 * 1024 * 1024)),
    )
    return persist_uploaded_file_metadata(
        attachment,
        owner_id=owner_id,
        raw_payload=payload,
        binary_upload=upload_file is not None,
    )


def persist_uploaded_file_metadata(
    attachment: dict[str, Any],
    *,
    owner_id: str = "",
    raw_payload: dict[str, Any] | None = None,
    binary_upload: bool | None = None,
) -> dict[str, Any]:
    if not _text(attachment.get("session_id")):
        raise UploadValidationError("session_id_required")
    guest_id = _payload_guest_id(raw_payload or {})
    session = _get_or_create_session(
        attachment.get("session_id"),
        owner_id=owner_id,
        guest_id=guest_id,
    )
    if session is not None and session.owner_id and session.owner_id != owner_id:
        raise PermissionError("session does not belong to authenticated owner")
    case = None
    case_id = _text((raw_payload or {}).get("case_id"))
    if case_id:
        if not owner_id:
            raise PermissionError("case upload requires an authenticated owner")
        case = Case.objects.filter(
            case_id=case_id,
            owner_id=owner_id,
            deleted_at__isnull=True,
        ).first()
        if case is None:
            raise PermissionError("case does not exist or belongs to another owner")
    elif session is not None and session.case_id:
        if not owner_id or session.case.owner_id != owner_id:
            raise PermissionError("session case does not belong to authenticated owner")
        case = session.case
    effective_owner_id = owner_id or (session.owner_id if session else "")
    attachment_id = _text(attachment.get("attachment_id"))
    if not attachment_id:
        raise ValueError("attachment_id is required")
    with transaction.atomic():
        existing_file = (
            UploadedFile.objects.select_for_update()
            .filter(attachment_id=attachment_id)
            .first()
        )
        _validate_uploaded_file_retry(
            existing_file,
            owner_id=effective_owner_id,
            session=session,
            case=case,
        )
    retention_expires_at = upload_retention_expires_at(
        owner_id=effective_owner_id,
        guest_id=guest_id,
        file_type=_text(attachment.get("type")),
        content_type=_text(attachment.get("content_type")),
    )
    metadata = _metadata_snapshot(attachment, raw_payload=raw_payload)
    object_storage = build_upload_storage_reference(
        attachment,
        owner_id=effective_owner_id,
    )
    quarantine_storage = build_quarantine_upload_storage_reference(
        attachment,
        owner_id=effective_owner_id,
    )
    quarantine_write = write_object_from_source_uri(
        quarantine_storage,
        fallback_payload=attachment,
    )
    quarantine_ready = (
        quarantine_write.get("status") == "written"
        and bool(quarantine_write.get("exists"))
    )
    source_storage_uri = _text(attachment.get("storage_uri"))
    has_binary_upload = (
        binary_upload
        if binary_upload is not None
        else source_storage_uri.startswith("mock://uploads/")
    )
    if not quarantine_ready and has_binary_upload:
        delete_source_uri(source_storage_uri, attachment_id=attachment_id)
        raise UploadStorageUnavailableError(
            _text(quarantine_write.get("reason")) or "quarantine_write_failed"
        )
    source_cleanup = (
        delete_source_uri(source_storage_uri, attachment_id=attachment_id)
        if quarantine_ready or not has_binary_upload
        else {"status": "retained", "reason": "quarantine_write_incomplete"}
    )
    upload_scan_status = (
        "not_started"
        if quarantine_ready
        else (
            "awaiting_upload"
            if quarantine_write.get("reason") == "source_file_unavailable"
            else "upload_error"
        )
    )
    upload_status = (
        UploadedFileStatus.UPLOADED
        if quarantine_ready
        else UploadedFileStatus.PENDING
    )
    object_storage.update(
        {
            "status": "pending_scan" if quarantine_ready else "awaiting_upload",
            "writes_binary": False,
            "persistence_state": "quarantine_pending",
        }
    )
    quarantine_storage.update(
        {
            "status": quarantine_write.get("status"),
            "writes_binary": bool(quarantine_write.get("writes_binary")),
            "persistence_state": quarantine_write.get("persistence_state"),
        }
    )
    metadata["source_storage_uri"] = source_storage_uri
    metadata["object_storage"] = object_storage
    metadata["object_storage_write"] = quarantine_write
    metadata["upload_storage_lifecycle"] = {
        "contract_version": UPLOAD_STORAGE_LIFECYCLE_VERSION,
        "state": "quarantined" if quarantine_ready else upload_scan_status,
        "quarantine": quarantine_storage,
        "clean": object_storage,
        "quarantine_write": quarantine_write,
        "source_cleanup": source_cleanup,
    }
    agent_handoff = dict(attachment.get("agent_handoff") or {})
    agent_handoff["storage_uri"] = object_storage["storage_uri"]
    agent_handoff["object_storage"] = object_storage
    agent_handoff["scan_status"] = upload_scan_status

    with transaction.atomic():
        existing_file = (
            UploadedFile.objects.select_for_update()
            .filter(attachment_id=attachment_id)
            .first()
        )
        _validate_uploaded_file_retry(
            existing_file,
            owner_id=effective_owner_id,
            session=session,
            case=case,
        )
        uploaded_file, _created = UploadedFile.objects.update_or_create(
            attachment_id=attachment_id,
            defaults={
                "owner_id": effective_owner_id,
                "case": case or (session.case if session else None),
                "session": session,
                "purpose": _text(attachment.get("purpose")) or "unknown",
                "file_type": _text(attachment.get("type")),
                "original_filename": _text(attachment.get("original_filename")),
                "content_type": _text(attachment.get("content_type")),
                "size_bytes": _positive_int_or_none(attachment.get("size_bytes")),
                "storage_uri": object_storage["storage_uri"],
                "privacy_risk": True,
                "status": upload_status,
                "scan_status": upload_scan_status,
                "agent_handoff": agent_handoff,
                "metadata": metadata,
                "retention_expires_at": retention_expires_at,
                "deleted_at": None,
            },
        )

    return uploaded_file_to_api(uploaded_file)


def _validate_uploaded_file_retry(
    uploaded_file: UploadedFile | None,
    *,
    owner_id: str,
    session: ChatSession | None,
    case: Case | None,
) -> None:
    if uploaded_file is None:
        return
    if uploaded_file.owner_id != owner_id:
        raise PermissionError("attachment_id belongs to another owner")
    if uploaded_file.session_id != (session.id if session is not None else None):
        raise PermissionError("attachment_id belongs to another session")
    expected_case_id = case.id if case is not None else (session.case_id if session is not None else None)
    if uploaded_file.case_id != expected_case_id:
        raise PermissionError("attachment_id belongs to another case")


def list_uploaded_files(
    session_id: str | None = None,
    *,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    queryset = UploadedFile.objects.select_related("session", "case").filter(deleted_at__isnull=True).order_by("-created_at")
    if session_id:
        queryset = queryset.filter(session__session_id=session_id)
    if owner_id is not None:
        queryset = queryset.filter(owner_id=owner_id)
    return [uploaded_file_to_api(uploaded_file) for uploaded_file in queryset]


def get_uploaded_file(attachment_id: str) -> dict[str, Any] | None:
    uploaded_file = (
        UploadedFile.objects.select_related("session", "case")
        .filter(attachment_id=attachment_id, deleted_at__isnull=True)
        .first()
    )
    if uploaded_file is None:
        return None
    return uploaded_file_to_api(uploaded_file)


def get_uploaded_file_access_metadata(attachment_id: str) -> dict[str, Any] | None:
    uploaded_file = (
        UploadedFile.objects.select_related("session")
        .filter(attachment_id=attachment_id)
        .first()
    )
    if uploaded_file is None:
        return None
    session = uploaded_file.session
    object_storage = _uploaded_file_object_storage(uploaded_file)
    return {
        "type": "uploaded_file",
        "attachment_id": uploaded_file.attachment_id,
        "owner_id": uploaded_file.owner_id or (session.owner_id if session else ""),
        "session_id": session.session_id if session else "",
        "guest_id": _chat_session_guest_id(session),
        "storage_backend": object_storage["backend"],
    }


def get_chat_session_access_metadata(session_id: str | None) -> dict[str, Any] | None:
    normalized_session_id = _text(session_id)
    if not normalized_session_id:
        return None
    session = ChatSession.objects.filter(session_id=normalized_session_id).first()
    if session is None:
        return None
    return {
        "type": "chat_session",
        "session_id": session.session_id,
        "owner_id": session.owner_id,
        "guest_id": _chat_session_guest_id(session),
    }


def conversation_save_state_from_payload(
    payload: dict[str, Any],
    *,
    default: str = "saved",
) -> str:
    auth_context = _dict_or_empty(payload.get("auth_context"))
    raw_state = _text(
        payload.get("conversation_save_state")
        or payload.get("save_state")
        or payload.get("save_decision")
        or auth_context.get("conversation_save_state")
        or auth_context.get("save_state")
    ).lower()
    aliases = {
        "": default,
        "defer": "pending",
        "deferred": "pending",
        "pending": "pending",
        "undecided": "pending",
        "save": "saved",
        "saved": "saved",
        "session": "session_only",
        "session_only": "session_only",
        "temporary": "session_only",
        "temp": "session_only",
        "not_saved": "session_only",
        "skip": "session_only",
    }
    normalized = aliases.get(raw_state, raw_state)
    return normalized if normalized in CONVERSATION_SAVE_STATES else default


def mark_conversation_save_state(
    *,
    session_id: str,
    save_state: str,
    owner_id: str = "",
    guest_id: str = "",
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_session_id = _text(session_id)
    normalized_state = conversation_save_state_from_payload(
        {"conversation_save_state": save_state},
        default="pending",
    )
    if not normalized_session_id:
        return _conversation_save_state_result("skipped", normalized_state, reason="missing_session_id")

    session = ChatSession.objects.filter(session_id=normalized_session_id).first()
    if session is None:
        return _conversation_save_state_result("skipped", normalized_state, reason="session_not_found")

    with transaction.atomic():
        session.metadata = _metadata_with_conversation_save_state(
            session.metadata,
            normalized_state,
            raw_payload=raw_payload,
        )
        if normalized_state == "saved" and owner_id and not session.owner_id:
            session.owner_id = owner_id
        session.save(update_fields=["owner_id", "metadata", "updated_at"])

        messages_updated = _update_session_message_save_state(session, normalized_state)
        jobs_updated = _update_session_job_save_state(session, normalized_state, owner_id=owner_id)
        history_events_updated = _update_session_history_save_state(session.session_id, normalized_state)

    session_cache = write_chat_session_state(session)
    return {
        **_conversation_save_state_result("updated", normalized_state),
        "session_id": session.session_id,
        "owner_id": session.owner_id or None,
        "guest_id": guest_id or _chat_session_guest_id(session) or None,
        "chat_messages_updated": messages_updated,
        "analysis_jobs_updated": jobs_updated,
        "history_events_updated": history_events_updated,
        "session_cache": session_cache,
    }


def persist_chat_message_analysis_boundary(
    payload: dict[str, Any],
    chat_response: dict[str, Any],
    *,
    node_execution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the canonical chat message and its analysis-job boundary."""

    owner_id = _owner_id(payload)
    session = _get_or_create_session(
        chat_response.get("session_id"),
        owner_id=owner_id,
        guest_id=_payload_guest_id(payload),
    )
    if session is None:
        raise ValueError("chat_response must include session_id")

    conversation_save_state = conversation_save_state_from_payload(payload)
    session.metadata = _metadata_with_conversation_save_state(
        session.metadata,
        conversation_save_state,
        raw_payload=payload,
    )
    session.save(update_fields=["metadata", "updated_at"])

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
                    "conversation_save_policy": CONVERSATION_SAVE_POLICY_VERSION,
                    "conversation_save_state": conversation_save_state,
                    "attachments": chat_response.get("attachments", []),
                    "blocked_attachments": chat_response.get("blocked_attachments", []),
                    "attachment_scan_policy": chat_response.get("attachment_scan_policy", {}),
                    "attachment_resolution": chat_response.get("attachment_resolution", {}),
                    "scan_gate": chat_response.get("scan_gate", {}),
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
                    "supervisor_state": chat_response.get("supervisor_state", {}),
                    "reporting_payload": chat_response.get("reporting_payload", {}),
                    "attachments": chat_response.get("attachments", []),
                    "blocked_attachments": chat_response.get("blocked_attachments", []),
                    "attachment_scan_policy": chat_response.get("attachment_scan_policy", {}),
                    "attachment_resolution": chat_response.get("attachment_resolution", {}),
                    "scan_gate": chat_response.get("scan_gate", {}),
                    "limitations": chat_response.get("limitations", []),
                    "conversation_save_policy": CONVERSATION_SAVE_POLICY_VERSION,
                    "conversation_save_state": conversation_save_state,
                },
            },
        )
        _upsert_initial_job_event(job, progress=progress)
        agent_results: list[AgentResult] = []
        agent_invocations: list[AgentInvocation] = []
        ai_session: AiSession | None = None
        if node_execution:
            job.status_counts = node_execution.get("status_counts") or job.status_counts
            job.metadata = {
                **_dict_or_empty(job.metadata),
                "supervisor_execution": _node_execution_summary(node_execution),
            }
            job.save(update_fields=["status_counts", "metadata", "updated_at"])
            agent_results = _persist_agent_results(job, node_execution)
            ai_session = _upsert_ai_session(
                job,
                payload=payload,
                job_payload={
                    **chat_response,
                    "job_id": job.job_id,
                    "session_id": session.session_id,
                    "message_id": message.message_id,
                    "owner_id": owner_id or session.owner_id,
                    "auth_context": _dict_or_empty(payload.get("auth_context")),
                },
            )
            agent_invocations = _persist_agent_invocations(
                job,
                ai_session=ai_session,
                node_execution=node_execution,
                agent_results=agent_results,
            )
            retrieval_events_saved = RetrievalEvent.objects.filter(job=job).count()
        else:
            retrieval_events_saved = 0

    progress_cache = write_analysis_job_progress(job)
    session_cache = write_chat_session_state(session, latest_job=job)

    return {
        "message_id": message.message_id,
        "job_id": job.job_id,
        "session_id": session.session_id,
        "conversation_save_policy": CONVERSATION_SAVE_POLICY_VERSION,
        "conversation_save_state": conversation_save_state,
        "supervisor_execution": _node_execution_summary(node_execution or {}),
        "agent_results_saved": len(agent_results),
        "agent_invocations_saved": len(agent_invocations),
        "retrieval_events_saved": retrieval_events_saved,
        "ai_session_id": ai_session.ai_session_id if ai_session else None,
        "node_codes": [result.node_code for result in agent_results],
        "progress_cache": progress_cache,
        "session_cache": session_cache,
    }


def persist_guest_session_identity(
    auth_payload: dict[str, Any],
    *,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the guest identity preview returned by the auth mock contract."""

    guest_payload = _dict_or_empty(auth_payload.get("guest"))
    subject = _dict_or_empty(auth_payload.get("subject"))
    session_binding = _dict_or_empty(auth_payload.get("session_binding"))
    guest_id = _normalize_guest_id(guest_payload.get("guest_id") or subject.get("guest_id"))
    if not guest_id:
        return _auth_persistence_skipped("missing_guest_id")

    subject_id = _text(subject.get("subject_id")) or f"guest:{guest_id}"
    session_id = _text(session_binding.get("session_id"))
    expires_at = _datetime_or_none(guest_payload.get("expires_at"))

    with transaction.atomic():
        guest, _created = GuestIdentity.objects.update_or_create(
            guest_id=guest_id,
            defaults={
                "status": GuestIdentityStatus.ACTIVE,
                "expires_at": expires_at,
                "metadata": {
                    "source": "auth_guest_session",
                    "auth_state": auth_payload.get("auth_state"),
                    "ttl_seconds": guest_payload.get("ttl_seconds"),
                    "policy_status": guest_payload.get("policy_status"),
                    "merge_policy": auth_payload.get("merge_policy") or {},
                    "rate_limit": auth_payload.get("rate_limit") or {},
                },
            },
        )
        chat_session = _bind_chat_session_auth_context(
            session_id=session_id,
            owner_id="",
            auth_context={
                "auth_state": "guest",
                "subject_id": subject_id,
                "subject_type": "guest",
                "guest_id": guest_id,
                "auth_session_id": None,
            },
        )
        event = _create_auth_event(
            event_type="guest_session_created",
            subject_id=subject_id,
            guest=guest,
            metadata={
                "source": "auth_guest_session",
                "chat_session_id": chat_session.session_id if chat_session else None,
                "raw_payload": _safe_payload(raw_payload or {}),
            },
        )

    return {
        "backend": "postgresql",
        "tables": [
            GuestIdentity._meta.db_table,
            AuthEvent._meta.db_table,
            ChatSession._meta.db_table,
        ],
        "guest_identity_table": GuestIdentity._meta.db_table,
        "auth_events_table": AuthEvent._meta.db_table,
        "chat_session_table": ChatSession._meta.db_table,
        "guest_id": guest.guest_id,
        "event_id": event.event_id,
        "session_id": chat_session.session_id if chat_session else None,
        "status": "saved",
    }


def _locked_active_auth_session(
    *,
    auth_session_id: str,
    user_id: str,
) -> AuthSession:
    auth_session = (
        AuthSession.objects.select_for_update()
        .select_related("user")
        .filter(auth_session_id=auth_session_id)
        .first()
    )
    if auth_session is None:
        raise AuthSessionStateError("auth_session_not_persisted")
    if auth_session.status != AuthSessionStatus.ACTIVE or auth_session.revoked_at is not None:
        raise AuthSessionStateError("auth_session_revoked")
    if auth_session.expires_at and auth_session.expires_at <= timezone.now():
        raise AuthSessionStateError("auth_session_expired")
    expected_subject_id = f"user:{user_id}"
    if auth_session.subject_type != "user" or auth_session.subject_id != expected_subject_id:
        raise AuthSessionStateError("auth_session_subject_mismatch")
    if auth_session.user is not None and auth_session.user.user_id != user_id:
        raise AuthSessionStateError("auth_session_subject_mismatch")
    return auth_session


def persist_current_auth_subject(
    auth_payload: dict[str, Any],
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Persist the current auth subject preview used by canonical APIs."""

    subject = _dict_or_empty(auth_payload.get("subject"))
    subject_id = _text(subject.get("subject_id")) or "anonymous"
    subject_type = _text(subject.get("subject_type")) or "anonymous"
    user_id = _text(subject.get("user_id"))
    guest_id = _normalize_guest_id(subject.get("guest_id"))
    auth_session_id = _text(subject.get("auth_session_id"))
    contract_version = _text(auth_payload.get("contract_version"))
    login_sources = {
        "google_auth.v1": ("auth_google_login", "auth_google_login_completed"),
        "google_auth_code.v1": ("auth_google_code", "auth_google_code_completed"),
    }
    auth_source, auth_event_type = login_sources.get(
        contract_version,
        ("auth_me", "auth_me_checked"),
    )

    with transaction.atomic():
        user = _get_or_create_user_account(user_id)
        if user is not None:
            _update_user_account_from_auth_payload(user, auth_payload)
        guest = _get_or_create_guest_identity(guest_id)
        auth_session = None
        if auth_session_id:
            session_metadata = {
                "source": auth_source,
                "auth_state": auth_payload.get("auth_state"),
                "verification": _dict_or_empty(auth_payload.get("auth_session")).get(
                    "verification"
                ),
                "google": _safe_google_connection_metadata(auth_payload),
                "rate_limit": auth_payload.get("rate_limit") or {},
                "merge_policy": auth_payload.get("merge_policy") or {},
            }
            if contract_version in login_sources:
                auth_session = AuthSession.objects.create(
                    auth_session_id=auth_session_id,
                    user=user,
                    guest=guest,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    status=AuthSessionStatus.ACTIVE,
                    issued_at=_datetime_or_none(auth_payload.get("issued_at")),
                    expires_at=_datetime_or_none(auth_payload.get("expires_at")),
                    revoked_at=None,
                    metadata=session_metadata,
                )
            else:
                auth_session = _locked_active_auth_session(
                    auth_session_id=auth_session_id,
                    user_id=user_id,
                )
                auth_session.user = user
                auth_session.guest = guest
                existing_metadata = dict(auth_session.metadata or {})
                existing_metadata.update(session_metadata)
                auth_session.metadata = existing_metadata
                auth_session.save(update_fields=["user", "guest", "metadata", "updated_at"])
        google_persistence = _upsert_google_oauth_subject(user, auth_payload)
        chat_session = _bind_chat_session_auth_context(
            session_id=session_id,
            owner_id=user_id,
            auth_context={
                "auth_state": auth_payload.get("auth_state"),
                "subject_id": subject_id,
                "subject_type": subject_type,
                "user_id": user_id or None,
                "guest_id": guest_id or None,
                "auth_session_id": auth_session_id or None,
            },
        )
        event = _create_auth_event(
            event_type=auth_event_type,
            subject_id=subject_id,
            user=user,
            guest=guest,
            auth_session=auth_session,
            metadata={
                "source": auth_source,
                "auth_state": auth_payload.get("auth_state"),
                "chat_session_id": chat_session.session_id if chat_session else None,
                "google": _safe_google_connection_metadata(auth_payload),
            },
        )

    tables = [
        UserAccount._meta.db_table,
        GuestIdentity._meta.db_table,
        AuthSession._meta.db_table,
        AuthEvent._meta.db_table,
        ChatSession._meta.db_table,
    ]
    for table_name in google_persistence.get("tables", []):
        if table_name not in tables:
            tables.append(table_name)

    return {
        "backend": "postgresql",
        "tables": tables,
        "user_table": UserAccount._meta.db_table,
        "guest_identity_table": GuestIdentity._meta.db_table,
        "auth_session_table": AuthSession._meta.db_table,
        "auth_events_table": AuthEvent._meta.db_table,
        "chat_session_table": ChatSession._meta.db_table,
        "social_account_table": google_persistence.get("social_account_table"),
        "oauth_connection_table": google_persistence.get("oauth_connection_table"),
        "user_id": user.user_id if user else None,
        "guest_id": guest.guest_id if guest else None,
        "auth_session_id": auth_session.auth_session_id if auth_session else None,
        "social_account_id": google_persistence.get("social_account_id"),
        "oauth_connection_id": google_persistence.get("oauth_connection_id"),
        "event_id": event.event_id,
        "session_id": chat_session.session_id if chat_session else None,
        "status": "saved",
    }


def persist_auth_token_refresh(
    auth_payload: dict[str, Any],
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    subject = _dict_or_empty(auth_payload.get("subject"))
    user_id = _text(subject.get("user_id"))
    guest_id = _normalize_guest_id(subject.get("guest_id"))
    auth_session_id = _text(subject.get("auth_session_id"))
    auth_session_payload = _dict_or_empty(auth_payload.get("auth_session"))
    rotation = _dict_or_empty(auth_session_payload.get("rotation"))
    previous_auth_session_id = _text(rotation.get("previous_auth_session_id"))
    if not user_id or not auth_session_id or not previous_auth_session_id:
        raise AuthSessionStateError("missing_refresh_subject")
    if auth_session_id == previous_auth_session_id:
        raise AuthSessionStateError("auth_session_rotation_required")

    with transaction.atomic():
        previous_auth_session = _locked_active_auth_session(
            auth_session_id=previous_auth_session_id,
            user_id=user_id,
        )
        user = previous_auth_session.user or _get_or_create_user_account(user_id)
        if user is not None:
            _update_user_account_from_auth_payload(user, auth_payload)
        guest = _get_or_create_guest_identity(guest_id)
        revoked_at = timezone.now()
        previous_metadata = dict(previous_auth_session.metadata or {})
        previous_metadata["rotation"] = {
            "rotated_to": auth_session_id,
            "rotated_at": revoked_at.isoformat(),
        }
        previous_auth_session.status = AuthSessionStatus.REVOKED
        previous_auth_session.revoked_at = revoked_at
        previous_auth_session.metadata = previous_metadata
        previous_auth_session.save(
            update_fields=["status", "revoked_at", "metadata", "updated_at"]
        )
        auth_session = AuthSession.objects.create(
            auth_session_id=auth_session_id,
            user=user,
            guest=guest,
            subject_type="user",
            subject_id=f"user:{user_id}",
            status=AuthSessionStatus.ACTIVE,
            issued_at=_datetime_or_none(auth_payload.get("issued_at")),
            expires_at=_datetime_or_none(auth_payload.get("expires_at")),
            revoked_at=None,
            metadata={
                "source": "auth_refresh",
                "auth_state": auth_payload.get("auth_state"),
                "verification": auth_session_payload.get("verification"),
                "refresh_policy": auth_session_payload.get("refresh_policy"),
                "rotated_from": previous_auth_session_id,
                "rate_limit": auth_payload.get("rate_limit") or {},
            },
        )
        chat_session = _bind_chat_session_auth_context(
            session_id=session_id,
            owner_id=user_id,
            auth_context={
                "auth_state": auth_payload.get("auth_state"),
                "subject_id": f"user:{user_id}",
                "subject_type": "user",
                "user_id": user_id,
                "guest_id": guest_id or None,
                "auth_session_id": auth_session_id,
            },
        )
        event = _create_auth_event(
            event_type="auth_token_refreshed",
            subject_id=f"user:{user_id}",
            user=user,
            guest=guest,
            auth_session=auth_session,
            metadata={
                "source": "auth_refresh",
                "auth_state": auth_payload.get("auth_state"),
                "chat_session_id": chat_session.session_id if chat_session else None,
                "expires_at": auth_payload.get("expires_at"),
                "previous_auth_session_id": previous_auth_session_id,
            },
        )

    return {
        "backend": "postgresql",
        "tables": [
            UserAccount._meta.db_table,
            GuestIdentity._meta.db_table,
            AuthSession._meta.db_table,
            AuthEvent._meta.db_table,
            ChatSession._meta.db_table,
        ],
        "auth_session_table": AuthSession._meta.db_table,
        "auth_events_table": AuthEvent._meta.db_table,
        "chat_session_table": ChatSession._meta.db_table,
        "user_id": user.user_id if user else None,
        "guest_id": guest.guest_id if guest else None,
        "auth_session_id": auth_session.auth_session_id,
        "previous_auth_session_id": previous_auth_session_id,
        "auth_session_status": auth_session.status,
        "event_id": event.event_id,
        "session_id": chat_session.session_id if chat_session else None,
        "status": "saved",
    }


def persist_auth_logout(
    auth_payload: dict[str, Any],
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    subject = _dict_or_empty(auth_payload.get("subject"))
    user_id = _text(subject.get("user_id"))
    guest_id = _normalize_guest_id(subject.get("guest_id"))
    auth_session_id = _text(subject.get("auth_session_id"))
    if not user_id or not auth_session_id:
        return _auth_persistence_skipped("missing_logout_subject")

    revoked_at = _datetime_or_none(auth_payload.get("revoked_at")) or timezone.now()
    with transaction.atomic():
        user = _get_or_create_user_account(user_id)
        if user is not None:
            _update_user_account_from_auth_payload(user, auth_payload)
        guest = _get_or_create_guest_identity(guest_id)
        auth_session, _created = AuthSession.objects.update_or_create(
            auth_session_id=auth_session_id,
            defaults={
                "user": user,
                "guest": guest,
                "subject_type": "user",
                "subject_id": f"user:{user_id}",
                "status": AuthSessionStatus.REVOKED,
                "revoked_at": revoked_at,
                "metadata": {
                    "source": "auth_logout",
                    "auth_state": "anonymous",
                    "client_action": auth_payload.get("client_action") or {},
                },
            },
        )
        chat_session = _bind_chat_session_auth_context(
            session_id=session_id,
            owner_id=user_id,
            auth_context={
                "auth_state": "guest" if guest_id else "anonymous",
                "subject_id": f"user:{user_id}",
                "subject_type": "user",
                "user_id": user_id,
                "guest_id": guest_id or None,
                "auth_session_id": auth_session_id,
            },
        )
        event = _create_auth_event(
            event_type="auth_logout_completed",
            subject_id=f"user:{user_id}",
            user=user,
            guest=guest,
            auth_session=auth_session,
            metadata={
                "source": "auth_logout",
                "auth_state": "anonymous",
                "chat_session_id": chat_session.session_id if chat_session else None,
                "revoked_at": revoked_at.isoformat(),
            },
        )

    return {
        "backend": "postgresql",
        "tables": [
            UserAccount._meta.db_table,
            GuestIdentity._meta.db_table,
            AuthSession._meta.db_table,
            AuthEvent._meta.db_table,
            ChatSession._meta.db_table,
        ],
        "auth_session_table": AuthSession._meta.db_table,
        "auth_events_table": AuthEvent._meta.db_table,
        "chat_session_table": ChatSession._meta.db_table,
        "user_id": user.user_id if user else None,
        "guest_id": guest.guest_id if guest else None,
        "auth_session_id": auth_session.auth_session_id,
        "auth_session_status": auth_session.status,
        "event_id": event.event_id,
        "session_id": chat_session.session_id if chat_session else None,
        "status": "saved",
    }


def _update_user_account_from_auth_payload(
    user: UserAccount,
    auth_payload: dict[str, Any],
) -> None:
    user_payload = _dict_or_empty(auth_payload.get("user"))
    metadata = dict(user.metadata or {})
    changed_fields: list[str] = []

    email = _text(user_payload.get("email"))
    if email and user.email != email:
        user.email = email
        changed_fields.append("email")

    display_name = _text(user_payload.get("display_name"))
    if display_name and user.display_name != display_name:
        user.display_name = display_name
        changed_fields.append("display_name")

    auth_provider = _text(user_payload.get("auth_provider") or auth_payload.get("provider"))
    if auth_provider and user.auth_provider != auth_provider:
        user.auth_provider = auth_provider
        changed_fields.append("auth_provider")

    provider_subject = _text(user_payload.get("provider_subject"))
    if provider_subject and user.provider_subject != provider_subject:
        user.provider_subject = provider_subject
        changed_fields.append("provider_subject")

    for key in ("picture", "policy_status"):
        value = user_payload.get(key)
        if value is not None and metadata.get(key) != value:
            metadata[key] = value
    metadata.setdefault("source", "auth_subject")
    if metadata != user.metadata:
        user.metadata = metadata
        changed_fields.append("metadata")

    if changed_fields:
        user.save(update_fields=[*sorted(set(changed_fields)), "updated_at"])


def _upsert_google_oauth_subject(
    user: UserAccount | None,
    auth_payload: dict[str, Any],
) -> dict[str, Any]:
    if user is None:
        return _google_oauth_persistence_skipped("missing_user")

    google = _dict_or_empty(auth_payload.get("google"))
    social_payload = _dict_or_empty(google.get("social_account"))
    provider = _text(
        social_payload.get("provider")
        or auth_payload.get("provider")
    ).lower()
    if provider != "google":
        return _google_oauth_persistence_skipped("not_google_code_flow")

    provider_user_id = _text(social_payload.get("provider_user_id") or user.provider_subject)
    if not provider_user_id:
        return _google_oauth_persistence_skipped("missing_provider_user_id")

    now = timezone.now()
    social_account_id = f"soc_google_{hashlib.sha256(provider_user_id.encode('utf-8')).hexdigest()[:16]}"
    social_account, _social_created = SocialAccount.objects.update_or_create(
        provider=provider,
        provider_user_id=provider_user_id,
        defaults={
            "social_account_id": social_account_id,
            "user": user,
            "email": _text(social_payload.get("email") or user.email),
            "email_verified": bool(social_payload.get("email_verified")),
            "connected_at": now,
            "metadata": {
                "source": "google_auth_code",
                "policy": "provider_user_id_is_google_sub",
            },
        },
    )
    return {
        "backend": "postgresql",
        "tables": [SocialAccount._meta.db_table],
        "social_account_table": SocialAccount._meta.db_table,
        "oauth_connection_table": None,
        "social_account_id": social_account.social_account_id,
        "oauth_connection_id": None,
        "token_storage": "discarded_after_login",
        "status": "saved",
    }


def _safe_google_connection_metadata(auth_payload: dict[str, Any]) -> dict[str, Any]:
    google = _dict_or_empty(auth_payload.get("google"))
    if not google:
        return {}
    return {
        "connected": bool(google.get("connected")),
        "purpose": _text(google.get("purpose")),
        "granted_scopes": _list_or_empty(google.get("granted_scopes")),
        "connection_policy": _text(google.get("connection_policy")),
        "token_storage": _text(_dict_or_empty(google.get("oauth_connection")).get("token_storage")),
    }


def _google_oauth_persistence_skipped(reason: str) -> dict[str, Any]:
    return {
        "backend": "postgresql",
        "tables": [SocialAccount._meta.db_table],
        "social_account_table": SocialAccount._meta.db_table,
        "oauth_connection_table": None,
        "status": "skipped",
        "reason": reason,
    }


def record_usage_event(
    payload: dict[str, Any],
    *,
    scope: str,
    amount: int = 1,
) -> dict[str, Any]:
    """Record and enforce a lightweight subject-scoped usage quota."""

    normalized_amount = max(amount, 1)
    subject = _ai_subject(payload, {})
    subject_id = subject["subject_id"]
    subject_type = subject["subject_type"]
    quota_key = f"rate_limit:{subject_id}:{scope}"
    policy = _usage_policy_for_subject(subject, scope=scope)
    now = timezone.now()

    with transaction.atomic():
        quota, _created = UsageQuota.objects.select_for_update().get_or_create(
            quota_id=_usage_quota_id(subject_id, scope),
            defaults={
                "subject_id": subject_id,
                "scope": scope,
                "limit_count": policy["limit_count"],
                "used_count": 0,
                "reset_at": now + timedelta(days=1),
                "metadata": {
                    "source": "canonical_usage_policy",
                    "subject_type": subject_type,
                    "plan_code": policy["plan_code"],
                    "subscription_id": policy["subscription_id"],
                    "policy_code_item": policy["policy_code_item"],
                    "policy_status": policy["policy_status"],
                    "policy_managed": True,
                },
            },
        )
        if not _created:
            quota = UsageQuota.objects.select_for_update().get(pk=quota.pk)
        if not _created and quota.metadata.get("policy_managed"):
            quota.metadata = {
                **quota.metadata,
                "subject_type": subject_type,
                "plan_code": policy["plan_code"],
                "subscription_id": policy["subscription_id"],
                "policy_code_item": policy["policy_code_item"],
                "policy_status": policy["policy_status"],
            }
            quota.limit_count = policy["limit_count"]
        if quota.reset_at and quota.reset_at <= now:
            quota.used_count = 0
            quota.reset_at = now + timedelta(days=1)

        projected_count = quota.used_count + normalized_amount
        allowed = quota.limit_count == 0 or projected_count <= quota.limit_count
        if allowed:
            quota.used_count = projected_count
        quota.save(update_fields=["limit_count", "used_count", "reset_at", "metadata", "updated_at"])

        usage_event = UsageEvent.objects.create(
            usage_event_id=_usage_event_id(subject_id, scope),
            subject_id=subject_id,
            scope=scope,
            amount=normalized_amount if allowed else 0,
            quota_key=quota_key,
            metadata={
                "source": "canonical_usage_enforcement",
                "status": "allowed" if allowed else "blocked",
                "subject_type": subject_type,
                "plan_code": policy["plan_code"],
                "subscription_id": policy["subscription_id"],
                "policy_code_item": policy["policy_code_item"],
                "limit_count": quota.limit_count,
                "used_count": quota.used_count,
                "requested_amount": normalized_amount,
                "reset_at": quota.reset_at.isoformat() if quota.reset_at else None,
            },
        )

    return {
        "backend": "postgresql",
        "tables": [UsageQuota._meta.db_table, UsageEvent._meta.db_table],
        "quota_table": UsageQuota._meta.db_table,
        "usage_event_table": UsageEvent._meta.db_table,
        "quota_id": quota.quota_id,
        "usage_event_id": usage_event.usage_event_id,
        "subject_id": subject_id,
        "subject_type": subject_type,
        "scope": scope,
        "quota_key": quota_key,
        "plan_code": policy["plan_code"],
        "subscription_id": policy["subscription_id"],
        "policy_code_item": policy["policy_code_item"],
        "policy_status": policy["policy_status"],
        "allowed": allowed,
        "limit_count": quota.limit_count,
        "used_count": quota.used_count,
        "remaining_count": max(quota.limit_count - quota.used_count, 0)
        if quota.limit_count
        else None,
        "reset_at": quota.reset_at.isoformat() if quota.reset_at else None,
        "status": "allowed" if allowed else "blocked",
    }


def refund_usage_event(usage: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """Refund one allowed usage reservation exactly once after a rejected request."""

    usage_event_id = _text(usage.get("usage_event_id"))
    quota_id = _text(usage.get("quota_id"))
    if not usage_event_id or not quota_id:
        return {"status": "skipped", "reason": "missing_usage_reference"}

    with transaction.atomic():
        usage_event = (
            UsageEvent.objects.select_for_update()
            .filter(usage_event_id=usage_event_id)
            .first()
        )
        if usage_event is None:
            return {"status": "skipped", "reason": "usage_event_not_found"}
        metadata = _dict_or_empty(usage_event.metadata)
        if usage_event.amount <= 0 or metadata.get("status") != "allowed":
            return {"status": "skipped", "reason": "usage_not_refundable"}
        quota = UsageQuota.objects.select_for_update().filter(quota_id=quota_id).first()
        if quota is None:
            return {"status": "skipped", "reason": "usage_quota_not_found"}

        refunded_amount = usage_event.amount
        quota.used_count = max(0, quota.used_count - refunded_amount)
        quota.save(update_fields=["used_count", "updated_at"])
        usage_event.amount = 0
        usage_event.metadata = {
            **metadata,
            "status": "refunded",
            "refund_reason": _text(reason) or "request_rejected",
            "refunded_amount": refunded_amount,
            "refunded_at": timezone.now().isoformat(),
            "used_count": quota.used_count,
        }
        usage_event.save(update_fields=["amount", "metadata"])

    return {
        "status": "refunded",
        "usage_event_id": usage_event.usage_event_id,
        "quota_id": quota.quota_id,
        "refunded_amount": refunded_amount,
        "used_count": quota.used_count,
    }


def record_history_event_record(
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
    """Persist one standard-light history event in PostgreSQL."""

    event_payload = build_history_event(
        event_type=event_type,
        status=status,
        summary=summary,
        actor=actor,
        subject=subject,
        source=source,
        metadata=metadata,
        privacy=privacy,
    )
    event_payload["metadata"] = _history_metadata_snapshot(metadata)
    return history_event_to_api(_upsert_history_event_payload(event_payload))


def record_agent_history_event_records(
    executions: list[dict[str, Any]],
    *,
    actor: dict[str, Any],
    source: dict[str, Any],
    subject: dict[str, Any],
) -> list[dict[str, Any]]:
    """Persist standard-light history events for Agent execution envelopes."""

    events = []
    for event_payload in build_agent_execution_events(
        executions,
        actor=actor,
        source=source,
        subject=subject,
    ):
        events.append(history_event_to_api(_upsert_history_event_payload(event_payload)))
    return events


def list_history_event_records(
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    guest_id: str | None = None,
    job_id: str | None = None,
    event_type: str | None = None,
    subject_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read history events from PostgreSQL using the public history filters."""

    queryset = HistoryEvent.objects.all()
    retention_days = _history_retention_days(subject_type)
    if retention_days:
        queryset = queryset.filter(occurred_at__gte=timezone.now() - timedelta(days=retention_days))
    if session_id:
        queryset = queryset.filter(subject_session_id=session_id)
    if user_id:
        queryset = queryset.filter(actor_user_id=user_id)
    if guest_id:
        queryset = queryset.filter(actor_guest_id=guest_id)
    if job_id:
        queryset = queryset.filter(subject_job_id=job_id)
    if event_type:
        queryset = queryset.filter(event_type=event_type)

    candidate_rows = list(queryset.order_by("-occurred_at", "-id")[: max(limit, 1) * 3])
    rows = [
        event
        for event in candidate_rows
        if _conversation_is_saved_metadata(event.metadata)
    ][: max(limit, 1)]
    return [history_event_to_api(event) for event in reversed(rows)]


def history_operating_policy(subject_type: str | None = None) -> dict[str, Any]:
    normalized_subject_type = _history_subject_type(subject_type)
    return {
        "policy_version": HISTORY_POLICY_VERSION,
        "storage_policy": "standard_light",
        "retention": {
            "applied_subject_type": normalized_subject_type,
            "applied_days": _history_retention_days(normalized_subject_type),
            "anonymous_days": HISTORY_RETENTION_DAYS["anonymous"],
            "guest_days": HISTORY_RETENTION_DAYS["guest"],
            "user_days": HISTORY_RETENTION_DAYS["user"],
        },
        "query_scope": {
            "member": "own_user_history_only",
            "guest": "own_guest_or_authorized_session_only",
            "anonymous": "history_query_denied_without_subject",
        },
        "metadata_policy": {
            "mode": "allowlist_with_sensitive_key_blocklist",
            "allowed_keys": sorted(HISTORY_METADATA_ALLOWED_KEYS),
            "blocked_keys": sorted(SENSITIVE_METADATA_KEYS),
        },
        "after_service_summary": {
            "source": "history_events_standard_light",
            "eligible_event_types": sorted(HISTORY_AFTER_SERVICE_EVENT_TYPES),
            "excludes": ["user_text", "ocr_raw", "agent_reasoning", "raw_output"],
        },
    }


def build_history_after_service_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    eligible_events = [
        event
        for event in events
        if _text(event.get("event_type")) in HISTORY_AFTER_SERVICE_EVENT_TYPES
    ]
    recent_event_types = []
    for event in eligible_events:
        event_type = _text(event.get("event_type"))
        if event_type and event_type not in recent_event_types:
            recent_event_types.append(event_type)

    return {
        "available": bool(eligible_events),
        "source_event_count": len(eligible_events),
        "source": "history_events_standard_light",
        "summary_basis": recent_event_types[:8],
        "excludes_sensitive_payload": True,
        "status": "ready" if eligible_events else "insufficient_history",
    }


def history_event_to_api(event: HistoryEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "event_version": event.event_version,
        "occurred_at": event.occurred_at.isoformat(),
        "actor": event.actor,
        "subject": event.subject,
        "source": event.source,
        "status": event.status,
        "summary": event.summary,
        "metadata": event.metadata,
        "privacy": event.privacy,
        "created_at": event.created_at.isoformat(),
    }


def persist_analysis_job_execution(
    payload: dict[str, Any],
    job_payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist a canonical analysis job and its agent execution outputs."""

    owner_id = _owner_id(payload)
    session = _get_or_create_session(
        job_payload.get("session_id"),
        owner_id=owner_id,
        guest_id=_payload_guest_id(payload),
    )
    if session is None:
        raise ValueError("job_payload must include session_id")

    message_id = _text(job_payload.get("message_id"))
    job_id = _text(job_payload.get("job_id"))
    if not job_id:
        raise ValueError("job_payload must include job_id")

    chat_response = job_payload.get("chat_response") or {}
    analysis_plan = job_payload.get("analysis_plan") or chat_response.get("analysis_plan") or {}
    progress = {
        "active_node": job_payload.get("active_node"),
        "message": job_payload.get("progress_message"),
    }

    with transaction.atomic():
        existing_job = (
            AnalysisJob.objects.select_for_update()
            .filter(job_id=job_id)
            .only("metadata")
            .first()
        )
        existing_metadata = _dict_or_empty(existing_job.metadata if existing_job else None)
        preserved_metadata = {
            key: existing_metadata[key]
            for key in ("idempotency", "work_queue")
            if isinstance(existing_metadata.get(key), dict)
        }
        message = None
        if message_id:
            message, _message_created = ChatMessage.objects.update_or_create(
                message_id=message_id,
                defaults={
                    "session": session,
                    "role": MessageRole.USER,
                    "content": _message_content(payload),
                    "routing_intent": _text(job_payload.get("routing_intent")),
                    "metadata": {
                        "source": "canonical_analysis_job",
                        "analysis_job_id": job_id,
                        "mock_scenario": job_payload.get("mock_scenario"),
                        "response_status": job_payload.get("status"),
                        "attachments": job_payload.get("attachments", []),
                        "blocked_attachments": job_payload.get("blocked_attachments", []),
                        "attachment_scan_policy": job_payload.get("attachment_scan_policy", {}),
                        "attachment_resolution": job_payload.get("attachment_resolution", {}),
                        "scan_gate": job_payload.get("scan_gate", {}),
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
                "routing_intent": _text(job_payload.get("routing_intent")),
                "mock_scenario": _text(job_payload.get("mock_scenario")),
                "status": _analysis_job_status(job_payload.get("status")),
                "active_node": _text(job_payload.get("active_node")),
                "progress_message": _text(job_payload.get("progress_message")),
                "analysis_plan_id": _text(job_payload.get("analysis_plan_id") or analysis_plan.get("plan_id")),
                "status_counts": job_payload.get("status_counts") or {},
                "metadata": {
                    **preserved_metadata,
                    "source": "canonical_analysis_job",
                    "analysis_plan": analysis_plan,
                    "assistant_message": chat_response.get("assistant_message"),
                    "case_status": chat_response.get("case_status"),
                    "cards": chat_response.get("cards", []),
                    "pending_questions": chat_response.get("pending_questions", []),
                    "report_links": chat_response.get("report_links", []),
                    "supervisor_state": chat_response.get("supervisor_state", {}),
                    "reporting_payload": chat_response.get("reporting_payload", {}),
                    "attachments": job_payload.get("attachments", []),
                    "blocked_attachments": job_payload.get("blocked_attachments", []),
                    "attachment_scan_policy": job_payload.get("attachment_scan_policy", {}),
                    "attachment_resolution": job_payload.get("attachment_resolution", {}),
                    "scan_gate": job_payload.get("scan_gate", {}),
                    "limitations": job_payload.get("limitations", []),
                },
            },
        )
        _upsert_initial_job_event(
            job,
            progress=progress,
            source="canonical_analysis_job",
            overwrite_existing=not bool(_text(job_payload.get("work_item_id"))),
        )
        node_execution = job_payload.get("node_execution") or {}
        agent_results = _persist_agent_results(job, node_execution)
        ai_session = _upsert_ai_session(job, payload=payload, job_payload=job_payload)
        agent_invocations = _persist_agent_invocations(
            job,
            ai_session=ai_session,
            node_execution=node_execution,
            agent_results=agent_results,
        )
        retrieval_events_saved = RetrievalEvent.objects.filter(job=job).count()

    progress_cache = write_analysis_job_progress(job)
    session_cache = write_chat_session_state(session, latest_job=job)

    return {
        "backend": "postgresql",
        "tables": [
            AnalysisJob._meta.db_table,
            AgentResult._meta.db_table,
            AiSession._meta.db_table,
            AgentInvocation._meta.db_table,
            RetrievalEvent._meta.db_table,
        ],
        "analysis_job_table": AnalysisJob._meta.db_table,
        "agent_results_table": AgentResult._meta.db_table,
        "ai_session_table": AiSession._meta.db_table,
        "agent_invocations_table": AgentInvocation._meta.db_table,
        "retrieval_events_table": RetrievalEvent._meta.db_table,
        "agent_results_saved": len(agent_results),
        "agent_invocations_saved": len(agent_invocations),
        "retrieval_events_saved": retrieval_events_saved,
        "agent_result_ids": [result.result_id for result in agent_results],
        "agent_invocation_ids": [invocation.invocation_id for invocation in agent_invocations],
        "ai_session_id": ai_session.ai_session_id,
        "node_codes": [result.node_code for result in agent_results],
        "progress_cache": progress_cache,
        "session_cache": session_cache,
        "status": "saved",
    }


def reserve_analysis_job_request(
    payload: dict[str, Any],
    *,
    job_id: str,
    request_fingerprint: str,
) -> dict[str, Any]:
    """Reserve a caller-supplied job id before quota use or plan generation."""

    normalized_job_id = _text(job_id)
    normalized_fingerprint = _text(request_fingerprint)
    owner_id = _owner_id(payload)
    session = _get_or_create_session(
        payload.get("session_id"),
        owner_id=owner_id,
        guest_id=_payload_guest_id(payload),
    )
    if not normalized_job_id or not normalized_fingerprint or session is None:
        raise ValueError("job_id, request_fingerprint, and session_id are required")
    if owner_id and session.owner_id and session.owner_id != owner_id:
        raise PermissionError("analysis job session belongs to another owner")

    now = timezone.now()
    reservation_token = secrets.token_urlsafe(32)
    reservation_metadata = {
        "source": "canonical_analysis_job_reservation",
        "idempotency": {
            "contract_version": "analysis_job_idempotency.v1",
            "request_fingerprint": normalized_fingerprint,
            "state": "reserved",
            "reserved_at": now.isoformat(),
            "reservation_token": reservation_token,
            "reservation_generation": 1,
        },
    }
    with transaction.atomic():
        job, created = AnalysisJob.objects.select_for_update().get_or_create(
            job_id=normalized_job_id,
            defaults={
                "session": session,
                "owner_id": owner_id or session.owner_id,
                "status": AnalysisJobStatus.QUEUED.value,
                "progress_message": "Analysis request reserved.",
                "metadata": reservation_metadata,
            },
        )
        if not created:
            job = AnalysisJob.objects.select_for_update().select_related("session").get(pk=job.pk)
            effective_owner = job.owner_id or job.session.owner_id
            if owner_id and effective_owner and effective_owner != owner_id:
                raise PermissionError("analysis job belongs to another owner")
            if job.session_id != session.pk:
                raise ValueError("analysis job id is already bound to another session")
            metadata = _dict_or_empty(job.metadata)
            idempotency = _dict_or_empty(metadata.get("idempotency"))
            if _text(idempotency.get("request_fingerprint")) != normalized_fingerprint:
                raise ValueError("analysis job id is already bound to another request")
            stale_after = _agent_worker_setting(
                "ANALYSIS_JOB_RESERVATION_STALE_AFTER_SECONDS",
                300,
            )
            stale_cutoff = now - timedelta(seconds=stale_after)
            is_recoverable_stale_reservation = (
                metadata.get("source") == "canonical_analysis_job_reservation"
                and not job.work_items.exists()
                and job.updated_at <= stale_cutoff
            )
            if is_recoverable_stale_reservation:
                recovered_token = secrets.token_urlsafe(32)
                recovered_generation = max(
                    1,
                    _positive_int_or_default(
                        idempotency.get("reservation_generation"),
                        default=1,
                    )
                    + 1,
                )
                job.progress_message = "Analysis request reservation recovered."
                job.metadata = {
                    **reservation_metadata,
                    "idempotency": {
                        **reservation_metadata["idempotency"],
                        "reservation_token": recovered_token,
                        "reservation_generation": recovered_generation,
                    },
                }
                job.save(update_fields=["progress_message", "metadata", "updated_at"])
                return {
                    "status": "reserved",
                    "created": False,
                    "acquired": True,
                    "recovered": True,
                    "job_id": job.job_id,
                    "reservation_token": recovered_token,
                    "reservation_generation": recovered_generation,
                }
            return {
                "status": "existing",
                "created": False,
                "acquired": False,
                "recovered": False,
                "job_id": job.job_id,
                "reservation_token": "",
                "reservation_generation": idempotency.get("reservation_generation"),
            }
    return {
        "status": "reserved",
        "created": True,
        "acquired": True,
        "recovered": False,
        "job_id": normalized_job_id,
        "reservation_token": reservation_token,
        "reservation_generation": 1,
    }


def release_analysis_job_reservation(
    *,
    job_id: str,
    request_fingerprint: str,
    reservation_token: str,
) -> bool:
    """Delete an unqueued reservation so a rejected or failed plan can be retried."""

    with transaction.atomic():
        job = (
            AnalysisJob.objects.select_for_update()
            .filter(job_id=_text(job_id), metadata__source="canonical_analysis_job_reservation")
            .first()
        )
        if job is None or job.work_items.exists():
            return False
        idempotency = _dict_or_empty(_dict_or_empty(job.metadata).get("idempotency"))
        if _text(idempotency.get("request_fingerprint")) != _text(request_fingerprint):
            return False
        if _text(idempotency.get("reservation_token")) != _text(reservation_token):
            return False
        job.delete()
        return True


def renew_analysis_job_reservation(
    *,
    job_id: str,
    request_fingerprint: str,
    reservation_token: str,
) -> bool:
    """Refresh only the current reservation holder's lease before quota use."""

    with transaction.atomic():
        job = (
            AnalysisJob.objects.select_for_update()
            .filter(job_id=_text(job_id), metadata__source="canonical_analysis_job_reservation")
            .first()
        )
        if job is None or job.work_items.exists():
            return False
        idempotency = _dict_or_empty(_dict_or_empty(job.metadata).get("idempotency"))
        if _text(idempotency.get("request_fingerprint")) != _text(request_fingerprint):
            return False
        if _text(idempotency.get("reservation_token")) != _text(reservation_token):
            return False
        job.progress_message = "Analysis request reservation active."
        job.save(update_fields=["progress_message", "updated_at"])
        return True


def enqueue_analysis_job_work(
    payload: dict[str, Any],
    job_payload: dict[str, Any],
    *,
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Persist a queued worker item without executing the agent plan inline."""

    owner_id = _owner_id(payload)
    session = _get_or_create_session(
        job_payload.get("session_id"),
        owner_id=owner_id,
        guest_id=_payload_guest_id(payload),
    )
    if session is None:
        raise ValueError("job_payload must include session_id")
    if owner_id and session.owner_id and session.owner_id != owner_id:
        raise PermissionError("analysis job session belongs to another owner")

    conversation_save_state = conversation_save_state_from_payload(payload)
    session.metadata = _metadata_with_conversation_save_state(
        session.metadata,
        conversation_save_state,
        raw_payload=payload,
    )
    session.save(update_fields=["metadata", "updated_at"])

    job_id = _text(job_payload.get("job_id"))
    if not job_id:
        raise ValueError("job_payload must include job_id")

    message_id = _text(job_payload.get("message_id"))
    chat_response = _dict_or_empty(job_payload.get("chat_response"))
    analysis_plan = _dict_or_empty(job_payload.get("analysis_plan") or chat_response.get("analysis_plan"))
    active_node = _text(job_payload.get("active_node")) or _analysis_plan_first_executable_node(
        analysis_plan
    )
    progress_message = _text(job_payload.get("progress_message")) or "Agent worker item queued."
    work_item_id = _agent_work_item_id(job_id)
    requested_idempotency = _dict_or_empty(job_payload.get("idempotency"))
    requested_fingerprint = _text(requested_idempotency.get("request_fingerprint"))
    requested_reservation_token = _text(requested_idempotency.get("reservation_token"))

    with transaction.atomic():
        message = None
        if message_id:
            message, _message_created = ChatMessage.objects.update_or_create(
                message_id=message_id,
                defaults={
                    "session": session,
                    "role": MessageRole.USER,
                    "content": _message_content(payload),
                    "routing_intent": _text(job_payload.get("routing_intent")),
                    "metadata": {
                        "source": "canonical_analysis_job_queue",
                        "analysis_job_id": job_id,
                        "mock_scenario": job_payload.get("mock_scenario"),
                        "response_status": AgentWorkItemStatus.QUEUED.value,
                        "attachments": job_payload.get("attachments", []),
                        "blocked_attachments": job_payload.get("blocked_attachments", []),
                        "attachment_scan_policy": job_payload.get("attachment_scan_policy", {}),
                        "attachment_resolution": job_payload.get("attachment_resolution", {}),
                        "scan_gate": job_payload.get("scan_gate", {}),
                        "raw_payload": _safe_payload(payload),
                    },
                },
            )

        queue_metadata = {
            "source": "canonical_analysis_job_queue",
            "analysis_plan": analysis_plan,
            "assistant_message": chat_response.get("assistant_message"),
            "case_status": chat_response.get("case_status"),
            "cards": chat_response.get("cards", []),
            "pending_questions": chat_response.get("pending_questions", []),
            "report_links": chat_response.get("report_links", []),
            "supervisor_state": chat_response.get("supervisor_state", {}),
            "reporting_payload": chat_response.get("reporting_payload", {}),
            "attachments": job_payload.get("attachments", []),
            "blocked_attachments": job_payload.get("blocked_attachments", []),
            "attachment_scan_policy": job_payload.get("attachment_scan_policy", {}),
            "attachment_resolution": job_payload.get("attachment_resolution", {}),
            "scan_gate": job_payload.get("scan_gate", {}),
            "limitations": job_payload.get("limitations", []),
            "work_queue": {
                "contract_version": "agent_worker_queue.v1",
                "work_item_id": work_item_id,
                "status": AgentWorkItemStatus.QUEUED.value,
            },
        }
        if requested_idempotency:
            queue_metadata["idempotency"] = {
                **requested_idempotency,
                "contract_version": "analysis_job_idempotency.v1",
                "state": "queued",
            }
        job_defaults = {
            "session": session,
            "message": message,
            "owner_id": owner_id or session.owner_id,
            "routing_intent": _text(job_payload.get("routing_intent")),
            "mock_scenario": _text(job_payload.get("mock_scenario")),
            "status": AnalysisJobStatus.QUEUED.value,
            "active_node": active_node,
            "progress_message": progress_message,
            "analysis_plan_id": _text(
                job_payload.get("analysis_plan_id") or analysis_plan.get("plan_id")
            ),
            "status_counts": _queued_analysis_plan_status_counts(analysis_plan),
            "metadata": queue_metadata,
        }
        job, job_created = AnalysisJob.objects.select_for_update().get_or_create(
            job_id=job_id,
            defaults=job_defaults,
        )
        requested_owner_id = owner_id or session.owner_id
        reservation_promoted = False
        if not job_created:
            effective_owner_id = job.owner_id or job.session.owner_id
            if requested_owner_id and effective_owner_id and effective_owner_id != requested_owner_id:
                raise PermissionError("analysis job belongs to another owner")
            if job.session_id != session.pk:
                raise ValueError("analysis job id is already bound to another session")
            existing_metadata = _dict_or_empty(job.metadata)
            existing_idempotency = _dict_or_empty(existing_metadata.get("idempotency"))
            existing_fingerprint = _text(existing_idempotency.get("request_fingerprint"))
            existing_reservation_token = _text(
                existing_idempotency.get("reservation_token")
            )
            if requested_fingerprint or existing_fingerprint:
                if not requested_fingerprint or requested_fingerprint != existing_fingerprint:
                    raise ValueError("analysis job id is already bound to another request")
            if existing_reservation_token or requested_reservation_token:
                if (
                    not requested_reservation_token
                    or requested_reservation_token != existing_reservation_token
                ):
                    raise ValueError("analysis job reservation holder is stale")

            if existing_metadata.get("source") == "canonical_analysis_job_reservation":
                if not requested_fingerprint or not requested_reservation_token:
                    raise ValueError("analysis job reservation requires a request fingerprint")
                if job.work_items.exists():
                    raise ValueError("analysis job reservation has an invalid work item binding")
                for field_name, field_value in job_defaults.items():
                    setattr(job, field_name, field_value)
                job.save(update_fields=[*job_defaults, "updated_at"])
                reservation_promoted = True

            requested_plan_id = _text(
                job_payload.get("analysis_plan_id") or analysis_plan.get("plan_id")
            )
            if (
                not requested_fingerprint
                and job.analysis_plan_id
                and requested_plan_id != job.analysis_plan_id
            ):
                raise ValueError("analysis job id is already bound to another plan")
            if (
                job.status
                in {
                    AnalysisJobStatus.SUCCESS.value,
                    AnalysisJobStatus.PARTIAL.value,
                    AnalysisJobStatus.FAILED.value,
                }
                and not job.work_items.exists()
            ):
                raise ValueError("terminal analysis job cannot create a new work item")

        work_item, work_item_created = AgentWorkItem.objects.get_or_create(
            work_item_id=work_item_id,
            defaults={
                "job": job,
                "ai_session": None,
                "status": AgentWorkItemStatus.QUEUED.value,
                "attempt_no": 0,
                "max_attempts": max(1, _positive_int_or_default(max_attempts, default=2)),
                "locked_at": None,
                "started_at": None,
                "completed_at": None,
                "next_run_at": timezone.now(),
                "payload": {
                    "contract_version": "agent_worker_queue.v1",
                    "persistence_mode": "analysis_job",
                    "request_payload": _json_compatible(payload),
                    "job_payload": _json_compatible(
                        {
                            **job_payload,
                            "status": AnalysisJobStatus.QUEUED.value,
                            "active_node": active_node,
                            "progress_message": progress_message,
                            "node_execution": {},
                        }
                    ),
                    "execution_payload": _json_compatible(
                        {
                            **payload,
                            "job_id": job_id,
                            "session_id": session.session_id,
                            "message_id": message_id,
                            "attachments": job_payload.get("attachments", []),
                        }
                    ),
                    "analysis_plan": _json_compatible(analysis_plan),
                },
                "result": {},
                "error_code": "",
                "metadata": {
                    "source": "canonical_analysis_job_queue",
                    "job_id": job_id,
                    "analysis_plan_id": _text(job_payload.get("analysis_plan_id") or analysis_plan.get("plan_id")),
                },
            },
        )
        if work_item.job_id != job.pk:
            raise ValueError("agent work item is already bound to another analysis job")
        if job_created or work_item_created or reservation_promoted:
            _append_analysis_job_event(
                job,
                status=AnalysisJobStatus.QUEUED.value,
                active_node=active_node,
                message=progress_message,
                source="agent_worker_queue",
                metadata={"work_item_id": work_item_id},
            )

    progress_cache = write_analysis_job_progress(job)
    session_cache = write_chat_session_state(session, latest_job=job)
    return {
        "backend": "postgresql",
        "status": work_item.status,
        "execution_mode": "async_worker",
        "progress_state": _work_item_progress_state(work_item, job_status=job.status),
        "tables": [AnalysisJob._meta.db_table, AgentWorkItem._meta.db_table],
        "analysis_job_table": AnalysisJob._meta.db_table,
        "agent_work_items_table": AgentWorkItem._meta.db_table,
        "job_id": job.job_id,
        "work_item_id": work_item.work_item_id,
        "work_item_status": work_item.status,
        "progress_cache": progress_cache,
        "session_cache": session_cache,
    }


def process_agent_work_items(*, limit: int = 1, stale_after_seconds: int | None = None) -> dict[str, Any]:
    """Run queued agent work items once, using the DB row as the worker boundary."""

    now = timezone.now()
    normalized_limit = max(1, min(_positive_int_or_default(limit, default=1), 50))
    stale_requeued = _requeue_stale_agent_work_items(
        now=now,
        stale_after_seconds=stale_after_seconds,
    )
    work_items = list(
        AgentWorkItem.objects.select_related("job", "job__session", "ai_session")
        .filter(
            status__in=[
                AgentWorkItemStatus.QUEUED.value,
                AgentWorkItemStatus.RETRYING.value,
            ]
        )
        .filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))
        .order_by("created_at")[:normalized_limit]
    )

    results = [process_agent_work_item(work_item.work_item_id) for work_item in work_items]
    return {
        "backend": "postgresql",
        "contract_version": "agent_worker_queue.v1",
        "requested_limit": normalized_limit,
        "stale_requeued": len(stale_requeued),
        "processed": len([item for item in results if item.get("status") != "skipped"]),
        "work_items": results,
        "stale_work_items": stale_requeued,
    }


def process_agent_work_item(work_item_id: str) -> dict[str, Any]:
    normalized_work_item_id = _text(work_item_id)
    if not normalized_work_item_id:
        return _agent_work_item_skipped("missing_work_item_id")

    claimed = _claim_agent_work_item(normalized_work_item_id)
    if not claimed["claimed"]:
        return claimed
    claimed_attempt_no = int(claimed.get("attempt_no") or 0)

    try:
        work_item = AgentWorkItem.objects.select_related("job", "job__session").get(
            work_item_id=normalized_work_item_id
        )
        with _agent_work_item_lease_heartbeat(
            normalized_work_item_id,
            expected_attempt_no=claimed_attempt_no,
        ):
            node_execution = _execute_agent_work_item_plan(work_item)
        final_status = _analysis_job_status_from_node_execution(node_execution)
        completed_job_payload = _completed_job_payload_for_work_item(
            work_item,
            node_execution=node_execution,
            final_status=final_status,
        )
        with transaction.atomic():
            leased_work_item = (
                AgentWorkItem.objects.select_for_update()
                .select_related("job", "job__session")
                .get(work_item_id=normalized_work_item_id)
            )
            if not _worker_lease_is_current(
                leased_work_item,
                expected_attempt_no=claimed_attempt_no,
            ):
                return _agent_work_item_skipped(
                    "stale_worker_lease",
                    work_item_id=normalized_work_item_id,
                    current_status=leased_work_item.status,
                )
            persistence = persist_analysis_job_execution(
                _dict_or_empty(work_item.payload.get("request_payload")),
                completed_job_payload,
            )
            return _complete_agent_work_item(
                normalized_work_item_id,
                final_status=final_status,
                node_execution=node_execution,
                persistence=persistence,
                expected_attempt_no=claimed_attempt_no,
            )
    except Exception as exc:  # pragma: no cover - exercised through retry smoke tests.
        return _fail_agent_work_item(
            normalized_work_item_id,
            exc,
            expected_attempt_no=claimed_attempt_no,
        )


def persist_analysis_display_result(result_payload: dict[str, Any]) -> dict[str, Any]:
    """Persist the canonical Supervisor display snapshot for an analysis job."""

    job_id = _text(result_payload.get("job_id"))
    if not job_id:
        return _display_result_persistence_skipped("missing_job_id")

    job = AnalysisJob.objects.filter(job_id=job_id).first()
    if job is None:
        return _display_result_persistence_skipped("analysis_job_not_found")

    display_result, _created = AnalysisDisplayResult.objects.update_or_create(
        display_result_id=_display_result_id(job.job_id),
        defaults={
            "job": job,
            "assistant_message": _dict_or_empty(result_payload.get("assistant_message")),
            "progress": _list_or_empty(result_payload.get("progress")),
            "cards": _list_or_empty(result_payload.get("cards")),
            "pending_questions": _list_or_empty(result_payload.get("pending_questions")),
            "attachments": _list_or_empty(result_payload.get("attachments")),
            "report_links": _list_or_empty(result_payload.get("report_links")),
            "limitations": _list_or_empty(result_payload.get("limitations")),
        },
    )

    return {
        "backend": "postgresql",
        "table": AnalysisDisplayResult._meta.db_table,
        "display_result_id": display_result.display_result_id,
        "status": "saved",
    }


def persist_report_action(
    payload: dict[str, Any],
    report_payload: dict[str, Any],
) -> dict[str, Any]:
    """Reserve, stage, and finalize an immutable canonical report version."""

    report_id = _text(report_payload.get("report_id"))
    if not report_id:
        return _report_persistence_skipped("missing_report_id")

    owner_id = _owner_id(payload)
    job = AnalysisJob.objects.filter(job_id=_text(payload.get("job_id"))).first()
    session = (
        job.session
        if job
        else _get_or_create_session(
            payload.get("session_id"),
            owner_id=owner_id,
            guest_id=_payload_guest_id(payload),
        )
    )
    display_result = _display_result_for_job(job)
    report_quality = _report_quality_snapshot(job, display_result, report_payload)
    report_owner_id = owner_id or (job.owner_id if job else "") or (session.owner_id if session else "")
    case = _owned_case_for_report_persistence(
        requested_case_id=_text(payload.get("case_id")),
        owner_id=report_owner_id,
        job=job,
        session=session,
    )
    source_fact_version = _source_fact_version_for_report(
        case=case,
        fact_version_id=_text(payload.get("source_fact_version")),
    )
    request_fingerprint = _report_request_fingerprint(
        payload=payload,
        report_payload=report_payload,
        owner_id=report_owner_id,
        case=case,
        session=session,
        job=job,
        source_fact_version=source_fact_version,
    )
    source_storage_uri = _text(payload.get("storage_uri")) or f"mock://reports/{report_id}"
    object_storage = build_report_storage_reference(
        report_id=report_id,
        owner_id=report_owner_id,
        session_id=session.session_id if session else "",
        job_id=job.job_id if job else "",
        source_uri=source_storage_uri,
    )

    cleanup_pending_report_pk: int | None = None
    with transaction.atomic():
        locked_case = (
            Case.objects.select_for_update().get(pk=case.pk)
            if case is not None
            else None
        )
        existing_report = Report.objects.select_for_update().filter(report_id=report_id).first()
        if existing_report is not None and existing_report.owner_id not in {"", report_owner_id}:
            raise PermissionError("report belongs to another owner")
        if (
            existing_report is not None
            and locked_case is not None
            and existing_report.case_id not in {None, locked_case.id}
        ):
            raise ReportReferenceError(
                "report_case_mismatch",
                "report belongs to another case",
            )
        if existing_report is not None:
            existing_fingerprint = _text(
                _dict_or_empty(existing_report.metadata).get("request_fingerprint")
            )
            if not existing_fingerprint or existing_fingerprint != request_fingerprint:
                raise ReportReferenceError(
                    "report_id_payload_mismatch",
                    "report_id was reused with a different canonical request",
                )
            if _text(_dict_or_empty(existing_report.metadata).get("persistence_state")) == "finalized":
                return _report_persistence_result(
                    existing_report,
                    report_quality=report_quality,
                )
            if (
                _text(
                    _dict_or_empty(existing_report.metadata).get(
                        "persistence_state"
                    )
                )
                == REPORT_STAGING_CLEANUP_PENDING
            ):
                cleanup_pending_report_pk = existing_report.pk
            report = existing_report
        else:
            version_no = locked_case.current_report_version + 1 if locked_case is not None else 1
            pending_storage = {
                **object_storage,
                "status": "pending",
                "writes_binary": False,
                "persistence_state": "database_reserved",
            }
            report = Report.objects.create(
                report_id=report_id,
                owner_id=report_owner_id,
                case=locked_case,
                session=session,
                job=job,
                display_result=display_result,
                source_fact_version=source_fact_version,
                version_no=version_no,
                report_type=_report_type(payload.get("report_type")),
                status=_report_status(report_payload.get("status")),
                title=_report_title(payload, report_payload),
                storage_uri=object_storage["storage_uri"],
                content_summary=_report_content_summary(
                    display_result,
                    report_payload,
                    payload=payload,
                ),
                content={
                    "format": _text(payload.get("format")) or "mock_text",
                    "action": _text(payload.get("action")) or "save",
                    "case_id": locked_case.case_id if locked_case is not None else None,
                    "download_url": report_payload.get("download_url"),
                    "reporting_payload": _dict_or_empty(payload.get("reporting_payload")),
                    "object_storage": pending_storage,
                    "report_quality": report_quality,
                },
                metadata={
                    "source": "canonical_report_action",
                    "action": _text(payload.get("action")) or "save",
                    "mock_status": report_payload.get("status"),
                    "report_quality": report_quality,
                    "limitations": report_payload.get("limitations", []),
                    "object_storage_status": "pending",
                    "object_storage": pending_storage,
                    "source_storage_uri": source_storage_uri,
                    "raw_payload": _safe_payload(payload),
                    "request_fingerprint": request_fingerprint,
                    "persistence_state": "database_reserved",
                },
            )

            if locked_case is not None and version_no > locked_case.current_report_version:
                locked_case.current_report_version = version_no
                locked_case.save(update_fields=["current_report_version", "updated_at"])

    if cleanup_pending_report_pk is not None:
        _purge_pending_report_staging_object(cleanup_pending_report_pk)
        report = Report.objects.get(pk=cleanup_pending_report_pk)
        return _report_persistence_result(report, report_quality=report_quality)

    staging_storage = _staging_report_storage_reference(object_storage)
    try:
        staging_write = write_object(
            staging_storage,
            _report_object_body_for_write(payload, report_payload),
            metadata={
                "report_id": report_id,
                "action": _text(payload.get("action")) or "save",
                "session_id": session.session_id if session else "",
                "job_id": job.job_id if job else "",
                "request_fingerprint": request_fingerprint,
            },
        )
    except Exception:
        cleanup = _safe_delete_staged_object(staging_storage)
        _mark_report_storage_failure(
            report.pk,
            cleanup=cleanup,
            staging_storage=staging_storage,
        )
        raise
    if staging_write.get("writes_binary"):
        try:
            promotion = copy_object(staging_storage, object_storage)
        except Exception:
            cleanup = _safe_delete_staged_object(staging_storage)
            _mark_report_storage_failure(
                report.pk,
                cleanup=cleanup,
                staging_storage=staging_storage,
            )
            raise
    else:
        promotion = {
            "status": "skipped",
            "writes_binary": False,
            "persistence_state": "staging_write_failed",
            "reason": "staging_write_failed",
        }
    cleanup = _safe_delete_staged_object(staging_storage)
    cleanup_completed = _report_staging_cleanup_completed(
        cleanup,
        reference=staging_storage,
    )
    cleanup_target_state = (
        "finalized" if promotion.get("writes_binary") else "storage_failed"
    )
    persistence_state = (
        cleanup_target_state
        if cleanup_completed
        else REPORT_STAGING_CLEANUP_PENDING
    )
    finalized_storage = {
        **object_storage,
        "write_result": promotion,
        "status": promotion.get("status") or "skipped",
        "writes_binary": bool(promotion.get("writes_binary")),
        "persistence_state": promotion.get("persistence_state") or "metadata_only_adapter",
    }

    with transaction.atomic():
        report = Report.objects.select_for_update().get(pk=report.pk)
        content = dict(report.content or {})
        content["object_storage"] = finalized_storage
        metadata = dict(report.metadata or {})
        metadata.update(
            {
                "object_storage_status": finalized_storage["status"],
                "object_storage": finalized_storage,
                "object_storage_write": promotion,
                "object_storage_staging_write": staging_write,
                "object_storage_staging_cleanup": cleanup,
                "object_storage_staging": _minimal_report_storage_reference(
                    staging_storage
                ),
                "staging_cleanup_target_state": cleanup_target_state,
                "persistence_state": persistence_state,
            }
        )
        if persistence_state != REPORT_STAGING_CLEANUP_PENDING:
            metadata.pop("staging_cleanup_target_state", None)
        report.content = content
        report.metadata = metadata
        report.save(update_fields=["content", "metadata", "updated_at"])

    return _report_persistence_result(report, report_quality=report_quality)


def _report_persistence_result(
    report: Report,
    *,
    report_quality: dict[str, Any],
) -> dict[str, Any]:
    metadata = _dict_or_empty(report.metadata)
    object_storage = _dict_or_empty(metadata.get("object_storage"))
    return {
        "backend": "postgresql",
        "table": Report._meta.db_table,
        "report_id": report.report_id,
        "status": "metadata_saved",
        "storage_uri": report.storage_uri,
        "object_storage": object_storage,
        "report_quality": _dict_or_empty(metadata.get("report_quality")) or report_quality,
    }


def _safe_delete_staged_object(reference: dict[str, Any]) -> dict[str, Any]:
    try:
        return delete_object(reference)
    except Exception as cleanup_error:
        return {
            "status": "failed",
            "error_class": cleanup_error.__class__.__name__,
        }


def _mark_report_storage_failure(
    report_pk: int,
    *,
    cleanup: dict[str, Any],
    staging_storage: dict[str, Any],
) -> None:
    with transaction.atomic():
        failed_report = Report.objects.select_for_update().get(pk=report_pk)
        metadata = dict(failed_report.metadata or {})
        cleanup_completed = _report_staging_cleanup_completed(
            cleanup,
            reference=staging_storage,
        )
        metadata.update(
            {
                "object_storage_status": "failed",
                "object_storage_staging_cleanup": cleanup,
                "object_storage_staging": _minimal_report_storage_reference(
                    staging_storage
                ),
                "persistence_state": (
                    "storage_failed"
                    if cleanup_completed
                    else REPORT_STAGING_CLEANUP_PENDING
                ),
            }
        )
        if cleanup_completed:
            metadata.pop("staging_cleanup_target_state", None)
        else:
            metadata["staging_cleanup_target_state"] = "storage_failed"
        failed_report.metadata = metadata
        failed_report.save(update_fields=["metadata", "updated_at"])


def _staging_report_storage_reference(reference: dict[str, Any]) -> dict[str, Any]:
    staging = dict(reference)
    key = _text(reference.get("key"))
    staging_key = f"staging/{key}"
    staging["key"] = staging_key
    bucket = _text(reference.get("bucket"))
    staging["storage_uri"] = f"s3://{bucket}/{staging_key}" if bucket else staging_key
    staging["resource_id"] = f"{_text(reference.get('resource_id'))}:staging"
    return staging


def purge_pending_report_staging(*, limit: int | None = None) -> dict[str, Any]:
    """Retry deletion of staged report objects before finalizing their state."""

    resolved_limit = _positive_report_staging_cleanup_limit(limit)
    queryset = (
        Report.objects.filter(
            metadata__persistence_state=REPORT_STAGING_CLEANUP_PENDING
        )
        .order_by("updated_at", "pk")
        .values_list("pk", flat=True)
    )
    selected_pks = list(queryset[:resolved_limit])
    batch = {
        "contract_version": REPORT_STAGING_CLEANUP_BATCH_VERSION,
        "status": "pass",
        "selected": len(selected_pks),
        "cleaned": 0,
        "retryable": 0,
        "skipped": 0,
    }
    for report_pk in selected_pks:
        outcome = _purge_pending_report_staging_object(report_pk)
        batch[outcome] += 1
    if batch["retryable"]:
        batch["status"] = "warn"
    return batch


def _purge_pending_report_staging_object(report_pk: int) -> str:
    report = Report.objects.filter(pk=report_pk).first()
    if report is None:
        return "skipped"
    metadata = _dict_or_empty(report.metadata)
    if _text(metadata.get("persistence_state")) != REPORT_STAGING_CLEANUP_PENDING:
        return "skipped"
    staging_reference = _validated_report_staging_reference(report)
    if not staging_reference:
        cleanup = {"status": "skipped", "reason": "staging_reference_invalid"}
    else:
        cleanup = _safe_delete_staged_object(staging_reference)
    cleanup_completed = bool(staging_reference) and _report_staging_cleanup_completed(
        cleanup,
        reference=staging_reference,
    )

    with transaction.atomic():
        locked_report = Report.objects.select_for_update().filter(pk=report_pk).first()
        if locked_report is None:
            return "skipped"
        locked_metadata = _dict_or_empty(locked_report.metadata)
        if (
            _text(locked_metadata.get("persistence_state"))
            != REPORT_STAGING_CLEANUP_PENDING
        ):
            return "skipped"
        locked_metadata["object_storage_staging_cleanup"] = cleanup
        if cleanup_completed:
            locked_metadata["persistence_state"] = (
                _text(locked_metadata.get("staging_cleanup_target_state"))
                or "finalized"
            )
            locked_metadata.pop("staging_cleanup_target_state", None)
        locked_report.metadata = locked_metadata
        locked_report.save(update_fields=["metadata", "updated_at"])
    return "cleaned" if cleanup_completed else "retryable"


def _validated_report_staging_reference(report: Report) -> dict[str, Any]:
    metadata = _dict_or_empty(report.metadata)
    final_reference = _dict_or_empty(metadata.get("object_storage"))
    if (
        _text(final_reference.get("resource_type")) != "report"
        or _text(final_reference.get("resource_id")) != report.report_id
        or _text(final_reference.get("bucket")) != object_storage_bucket()
    ):
        return {}
    final_key = _text(final_reference.get("key"))
    prefix = object_storage_prefix().strip("/")
    expected_prefix = f"{prefix}/reports/" if prefix else "reports/"
    if (
        not final_key.startswith(expected_prefix)
        or ".." in final_key.split("/")
        or "\\" in final_key
    ):
        return {}
    expected = _staging_report_storage_reference(final_reference)
    stored = _dict_or_empty(metadata.get("object_storage_staging"))
    for field in ("provider", "bucket", "key", "resource_type", "resource_id"):
        if stored and _text(stored.get(field)) != _text(expected.get(field)):
            return {}
    return expected


def _report_staging_cleanup_completed(
    cleanup: dict[str, Any],
    *,
    reference: dict[str, Any],
) -> bool:
    if cleanup.get("status") not in SUCCESSFUL_STORAGE_DELETE_STATUSES:
        return False
    provider = _text(reference.get("provider")) or _text(
        object_storage_policy().get("provider")
    )
    return provider != "s3" or bool(cleanup.get("permanent"))


def _minimal_report_storage_reference(reference: dict[str, Any]) -> dict[str, Any]:
    return {
        key: reference[key]
        for key in (
            "policy_version",
            "backend",
            "provider",
            "bucket",
            "key",
            "resource_type",
            "resource_id",
        )
        if reference.get(key) not in (None, "")
    }


def _positive_report_staging_cleanup_limit(value: int | None) -> int:
    raw_value = (
        value
        if value is not None
        else getattr(
            settings,
            "REPORT_STAGING_CLEANUP_LIMIT",
            DEFAULT_REPORT_STAGING_CLEANUP_LIMIT,
        )
    )
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_REPORT_STAGING_CLEANUP_LIMIT
    return parsed if parsed > 0 else DEFAULT_REPORT_STAGING_CLEANUP_LIMIT


def _report_request_fingerprint(
    *,
    payload: dict[str, Any],
    report_payload: dict[str, Any],
    owner_id: str,
    case: Case | None,
    session: ChatSession | None,
    job: AnalysisJob | None,
    source_fact_version: ConfirmedFactVersion | None,
) -> str:
    canonical_request = {
        "action": _text(payload.get("action")) or "save",
        "owner_id": owner_id,
        "case_id": case.case_id if case is not None else "",
        "session_id": session.session_id if session is not None else "",
        "job_id": job.job_id if job is not None else "",
        "source_fact_version": (
            source_fact_version.fact_version_id if source_fact_version is not None else ""
        ),
        "report_type": _report_type(payload.get("report_type")),
        "format": _text(payload.get("format")) or "mock_text",
        "title": _report_title(payload, report_payload),
        "status": _report_status(report_payload.get("status")),
        "reporting_payload": _dict_or_empty(payload.get("reporting_payload")),
        "limitations": _list_or_empty(report_payload.get("limitations")),
    }
    encoded = json.dumps(
        canonical_request,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _owned_case_for_report_persistence(
    *,
    requested_case_id: str,
    owner_id: str,
    job: AnalysisJob | None,
    session: ChatSession | None,
) -> Case | None:
    if job is not None and job.owner_id and job.owner_id != owner_id:
        raise PermissionError("analysis job belongs to another owner")
    if session is not None and session.owner_id and session.owner_id != owner_id:
        raise PermissionError("chat session belongs to another owner")

    if requested_case_id:
        if not owner_id:
            raise PermissionError("case report requires an authenticated owner")
        case = Case.objects.filter(
            case_id=requested_case_id,
            owner_id=owner_id,
            deleted_at__isnull=True,
        ).first()
        if case is None:
            raise PermissionError("case does not exist or belongs to another owner")
    else:
        case = job.case if job is not None and job.case_id else None
        if case is None and session is not None and session.case_id:
            case = session.case

    if case is not None and (not owner_id or case.owner_id != owner_id):
        raise PermissionError("case does not belong to authenticated owner")
    related_cases = {
        related_case_id
        for related_case_id in (
            job.case_id if job is not None else None,
            session.case_id if session is not None else None,
        )
        if related_case_id is not None
    }
    if case is not None:
        related_cases.add(case.id)
    if len(related_cases) > 1:
        raise ReportReferenceError(
            "provenance_mismatch",
            "job, session, and requested case do not share the same provenance",
        )
    return case


def _source_fact_version_for_report(
    *,
    case: Case | None,
    fact_version_id: str,
) -> ConfirmedFactVersion | None:
    if not fact_version_id:
        return None
    if case is None:
        raise ReportReferenceError(
            "case_required_for_fact_version",
            "source_fact_version requires a case",
        )
    fact_version = ConfirmedFactVersion.objects.filter(fact_version_id=fact_version_id).first()
    if fact_version is None:
        raise ReportReferenceError(
            "fact_version_not_found",
            f"source_fact_version was not found: {fact_version_id}",
        )
    if fact_version.case_id != case.id:
        raise ReportReferenceError(
            "fact_case_mismatch",
            "source_fact_version does not belong to the requested case",
        )
    if fact_version.status != "confirmed":
        raise ReportReferenceError(
            "fact_version_not_confirmed",
            "source_fact_version is not confirmed",
        )
    return fact_version


def get_report_download_metadata(report_id: str, *, document_type: str | None = None) -> dict[str, Any] | None:
    report = (
        Report.objects.select_related("session", "job", "display_result")
        .filter(report_id=report_id)
        .first()
    )
    if report is None:
        return None

    object_storage = _report_object_storage(report)
    storage_uri = object_storage["storage_uri"]
    storage_backend = object_storage["backend"]
    normalized_document_type = _report_download_document_type(document_type)
    if normalized_document_type == REPORT_DOWNLOAD_TYPE_OBJECTION_FORM:
        text_body = _report_objection_form_body(report)
        title = "과태료 부과 처분 이의신청서"
        filename = f"{report.report_id}-objection-form.pdf"
        pdf_body = _report_objection_form_pdf_body(
            report,
            title=title,
            text_body=text_body,
        )
    else:
        text_body = _report_download_body(
            report,
            storage_backend=storage_backend,
            object_storage=object_storage,
        )
        title = report.title or report.report_id
        filename = f"{report.report_id}.pdf"
        pdf_body = build_report_download_pdf_body(
            report_id=report.report_id,
            title=title,
            body_text=text_body,
        )
    return {
        "report_id": report.report_id,
        "document_type": normalized_document_type,
        "owner_id": report.owner_id,
        "session_id": report.session.session_id if report.session_id else None,
        "job_id": report.job.job_id if report.job_id else None,
        "filename": filename,
        "content_type": REPORT_PDF_CONTENT_TYPE,
        "storage_uri": storage_uri,
        "storage_backend": storage_backend,
        "object_storage": object_storage,
        "object_key": object_storage.get("key", ""),
        "status": report.status,
        "body": pdf_body,
        "text_body": text_body,
    }


def list_report_records(
    *,
    session_id: str | None = None,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    reports = Report.objects.select_related("session", "job", "display_result").order_by("-created_at")
    if session_id:
        reports = reports.filter(session__session_id=session_id)
    if owner_id:
        reports = reports.filter(owner_id=owner_id)
    return [_report_record_summary(report) for report in reports]


def get_report_record_detail(report_id: str) -> dict[str, Any] | None:
    report = (
        Report.objects.select_related("session", "job", "display_result")
        .filter(report_id=report_id)
        .first()
    )
    if report is None:
        return None

    content = _dict_or_empty(report.content)
    metadata = _dict_or_empty(report.metadata)
    reporting_payload = _dict_or_empty(content.get("reporting_payload"))
    job = report.job
    return {
        **_report_record_summary(report),
        "content": {
            "reporting_payload": reporting_payload,
            "format": _text(content.get("format")),
            "action": _text(content.get("action")),
        },
        "metadata": {
            "report_quality": _dict_or_empty(metadata.get("report_quality")),
            "limitations": _list_or_empty(metadata.get("limitations")),
            "object_storage": _dict_or_empty(metadata.get("object_storage")),
        },
        "job": {
            "job_id": job.job_id,
            "status": job.status,
            "routing_intent": job.routing_intent,
            "mock_scenario": job.mock_scenario,
        }
        if job
        else None,
    }


def _report_record_summary(report: Report) -> dict[str, Any]:
    metadata = _dict_or_empty(report.metadata)
    content = _dict_or_empty(report.content)
    reporting_payload = _dict_or_empty(content.get("reporting_payload"))
    report_quality = _dict_or_empty(metadata.get("report_quality"))
    return {
        "report_id": report.report_id,
        "report_type": report.report_type,
        "screen_id": _text(reporting_payload.get("screen_id")),
        "title": report.title,
        "status": report.status,
        "session_id": report.session.session_id if report.session_id else None,
        "job_id": report.job.job_id if report.job_id else None,
        "summary": report.content_summary,
        "download_url": f"/api/reports/{report.report_id}/download/",
        "partial_report": bool(report_quality.get("partial_report")),
        "created_at": report.created_at.isoformat(),
        "updated_at": report.updated_at.isoformat(),
    }


def authorize_report_download_metadata(
    download: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Authorize report metadata download before the object body is returned."""

    resource = {
        "type": "report",
        "report_id": download.get("report_id"),
        "owner_id": download.get("owner_id"),
        "session_id": download.get("session_id"),
        "storage_backend": download.get("storage_backend"),
    }
    return authorize_resource_access(resource, payload)


def access_subject_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    auth_context = _dict_or_empty(payload.get("auth_context"))
    context_has_identity = any(
        key in auth_context
        for key in (
            "subject_id",
            "subject_type",
            "user_id",
            "guest_id",
            "auth_session_id",
        )
    )
    if context_has_identity:
        user_id = _text(auth_context.get("user_id"))
        guest_id = _normalize_guest_id(auth_context.get("guest_id"))
        auth_session_id = _text(auth_context.get("auth_session_id"))
    else:
        user_id = _owner_id(payload)
        guest_id = _normalize_guest_id(payload.get("guest_id"))
        auth_session_id = _text(payload.get("auth_session_id"))
    session_id = _text(payload.get("session_id") or auth_context.get("session_id"))

    if user_id:
        subject_type = "user"
        subject_id = f"user:{user_id}"
    elif guest_id:
        subject_type = "guest"
        subject_id = f"guest:{guest_id}"
    else:
        subject_type = "anonymous"
        subject_id = "anonymous"

    return {
        "subject": {
            "subject_id": subject_id,
            "subject_type": subject_type,
            "user_id": user_id or None,
            "guest_id": guest_id or None,
            "session_id": session_id or None,
            "auth_session_id": auth_session_id or None,
        },
    }


def authorize_resource_access(
    resource: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Authorize a canonical resource using the normalized mock auth subject."""

    subject = access_subject_from_payload(payload)["subject"]
    user_id = _text(subject.get("user_id"))
    guest_id = _normalize_guest_id(subject.get("guest_id"))
    session_id = _text(subject.get("session_id"))
    resource_owner_id = _text(resource.get("owner_id"))
    resource_guest_id = _normalize_guest_id(resource.get("guest_id"))
    resource_session_id = _text(resource.get("session_id"))

    allowed = False
    reason = "owner_mismatch"
    if resource_owner_id:
        allowed = bool(user_id and user_id == resource_owner_id)
        reason = "owner_match" if allowed else "owner_mismatch"
    elif resource_guest_id:
        allowed = bool(guest_id and guest_id == resource_guest_id)
        reason = "guest_match" if allowed else "guest_mismatch"
    elif resource_session_id:
        allowed = bool(session_id and session_id == resource_session_id)
        reason = "session_match" if allowed else "session_mismatch"
    else:
        object_identifiers = (
            resource.get("attachment_id"),
            resource.get("job_id"),
            resource.get("report_id"),
        )
        allowed = not any(_text(value) for value in object_identifiers)
        reason = "unscoped_collection" if allowed else "unbound_resource"

    return {
        "contract_version": "object_access.v1",
        "allowed": allowed,
        "reason": reason,
        "subject": subject,
        "resource": {
            key: value
            for key, value in {
                "type": resource.get("type"),
                "report_id": resource.get("report_id"),
                "attachment_id": resource.get("attachment_id"),
                "job_id": resource.get("job_id"),
                "session_id": resource_session_id or None,
                "owner_id": resource_owner_id or None,
                "guest_id": resource_guest_id or None,
                "storage_backend": resource.get("storage_backend"),
            }.items()
            if value is not None
        },
    }


def get_mycase_summary(
    *,
    session_id: str | None = None,
    owner_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    queryset = (
        AnalysisJob.objects.select_related("session", "message")
        .prefetch_related("events", "agent_results", "agent_invocations", "reports")
        .order_by("-updated_at")
    )
    if session_id:
        queryset = queryset.filter(session__session_id=session_id)
    if owner_id:
        queryset = queryset.filter(owner_id=owner_id)

    candidate_jobs = list(queryset[: max(limit, 1) * 3])
    jobs = [
        job
        for job in candidate_jobs
        if _conversation_is_saved_for_job(job)
    ][: max(limit, 1)]
    cases = [_case_summary(job) for job in jobs]
    active_statuses = {
        AnalysisJobStatus.QUEUED.value,
        AnalysisJobStatus.RUNNING.value,
        AnalysisJobStatus.PARTIAL.value,
    }
    saved_reports = Report.objects.all()
    if session_id:
        saved_reports = saved_reports.filter(session__session_id=session_id)
    if owner_id:
        saved_reports = saved_reports.filter(owner_id=owner_id)

    report_rows = list(saved_reports.select_related("session"))
    saved_report_count = sum(1 for report in report_rows if _conversation_is_saved_for_report(report))

    return {
        "storage": {
            "backend": "postgresql",
            "tables": [
                ChatSession._meta.db_table,
                ChatMessage._meta.db_table,
                AnalysisJob._meta.db_table,
                AnalysisJobEvent._meta.db_table,
                AgentResult._meta.db_table,
                AiSession._meta.db_table,
                AgentInvocation._meta.db_table,
                AnalysisDisplayResult._meta.db_table,
                Report._meta.db_table,
            ],
        },
        "progress_cache": progress_cache_policy(),
        "object_storage": object_storage_policy(),
        "active_cases": sum(1 for case in cases if case["case_status"] in active_statuses),
        "due_soon_cases": 0,
        "saved_reports": saved_report_count,
        "recent_analysis_count": len(cases),
        "cases": cases,
        "conversation_save_policy": {
            "policy_version": CONVERSATION_SAVE_POLICY_VERSION,
            "saved_state": "saved",
            "hidden_states": ["pending", "session_only"],
        },
        "limitations": [
            "deadline calculation is not connected yet; due_soon_cases stays 0.",
            "authorization is still mock bearer/guest-shape based.",
        ],
    }


def get_analysis_job_access_metadata(job_id: str) -> dict[str, Any] | None:
    """Return the minimum ownership record needed before exposing a job."""

    job = (
        AnalysisJob.objects.select_related("session")
        .filter(job_id=_text(job_id))
        .only("job_id", "owner_id", "session__session_id", "session__owner_id")
        .first()
    )
    if job is None:
        return None
    return {
        "type": "analysis_job",
        "job_id": job.job_id,
        "owner_id": job.owner_id or job.session.owner_id,
        "session_id": job.session.session_id,
    }


def list_analysis_job_records(
    *,
    owner_id: str,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """List only jobs owned by the authenticated principal."""

    normalized_owner_id = _text(owner_id)
    if not normalized_owner_id:
        return []
    queryset = (
        AnalysisJob.objects.select_related("session")
        .filter(
            Q(owner_id=normalized_owner_id)
            | Q(owner_id="", session__owner_id=normalized_owner_id)
        )
        .order_by("-updated_at")
    )
    if session_id:
        queryset = queryset.filter(session__session_id=_text(session_id))
    return [
        {
            "contract_version": "analysis_job_summary.v1",
            "job_id": job.job_id,
            "session_id": job.session.session_id,
            "owner_id": job.owner_id or job.session.owner_id,
            "routing_intent": job.routing_intent,
            "status": job.status,
            "active_node": job.active_node,
            "progress_message": job.progress_message,
            "analysis_plan_id": job.analysis_plan_id,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
        }
        for job in queryset
    ]


def get_analysis_job_record(job_id: str) -> dict[str, Any] | None:
    job = (
        AnalysisJob.objects.select_related("session", "message")
        .prefetch_related("events", "agent_results", "agent_invocations", "work_items", "reports")
        .filter(job_id=_text(job_id))
        .first()
    )
    if job is None:
        return None

    display_result = _display_result_for_job(job)
    work_items = list(job.work_items.order_by("-updated_at"))
    latest_work_item = work_items[0] if work_items else None
    agent_results = list(job.agent_results.all())
    agent_invocations = list(job.agent_invocations.all())
    latest_event = job.events.order_by("-created_at").first()
    metadata = _dict_or_empty(job.metadata)
    work_queue = _dict_or_empty(metadata.get("work_queue"))
    reports = list(job.reports.order_by("-created_at"))
    latest_report = reports[0] if reports else None
    display_payload = _analysis_job_display_payload(job, display_result)
    node_results = _agent_result_node_results(agent_results)
    supervisor_execution = _analysis_job_supervisor_execution(
        job,
        metadata=metadata,
        node_results=node_results,
        agent_results=agent_results,
        latest_work_item=latest_work_item,
    )
    progress_state = work_queue.get("progress_state")
    if not isinstance(progress_state, dict) and latest_work_item:
        progress_state = _work_item_progress_state(latest_work_item, job_status=job.status)

    return {
        "backend": "postgresql",
        "contract_version": "analysis_job_detail.v1",
        "job_id": job.job_id,
        "session_id": job.session.session_id,
        "message_id": job.message.message_id if job.message_id else None,
        "owner_id": job.owner_id or None,
        "routing_intent": job.routing_intent,
        "mock_scenario": job.mock_scenario,
        "status": job.status,
        "active_node": job.active_node,
        "progress_message": job.progress_message,
        "analysis_plan_id": job.analysis_plan_id,
        "analysis_plan": _dict_or_empty(metadata.get("analysis_plan")),
        "status_counts": job.status_counts or {},
        "progress_state": progress_state or {},
        "work_queue": work_queue,
        "work_item": _analysis_job_work_item_summary(latest_work_item),
        "work_items": [_analysis_job_work_item_summary(work_item) for work_item in work_items],
        "conversation_messages": _analysis_job_conversation_messages(job),
        "assistant_message": display_payload["assistant_message"],
        "assistant_message_payload": display_payload["assistant_message_payload"],
        "cards": display_payload["cards"],
        "pending_questions": display_payload["pending_questions"],
        "attachments": display_payload["attachments"],
        "report_links": display_payload["report_links"],
        "limitations": display_payload["limitations"],
        "supervisor_state": _dict_or_empty(metadata.get("supervisor_state")),
        "reporting_payload": _dict_or_empty(metadata.get("reporting_payload")),
        "supervisor_execution": supervisor_execution,
        "agent_results": node_results,
        "agent_result_count": len(agent_results),
        "agent_status_counts": _agent_status_counts(agent_results),
        "agent_invocation_count": len(agent_invocations),
        "agent_invocation_status_counts": _agent_invocation_status_counts(agent_invocations),
        "display_result_id": display_result.display_result_id if display_result else None,
        "report_count": len(reports),
        "reports": [_analysis_job_report_summary(report) for report in reports],
        "latest_report_id": latest_report.report_id if latest_report else None,
        "latest_report_status": latest_report.status if latest_report else None,
        "last_event_at": (latest_event.created_at if latest_event else job.updated_at).isoformat(),
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "metadata": {
            "source": metadata.get("source"),
            "scan_gate": metadata.get("scan_gate") or {},
            "blocked_attachments": metadata.get("blocked_attachments") or [],
            "attachment_scan_policy": metadata.get("attachment_scan_policy") or {},
        },
    }


def _analysis_job_display_payload(
    job: AnalysisJob,
    display_result: AnalysisDisplayResult | None,
) -> dict[str, Any]:
    metadata = _dict_or_empty(job.metadata)
    assistant_payload = _dict_or_empty(display_result.assistant_message if display_result else None)
    metadata_assistant_message = _text(metadata.get("assistant_message"))
    assistant_message = (
        _text(assistant_payload.get("answer"))
        or _text(assistant_payload.get("summary"))
        or metadata_assistant_message
        or job.progress_message
    )
    cards = _list_or_empty(display_result.cards if display_result else metadata.get("cards"))
    pending_questions = _list_or_empty(
        display_result.pending_questions if display_result else metadata.get("pending_questions")
    )
    attachments = _list_or_empty(display_result.attachments if display_result else metadata.get("attachments"))
    report_links = _list_or_empty(display_result.report_links if display_result else metadata.get("report_links"))
    limitations = _list_or_empty(display_result.limitations if display_result else metadata.get("limitations"))
    if not limitations:
        limitations = _list_or_empty(metadata.get("limitations"))

    return {
        "assistant_message": assistant_message,
        "assistant_message_payload": assistant_payload
        or {
            "answer": assistant_message,
            "summary": _case_display_summary(display_result) or assistant_message,
            "limitations": limitations,
        },
        "cards": cards,
        "pending_questions": pending_questions,
        "attachments": attachments,
        "report_links": report_links,
        "limitations": limitations,
    }


def _analysis_job_conversation_messages(job: AnalysisJob) -> list[dict[str, Any]]:
    messages = ChatMessage.objects.filter(session=job.session).order_by("created_at")
    return [
        {
            "message_id": message.message_id,
            "role": message.role,
            "content": message.content,
            "routing_intent": message.routing_intent,
            "metadata": {
                "analysis_job_id": _dict_or_empty(message.metadata).get("analysis_job_id"),
                "conversation_save_state": _dict_or_empty(message.metadata).get("conversation_save_state"),
                "response_status": _dict_or_empty(message.metadata).get("response_status"),
            },
            "created_at": message.created_at.isoformat(),
        }
        for message in messages
    ]


def _agent_result_node_results(agent_results: list[AgentResult]) -> list[dict[str, Any]]:
    node_results = []
    for index, result in enumerate(agent_results, start=1):
        raw_output = _dict_or_empty(result.raw_output)
        adapter_context = _dict_or_empty(raw_output.get("adapter_context"))
        plan_step = _dict_or_empty(raw_output.get("plan_step"))
        node_results.append(
            {
                "result_id": result.result_id,
                "execution_id": _text(raw_output.get("execution_id")) or result.result_id,
                "node_code": result.node_code,
                "node_name": result.node_name,
                "execution_mode": _text(raw_output.get("execution_mode")) or adapter_context.get("execution_mode") or "mock",
                "adapter_execution_mode": adapter_context.get("execution_mode") or raw_output.get("execution_mode") or "mock",
                "plan_step": {
                    "order": plan_step.get("order") or index,
                    "status": plan_step.get("status") or result.status,
                    "fallback": plan_step.get("fallback"),
                    "depends_on": plan_step.get("depends_on") or [],
                },
                "status": result.status,
                "summary": result.summary,
                "structured_result": result.structured_result or {},
                "evidence": result.evidence or [],
                "next_actions": result.next_actions or [],
                "limitations": result.limitations or [],
                "created_at": result.created_at.isoformat(),
            }
        )
    return node_results


def _analysis_job_supervisor_execution(
    job: AnalysisJob,
    *,
    metadata: dict[str, Any],
    node_results: list[dict[str, Any]],
    agent_results: list[AgentResult],
    latest_work_item: AgentWorkItem | None,
) -> dict[str, Any]:
    supervisor_execution = dict(_dict_or_empty(metadata.get("supervisor_execution")))
    supervisor_execution.setdefault("contract_version", "supervisor_execution.v1")
    supervisor_execution.setdefault("orchestration_mode", "background_session")
    supervisor_execution.setdefault("execution_mode", "sync" if node_results else "not_recorded")
    supervisor_execution.setdefault("job_id", job.job_id)
    supervisor_execution.setdefault("session_id", job.session.session_id)
    supervisor_execution.setdefault("message_id", job.message.message_id if job.message_id else None)
    supervisor_execution["agent_results_saved"] = len(agent_results)
    supervisor_execution["node_results"] = node_results
    if latest_work_item:
        supervisor_execution["work_item"] = _analysis_job_work_item_summary(latest_work_item)
    return supervisor_execution


def _analysis_job_report_summary(report: Report) -> dict[str, Any]:
    metadata = _dict_or_empty(report.metadata)
    return {
        "report_id": report.report_id,
        "report_type": report.report_type,
        "status": report.status,
        "title": report.title,
        "content_summary": report.content_summary,
        "storage_uri": report.storage_uri,
        "object_storage": _dict_or_empty(metadata.get("object_storage")),
        "report_quality": _dict_or_empty(metadata.get("report_quality")),
        "created_at": report.created_at.isoformat(),
        "updated_at": report.updated_at.isoformat(),
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
    object_storage = _uploaded_file_object_storage(uploaded_file)

    attachment = {
        "attachment_id": uploaded_file.attachment_id,
        "case_id": uploaded_file.case.case_id if uploaded_file.case_id else None,
        "session_id": session_id,
        "message_id": metadata.get("message_id"),
        "purpose": uploaded_file.purpose,
        "type": uploaded_file.file_type,
        "original_filename": uploaded_file.original_filename,
        "filename": filename,
        "content_type": uploaded_file.content_type,
        "size_bytes": uploaded_file.size_bytes or 0,
        "storage_uri": uploaded_file.storage_uri,
        "object_storage": object_storage,
        "status": uploaded_file.status,
        "scan_status": uploaded_file.scan_status,
        "retention_expires_at": (
            uploaded_file.retention_expires_at.isoformat()
            if uploaded_file.retention_expires_at
            else None
        ),
        "deleted_at": uploaded_file.deleted_at.isoformat() if uploaded_file.deleted_at else None,
        "privacy_risk": uploaded_file.privacy_risk,
        "scan_result": metadata.get("scan_result"),
        "created_at": uploaded_file.created_at.isoformat(),
        "checks": checks,
        "agent_handoff": uploaded_file.agent_handoff or {},
        "limitations": limitations,
        "persistence": {
            "backend": "postgresql",
            "table": UploadedFile._meta.db_table,
            "status": "metadata_saved",
            "object_storage": object_storage,
        },
    }
    return {key: value for key, value in attachment.items() if value is not None}


def _uploaded_file_object_storage(uploaded_file: UploadedFile) -> dict[str, Any]:
    metadata = uploaded_file.metadata if isinstance(uploaded_file.metadata, dict) else {}
    object_storage = metadata.get("object_storage")
    if isinstance(object_storage, dict) and object_storage.get("storage_uri"):
        return dict(object_storage)
    return storage_reference_from_uri(
        uploaded_file.storage_uri,
        resource_type="uploaded_file",
        resource_id=uploaded_file.attachment_id,
        filename=Path(uploaded_file.original_filename).name,
        content_type=uploaded_file.content_type,
        size_bytes=uploaded_file.size_bytes,
    )


def _get_or_create_session(
    session_id: Any,
    *,
    owner_id: str,
    guest_id: str = "",
) -> ChatSession | None:
    normalized_session_id = _text(session_id)
    if not normalized_session_id:
        return None

    normalized_owner_id = _text(owner_id)
    normalized_guest_id = _normalize_guest_id(guest_id)
    initial_auth_context = (
        {"guest_id": normalized_guest_id, "subject_type": "guest"}
        if normalized_guest_id
        else {}
    )
    with transaction.atomic():
        session, created = ChatSession.objects.select_for_update().get_or_create(
            session_id=normalized_session_id,
            defaults={
                "owner_id": normalized_owner_id,
                "status": ChatSessionStatus.ACTIVE,
                "metadata": {
                    "created_by": "canonical_session_binding",
                    **(
                        {"auth_context": initial_auth_context}
                        if initial_auth_context
                        else {}
                    ),
                },
            },
        )
        if created:
            return session

        existing_guest_id = _chat_session_guest_id(session)
        if session.owner_id:
            if not normalized_owner_id or session.owner_id != normalized_owner_id:
                raise PermissionError("session belongs to another identity")
            return session

        if normalized_owner_id:
            if not existing_guest_id:
                raise PermissionError("unbound session cannot be claimed")
            if not normalized_guest_id or existing_guest_id != normalized_guest_id:
                raise PermissionError("guest session binding does not match")
            session.owner_id = normalized_owner_id
            session.save(update_fields=["owner_id", "updated_at"])
            return session

        if existing_guest_id:
            if not normalized_guest_id or existing_guest_id != normalized_guest_id:
                raise PermissionError("guest session binding does not match")
            return session

        if normalized_guest_id:
            raise PermissionError("unbound session cannot be claimed")
        return session


def _conversation_save_state_result(status: str, save_state: str, *, reason: str | None = None) -> dict[str, Any]:
    result = {
        "backend": "postgresql",
        "policy_version": CONVERSATION_SAVE_POLICY_VERSION,
        "status": status,
        "conversation_save_state": save_state,
    }
    if reason:
        result["reason"] = reason
    return result


def _metadata_with_conversation_save_state(
    metadata: Any,
    save_state: str,
    *,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    next_metadata = dict(metadata or {})
    next_metadata["conversation_save_policy"] = CONVERSATION_SAVE_POLICY_VERSION
    next_metadata["conversation_save_state"] = save_state
    if raw_payload:
        auth_context = raw_payload.get("auth_context") if isinstance(raw_payload.get("auth_context"), dict) else {}
        if auth_context:
            existing_auth_context = (
                next_metadata.get("auth_context")
                if isinstance(next_metadata.get("auth_context"), dict)
                else {}
            )
            next_metadata["auth_context"] = {
                **existing_auth_context,
                **{key: value for key, value in auth_context.items() if value is not None},
            }
        next_metadata.setdefault("conversation_save_source", _conversation_save_source(raw_payload))
    return next_metadata


def _conversation_save_source(payload: dict[str, Any]) -> str:
    if payload.get("conversation_save_source"):
        return _text(payload.get("conversation_save_source"))
    if payload.get("provider") == "google":
        return "auth_login"
    if payload.get("save_state") or payload.get("conversation_save_state"):
        return "save_state_endpoint"
    return "chat_message"


def _conversation_is_saved_for_job(job: AnalysisJob) -> bool:
    state = _conversation_metadata_state(job.metadata)
    if state:
        return state == "saved"
    return _conversation_is_saved_metadata(job.session.metadata if job.session_id else {})


def _conversation_is_saved_for_report(report: Report) -> bool:
    state = _conversation_metadata_state(report.metadata)
    if state:
        return state == "saved"
    return _conversation_is_saved_metadata(report.session.metadata if report.session_id else {})


def _conversation_is_saved_metadata(metadata: Any) -> bool:
    state = _conversation_metadata_state(metadata)
    return state not in {"pending", "session_only"}


def _conversation_metadata_state(metadata: Any) -> str:
    return _text(_dict_or_empty(metadata).get("conversation_save_state"))


def _update_session_message_save_state(session: ChatSession, save_state: str) -> int:
    updated = 0
    for message in ChatMessage.objects.filter(session=session):
        message.metadata = _metadata_with_conversation_save_state(message.metadata, save_state)
        message.save(update_fields=["metadata"])
        updated += 1
    return updated


def _update_session_job_save_state(session: ChatSession, save_state: str, *, owner_id: str = "") -> int:
    updated = 0
    for job in AnalysisJob.objects.filter(session=session):
        job.metadata = _metadata_with_conversation_save_state(job.metadata, save_state)
        update_fields = ["metadata", "updated_at"]
        if save_state == "saved" and owner_id and not job.owner_id:
            job.owner_id = owner_id
            update_fields.append("owner_id")
        job.save(update_fields=update_fields)
        updated += 1
    return updated


def _update_session_history_save_state(session_id: str, save_state: str) -> int:
    updated = 0
    for event in HistoryEvent.objects.filter(subject_session_id=session_id):
        event.metadata = _metadata_with_conversation_save_state(event.metadata, save_state)
        event.save(update_fields=["metadata"])
        updated += 1
    return updated


def _bind_chat_session_auth_context(
    *,
    session_id: str,
    owner_id: str,
    auth_context: dict[str, Any],
) -> ChatSession | None:
    session = _get_or_create_session(
        session_id,
        owner_id=owner_id,
        guest_id=_normalize_guest_id(auth_context.get("guest_id")),
    )
    if session is None:
        return None

    metadata = dict(session.metadata or {})
    existing_auth_context = (
        metadata.get("auth_context")
        if isinstance(metadata.get("auth_context"), dict)
        else {}
    )
    existing_auth_context.update(
        {key: value for key, value in auth_context.items() if value is not None}
    )
    metadata["auth_context"] = existing_auth_context
    metadata.setdefault("created_by", "canonical_auth_session")
    session.metadata = metadata
    if owner_id and not session.owner_id:
        session.owner_id = owner_id
    session.save(update_fields=["owner_id", "metadata", "updated_at"])
    return session


def _chat_session_guest_id(session: ChatSession | None) -> str:
    if session is None:
        return ""
    metadata = session.metadata if isinstance(session.metadata, dict) else {}
    auth_context = metadata.get("auth_context") if isinstance(metadata.get("auth_context"), dict) else {}
    return _normalize_guest_id(auth_context.get("guest_id"))


def _create_auth_event(
    *,
    event_type: str,
    subject_id: str,
    metadata: dict[str, Any],
    user: UserAccount | None = None,
    guest: GuestIdentity | None = None,
    auth_session: AuthSession | None = None,
) -> AuthEvent:
    now = timezone.now()
    digest = hashlib.sha1(
        f"{event_type}:{subject_id}:{now.isoformat()}".encode("utf-8")
    ).hexdigest()[:16]
    return AuthEvent.objects.create(
        event_id=f"authevt_{digest}",
        user=user,
        guest=guest,
        auth_session=auth_session,
        event_type=event_type,
        subject_id=subject_id,
        metadata=metadata,
    )


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


def _json_compatible(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return _text(value)


def _owner_id(payload: dict[str, Any]) -> str:
    return _text(payload.get("owner_id") or payload.get("user_id"))


def _payload_guest_id(payload: dict[str, Any]) -> str:
    auth_context = _dict_or_empty(payload.get("auth_context"))
    return _normalize_guest_id(payload.get("guest_id") or auth_context.get("guest_id"))


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


def _queued_analysis_plan_status_counts(analysis_plan: dict[str, Any]) -> dict[str, int]:
    from app.services.agent_node_service import executable_analysis_plan_steps

    return {"queued": len(executable_analysis_plan_steps(analysis_plan))}


def _analysis_plan_first_executable_node(analysis_plan: dict[str, Any]) -> str:
    from app.services.agent_node_service import executable_analysis_plan_steps

    steps = executable_analysis_plan_steps(analysis_plan)
    if not steps:
        return ""
    return _text(steps[0].get("node_code"))


def _analysis_plan_first_node(analysis_plan: dict[str, Any]) -> str:
    steps = analysis_plan.get("steps") or []
    for step in steps:
        if not isinstance(step, dict):
            continue
        node_code = _text(step.get("node_code"))
        if node_code:
            return node_code
    return ""


def _node_execution_summary(node_execution: dict[str, Any]) -> dict[str, Any]:
    if not node_execution:
        return {
            "contract_version": "supervisor_execution.v1",
            "orchestration_mode": "not_recorded",
            "node_codes": [],
        }

    executions = [
        execution
        for execution in node_execution.get("executions", [])
        if isinstance(execution, dict)
    ]
    node_codes = []
    for execution in executions:
        agent_output = execution.get("agent_output") if isinstance(execution.get("agent_output"), dict) else {}
        node_code = _text(agent_output.get("node_code") or execution.get("node_code"))
        if node_code and node_code not in node_codes:
            node_codes.append(node_code)

    return {
        "contract_version": "supervisor_execution.v1",
        "orchestration_mode": "background_session",
        "execution_mode": _text(node_execution.get("execution_mode")) or "mock",
        "job_id": _text(node_execution.get("job_id")) or None,
        "plan_id": _text(node_execution.get("plan_id")) or None,
        "session_id": _text(node_execution.get("session_id")) or None,
        "message_id": _text(node_execution.get("message_id")) or None,
        "status_counts": _dict_or_empty(node_execution.get("status_counts")),
        "completed_node_codes": _list_or_empty(node_execution.get("completed_node_codes")),
        "node_codes": node_codes,
        "node_count": len(executions),
    }


def _analysis_job_status_from_node_execution(node_execution: dict[str, Any]) -> str:
    executions = [
        execution
        for execution in node_execution.get("executions", [])
        if isinstance(execution, dict)
    ]
    if not executions:
        return AnalysisJobStatus.FAILED.value

    counts = _dict_or_empty(node_execution.get("status_counts"))
    failed = int(counts.get("failed") or 0)
    partial = int(counts.get("partial") or 0)
    success = int(counts.get("success") or 0)
    if failed and not success and not partial:
        return AnalysisJobStatus.FAILED.value
    if failed or partial:
        return AnalysisJobStatus.PARTIAL.value
    return AnalysisJobStatus.SUCCESS.value


def _final_node_from_execution(node_execution: dict[str, Any]) -> str:
    completed = _list_or_empty(node_execution.get("completed_node_codes"))
    if completed:
        return _text(completed[-1])
    executions = [
        execution
        for execution in node_execution.get("executions", [])
        if isinstance(execution, dict)
    ]
    if not executions:
        return ""
    last_execution = executions[-1]
    agent_output = last_execution.get("agent_output") if isinstance(last_execution.get("agent_output"), dict) else {}
    return _text(agent_output.get("node_code") or last_execution.get("node_code"))


def _worker_completion_message(final_status: str) -> str:
    if final_status == AnalysisJobStatus.SUCCESS.value:
        return "Agent worker item completed."
    if final_status == AnalysisJobStatus.PARTIAL.value:
        return "Agent worker item completed with partial results."
    return "Agent worker item failed."


def _agent_worker_retry_backoff(work_item: AgentWorkItem) -> timedelta:
    base_seconds = _agent_worker_setting("AGENT_WORKER_RETRY_BACKOFF_SECONDS", 60)
    max_seconds = _agent_worker_setting("AGENT_WORKER_RETRY_BACKOFF_MAX_SECONDS", 900)
    multiplier = 2 ** max(0, work_item.attempt_no - 1)
    return timedelta(seconds=min(base_seconds * multiplier, max_seconds))


def _agent_worker_setting(name: str, default: int) -> int:
    return _positive_int_or_default(getattr(settings, name, default), default=default)


def _worker_lease_is_current(
    work_item: AgentWorkItem,
    *,
    expected_attempt_no: int,
) -> bool:
    return (
        work_item.status == AgentWorkItemStatus.RUNNING.value
        and work_item.attempt_no == expected_attempt_no
    )


def _refresh_agent_work_item_lease(
    work_item_id: str,
    *,
    expected_attempt_no: int,
) -> bool:
    updated = AgentWorkItem.objects.filter(
        work_item_id=_text(work_item_id),
        status=AgentWorkItemStatus.RUNNING.value,
        attempt_no=expected_attempt_no,
    ).update(locked_at=timezone.now())
    return updated == 1


@contextmanager
def _agent_work_item_lease_heartbeat(
    work_item_id: str,
    *,
    expected_attempt_no: int,
) -> Iterator[None]:
    configured_interval = _agent_worker_setting("AGENT_WORKER_HEARTBEAT_SECONDS", 30)
    stale_after = _agent_worker_setting("AGENT_WORKER_STALE_AFTER_SECONDS", 900)
    interval_seconds = min(configured_interval, max(1, stale_after // 3))
    stop_event = Event()

    def refresh_until_stopped() -> None:
        close_old_connections()
        try:
            while not stop_event.wait(interval_seconds):
                try:
                    refreshed = _refresh_agent_work_item_lease(
                        work_item_id,
                        expected_attempt_no=expected_attempt_no,
                    )
                except (DatabaseError, OSError):
                    close_old_connections()
                    continue
                if not refreshed:
                    break
        finally:
            close_old_connections()

    heartbeat = Thread(
        target=refresh_until_stopped,
        name=f"agent-work-heartbeat-{work_item_id}",
        daemon=True,
    )
    heartbeat.start()
    try:
        yield
    finally:
        stop_event.set()
        heartbeat.join(timeout=5)


def _agent_work_item_skipped(
    reason: str,
    *,
    work_item_id: str = "",
    current_status: str = "",
    next_run_at: Any = None,
) -> dict[str, Any]:
    result = {
        "backend": "postgresql",
        "status": "skipped",
        "claimed": False,
        "reason": reason,
    }
    if work_item_id:
        result["work_item_id"] = work_item_id
    if current_status:
        result["current_status"] = current_status
    if next_run_at:
        result["next_run_at"] = next_run_at
    return result


def _upsert_initial_job_event(
    job: AnalysisJob,
    *,
    progress: dict[str, Any],
    source: str = "canonical_chat_message",
    overwrite_existing: bool = True,
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
            metadata={"source": source},
        )
        return

    if not overwrite_existing:
        return

    first_event.status = status
    first_event.active_node = active_node
    first_event.message = message
    first_event.metadata = {"source": source}
    first_event.save(update_fields=["status", "active_node", "message", "metadata"])


def _append_analysis_job_event(
    job: AnalysisJob,
    *,
    status: str,
    active_node: str = "",
    message: str = "",
    source: str,
    metadata: dict[str, Any] | None = None,
) -> AnalysisJobEvent:
    event_metadata = dict(metadata or {})
    event_metadata["source"] = source
    return AnalysisJobEvent.objects.create(
        job=job,
        status=_analysis_job_status(status),
        active_node=_text(active_node),
        message=_text(message),
        metadata=event_metadata,
    )


def _requeue_stale_agent_work_items(
    *,
    now,
    stale_after_seconds: int | None = None,
) -> list[dict[str, Any]]:
    stale_after = _positive_int_or_default(
        stale_after_seconds,
        default=_agent_worker_setting("AGENT_WORKER_STALE_AFTER_SECONDS", 900),
    )
    cutoff = now - timedelta(seconds=stale_after)
    requeued: list[dict[str, Any]] = []

    with transaction.atomic():
        stale_items = list(
            AgentWorkItem.objects.select_for_update()
            .select_related("job", "job__session")
            .filter(
                status=AgentWorkItemStatus.RUNNING.value,
                locked_at__isnull=False,
                locked_at__lte=cutoff,
            )
            .order_by("locked_at")[:50]
        )
        for work_item in stale_items:
            job = work_item.job
            can_retry = work_item.attempt_no < work_item.max_attempts
            work_item.status = (
                AgentWorkItemStatus.RETRYING.value
                if can_retry
                else AgentWorkItemStatus.FAILED.value
            )
            work_item.locked_at = None
            work_item.completed_at = None if can_retry else now
            work_item.next_run_at = now if can_retry else None
            work_item.error_code = "worker_lock_timeout"
            work_item.result = {
                "error_code": "worker_lock_timeout",
                "message": f"Agent worker lock exceeded {stale_after} seconds.",
                "retryable": can_retry,
                "stale_after_seconds": stale_after,
            }
            work_item.save(
                update_fields=[
                    "status",
                    "locked_at",
                    "completed_at",
                    "next_run_at",
                    "error_code",
                    "result",
                    "updated_at",
                ]
            )
            job_status = AnalysisJobStatus.RUNNING.value if can_retry else AnalysisJobStatus.FAILED.value
            message = (
                "Agent worker lock expired; item was requeued."
                if can_retry
                else "Agent worker lock expired; item failed."
            )
            _update_job_worker_state(
                job,
                status=job_status,
                active_node=job.active_node,
                progress_message=message,
                work_item=work_item,
            )
            _append_analysis_job_event(
                job,
                status=job_status,
                active_node=job.active_node,
                message=message,
                source="agent_worker_queue",
                metadata={
                    "work_item_id": work_item.work_item_id,
                    "attempt_no": work_item.attempt_no,
                    "error_code": "worker_lock_timeout",
                    "retryable": can_retry,
                    "stale_after_seconds": stale_after,
                },
            )
            requeued.append(
                {
                    "work_item_id": work_item.work_item_id,
                    "job_id": job.job_id,
                    "status": work_item.status,
                    "retryable": can_retry,
                    "attempt_no": work_item.attempt_no,
                    "max_attempts": work_item.max_attempts,
                }
            )

    for item in requeued:
        job = AnalysisJob.objects.select_related("session").filter(job_id=item["job_id"]).first()
        if job is not None:
            write_analysis_job_progress(job)
            write_chat_session_state(job.session, latest_job=job)
    return requeued


def _claim_agent_work_item(work_item_id: str) -> dict[str, Any]:
    with transaction.atomic():
        work_item = (
            AgentWorkItem.objects.select_for_update()
            .select_related("job", "job__session")
            .filter(work_item_id=work_item_id)
            .first()
        )
        if work_item is None:
            return _agent_work_item_skipped("work_item_not_found", work_item_id=work_item_id)
        if work_item.status not in {
            AgentWorkItemStatus.QUEUED.value,
            AgentWorkItemStatus.RETRYING.value,
        }:
            return _agent_work_item_skipped(
                "work_item_not_queued",
                work_item_id=work_item.work_item_id,
                current_status=work_item.status,
            )

        now = timezone.now()
        if work_item.next_run_at and work_item.next_run_at > now:
            return _agent_work_item_skipped(
                "work_item_not_ready",
                work_item_id=work_item.work_item_id,
                current_status=work_item.status,
                next_run_at=work_item.next_run_at,
            )

        work_item.status = AgentWorkItemStatus.RUNNING.value
        work_item.attempt_no += 1
        work_item.locked_at = now
        work_item.started_at = work_item.started_at or now
        work_item.completed_at = None
        work_item.next_run_at = None
        work_item.error_code = ""
        work_item.save(
            update_fields=[
                "status",
                "attempt_no",
                "locked_at",
                "started_at",
                "completed_at",
                "next_run_at",
                "error_code",
                "updated_at",
            ]
        )

        job = work_item.job
        active_node = _analysis_plan_first_executable_node(
            _dict_or_empty(work_item.payload.get("analysis_plan"))
        )
        _update_job_worker_state(
            job,
            status=AnalysisJobStatus.RUNNING.value,
            active_node=active_node or job.active_node,
            progress_message="Agent worker item is running.",
            work_item=work_item,
        )
        _append_analysis_job_event(
            job,
            status=AnalysisJobStatus.RUNNING.value,
            active_node=active_node or job.active_node,
            message="Agent worker item is running.",
            source="agent_worker_queue",
            metadata={"work_item_id": work_item.work_item_id, "attempt_no": work_item.attempt_no},
        )

    progress_cache = write_analysis_job_progress(job)
    write_chat_session_state(job.session, latest_job=job)
    return {
        "backend": "postgresql",
        "status": AgentWorkItemStatus.RUNNING.value,
        "claimed": True,
        "work_item_id": work_item.work_item_id,
        "job_id": job.job_id,
        "attempt_no": work_item.attempt_no,
        "progress_state": _work_item_progress_state(work_item, job_status=job.status),
        "progress_cache": progress_cache,
    }


def _execute_agent_work_item_plan(work_item: AgentWorkItem) -> dict[str, Any]:
    from app.services.agent_node_service import execute_agent_plan

    queue_payload = _dict_or_empty(work_item.payload)
    analysis_plan = _dict_or_empty(queue_payload.get("analysis_plan"))
    job_payload = _dict_or_empty(queue_payload.get("job_payload"))
    execution_payload = _dict_or_empty(queue_payload.get("execution_payload"))
    execution_payload.setdefault("job_id", work_item.job.job_id)
    execution_payload.setdefault("session_id", work_item.job.session.session_id)
    execution_payload.setdefault("message_id", _text(job_payload.get("message_id")))
    if "attachments" in execution_payload or "attachment_ids" in execution_payload:
        from chatbot.file_scan_service import apply_attachment_scan_gate

        execution_payload = apply_attachment_scan_gate(execution_payload)
        if _list_or_empty(execution_payload.get("blocked_attachments")):
            raise AttachmentScanGateError
        from app.services.attachment_mock_service import (
            resolve_attachment_references,
        )

        execution_payload = resolve_attachment_references(execution_payload)
    return execute_agent_plan(analysis_plan, execution_payload)


def _completed_job_payload_for_work_item(
    work_item: AgentWorkItem,
    *,
    node_execution: dict[str, Any],
    final_status: str,
) -> dict[str, Any]:
    queue_payload = _dict_or_empty(work_item.payload)
    job_payload = _dict_or_empty(queue_payload.get("job_payload"))
    analysis_plan = _dict_or_empty(queue_payload.get("analysis_plan") or job_payload.get("analysis_plan"))
    return {
        **job_payload,
        "job_id": work_item.job.job_id,
        "session_id": work_item.job.session.session_id,
        "message_id": _text(job_payload.get("message_id")),
        "status": final_status,
        "active_node": _final_node_from_execution(node_execution),
        "progress_message": _worker_completion_message(final_status),
        "analysis_plan": analysis_plan,
        "analysis_plan_id": _text(job_payload.get("analysis_plan_id") or analysis_plan.get("plan_id")),
        "node_execution": node_execution,
        "status_counts": _dict_or_empty(node_execution.get("status_counts")),
        "work_item_id": work_item.work_item_id,
    }


def _complete_agent_work_item(
    work_item_id: str,
    *,
    final_status: str,
    node_execution: dict[str, Any],
    persistence: dict[str, Any],
    expected_attempt_no: int,
) -> dict[str, Any]:
    with transaction.atomic():
        work_item = (
            AgentWorkItem.objects.select_for_update()
            .select_related("job", "job__session")
            .get(work_item_id=work_item_id)
        )
        if not _worker_lease_is_current(
            work_item,
            expected_attempt_no=expected_attempt_no,
        ):
            return _agent_work_item_skipped(
                "stale_worker_lease",
                work_item_id=work_item_id,
                current_status=work_item.status,
            )
        job = work_item.job
        ai_session = AiSession.objects.filter(ai_session_id=persistence.get("ai_session_id")).first()
        work_item.ai_session = ai_session
        work_item.status = (
            AgentWorkItemStatus.FAILED.value
            if final_status == AnalysisJobStatus.FAILED.value
            else AgentWorkItemStatus.SUCCESS.value
        )
        work_item.completed_at = timezone.now()
        work_item.locked_at = None
        work_item.next_run_at = None
        work_item.error_code = ""
        work_item.result = {
            "final_status": final_status,
            "node_execution": _node_execution_summary(node_execution),
            "persistence": {
                "agent_results_saved": persistence.get("agent_results_saved", 0),
                "agent_invocations_saved": persistence.get("agent_invocations_saved", 0),
                "retrieval_events_saved": persistence.get("retrieval_events_saved", 0),
            },
        }
        work_item.save(
            update_fields=[
                "ai_session",
                "status",
                "completed_at",
                "locked_at",
                "next_run_at",
                "error_code",
                "result",
                "updated_at",
            ]
        )
        _update_job_worker_state(
            job,
            status=final_status,
            active_node=_final_node_from_execution(node_execution),
            progress_message=_worker_completion_message(final_status),
            work_item=work_item,
        )
        _append_analysis_job_event(
            job,
            status=final_status,
            active_node=job.active_node,
            message=_worker_completion_message(final_status),
            source="agent_worker_queue",
            metadata={"work_item_id": work_item.work_item_id, "attempt_no": work_item.attempt_no},
        )

    progress_cache = write_analysis_job_progress(job)
    session_cache = write_chat_session_state(job.session, latest_job=job)
    return {
        "backend": "postgresql",
        "status": work_item.status,
        "job_status": final_status,
        "work_item_id": work_item.work_item_id,
        "job_id": job.job_id,
        "attempt_no": work_item.attempt_no,
        "progress_state": _work_item_progress_state(work_item, job_status=final_status),
        "progress_cache": progress_cache,
        "session_cache": session_cache,
        "persistence": persistence,
    }


def _fail_agent_work_item(
    work_item_id: str,
    exc: Exception,
    *,
    expected_attempt_no: int,
) -> dict[str, Any]:
    error_code = exc.__class__.__name__
    with transaction.atomic():
        work_item = (
            AgentWorkItem.objects.select_for_update()
            .select_related("job", "job__session")
            .filter(work_item_id=work_item_id)
            .first()
        )
        if work_item is None:
            return _agent_work_item_skipped("work_item_not_found", work_item_id=work_item_id)
        if not _worker_lease_is_current(
            work_item,
            expected_attempt_no=expected_attempt_no,
        ):
            return _agent_work_item_skipped(
                "stale_worker_lease",
                work_item_id=work_item_id,
                current_status=work_item.status,
            )

        job = work_item.job
        can_retry = work_item.attempt_no < work_item.max_attempts
        work_item.status = (
            AgentWorkItemStatus.RETRYING.value
            if can_retry
            else AgentWorkItemStatus.FAILED.value
        )
        work_item.locked_at = None
        work_item.completed_at = None if can_retry else timezone.now()
        retry_after = _agent_worker_retry_backoff(work_item) if can_retry else None
        work_item.next_run_at = timezone.now() + retry_after if retry_after else None
        work_item.error_code = error_code
        work_item.result = {
            "error_code": error_code,
            "message": "Agent worker execution failed.",
            "retryable": can_retry,
            "retry_after_seconds": int(retry_after.total_seconds()) if retry_after else 0,
        }
        work_item.save(
            update_fields=[
                "status",
                "locked_at",
                "completed_at",
                "next_run_at",
                "error_code",
                "result",
                "updated_at",
            ]
        )
        job_status = AnalysisJobStatus.RUNNING.value if can_retry else AnalysisJobStatus.FAILED.value
        _update_job_worker_state(
            job,
            status=job_status,
            active_node=job.active_node,
            progress_message="Agent worker item will retry." if can_retry else "Agent worker item failed.",
            work_item=work_item,
        )
        _append_analysis_job_event(
            job,
            status=job_status,
            active_node=job.active_node,
            message="Agent worker item will retry." if can_retry else "Agent worker item failed.",
            source="agent_worker_queue",
            metadata={
                "work_item_id": work_item.work_item_id,
                "attempt_no": work_item.attempt_no,
                "error_code": error_code,
                "retryable": can_retry,
            },
        )

    progress_cache = write_analysis_job_progress(job)
    write_chat_session_state(job.session, latest_job=job)
    return {
        "backend": "postgresql",
        "status": work_item.status,
        "job_status": job.status,
        "work_item_id": work_item.work_item_id,
        "job_id": job.job_id,
        "attempt_no": work_item.attempt_no,
        "error_code": error_code,
        "retryable": can_retry,
        "progress_state": _work_item_progress_state(work_item, job_status=job.status),
        "progress_cache": progress_cache,
    }


def _update_job_worker_state(
    job: AnalysisJob,
    *,
    status: str,
    active_node: str,
    progress_message: str,
    work_item: AgentWorkItem,
) -> None:
    metadata = _dict_or_empty(job.metadata)
    metadata["work_queue"] = {
        **_dict_or_empty(metadata.get("work_queue")),
        "contract_version": "agent_worker_queue.v1",
        "work_item_id": work_item.work_item_id,
        "status": work_item.status,
        "progress_state": _work_item_progress_state(work_item, job_status=status),
        "attempt_no": work_item.attempt_no,
        "max_attempts": work_item.max_attempts,
        "next_run_at": work_item.next_run_at.isoformat() if work_item.next_run_at else None,
    }
    job.status = _analysis_job_status(status)
    job.active_node = _text(active_node)
    job.progress_message = _text(progress_message)
    job.metadata = metadata
    job.save(update_fields=["status", "active_node", "progress_message", "metadata", "updated_at"])


def _work_item_progress_state(
    work_item: AgentWorkItem,
    *,
    job_status: str,
) -> dict[str, Any]:
    state = AgentWorkItemStatus.RETRYING.value if work_item.status == AgentWorkItemStatus.RETRYING.value else work_item.status
    if state == AgentWorkItemStatus.RETRYING.value:
        state = "retry_waiting"
    retry_after_seconds = 0
    if work_item.next_run_at:
        retry_after_seconds = max(0, int((work_item.next_run_at - timezone.now()).total_seconds()))
    return {
        "contract_version": "agent_worker_progress.v1",
        "state": state,
        "work_item_status": work_item.status,
        "job_status": _analysis_job_status(job_status),
        "attempt_no": work_item.attempt_no,
        "max_attempts": work_item.max_attempts,
        "retryable": work_item.status == AgentWorkItemStatus.RETRYING.value,
        "retry_after_seconds": retry_after_seconds,
        "next_run_at": work_item.next_run_at.isoformat() if work_item.next_run_at else None,
    }


def _persist_agent_results(
    job: AnalysisJob,
    node_execution: dict[str, Any],
) -> list[AgentResult]:
    executions = node_execution.get("executions") or []
    agent_results = []
    for index, execution in enumerate(executions, start=1):
        if not isinstance(execution, dict):
            continue

        agent_output = execution.get("agent_output") or {}
        if not isinstance(agent_output, dict):
            continue

        node_code = _text(agent_output.get("node_code") or execution.get("node_code"))
        if not node_code:
            continue

        agent_result, _created = AgentResult.objects.update_or_create(
            result_id=_agent_result_id(job.job_id, node_code, index),
            defaults={
                "job": job,
                "node_code": node_code,
                "node_name": _text(agent_output.get("node_name")),
                "status": _agent_result_status(agent_output.get("status")),
                "summary": _text(agent_output.get("summary")),
                "structured_result": _dict_or_empty(agent_output.get("structured_result")),
                "evidence": _list_or_empty(agent_output.get("evidence")),
                "next_actions": _list_or_empty(agent_output.get("next_actions")),
                "limitations": _list_or_empty(agent_output.get("limitations")),
                "raw_output": _agent_result_raw_output(execution, agent_output),
            },
        )
        agent_results.append(agent_result)
    return agent_results


def _upsert_ai_session(
    job: AnalysisJob,
    *,
    payload: dict[str, Any],
    job_payload: dict[str, Any],
) -> AiSession:
    subject = _ai_subject(payload, job_payload)
    user = _get_or_create_user_account(subject["user_id"])
    guest = _get_or_create_guest_identity(subject["guest_id"])
    quota_key = subject["quota_key"]

    ai_session, _created = AiSession.objects.update_or_create(
        ai_session_id=_ai_session_id(job.job_id),
        defaults={
            "session": job.session,
            "user": user,
            "guest": guest,
            "owner_id": subject["user_id"] or job.owner_id,
            "status": "active",
            "routing_intent": job.routing_intent,
            "quota_key": quota_key,
            "metadata": {
                "source": "canonical_analysis_job",
                "job_id": job.job_id,
                "subject_id": subject["subject_id"],
                "subject_type": subject["subject_type"],
                "auth_session_id": subject["auth_session_id"],
                "chat_session_id": job.session.session_id,
                "analysis_plan_id": job.analysis_plan_id,
            },
        },
    )
    return ai_session


def _persist_agent_invocations(
    job: AnalysisJob,
    *,
    ai_session: AiSession,
    node_execution: dict[str, Any],
    agent_results: list[AgentResult],
) -> list[AgentInvocation]:
    executions = node_execution.get("executions") or []
    results_by_id = {result.result_id: result for result in agent_results}
    invocations = []

    for index, execution in enumerate(executions, start=1):
        if not isinstance(execution, dict):
            continue

        agent_output = execution.get("agent_output") or {}
        if not isinstance(agent_output, dict):
            continue

        node_code = _text(agent_output.get("node_code") or execution.get("node_code"))
        if not node_code:
            continue

        result_id = _agent_result_id(job.job_id, node_code, index)
        agent_result = results_by_id.get(result_id)
        agent_node = _upsert_agent_node_definition(execution, agent_output)
        status = _agent_invocation_status(
            agent_output.get("status"),
            execution.get("execution_status") or agent_output.get("execution_status"),
        )
        now = timezone.now()

        invocation, _created = AgentInvocation.objects.update_or_create(
            invocation_id=_agent_invocation_id(job.job_id, node_code, index),
            defaults={
                "ai_session": ai_session,
                "job": job,
                "agent_node": agent_node,
                "node_code": node_code,
                "status": status,
                "attempt_no": _positive_int_or_default(execution.get("attempt_no"), default=1),
                "execution_mode": _text(execution.get("execution_mode")),
                "started_at": now,
                "completed_at": None if status == AgentInvocationStatus.RUNNING.value else now,
                "latency_ms": _positive_int_or_none(execution.get("latency_ms")),
                "token_count": _positive_int_or_none(execution.get("token_count")),
                "evidence_count": len(_list_or_empty(agent_output.get("evidence"))),
                "limitation_count": len(_list_or_empty(agent_output.get("limitations"))),
                "retryable": status in {
                    AgentInvocationStatus.FAILED.value,
                    AgentInvocationStatus.RETRYING.value,
                },
                "error_code": _agent_invocation_error_code(agent_output, status),
                "quota_key": ai_session.quota_key,
                "metadata": _agent_invocation_metadata(
                    execution=execution,
                    agent_output=agent_output,
                    agent_result=agent_result,
                    final_status=status,
                ),
            },
        )
        _persist_retrieval_event_for_invocation(
            job=job,
            invocation=invocation,
            execution=execution,
            agent_output=agent_output,
            agent_result=agent_result,
        )
        invocations.append(invocation)

    return invocations


def _upsert_agent_node_definition(
    execution: dict[str, Any],
    agent_output: dict[str, Any],
) -> AgentNodeDefinition | None:
    node_code = _text(agent_output.get("node_code") or execution.get("node_code"))
    if not node_code:
        return None

    node = execution.get("node") if isinstance(execution.get("node"), dict) else {}
    adapter_contract = node.get("adapter_contract") if isinstance(node.get("adapter_contract"), dict) else {}
    agent_node, _created = AgentNodeDefinition.objects.update_or_create(
        node_code=node_code,
        defaults={
            "node_name": _text(agent_output.get("node_name") or node.get("node_name") or node_code),
            "node_type": _text(agent_output.get("node_type") or node.get("node_type")) or "agent",
            "owner": _text(agent_output.get("owner") or node.get("owner")),
            "status": _text(node.get("status")) or "mock_ready",
            "contract_version": _text(adapter_contract.get("contract_version")) or "agent_adapter.v1",
            "adapter_key": _text(adapter_contract.get("function_name")),
            "metadata": {
                "source": "mock_node_registry",
                "order": node.get("order"),
                "description": node.get("description"),
                "required_inputs": node.get("required_inputs") or [],
                "produces": node.get("produces") or [],
                "handoff_to": node.get("handoff_to") or [],
            },
        },
    )
    return agent_node


def _agent_result_id(job_id: str, node_code: str, index: int) -> str:
    readable_id = f"res_{job_id}_{index}_{node_code}"
    if len(readable_id) <= 64:
        return readable_id
    digest = hashlib.sha1(f"{job_id}:{index}:{node_code}".encode("utf-8")).hexdigest()[:16]
    return f"res_{digest}_{index}"


def _ai_session_id(job_id: str) -> str:
    readable_id = f"ais_{job_id}"
    if len(readable_id) <= 64:
        return readable_id
    digest = hashlib.sha1(job_id.encode("utf-8")).hexdigest()[:20]
    return f"ais_{digest}"


def _agent_invocation_id(job_id: str, node_code: str, index: int) -> str:
    readable_id = f"ainv_{job_id}_{index}_{node_code}"
    if len(readable_id) <= 64:
        return readable_id
    digest = hashlib.sha1(f"{job_id}:{index}:{node_code}".encode("utf-8")).hexdigest()[:16]
    return f"ainv_{digest}_{index}"


def _agent_work_item_id(job_id: str) -> str:
    readable_id = f"awork_{job_id}"
    if len(readable_id) <= 64:
        return readable_id
    digest = hashlib.sha1(job_id.encode("utf-8")).hexdigest()[:20]
    return f"awork_{digest}"


def _usage_quota_id(subject_id: str, scope: str) -> str:
    readable_id = f"quota_{subject_id.replace(':', '_')}_{scope}"
    if len(readable_id) <= 64:
        return readable_id
    digest = hashlib.sha1(f"{subject_id}:{scope}".encode("utf-8")).hexdigest()[:20]
    return f"quota_{digest}"


def _usage_event_id(subject_id: str, scope: str) -> str:
    now = timezone.now().isoformat()
    digest = hashlib.sha1(f"{subject_id}:{scope}:{now}".encode("utf-8")).hexdigest()[:20]
    return f"use_{digest}"


def _usage_policy_for_subject(subject: dict[str, str], *, scope: str) -> dict[str, Any]:
    plan_code = _usage_plan_code(subject)
    code_item = _ensure_usage_policy_code_item(plan_code)
    limits = _dict_or_empty(code_item.metadata.get("limits"))
    limit_count = _positive_int_or_none(limits.get(scope))
    if limit_count is None:
        limit_count = _default_usage_limit(plan_code, scope)
    subscription = _active_subscription_for_subject(subject)
    return {
        "plan_code": plan_code,
        "subscription_id": subscription.subscription_id if subscription else None,
        "policy_code_item": f"{USAGE_POLICY_GROUP_CODE}:{code_item.code}",
        "policy_status": _text(code_item.metadata.get("policy_status")) or "seeded_default",
        "limit_count": limit_count,
    }


def _usage_plan_code(subject: dict[str, str]) -> str:
    subject_type = subject["subject_type"]
    if subject_type == "anonymous":
        return "anonymous"
    if subject_type == "guest":
        return "guest"

    subscription = _active_subscription_for_subject(subject)
    if subscription:
        return subscription.plan_code
    user = _get_or_create_user_account(subject["user_id"])
    if user is not None:
        _ensure_default_free_subscription(user)
    return "free"


def _active_subscription_for_subject(subject: dict[str, str]) -> Subscription | None:
    user_id = subject.get("user_id")
    if not user_id:
        return None
    user = _get_or_create_user_account(user_id)
    if user is None:
        return None
    return (
        Subscription.objects.filter(
            user=user,
            status__in=[
                SubscriptionStatus.ACTIVE,
                SubscriptionStatus.TRIAL,
                SubscriptionStatus.FREE,
            ],
        )
        .order_by("-updated_at")
        .first()
    )


def _ensure_default_free_subscription(user: UserAccount) -> Subscription:
    subscription_id = f"sub_free_{user.user_id}"
    subscription, _created = Subscription.objects.get_or_create(
        subscription_id=subscription_id,
        defaults={
            "user": user,
            "plan_code": "free",
            "status": SubscriptionStatus.FREE,
            "metadata": {
                "source": "canonical_usage_policy",
                "policy_status": "seeded_default",
            },
        },
    )
    return subscription


def _ensure_usage_policy_code_item(plan_code: str) -> CodeItem:
    group, _created = CodeGroup.objects.get_or_create(
        group_code=USAGE_POLICY_GROUP_CODE,
        defaults={
            "name": "Usage quota policy",
            "description": "Subject plan to API usage quota defaults.",
            "metadata": {"source": "canonical_usage_policy"},
        },
    )
    defaults = USAGE_POLICY_LIMITS.get(plan_code, USAGE_POLICY_LIMITS["anonymous"])
    code_item, created = CodeItem.objects.get_or_create(
        group=group,
        code=plan_code,
        defaults={
            "label": f"{plan_code} usage policy",
            "description": "Seeded API usage policy. 운영 정책 확정 전 기본값입니다.",
            "is_active": True,
            "metadata": {
                "source": "canonical_usage_policy",
                "policy_status": "seeded_default",
                "limits": defaults,
            },
        },
    )
    if created:
        return code_item
    metadata = dict(code_item.metadata or {})
    metadata.setdefault("source", "canonical_usage_policy")
    metadata.setdefault("policy_status", "seeded_default")
    metadata.setdefault("limits", defaults)
    if metadata != code_item.metadata:
        code_item.metadata = metadata
        code_item.save(update_fields=["metadata", "updated_at"])
    return code_item


def _default_usage_limit(subject_type: str, scope: str) -> int:
    policy = USAGE_POLICY_LIMITS.get(subject_type, USAGE_POLICY_LIMITS["anonymous"])
    return policy.get(scope, 10)


def _display_result_id(job_id: str) -> str:
    readable_id = f"disp_{job_id}"
    if len(readable_id) <= 64:
        return readable_id
    digest = hashlib.sha1(job_id.encode("utf-8")).hexdigest()[:20]
    return f"disp_{digest}"


def _display_result_for_job(job: AnalysisJob | None) -> AnalysisDisplayResult | None:
    if job is None:
        return None
    try:
        return job.display_result
    except AnalysisDisplayResult.DoesNotExist:
        return None


def _upsert_history_event_payload(event_payload: dict[str, Any]) -> HistoryEvent:
    actor = _dict_or_empty(event_payload.get("actor"))
    subject = _dict_or_empty(event_payload.get("subject"))
    source = _dict_or_empty(event_payload.get("source"))
    occurred_at = _datetime_or_none(event_payload.get("occurred_at")) or timezone.now()

    event, _created = HistoryEvent.objects.update_or_create(
        event_id=_text(event_payload.get("event_id")),
        defaults={
            "event_type": _text(event_payload.get("event_type")),
            "event_version": _text(event_payload.get("event_version")) or "history_event.v1",
            "occurred_at": occurred_at,
            "actor_user_id": _text(actor.get("user_id")),
            "actor_guest_id": _text(actor.get("guest_id")),
            "actor_auth_session_id": _text(actor.get("auth_session_id")),
            "actor_auth_state": _text(actor.get("auth_state")),
            "subject_session_id": _text(subject.get("session_id")),
            "subject_message_id": _text(subject.get("message_id")),
            "subject_job_id": _text(subject.get("job_id")),
            "subject_report_id": _text(subject.get("report_id")),
            "source_surface": _text(source.get("surface")),
            "source_api_path": _text(source.get("api_path")),
            "source_execution_mode": _text(source.get("execution_mode")),
            "source_node_code": _text(source.get("node_code")),
            "status": _text(event_payload.get("status")) or "success",
            "summary": _text(event_payload.get("summary")),
            "actor": actor,
            "subject": subject,
            "source": source,
            "metadata": _history_metadata_snapshot(event_payload.get("metadata")),
            "privacy": _dict_or_empty(event_payload.get("privacy")),
        },
    )
    return event


def _history_metadata_snapshot(metadata: Any) -> dict[str, Any]:
    raw_metadata = _dict_or_empty(metadata)
    sanitized: dict[str, Any] = {}
    dropped_keys = []

    for key, value in raw_metadata.items():
        normalized_key = str(key)
        if (
            normalized_key not in HISTORY_METADATA_ALLOWED_KEYS
            or normalized_key.lower() in SENSITIVE_METADATA_KEYS
        ):
            dropped_keys.append(normalized_key)
            continue
        sanitized[normalized_key] = _strip_sensitive_history_metadata(value)

    if dropped_keys:
        sanitized["metadata_policy"] = {
            "policy_version": HISTORY_POLICY_VERSION,
            "dropped_keys": sorted(dropped_keys),
        }
    return sanitized


def _strip_sensitive_history_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _strip_sensitive_history_metadata(item)
            for key, item in value.items()
            if str(key).lower() not in SENSITIVE_METADATA_KEYS
        }
    if isinstance(value, list):
        return [_strip_sensitive_history_metadata(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _history_retention_days(subject_type: str | None) -> int:
    return HISTORY_RETENTION_DAYS.get(_history_subject_type(subject_type), HISTORY_RETENTION_DAYS["anonymous"])


def _history_subject_type(subject_type: str | None) -> str:
    normalized = _text(subject_type)
    if normalized == "authenticated":
        return "user"
    if normalized in HISTORY_RETENTION_DAYS:
        return normalized
    return "anonymous"


def _agent_result_status(status: Any) -> str:
    status_text = _text(status)
    if status_text in {choice.value for choice in AgentResultStatus}:
        return status_text
    if status_text in {"pending", "running", "blocked"}:
        return AgentResultStatus.PARTIAL
    return AgentResultStatus.SUCCESS


def _agent_invocation_status(status: Any, execution_status: Any) -> str:
    status_text = _text(status) or _text(execution_status)
    if status_text in {choice.value for choice in AgentInvocationStatus}:
        return status_text
    if status_text == "pending":
        return AgentInvocationStatus.QUEUED
    if status_text == "running":
        return AgentInvocationStatus.RUNNING
    if status_text in {"blocked", "skipped"}:
        return AgentInvocationStatus.PARTIAL
    if status_text in {"error", "failed"}:
        return AgentInvocationStatus.FAILED
    return AgentInvocationStatus.SUCCESS


def _agent_invocation_error_code(agent_output: dict[str, Any], status: str) -> str:
    if status != AgentInvocationStatus.FAILED.value:
        return ""
    return _text(agent_output.get("error_code")) or "mock_agent_failed"


def _agent_invocation_metadata(
    *,
    execution: dict[str, Any],
    agent_output: dict[str, Any],
    agent_result: AgentResult | None,
    final_status: str,
) -> dict[str, Any]:
    plan_step = execution.get("plan_step") if isinstance(execution.get("plan_step"), dict) else {}
    return {
        "source": "canonical_analysis_job",
        "orchestration_policy": "sync_worker_progress.v1",
        "queue_runtime": "inline_sync",
        "execution_id": execution.get("execution_id"),
        "agent_result_id": agent_result.result_id if agent_result else None,
        "plan_step": plan_step,
        "adapter_context": execution.get("adapter_context") or {},
        "execution_status": execution.get("execution_status") or agent_output.get("execution_status"),
        "status_timeline": _agent_invocation_status_timeline(final_status),
        "created_at": agent_output.get("created_at") or execution.get("created_at"),
    }


def _persist_retrieval_event_for_invocation(
    *,
    job: AnalysisJob,
    invocation: AgentInvocation,
    execution: dict[str, Any],
    agent_output: dict[str, Any],
    agent_result: AgentResult | None,
) -> RetrievalEvent | None:
    if invocation.node_code != "law_ground_search":
        return None

    structured_result = _dict_or_empty(agent_output.get("structured_result"))
    retrieval = _dict_or_empty(structured_result.get("retrieval"))
    matched_laws = _list_or_empty(structured_result.get("matched_laws"))
    source_refs = [
        _text(item.get("source_reference"))
        for item in matched_laws
        if isinstance(item, dict) and _text(item.get("source_reference"))
    ]
    if not source_refs:
        source_refs = [
            _text(item.get("source_reference"))
            for item in _list_or_empty(agent_output.get("evidence"))
            if isinstance(item, dict) and _text(item.get("source_reference"))
        ]
    query_text = _text(retrieval.get("query")) or _law_ground_query_from_execution(execution)
    event, _created = RetrievalEvent.objects.update_or_create(
        retrieval_event_id=_retrieval_event_id(job.job_id, invocation.invocation_id),
        defaults={
            "job": job,
            "invocation": invocation,
            "query_text": query_text,
            "query_type": _text(retrieval.get("backend")) or "mock_or_semantic",
            "top_k": _positive_int_or_default(retrieval.get("top_k"), default=len(source_refs)),
            "result_count": _positive_int_or_default(retrieval.get("result_count"), default=len(source_refs)),
            "source_refs": source_refs,
            "filters": {"node_code": invocation.node_code, "source_type": "law"},
            "latency_ms": _positive_int_or_none(retrieval.get("latency_ms")),
            "metadata": {
                "source": "agent_invocation_persistence",
                "retrieval_contract_version": retrieval.get("contract_version"),
                "retrieval_status": retrieval.get("status"),
                "retrieval_backend": retrieval.get("backend"),
                "retrieval_quality": structured_result.get("retrieval_quality"),
                "fallback_from": retrieval.get("fallback_from"),
                "attempted_backends": retrieval.get("attempted_backends") or [],
                "embedding": retrieval.get("embedding") or {},
                "sql_tables": retrieval.get("sql_tables") or [],
                "agent_result_id": agent_result.result_id if agent_result else None,
                "execution_id": execution.get("execution_id"),
            },
        },
    )
    return event


def _agent_invocation_status_timeline(final_status: str) -> list[dict[str, str]]:
    timeline = [
        {"status": AgentInvocationStatus.QUEUED.value, "stage": "scheduled"},
        {"status": AgentInvocationStatus.RUNNING.value, "stage": "worker_started"},
    ]
    if final_status == AgentInvocationStatus.QUEUED.value:
        return timeline[:1]
    if final_status == AgentInvocationStatus.RUNNING.value:
        return timeline
    timeline.append({"status": final_status, "stage": "worker_finished"})
    if final_status == AgentInvocationStatus.FAILED.value:
        timeline.append({"status": AgentInvocationStatus.RETRYING.value, "stage": "retryable_review"})
    return timeline


def _law_ground_query_from_execution(execution: dict[str, Any]) -> str:
    agent_input = _dict_or_empty(execution.get("agent_input"))
    context = _dict_or_empty(agent_input.get("context"))
    supervisor = _dict_or_empty(context.get("supervisor_handoff"))
    for package in _list_or_empty(supervisor.get("agent_input_packages")):
        if not isinstance(package, dict) or package.get("node_code") != "law_ground_search":
            continue
        payload = _dict_or_empty(package.get("payload"))
        query = payload.get("search_query") or payload.get("violation_text")
        if query:
            return _text(query)
    return _text(agent_input.get("user_text"))


def _retrieval_event_id(job_id: str, invocation_id: str) -> str:
    readable_id = f"retr_{job_id}_{invocation_id}"
    if len(readable_id) <= 64:
        return readable_id
    digest = hashlib.sha1(f"{job_id}:{invocation_id}".encode("utf-8")).hexdigest()[:20]
    return f"retr_{digest}"


def _ai_subject(payload: dict[str, Any], job_payload: dict[str, Any]) -> dict[str, str]:
    auth_context = _dict_or_empty(payload.get("auth_context")) or _dict_or_empty(
        job_payload.get("auth_context")
    )
    user_id = _text(
        payload.get("owner_id")
        or payload.get("user_id")
        or auth_context.get("user_id")
        or job_payload.get("owner_id")
        or job_payload.get("user_id")
    )
    guest_id = _normalize_guest_id(
        payload.get("guest_id") or auth_context.get("guest_id") or job_payload.get("guest_id")
    )
    auth_session_id = _text(
        payload.get("auth_session_id")
        or auth_context.get("auth_session_id")
        or job_payload.get("auth_session_id")
    )

    if user_id:
        subject_type = "user"
        subject_id = f"user:{user_id}"
    elif guest_id:
        subject_type = "guest"
        subject_id = f"guest:{guest_id}"
    else:
        subject_type = "anonymous"
        subject_id = "anonymous"

    return {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "user_id": user_id,
        "guest_id": guest_id,
        "auth_session_id": auth_session_id,
        "quota_key": f"rate_limit:{subject_id}:agent_run",
    }


def _get_or_create_user_account(user_id: str) -> UserAccount | None:
    if not user_id:
        return None
    user, _created = UserAccount.objects.get_or_create(
        user_id=user_id,
        defaults={
            "display_name": user_id,
            "status": UserAccountStatus.ACTIVE,
            "metadata": {"source": "canonical_analysis_job"},
        },
    )
    return user


def _get_or_create_guest_identity(guest_id: str) -> GuestIdentity | None:
    if not guest_id:
        return None
    guest, _created = GuestIdentity.objects.get_or_create(
        guest_id=guest_id,
        defaults={
            "status": GuestIdentityStatus.ACTIVE,
            "metadata": {"source": "canonical_analysis_job"},
        },
    )
    return guest


def _agent_result_raw_output(
    execution: dict[str, Any],
    agent_output: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source": "mock_node_execution",
        "execution_id": execution.get("execution_id"),
        "execution_mode": execution.get("execution_mode"),
        "adapter_context": execution.get("adapter_context") or {},
        "plan_step": execution.get("plan_step") or {},
        "agent_output": agent_output,
        "created_at": agent_output.get("created_at") or execution.get("created_at"),
    }


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _display_result_persistence_skipped(reason: str) -> dict[str, Any]:
    return {
        "backend": "postgresql",
        "table": AnalysisDisplayResult._meta.db_table,
        "status": "skipped",
        "reason": reason,
    }


def _report_persistence_skipped(reason: str) -> dict[str, Any]:
    return {
        "backend": "postgresql",
        "table": Report._meta.db_table,
        "status": "skipped",
        "reason": reason,
    }


def _auth_persistence_skipped(reason: str) -> dict[str, Any]:
    return {
        "backend": "postgresql",
        "tables": [
            UserAccount._meta.db_table,
            GuestIdentity._meta.db_table,
            AuthSession._meta.db_table,
            AuthEvent._meta.db_table,
        ],
        "status": "skipped",
        "reason": reason,
    }


def _report_type(value: Any) -> str:
    report_type = _text(value)
    if report_type in {choice.value for choice in ReportType}:
        return report_type
    legacy_aliases = {
        "objection_draft": ReportType.FINE_NOTICE_OBJECTION,
        "fault_analysis": ReportType.FAULT_RATIO_ANALYSIS,
        "generic_supervisor": ReportType.GENERAL,
    }
    return legacy_aliases.get(report_type, ReportType.FINE_NOTICE_OBJECTION)


def _report_status(value: Any) -> str:
    status = _text(value)
    if status in {choice.value for choice in ReportStatus}:
        return status
    if status in {"downloaded", "report_saved", "saved", "success"}:
        return ReportStatus.READY
    if status == "failed":
        return ReportStatus.FAILED
    return ReportStatus.READY


def _report_object_storage(report: Report) -> dict[str, Any]:
    metadata = report.metadata if isinstance(report.metadata, dict) else {}
    object_storage = metadata.get("object_storage")
    if isinstance(object_storage, dict) and object_storage.get("storage_uri"):
        return dict(object_storage)
    return storage_reference_from_uri(
        report.storage_uri or f"mock://reports/{report.report_id}",
        resource_type="report",
        resource_id=report.report_id,
        filename=f"{report.report_id}.txt",
        content_type="text/plain; charset=utf-8",
    )


def _report_title(payload: dict[str, Any], report_payload: dict[str, Any]) -> str:
    return (
        _text(payload.get("title"))
        or _text(report_payload.get("title"))
        or _text(payload.get("action"))
        or "report"
    )


def _report_content_summary(
    display_result: AnalysisDisplayResult | None,
    report_payload: dict[str, Any],
    *,
    payload: dict[str, Any] | None = None,
) -> str:
    reporting_summary = _reporting_payload_content_summary(
        _dict_or_empty((payload or {}).get("reporting_payload"))
    )
    if reporting_summary:
        return reporting_summary
    if display_result and isinstance(display_result.assistant_message, dict):
        summary = _text(display_result.assistant_message.get("summary"))
        if summary:
            return summary
        answer = _text(display_result.assistant_message.get("answer"))
        if answer:
            return answer[:500]
    return f"Mock report action result: {_text(report_payload.get('status')) or 'ready'}"


def _reporting_payload_content_summary(reporting_payload: dict[str, Any]) -> str:
    if not reporting_payload:
        return ""
    report_type = _text(reporting_payload.get("report_type"))
    screen_id = _text(reporting_payload.get("screen_id"))
    stage = _text(reporting_payload.get("stage"))
    quality = _dict_or_empty(reporting_payload.get("quality"))
    lines = [
        _text(reporting_payload.get("title")) or "상담 분석 리포트",
        _text(reporting_payload.get("summary")),
        "",
        "## 문서 정보",
        f"- 리포트 유형: {_report_type_display_label(report_type)}",
    ]
    if screen_id:
        lines.append(f"- 화면 ID: {screen_id}")
    if stage:
        lines.append(f"- 진행 상태: {_report_stage_display_label(stage)}")
    if quality:
        lines.append(f"- 검토 상태: {_report_quality_display_label(quality)}")
        if quality.get("review_required"):
            lines.append("- 검토 기준: 제출 전 사실관계와 증거 자료를 다시 확인해야 합니다.")
    if report_type == ReportType.FAULT_RATIO_ANALYSIS.value:
        lines.extend(
            [
                "",
                "## 과실비율 리포트 기준",
                "- 사고 개요, AI 분석 결과, 판단 근거, 유사 사례·판례, 후속 조치를 PDF에 포함합니다.",
                "- 유사 사례와 보험 기준은 참고 자료이며 법적 확정 판단으로 표현하지 않습니다.",
            ]
        )
    for section in _list_or_empty(reporting_payload.get("sections")):
        if not isinstance(section, dict):
            continue
        title = _text(section.get("title"))
        if title:
            lines.extend(["", f"## {title}"])
        for item in _list_or_empty(section.get("items")):
            text = _reporting_payload_item_text(item)
            if text:
                lines.append(f"- {text}")
    return "\n".join(line for line in lines if line).strip()


def _report_type_display_label(report_type: str) -> str:
    labels = {
        ReportType.FINE_NOTICE_OBJECTION.value: "과태료 대응",
        ReportType.FAULT_RATIO_ANALYSIS.value: "사고 과실비율 분석",
        "generic_supervisor": "상담 요약",
        "objection_draft": "이의신청 초안",
        "fault_analysis": "과실 분석",
        "general": "일반 리포트",
    }
    return labels.get(report_type, report_type or "일반 리포트")


def _report_stage_display_label(stage: str) -> str:
    labels = {
        "draft": "작성 중",
        "agent_execution_ready": "분석 준비 완료",
        "partial": "보완 필요",
        "success": "분석 완료",
        "ready": "저장 완료",
        "downloaded": "다운로드 완료",
    }
    return labels.get(str(stage or "").lower(), stage or "상태 확인")


def _report_quality_display_label(quality: dict[str, Any]) -> str:
    if quality.get("partial_report"):
        return "추가 자료 필요"
    return _text(quality.get("confidence_label")) or "검토 가능"


def _reporting_payload_item_text(item: Any) -> str:
    if isinstance(item, dict):
        label = _text(item.get("label") or item.get("title") or item.get("field") or item.get("node_code"))
        value = _text(
            item.get("value")
            or item.get("summary")
            or item.get("text")
            or item.get("question")
            or item.get("status")
        )
        if label and value:
            return f"{label}: {value}"
        if label:
            return label
        return " · ".join(
            f"{_text(key)}: {_text(value)}"
            for key, value in list(item.items())[:4]
            if _text(value)
        )
    return _text(item)


def _report_pdf_font_file() -> str | None:
    candidates = [
        Path("C:/Windows/Fonts/malgun.ttf"),
        Path("C:/Windows/Fonts/malgunbd.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansKR-Regular.otf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _reportlab_pdf_modules() -> dict[str, Any] | None:
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen.canvas import Canvas
    except Exception:
        for candidate in _bundled_pdf_site_packages_candidates():
            if candidate.exists() and str(candidate) not in sys.path:
                sys.path.append(str(candidate))
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.pdfgen.canvas import Canvas
        except Exception:
            return None
    return {
        "pdfmetrics": pdfmetrics,
        "ttfont": TTFont,
        "canvas": Canvas,
    }


def _wrap_reportlab_pdf_line(
    text: str,
    *,
    font_name: str,
    font_size: float,
    max_width: float,
    pdfmetrics: Any,
) -> list[str]:
    value = " ".join(str(text or "").split())
    if not value:
        return [""]
    if pdfmetrics.stringWidth(value, font_name, font_size) <= max_width:
        return [value]

    lines: list[str] = []
    current = ""
    for word in value.split(" "):
        candidate = f"{current} {word}".strip()
        if current and pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
            lines.extend(
                _wrap_reportlab_pdf_token(
                    current,
                    font_name=font_name,
                    font_size=font_size,
                    max_width=max_width,
                    pdfmetrics=pdfmetrics,
                )
            )
            current = word
            continue
        current = candidate
    if current:
        lines.extend(
            _wrap_reportlab_pdf_token(
                current,
                font_name=font_name,
                font_size=font_size,
                max_width=max_width,
                pdfmetrics=pdfmetrics,
            )
        )
    return lines or [value]


def _wrap_reportlab_pdf_token(
    text: str,
    *,
    font_name: str,
    font_size: float,
    max_width: float,
    pdfmetrics: Any,
) -> list[str]:
    if pdfmetrics.stringWidth(text, font_name, font_size) <= max_width:
        return [text]

    chunks: list[str] = []
    current = ""
    for char in text:
        candidate = f"{current}{char}"
        if current and pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
            chunks.append(current)
            current = char
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _wrap_report_pdf_line(text: str, *, width: int) -> list[str]:
    value = str(text or "")
    if len(value) <= width:
        return [value]
    chunks = []
    current = ""
    for word in value.split(" "):
        if not word:
            continue
        if len(word) > width:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(word[index : index + width] for index in range(0, len(word), width))
            continue
        next_value = f"{current} {word}".strip()
        if len(next_value) > width and current:
            chunks.append(current)
            current = word
        else:
            current = next_value
    if current:
        chunks.append(current)
    return chunks or [value[:width]]


def _minimal_pdf_bytes(*, title: str, body_text: str) -> bytes:
    lines = [title or "Traffic Dispute AI report", ""]
    for raw_line in str(body_text or "").splitlines():
        if not raw_line.strip():
            lines.append("")
            continue
        lines.extend(_wrap_report_pdf_line(raw_line.strip(), width=54))
    pages = []
    current_page = []
    for line in lines[:180]:
        if len(current_page) >= 42:
            pages.append(current_page)
            current_page = []
        current_page.append(line)
    if current_page:
        pages.append(current_page)
    if not pages:
        pages = [["Traffic Dispute AI report"]]

    objects = [
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        "",
        (
            "3 0 obj << /Type /Font /Subtype /Type0 /BaseFont /HYSMyeongJo-Medium "
            "/Encoding /UniKS-UCS2-H /DescendantFonts [4 0 R] >> endobj\n"
        ),
        (
            "4 0 obj << /Type /Font /Subtype /CIDFontType0 /BaseFont /HYSMyeongJo-Medium "
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (Korea1) /Supplement 2 >> >> endobj\n"
        ),
    ]
    page_object_ids = []
    next_object_id = 5
    for page_lines in pages:
        page_id = next_object_id
        content_id = next_object_id + 1
        next_object_id += 2
        page_object_ids.append(page_id)
        stream = _minimal_pdf_page_stream(page_lines)
        objects.append(
            f"{page_id} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >> endobj\n"
        )
        objects.append(
            f"{content_id} 0 obj << /Length {len(stream.encode('ascii'))} >> stream\n"
            f"{stream}endstream endobj\n"
        )
    objects[1] = (
        f"2 0 obj << /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_object_ids)}] "
        f"/Count {len(page_object_ids)} >> endobj\n"
    )
    body = "%PDF-1.4\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(body.encode("ascii")))
        body += obj
    xref_offset = len(body.encode("ascii"))
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for offset in offsets[1:]:
        body += f"{offset:010d} 00000 n \n"
    body += f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    return body.encode("ascii")


def _minimal_pdf_page_stream(lines: list[str]) -> str:
    commands = ["BT\n", "/F1 11 Tf\n", "50 790 Td\n"]
    first_line = True
    for line in lines:
        if first_line:
            first_line = False
        else:
            commands.append("0 -17 Td\n")
        if not line:
            continue
        if line.startswith("## "):
            commands.append("/F1 13 Tf\n")
            commands.append(f"<{_pdf_utf16be_hex(line[3:])}> Tj\n")
            commands.append("/F1 11 Tf\n")
        else:
            commands.append(f"<{_pdf_utf16be_hex(line)}> Tj\n")
    commands.append("ET\n")
    return "".join(commands)


def _pdf_utf16be_hex(value: Any) -> str:
    return str(value or "").encode("utf-16-be", errors="replace").hex().upper()


def _report_download_document_type(value: str | None) -> str:
    normalized = _text(value).lower()
    if normalized in {"objection", "objection_form", "objection-draft", "application", "form"}:
        return REPORT_DOWNLOAD_TYPE_OBJECTION_FORM
    return REPORT_DOWNLOAD_TYPE_REPORT


def _report_objection_form_body(report: Report) -> str:
    content = _dict_or_empty(report.content)
    reporting_payload = _dict_or_empty(content.get("reporting_payload"))
    sections = _list_or_empty(reporting_payload.get("sections"))
    draft_section = _report_section_by_title(sections, ("이의신청서", "의견제출서", "초안"))
    draft_items = _report_section_item_map(draft_section)
    evidence_section = _report_section_by_title(sections, ("필요 증거", "제출 자료", "증거"))
    evidence_items = _report_section_item_map(evidence_section)
    agency = (
        draft_items.get("제출 대상")
        or draft_items.get("수신")
        or "고지서에 표시된 처분 기관"
    )
    title = (
        draft_items.get("제목")
        or "과태료 부과 처분에 대한 의견제출서 및 이의신청서"
    )
    facts = _compact_repeated_fact_text(
        draft_items.get("사실관계") or _text(reporting_payload.get("summary")) or report.content_summary
    )
    purpose = (
        draft_items.get("신청 취지")
        or "고지 내용과 실제 사실관계를 재확인해 처분 취소 또는 감경을 요청합니다."
    )
    attachments = draft_items.get("첨부 자료") or evidence_items.get("현재 증빙") or "고지서 원본, 현장 사진, 블랙박스 등 증빙 자료"
    review_note = (
        draft_items.get("검토 안내")
        or "본 문서는 AI가 작성한 제출 전 검토용 초안이며, 실제 제출 전 사실관계와 관할 기관 양식을 확인해야 합니다."
    )
    lines = [
        "## 문서 정보",
        "- 문서 유형: 이의신청서 초안",
        f"- 리포트 ID: {report.report_id}",
        f"- 사건 ID: {report.job.job_id if report.job_id else report.session.session_id if report.session_id else '-'}",
        "- 작성 기준: 상담 내용과 리포트 payload",
        "",
        "## 제출 정보",
        f"- 수신: {agency}",
        f"- 제목: {title}",
        "",
        "## 신청 취지",
        f"- {purpose}",
        "",
        "## 사실관계",
        f"- {facts}",
        "",
        "## 신청 사유",
        "- 위반 당시 상황, 긴급성, 표지·신호 상태, 운전자 진술과 제출 증빙을 근거로 처분 재검토를 요청합니다.",
        "",
        "## 첨부 자료",
        f"- {attachments}",
        "",
        "## 제출 전 확인",
        f"- {review_note}",
        "- 관할 기관의 공식 양식, 접수 기한, 서명 또는 날인 필요 여부를 최종 확인하세요.",
    ]
    return "\n".join(lines) + "\n"


def _report_objection_form_pdf_body(
    report: Report,
    *,
    title: str,
    text_body: str,
) -> bytes:
    if _should_use_accident_objection_template(report):
        template_pdf = _build_accident_objection_template_pdf(report)
        if template_pdf:
            return template_pdf
    return build_report_download_pdf_body(
        report_id=report.report_id,
        title=title,
        body_text=text_body,
    )


def _should_use_accident_objection_template(report: Report) -> bool:
    return report.report_type == ReportType.FAULT_RATIO_ANALYSIS.value


def _build_accident_objection_template_pdf(report: Report) -> bytes | None:
    if not ACCIDENT_OBJECTION_TEMPLATE_PATH.exists():
        return None

    modules = _pdf_overlay_modules()
    if modules is None:
        return _build_accident_objection_template_pdf_via_bundled_python(report)

    pdfmetrics = modules["pdfmetrics"]
    ttfont = modules["ttfont"]
    canvas_cls = modules["canvas"]
    pdf_reader_cls = modules["pdf_reader"]
    pdf_writer_cls = modules["pdf_writer"]

    try:
        template_reader = pdf_reader_cls(str(ACCIDENT_OBJECTION_TEMPLATE_PATH))
    except Exception:
        return None

    if not template_reader.pages:
        return None

    try:
        font_name = "ReportOverlay"
        font_file = _report_pdf_font_file()
        if font_file and font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(ttfont(font_name, font_file))
    except Exception:
        font_name = "Helvetica"

    first_page = template_reader.pages[0]
    page_width = float(first_page.mediabox.width)
    page_height = float(first_page.mediabox.height)
    form_data = _accident_objection_template_data(report)

    overlay_stream = BytesIO()
    overlay_canvas = canvas_cls(overlay_stream, pagesize=(page_width, page_height))
    overlay_canvas.setFillColorRGB(0, 0, 0)

    total_pages = len(template_reader.pages)
    for page_index in range(total_pages):
        if page_index == 1:
            _draw_accident_objection_template_page_2(
                overlay_canvas,
                page_height=page_height,
                font_name=font_name,
                data=form_data,
            )
        elif page_index == 2:
            _draw_accident_objection_template_page_3(
                overlay_canvas,
                page_height=page_height,
                font_name=font_name,
                data=form_data,
            )
        elif page_index == 3:
            _draw_accident_objection_template_page_4(
                overlay_canvas,
                page_height=page_height,
                font_name=font_name,
                data=form_data,
            )
        elif page_index == 4:
            _draw_accident_objection_template_page_5(
                overlay_canvas,
                page_height=page_height,
                font_name=font_name,
                data=form_data,
            )
        overlay_canvas.showPage()
    overlay_canvas.save()
    overlay_stream.seek(0)

    try:
        overlay_reader = pdf_reader_cls(overlay_stream)
        writer = pdf_writer_cls()
        for page_index, template_page in enumerate(template_reader.pages):
            if page_index < len(overlay_reader.pages):
                template_page.merge_page(overlay_reader.pages[page_index])
            writer.add_page(template_page)
        output = BytesIO()
        writer.write(output)
        return output.getvalue()
    except Exception:
        return _build_accident_objection_template_pdf_via_bundled_python(report)


def _build_accident_objection_template_pdf_via_bundled_python(report: Report) -> bytes | None:
    if not ACCIDENT_OBJECTION_RENDERER_PATH.exists():
        return None

    bundled_python = _bundled_pdf_python_path()
    if bundled_python is None:
        return None

    payload = {
        "template_pdf": str(ACCIDENT_OBJECTION_TEMPLATE_PATH),
        "font_file": _report_pdf_font_file(),
        "form_data": _json_compatible(_accident_objection_template_data(report)),
    }
    try:
        with tempfile.TemporaryDirectory(prefix="objection-pdf-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            payload_path = temp_dir / "payload.json"
            output_path = temp_dir / "objection-form.pdf"
            payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    str(bundled_python),
                    str(ACCIDENT_OBJECTION_RENDERER_PATH),
                    str(payload_path),
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if completed.returncode != 0 or not output_path.exists():
                return None
            return output_path.read_bytes()
    except Exception:
        return None


def _pdf_overlay_modules() -> dict[str, Any] | None:
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen.canvas import Canvas
        from pypdf import PdfReader, PdfWriter
    except Exception:
        for candidate in _bundled_pdf_site_packages_candidates():
            if candidate.exists() and str(candidate) not in sys.path:
                sys.path.append(str(candidate))
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.pdfgen.canvas import Canvas
            from pypdf import PdfReader, PdfWriter
        except Exception:
            return None
    return {
        "pdfmetrics": pdfmetrics,
        "ttfont": TTFont,
        "canvas": Canvas,
        "pdf_reader": PdfReader,
        "pdf_writer": PdfWriter,
    }


def _bundled_pdf_site_packages_candidates() -> list[Path]:
    return [
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "python"
        / "Lib"
        / "site-packages"
    ]


def _bundled_pdf_python_path() -> Path | None:
    candidates: list[Path] = []
    for site_packages in _bundled_pdf_site_packages_candidates():
        runtime_root = site_packages.parent.parent
        candidates.extend(
            [
                runtime_root / "python.exe",
                runtime_root / "python",
                runtime_root / "bin" / "python3",
                runtime_root / "bin" / "python",
            ]
        )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _accident_objection_template_data(report: Report) -> dict[str, Any]:
    content = _dict_or_empty(report.content)
    reporting_payload = _dict_or_empty(content.get("reporting_payload"))
    sections = _list_or_empty(reporting_payload.get("sections"))
    overview_items = _report_section_item_map(_report_section_by_title(sections, ("사고 개요", "고지서 OCR 결과")))
    issue_items = _report_section_item_map(_report_section_by_title(sections, ("핵심 쟁점", "이의제기 가능성")))
    evidence_items = _report_section_item_map(_report_section_by_title(sections, ("필요 증거", "제출 자료", "증거자료")))
    guide_items = _report_section_item_map(_report_section_by_title(sections, ("후속 조치", "제출 가이드라인")))
    law_items = _report_section_item_map(_report_section_by_title(sections, ("판단 근거", "관련 법령", "판례")))
    draft_items = _report_section_item_map(_report_section_by_title(sections, ("이의신청서", "초안")))
    report_summary = _text(reporting_payload.get("summary")) or report.content_summary
    issue_values = [value for value in issue_items.values() if _text(value)]
    evidence_values = [value for value in evidence_items.values() if _text(value)]
    guide_values = [value for value in guide_items.values() if _text(value)]
    law_values = [value for value in law_items.values() if _text(value)]
    issue_summary = " / ".join(
        value
        for value in (
            issue_items.get("판단"),
            issue_items.get("주요 사유"),
            issue_items.get("보완 필요"),
        )
        if _text(value)
    )
    issue_summary = issue_summary or " / ".join(issue_values[:3])
    evidence_summary = " / ".join(
        value
        for value in (
            evidence_items.get("현재 증빙"),
            evidence_items.get("현장 자료"),
            evidence_items.get("운전자 진술"),
            evidence_items.get("고지서 원본"),
        )
        if _text(value)
    )
    evidence_summary = evidence_summary or " / ".join(evidence_values[:4])
    reason_detail = "\n".join(
        line
        for line in (
            _text(law_items.get("적용 한계")),
            _text(law_items.get("검증 필요")),
            _text(issue_items.get("주요 사유")),
            _text(report_summary),
        )
        if line
    )
    reason_detail = reason_detail or "\n".join(law_values[:2] + [report_summary])
    action_detail = "\n".join(
        line
        for line in (
            _text(guide_items.get("1단계")),
            _text(guide_items.get("2단계")),
            _text(guide_items.get("3단계")),
            _text(guide_items.get("4단계")),
        )
        if line
    )
    relationship = "보행자" if "보행" in f"{report_summary} {issue_summary}" else "운전자"
    action_detail = action_detail or "\n".join(guide_values[:4])
    incident_at = _first_nonempty(
        overview_items.get("사고 일시"),
        overview_items.get("위반 일시"),
        draft_items.get("사실관계"),
    )
    location = _first_nonempty(
        overview_items.get("사고 장소"),
        overview_items.get("위반 장소"),
        draft_items.get("사실관계"),
    )
    case_number = _first_nonempty(
        overview_items.get("사건번호 / 접수번호"),
        report.job.job_id if report.job_id else "",
    )
    write_date = timezone.localtime(timezone.now()).strftime("%Y년 %m월 %d일")
    applicant_name = _first_nonempty(
        content.get("applicant_name"),
        reporting_payload.get("applicant_name"),
        report.metadata.get("applicant_name"),
    )
    evidence_rows = _objection_evidence_rows(evidence_items, law_items, draft_items)
    objection_targets = _objection_target_labels(f"{issue_summary} {report_summary} {evidence_summary}")
    rebuttal_brief = _brief_text(_first_nonempty(issue_summary, report_summary), limit=52)
    response_brief = _brief_text(_first_nonempty(action_detail, report_summary), limit=52)
    target_brief = _brief_text(", ".join(objection_targets[:2]), limit=28)
    recipient = _first_nonempty(
        draft_items.get("제출 대상"),
        draft_items.get("수신"),
        "○○경찰서장 귀하",
    )
    police_station = _first_nonempty(
        overview_items.get("담당 경찰서"),
        overview_items.get("해당 경찰서"),
        "담당 경찰서 확인 필요",
    )

    return {
        "recipient": recipient,
        "applicant_name": applicant_name,
        "relationship": relationship,
        "case_number": case_number,
        "incident_at": incident_at,
        "location": location,
        "investigator": _text(overview_items.get("담당 조사관")),
        "notice_date": _text(overview_items.get("조사결과 통지일")),
        "police_station": police_station,
        "vehicle_parties": _first_nonempty(
            overview_items.get("관련 차량 / 당사자"),
            _text(overview_items.get("사고 유형")),
        ),
        "insurance_number": _text(overview_items.get("보험사 / 접수번호")),
        "objection_targets": objection_targets,
        "purpose": _first_nonempty(
            draft_items.get("신청 취지"),
            "관련 증거를 재검토하고 필요한 재조사를 통해 조사결과를 재확인해 주시기 바랍니다.",
        ),
        "summary": _compact_repeated_fact_text(
            _first_nonempty(
                draft_items.get("사실관계"),
                report_summary,
                report.content_summary,
            )
        ),
        "issue_summary": issue_summary,
        "reason_detail": reason_detail,
        "action_detail": action_detail,
        "evidence_summary": evidence_summary,
        "evidence_rows": evidence_rows,
        "write_date": write_date,
        "rebuttal_brief": rebuttal_brief,
        "response_brief": response_brief,
        "target_brief": target_brief,
        "law_summary": " / ".join(
            value
            for value in (
                law_items.get("검색 쿼리"),
                law_items.get("적용 한계"),
                law_items.get("Agent 상태"),
            )
            if _text(value)
        ),
        "rebuttal_summary": _first_nonempty(issue_items.get("판단"), report_summary),
    }


def _brief_text(value: Any, *, limit: int = 56) -> str:
    text = " ".join(_text(value).replace("\r", " ").replace("\n", " ").split())
    if not text or len(text) <= limit:
        return text
    return f"{text[: max(limit - 3, 1)].rstrip()}..."


def _compact_repeated_fact_text(value: Any) -> str:
    text = " ".join(_text(value).replace("\r", " ").replace("\n", " ").split())
    if not text:
        return ""

    marker = "에서 "
    marker_start = 0
    while True:
        marker_index = text.find(marker, marker_start)
        if marker_index < 0:
            break
        suffix = text[marker_index + len(marker) :]
        prefix = text[:marker_index]
        if len(suffix) >= 20 and any(char.isdigit() for char in suffix) and suffix in prefix:
            text = suffix
            break
        marker_start = marker_index + len(marker)

    words = text.split()
    for size in range(len(words) // 2, 0, -1):
        if words[:size] == words[size : size * 2]:
            return " ".join(words[size:])
    return text


def _objection_evidence_rows(
    evidence_items: dict[str, str],
    law_items: dict[str, str],
    draft_items: dict[str, str],
) -> list[dict[str, str]]:
    raw_values = [
        evidence_items.get("현재 증빙"),
        evidence_items.get("현장 자료"),
        evidence_items.get("운전자 진술"),
        evidence_items.get("고지서 원본"),
        draft_items.get("첨부 자료"),
        law_items.get("검색 쿼리"),
    ]
    if not any(_text(value) for value in raw_values):
        raw_values = list(evidence_items.values()) + list(draft_items.values()) + list(law_items.values())
    rows = []
    for index, value in enumerate(_split_listish_values(raw_values, limit=6), start=1):
        rows.append(
            {
                "no": str(index),
                "name": value,
                "fact": "신청인 주장과 기존 조사결과 차이를 입증",
                "format": "PDF / 이미지 / 메모",
                "note": "",
            }
        )
    return rows


def _draw_accident_objection_template_page_2(pdf_canvas, *, page_height: float, font_name: str, data: dict[str, Any]) -> None:
    _draw_text_block(pdf_canvas, data["recipient"], x=250, top=147, page_height=page_height, width=34, max_lines=1, font_name=font_name, font_size=10)
    _draw_text_block(pdf_canvas, data["applicant_name"], x=126, top=289, page_height=page_height, width=20, max_lines=1, font_name=font_name)
    _draw_text_block(pdf_canvas, "", x=428, top=289, page_height=page_height, width=18, max_lines=1, font_name=font_name)
    _draw_text_block(pdf_canvas, "", x=126, top=329, page_height=page_height, width=28, max_lines=2, font_name=font_name)
    _draw_text_block(pdf_canvas, "", x=428, top=329, page_height=page_height, width=18, max_lines=1, font_name=font_name)
    _draw_text_block(pdf_canvas, "", x=126, top=369, page_height=page_height, width=28, max_lines=1, font_name=font_name)
    _draw_text_block(pdf_canvas, data["relationship"], x=427, top=369, page_height=page_height, width=24, max_lines=2, font_name=font_name)

    _draw_text_block(pdf_canvas, data["case_number"], x=126, top=482, page_height=page_height, width=26, max_lines=1, font_name=font_name)
    _draw_text_block(pdf_canvas, data["incident_at"], x=428, top=482, page_height=page_height, width=22, max_lines=2, font_name=font_name)
    _draw_text_block(pdf_canvas, data["location"], x=126, top=522, page_height=page_height, width=30, max_lines=2, font_name=font_name)
    _draw_text_block(pdf_canvas, data["police_station"], x=428, top=522, page_height=page_height, width=20, max_lines=2, font_name=font_name)
    _draw_text_block(pdf_canvas, data["investigator"], x=126, top=562, page_height=page_height, width=24, max_lines=1, font_name=font_name)
    _draw_text_block(pdf_canvas, data["notice_date"], x=428, top=562, page_height=page_height, width=18, max_lines=1, font_name=font_name)
    _draw_text_block(pdf_canvas, data["vehicle_parties"], x=126, top=603, page_height=page_height, width=30, max_lines=2, font_name=font_name)
    _draw_text_block(pdf_canvas, data["insurance_number"], x=428, top=603, page_height=page_height, width=20, max_lines=2, font_name=font_name)

    _draw_text_block(
        pdf_canvas,
        f"선택 쟁점: {', '.join(data['objection_targets'])}",
        x=96,
        top=696,
        page_height=page_height,
        width=94,
        max_lines=2,
        font_name=font_name,
        font_size=9,
        leading=12,
    )
    _draw_text_block(pdf_canvas, data["purpose"], x=96, top=780, page_height=page_height, width=94, max_lines=5, font_name=font_name, leading=14)
    _draw_text_block(pdf_canvas, data["write_date"], x=126, top=927, page_height=page_height, width=20, max_lines=1, font_name=font_name)
    _draw_text_block(pdf_canvas, data["applicant_name"], x=428, top=927, page_height=page_height, width=16, max_lines=1, font_name=font_name)


def _draw_accident_objection_template_page_3(pdf_canvas, *, page_height: float, font_name: str, data: dict[str, Any]) -> None:
    _draw_text_block(pdf_canvas, data["rebuttal_summary"], x=92, top=180, page_height=page_height, width=92, max_lines=3, font_name=font_name, font_size=10, leading=13)

    issue_rows = [
        {
            "dispute": target,
            "claim": data["summary"],
            "evidence": row["no"],
        }
        for target, row in zip(data["objection_targets"][:3], data["evidence_rows"][:3], strict=False)
    ]
    row_tops = [257, 287, 317]
    for index, row in enumerate(issue_rows[:3]):
        _draw_text_block(pdf_canvas, str(index + 1), x=118, top=row_tops[index], page_height=page_height, width=3, max_lines=1, font_name=font_name, font_size=9)
        _draw_text_block(pdf_canvas, row["dispute"], x=148, top=row_tops[index], page_height=page_height, width=18, max_lines=2, font_name=font_name, font_size=9, leading=11)
        _draw_text_block(pdf_canvas, row["claim"], x=282, top=row_tops[index], page_height=page_height, width=22, max_lines=2, font_name=font_name, font_size=9, leading=11)
        _draw_text_block(pdf_canvas, row["evidence"], x=503, top=row_tops[index], page_height=page_height, width=5, max_lines=1, font_name=font_name, font_size=9)

    _draw_text_block(pdf_canvas, data["summary"], x=92, top=410, page_height=page_height, width=94, max_lines=5, font_name=font_name, leading=14)
    _draw_text_block(pdf_canvas, data["evidence_summary"], x=92, top=533, page_height=page_height, width=94, max_lines=4, font_name=font_name, leading=14)
    _draw_text_block(pdf_canvas, data["action_detail"], x=92, top=655, page_height=page_height, width=94, max_lines=3, font_name=font_name, leading=14)


def _draw_accident_objection_template_page_4(pdf_canvas, *, page_height: float, font_name: str, data: dict[str, Any]) -> None:
    evidence_row_tops = [164, 196, 228, 260, 292, 324]
    for index, row in enumerate(data["evidence_rows"][:6]):
        top = evidence_row_tops[index]
        _draw_text_block(pdf_canvas, row["name"], x=100, top=top, page_height=page_height, width=18, max_lines=2, font_name=font_name, font_size=8, leading=9.5)
        _draw_text_block(pdf_canvas, row["fact"], x=260, top=top, page_height=page_height, width=20, max_lines=2, font_name=font_name, font_size=8, leading=9.5)
        _draw_text_block(pdf_canvas, row["format"], x=425, top=top, page_height=page_height, width=12, max_lines=2, font_name=font_name, font_size=8, leading=9.5)

    _draw_text_block(pdf_canvas, data.get("rebuttal_brief", data["rebuttal_summary"]), x=92, top=473, page_height=page_height, width=20, max_lines=2, font_name=font_name, font_size=8, leading=9.5)
    _draw_text_block(pdf_canvas, data.get("response_brief", data["summary"]), x=280, top=473, page_height=page_height, width=20, max_lines=2, font_name=font_name, font_size=8, leading=9.5)
    _draw_text_block(pdf_canvas, "1-3", x=469, top=473, page_height=page_height, width=6, max_lines=1, font_name=font_name, font_size=8.5)
    _draw_text_block(pdf_canvas, "재조사 요청", x=514, top=473, page_height=page_height, width=10, max_lines=2, font_name=font_name, font_size=8.5, leading=10)



def _draw_accident_objection_template_page_5(pdf_canvas, *, page_height: float, font_name: str, data: dict[str, Any]) -> None:
    _draw_text_block(pdf_canvas, data.get("target_brief", ""), x=372, top=551, page_height=page_height, width=16, max_lines=2, font_name=font_name, font_size=8.5, leading=9.5)
    _draw_text_block(pdf_canvas, data["reason_detail"], x=92, top=657, page_height=page_height, width=90, max_lines=4, font_name=font_name, font_size=8.5, leading=11)


def _draw_text_block(
    pdf_canvas,
    text: str,
    *,
    x: float,
    top: float,
    page_height: float,
    width: int,
    max_lines: int,
    font_name: str,
    font_size: float = 10,
    leading: float = 12,
) -> None:
    lines = _pdf_block_lines(text, width=width, max_lines=max_lines)
    if not lines:
        return
    pdf_canvas.setFont(font_name, font_size)
    baseline = page_height - top
    for index, line in enumerate(lines):
        pdf_canvas.drawString(x, baseline - (index * leading), line)


def _pdf_block_lines(text: str, *, width: int, max_lines: int) -> list[str]:
    if not _text(text):
        return []
    lines = []
    for raw_line in str(text).replace("\r", "").split("\n"):
        wrapped = _wrap_report_pdf_line(raw_line.strip(), width=width)
        lines.extend(wrapped or [""])
    compact_lines = [line for line in lines if line]
    if not compact_lines:
        return []
    if len(compact_lines) <= max_lines:
        return compact_lines
    truncated = compact_lines[:max_lines]
    if len(truncated[-1]) >= max(width - 3, 1):
        truncated[-1] = truncated[-1][: width - 3].rstrip()
    truncated[-1] = f"{truncated[-1]}..."
    return truncated


def _objection_target_labels(text: str) -> list[str]:
    keyword_map = [
        ("블랙박스 / CCTV 등 증거 미반영", ("블랙박스", "cctv", "증거", "영상")),
        ("신호위반 판단", ("신호",)),
        ("진로변경 / 끼어들기 판단", ("진로변경", "끼어들기", "차선 변경", "차선변경")),
        ("안전거리 / 전방주시 판단", ("안전거리", "전방주시")),
        ("속도 / 제한속도 판단", ("속도", "제동거리", "제한속도")),
        ("현장조사 미흡", ("현장", "사진", "로드뷰")),
        ("목격자 진술 누락", ("목격자", "진술")),
        ("교통법규 적용 오류", ("법령", "법규", "판례")),
    ]
    normalized = _text(text).lower()
    matches = [label for label, keywords in keyword_map if any(keyword in normalized for keyword in keywords)]
    if not matches:
        matches.append("교통법규 적용 오류")
    return matches[:4]


def _split_listish_values(values: list[Any], *, limit: int) -> list[str]:
    parts: list[str] = []
    for value in values:
        text = _text(value)
        if not text:
            continue
        normalized = text.replace("\n", ", ").replace("·", ", ").replace(" / ", ", ")
        for piece in normalized.split(","):
            cleaned = piece.strip()
            if cleaned and cleaned not in parts:
                parts.append(cleaned)
            if len(parts) >= limit:
                return parts
    return parts


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _report_section_by_title(sections: list[Any], keywords: tuple[str, ...]) -> dict[str, Any]:
    for section in sections:
        if not isinstance(section, dict):
            continue
        title = _text(section.get("title"))
        if any(keyword in title for keyword in keywords):
            return section
    return {}


def _report_section_item_map(section: dict[str, Any]) -> dict[str, str]:
    items: dict[str, str] = {}
    for item in _list_or_empty(section.get("items")):
        if not isinstance(item, dict):
            continue
        label = _text(item.get("label") or item.get("title") or item.get("field"))
        value = _reporting_payload_item_text(item)
        if label and value:
            if value.startswith(f"{label}: "):
                value = value[len(label) + 2 :]
            items[label] = value
    return items


def _report_download_body(
    report: Report,
    *,
    storage_backend: str,
    object_storage: dict[str, Any] | None = None,
) -> str:
    object_storage = object_storage or _report_object_storage(report)
    lines = [
        f"Report metadata download for {report.report_id}",
        f"status: {report.status}",
        f"storage_backend: {storage_backend}",
        f"storage_uri: {object_storage.get('storage_uri') or report.storage_uri}",
        f"object_key: {object_storage.get('key') or ''}",
        f"object_storage_policy: {object_storage.get('policy_version') or ''}",
    ]
    if report.job_id:
        lines.append(f"job_id: {report.job.job_id}")
        report_quality = _dict_or_empty(report.metadata.get("report_quality"))
        if report_quality:
            lines.append(f"analysis_job_status: {report_quality.get('analysis_job_status')}")
            lines.append(f"partial_report: {report_quality.get('partial_report')}")
            for index, limitation in enumerate(_list_or_empty(report_quality.get("limitations"))[:3], start=1):
                lines.append(f"limitation_{index}: {_text(limitation)}")
    if report.display_result_id:
        lines.append(f"display_result_id: {report.display_result.display_result_id}")
    if report.content_summary:
        lines.append("")
        lines.append(report.content_summary)
    return "\n".join(lines) + "\n"


def _report_quality_snapshot(
    job: AnalysisJob | None,
    display_result: AnalysisDisplayResult | None,
    report_payload: dict[str, Any],
) -> dict[str, Any]:
    agent_results = list(job.agent_results.all()) if job else []
    limitations = []
    limitations.extend(_list_or_empty(report_payload.get("limitations")))
    if display_result:
        limitations.extend(_list_or_empty(display_result.limitations))
    for result in agent_results:
        limitations.extend(_list_or_empty(result.limitations))
    agent_status_counts = _agent_status_counts(agent_results)
    analysis_job_status = job.status if job else ""
    partial_report = analysis_job_status in {
        AnalysisJobStatus.PARTIAL.value,
        AnalysisJobStatus.FAILED.value,
    }
    deduped_limitations = []
    for limitation in limitations:
        if limitation not in deduped_limitations:
            deduped_limitations.append(limitation)
    return {
        "contract_version": "report_quality.v1",
        "analysis_job_status": analysis_job_status or None,
        "agent_status_counts": agent_status_counts,
        "partial_report": partial_report,
        "limitation_count": len(deduped_limitations),
        "limitations": deduped_limitations[:12],
    }


def _report_object_body_for_write(
    payload: dict[str, Any],
    report_payload: dict[str, Any],
) -> str:
    lines = [
        f"Report object for {report_payload.get('report_id')}",
        f"action: {_text(payload.get('action')) or 'save'}",
        f"status: {_text(report_payload.get('status'))}",
        f"title: {_text(payload.get('title'))}",
        f"case_id: {_text(report_payload.get('case_id'))}",
    ]
    reporting_summary = _reporting_payload_content_summary(_dict_or_empty(payload.get("reporting_payload")))
    if reporting_summary:
        lines.extend(["", reporting_summary])
    return "\n".join(lines) + "\n"


def _analysis_job_work_item_summary(work_item: AgentWorkItem | None) -> dict[str, Any] | None:
    if work_item is None:
        return None
    return {
        "contract_version": "agent_worker_queue.v1",
        "work_item_id": work_item.work_item_id,
        "job_id": work_item.job.job_id,
        "status": work_item.status,
        "attempt_no": work_item.attempt_no,
        "max_attempts": work_item.max_attempts,
        "next_run_at": work_item.next_run_at.isoformat() if work_item.next_run_at else None,
        "progress_state": _work_item_progress_state(work_item, job_status=work_item.job.status),
    }


def _case_summary(job: AnalysisJob) -> dict[str, Any]:
    display_result = _display_result_for_job(job)
    reports = list(job.reports.order_by("-created_at"))
    latest_report = reports[0] if reports else None
    latest_event = job.events.order_by("-created_at").first()
    agent_results = list(job.agent_results.all())
    agent_invocations = list(job.agent_invocations.all())
    next_actions = _case_next_actions(agent_results)
    limitations = _case_limitations(display_result, agent_results)
    summary = _case_display_summary(display_result)

    return {
        "case_id": job.job_id,
        "job_id": job.job_id,
        "session_id": job.session.session_id,
        "message_id": job.message.message_id if job.message_id else None,
        "title": summary or _case_title(job),
        "case_status": job.status,
        "routing_intent": job.routing_intent,
        "active_node": job.active_node,
        "progress_message": job.progress_message,
        "last_event_at": (latest_event.created_at if latest_event else job.updated_at).isoformat(),
        "analysis_plan_id": job.analysis_plan_id,
        "agent_result_count": len(agent_results),
        "agent_status_counts": _agent_status_counts(agent_results),
        "agent_invocation_count": len(agent_invocations),
        "agent_invocation_status_counts": _agent_invocation_status_counts(agent_invocations),
        "ai_session_ids": _case_ai_session_ids(agent_invocations),
        "display_result_id": display_result.display_result_id if display_result else None,
        "report_count": len(reports),
        "latest_report_id": latest_report.report_id if latest_report else None,
        "latest_report_status": latest_report.status if latest_report else None,
        "next_actions": next_actions,
        "limitations": limitations,
    }


def _case_title(job: AnalysisJob) -> str:
    if job.message_id and job.message.content:
        return job.message.content[:80]
    if job.routing_intent:
        return job.routing_intent
    return job.job_id


def _case_display_summary(display_result: AnalysisDisplayResult | None) -> str:
    if display_result and isinstance(display_result.assistant_message, dict):
        summary = _text(display_result.assistant_message.get("summary"))
        if summary:
            return summary
        answer = _text(display_result.assistant_message.get("answer"))
        if answer:
            return answer[:120]
    if display_result and isinstance(display_result.cards, list):
        for card in display_result.cards:
            if isinstance(card, dict) and card.get("title"):
                return _text(card.get("title"))
    return ""


def _case_next_actions(agent_results: list[AgentResult]) -> list[Any]:
    actions = []
    for result in agent_results:
        for action in result.next_actions or []:
            if action not in actions:
                actions.append(action)
    return actions[:5]


def _case_limitations(
    display_result: AnalysisDisplayResult | None,
    agent_results: list[AgentResult],
) -> list[Any]:
    limitations = []
    if display_result:
        limitations.extend(display_result.limitations or [])
    for result in agent_results:
        limitations.extend(result.limitations or [])

    deduped = []
    for limitation in limitations:
        if limitation not in deduped:
            deduped.append(limitation)
    return deduped[:5]


def _agent_status_counts(agent_results: list[AgentResult]) -> dict[str, int]:
    counts = {AgentResultStatus.SUCCESS: 0, AgentResultStatus.PARTIAL: 0, AgentResultStatus.FAILED: 0}
    for result in agent_results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def _agent_invocation_status_counts(agent_invocations: list[AgentInvocation]) -> dict[str, int]:
    counts = {choice.value: 0 for choice in AgentInvocationStatus}
    for invocation in agent_invocations:
        counts[invocation.status] = counts.get(invocation.status, 0) + 1
    return {status: count for status, count in counts.items() if count}


def _case_ai_session_ids(agent_invocations: list[AgentInvocation]) -> list[str]:
    ai_session_ids = []
    for invocation in agent_invocations:
        if not invocation.ai_session_id:
            continue
        ai_session_id = invocation.ai_session.ai_session_id
        if ai_session_id not in ai_session_ids:
            ai_session_ids.append(ai_session_id)
    return ai_session_ids


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


def _positive_int_or_default(value: Any, *, default: int) -> int:
    number = _positive_int_or_none(value)
    if number is None or number == 0:
        return default
    return number


def _datetime_or_none(value: Any):
    text = _text(value)
    if not text:
        return None
    parsed = parse_datetime(text)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone=datetime_timezone.utc)
    return parsed


def _normalize_guest_id(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    if text.startswith("gst_"):
        return text
    return f"gst_{text}"


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
