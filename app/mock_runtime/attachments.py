"""Mock attachment metadata and local upload storage for Django integration."""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from app.services.attachment_scan_gate_contract import (
    CANONICAL_SCAN_GATE_MARKER,
    is_canonical_scan_ready_reference,
    merge_canonical_scan_ready_reference,
)



SUPPORTED_PURPOSES = {
    "fine_notice",
    "accident_scene",
    "evidence",
    "accident_statement",
    "traffic_accident_confirmation",
    "blackbox_video",
    "insurance_record",
    "unknown",
}

MAX_MOCK_UPLOAD_BYTES = 20 * 1024 * 1024



class UploadTooLargeError(ValueError):
    """Raised before an oversized upload can become a durable local object."""

    def __init__(self, *, size_bytes: int, limit_bytes: int) -> None:
        super().__init__("uploaded file exceeds the configured size limit")
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes


def register_attachment(
    payload: dict[str, Any],
    upload_file: Any | None = None,
    *,
    max_upload_bytes: int | None = None,
) -> dict[str, Any]:
    upload_limit = _positive_upload_limit(max_upload_bytes)
    declared_size = getattr(upload_file, "size", None)
    if upload_file is not None and declared_size is not None:
        normalized_size = int(declared_size)
        if normalized_size > upload_limit:
            raise UploadTooLargeError(
                size_bytes=normalized_size,
                limit_bytes=upload_limit,
            )

    attachment_id = payload.get("attachment_id") or f"att_{uuid4().hex[:12]}"
    original_filename = _original_filename(payload, upload_file)
    safe_filename = _safe_filename(original_filename)
    content_type = _content_type(payload, upload_file)
    attachment_type = payload.get("type") or _infer_attachment_type(content_type, safe_filename)
    purpose = _normalize_purpose(payload.get("purpose") or _infer_purpose(safe_filename, attachment_type))

    upload_dir = _upload_root() / attachment_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    stored_path = None
    size_bytes = int(payload.get("size_bytes") or 0)
    if upload_file is not None:
        stored_path = upload_dir / safe_filename
        try:
            size_bytes = _write_upload(
                stored_path,
                upload_file,
                max_bytes=upload_limit,
            )
        except UploadTooLargeError:
            stored_path.unlink(missing_ok=True)
            try:
                upload_dir.rmdir()
            except OSError:
                pass
            raise

    storage_uri = (
        f"mock://uploads/{attachment_id}/{safe_filename}"
        if stored_path
        else payload.get("storage_uri") or f"mock://metadata/{attachment_id}"
    )
    status = "uploaded" if upload_file is not None else "metadata_registered"
    now = _now_iso()

    attachment = {
        "attachment_id": attachment_id,
        "session_id": payload.get("session_id"),
        "message_id": payload.get("message_id"),
        "purpose": purpose,
        "type": attachment_type,
        "original_filename": original_filename,
        "filename": safe_filename,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "storage_uri": storage_uri,
        "status": status,
        "created_at": now,
        "checks": {
            "accepted": size_bytes <= upload_limit,
            "size_limit_bytes": upload_limit,
            "extension": Path(safe_filename).suffix.lower(),
            "metadata_sidecar": f"mock://uploads/{attachment_id}/metadata.json",
        },
        "agent_handoff": {
            "attachment_id": attachment_id,
            "purpose": purpose,
            "type": attachment_type,
            "storage_uri": storage_uri,
            "content_type": content_type,
            "size_bytes": size_bytes,
        },
        "limitations": [
            "중간발표용 mock local storage이며 실제 object storage, virus scan, OCR 처리는 수행하지 않습니다."
        ],
    }

    _write_metadata(upload_dir / "metadata.json", attachment)
    return attachment


def list_attachments(session_id: str | None = None) -> list[dict[str, Any]]:
    attachments = []
    root = _upload_root()
    if not root.exists():
        return attachments

    for metadata_path in sorted(root.glob("*/metadata.json")):
        metadata = _read_metadata(metadata_path)
        if not metadata:
            continue
        if session_id and metadata.get("session_id") != session_id:
            continue
        attachments.append(metadata)
    return attachments


def get_attachment(attachment_id: str) -> dict[str, Any] | None:
    metadata_path = _upload_root() / attachment_id / "metadata.json"
    return _read_metadata(metadata_path)


def resolve_attachment_references(payload: dict[str, Any]) -> dict[str, Any]:
    """Expand attachment_id references into Agent handoff metadata.

    The mock API accepts both fully inline attachment metadata and lightweight
    references such as {"attachment_id": "att_..."}.
    """

    enriched_payload = deepcopy(payload)
    attachments = _coerce_attachment_refs(enriched_payload)
    resolved_attachments = []
    resolution = {
        "resolved_attachment_ids": [],
        "inline_attachment_ids": [],
        "metadata_missing_attachment_ids": [],
        "unresolved_attachment_ids": [],
    }

    for attachment in attachments:
        attachment_id = attachment.get("attachment_id")

        if is_canonical_scan_ready_reference(attachment):
            resolved_attachments.append(merge_canonical_scan_ready_reference(attachment))
            if attachment_id:
                resolution["resolved_attachment_ids"].append(str(attachment_id))
            continue

        metadata = get_attachment(str(attachment_id)) if attachment_id else None

        if metadata:
            resolved_attachments.append(_merge_attachment_metadata(attachment, metadata))
            resolution["resolved_attachment_ids"].append(metadata["attachment_id"])
            continue

        if _has_inline_metadata(attachment):
            inline_attachment = dict(attachment)
            inline_attachment.pop("_canonical_scan_gate", None)
            inline_attachment["resolution_status"] = "inline_metadata"
            resolved_attachments.append(inline_attachment)
            if attachment_id:
                resolution["inline_attachment_ids"].append(str(attachment_id))
                resolution["metadata_missing_attachment_ids"].append(str(attachment_id))
            continue

        unresolved_attachment = dict(attachment)
        unresolved_attachment.pop("_canonical_scan_gate", None)
        unresolved_attachment["resolution_status"] = "unresolved"
        resolved_attachments.append(unresolved_attachment)
        if attachment_id:
            resolution["unresolved_attachment_ids"].append(str(attachment_id))

    enriched_payload["attachments"] = resolved_attachments
    enriched_payload["attachment_resolution"] = resolution
    return enriched_payload


def _upload_root() -> Path:
    return Path(os.environ.get("MOCK_UPLOAD_ROOT", "backend/media/mock_uploads"))


def _original_filename(payload: dict[str, Any], upload_file: Any | None) -> str:
    if upload_file is not None and getattr(upload_file, "name", None):
        return str(upload_file.name)
    return str(payload.get("filename") or payload.get("original_filename") or "metadata-only.txt")


def _safe_filename(filename: str) -> str:
    basename = Path(filename).name.strip() or "attachment"
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", basename)
    return sanitized[:120] or "attachment"


def _content_type(payload: dict[str, Any], upload_file: Any | None) -> str:
    if upload_file is not None and getattr(upload_file, "content_type", None):
        return str(upload_file.content_type)
    return str(payload.get("content_type") or "application/octet-stream")


def _infer_attachment_type(content_type: str, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if content_type.startswith("image/") or suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return "image"
    if content_type.startswith("video/") or suffix in {".mp4", ".mov", ".avi", ".mkv"}:
        return "video"
    if content_type == "application/pdf" or suffix == ".pdf":
        return "pdf"
    if suffix in {".txt", ".md"} or content_type.startswith("text/"):
        return "text"
    if suffix in {".doc", ".docx", ".hwp", ".hwpx"}:
        return "document"
    return "file"


def _infer_purpose(filename: str, attachment_type: str) -> str:
    lower_name = filename.lower()
    if "notice" in lower_name or "fine" in lower_name:
        return "fine_notice"
    if "blackbox" in lower_name or attachment_type == "video":
        return "blackbox_video"
    if "statement" in lower_name:
        return "accident_statement"
    if attachment_type == "image":
        return "accident_scene"
    return "unknown"


def _normalize_purpose(purpose: str) -> str:
    return purpose if purpose in SUPPORTED_PURPOSES else "unknown"


def _write_upload(
    stored_path: Path,
    upload_file: Any,
    *,
    max_bytes: int,
) -> int:
    size_bytes = 0
    try:
        with stored_path.open("wb") as file_handle:
            chunks = upload_file.chunks() if hasattr(upload_file, "chunks") else [upload_file.read()]
            for chunk in chunks:
                next_size = size_bytes + len(chunk)
                if next_size > max_bytes:
                    raise UploadTooLargeError(
                        size_bytes=next_size,
                        limit_bytes=max_bytes,
                    )
                file_handle.write(chunk)
                size_bytes = next_size
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise
    return size_bytes


def _positive_upload_limit(value: int | None) -> int:
    if value is None:
        return MAX_MOCK_UPLOAD_BYTES
    normalized = int(value)
    return normalized if normalized > 0 else MAX_MOCK_UPLOAD_BYTES


def _write_metadata(metadata_path: Path, attachment: dict[str, Any]) -> None:
    metadata_path.write_text(
        json.dumps(attachment, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_metadata(metadata_path: Path) -> dict[str, Any] | None:
    if not metadata_path.exists():
        return None
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _coerce_attachment_refs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_attachments = payload.get("attachments") or []
    attachments = []

    if isinstance(raw_attachments, list):
        for item in raw_attachments:
            if isinstance(item, dict):
                attachments.append(_normalize_inline_attachment(dict(item)))
            elif item:
                attachments.append({"attachment_id": str(item)})

    raw_attachment_ids = payload.get("attachment_ids") or []
    if isinstance(raw_attachment_ids, str):
        raw_attachment_ids = [raw_attachment_ids]

    for attachment_id in raw_attachment_ids:
        if not any(item.get("attachment_id") == attachment_id for item in attachments):
            attachments.append({"attachment_id": str(attachment_id)})

    return attachments


def _merge_attachment_metadata(
    attachment_ref: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    handoff = metadata.get("agent_handoff", {})
    attachment = {
        **attachment_ref,
        **handoff,
        "original_filename": metadata.get("original_filename"),
        "filename": metadata.get("filename"),
        "status": metadata.get("status"),
        "created_at": metadata.get("created_at"),
        "resolution_status": "resolved",
        "metadata_source": "mock_upload_registry",
    }
    return {key: value for key, value in attachment.items() if value is not None}


def _normalize_inline_attachment(attachment: dict[str, Any]) -> dict[str, Any]:
    if attachment.get("mime_type") and not attachment.get("content_type"):
        attachment["content_type"] = attachment["mime_type"]
    return attachment


def _has_inline_metadata(attachment: dict[str, Any]) -> bool:
    return any(
        attachment.get(field)
        for field in (
            "purpose",
            "type",
            "storage_uri",
            "content_type",
            "mime_type",
            "size_bytes",
            "filename",
            "original_filename",
        )
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
