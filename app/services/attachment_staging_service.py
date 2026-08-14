"""Neutral local attachment staging contract for canonical uploads.

This module provides a local Infrastructure Adapter used before a canonical
object-storage handoff. It intentionally contains no fixture or scenario
behavior and does not expose Explicit Mock URI schemes.
"""

from __future__ import annotations

import json
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


from app.services.attachment_staging_path_contract import (
    delete_staged_attachment_file,
    open_staged_attachment_file_for_write,
    prepare_staged_attachment_directory,
    read_staged_attachment_metadata,
    remove_empty_staged_attachment_directory,
    staging_root,
    write_staged_attachment_metadata,
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

DEFAULT_MAX_STAGING_BYTES = 20 * 1024 * 1024



class UploadTooLargeError(ValueError):
    """Raised before an oversized upload can enter local staging."""

    def __init__(self, *, size_bytes: int, limit_bytes: int) -> None:
        super().__init__("uploaded file exceeds the configured size limit")
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes


def register_staged_attachment(
    payload: dict[str, Any],
    upload_file: Any | None = None,
    *,
    max_upload_bytes: int | None = None,
) -> dict[str, Any]:
    """Write a local staging record for one canonical upload boundary."""

    upload_limit = _positive_upload_limit(max_upload_bytes)
    declared_size = getattr(upload_file, "size", None)
    if upload_file is not None and declared_size is not None and int(declared_size) > upload_limit:
        raise UploadTooLargeError(size_bytes=int(declared_size), limit_bytes=upload_limit)

    supplied_attachment_id = _text(payload.get("attachment_id"))
    attachment_id = (
        _validated_attachment_id(supplied_attachment_id)
        if supplied_attachment_id
        else f"att_{uuid4().hex[:12]}"
    )
    original_filename = _original_filename(payload, upload_file)
    safe_filename = _safe_filename(original_filename)
    content_type = _content_type(payload, upload_file)
    attachment_type = _text(payload.get("type")) or _infer_attachment_type(content_type, safe_filename)
    purpose = _normalize_purpose(_text(payload.get("purpose")) or _infer_purpose(safe_filename, attachment_type))
    staging_dir = prepare_staged_attachment_directory(attachment_id)

    stored_path: Path | None = None
    size_bytes = _positive_int(payload.get("size_bytes"))
    if upload_file is not None:
        stored_path = staging_dir / safe_filename
        try:
            size_bytes = _write_upload(attachment_id, safe_filename, upload_file, max_bytes=upload_limit)
        except UploadTooLargeError:
            delete_staged_attachment_file(attachment_id, safe_filename)
            remove_empty_staged_attachment_directory(attachment_id)
            raise

    storage_uri = (
        f"local://attachment-staging/{attachment_id}/{safe_filename}"
        if stored_path
        else _text(payload.get("storage_uri")) or f"local://attachment-staging/{attachment_id}/metadata"
    )
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
        "staging_status": "staged" if upload_file is not None else "metadata_registered",
        "created_at": now,
        "checks": {
            "accepted": size_bytes <= upload_limit,
            "size_limit_bytes": upload_limit,
            "extension": Path(safe_filename).suffix.lower(),
            "metadata_sidecar": f"local://attachment-staging/{attachment_id}/metadata.json",
        },
        "agent_handoff": {
            "attachment_id": attachment_id,
            "purpose": purpose,
            "type": attachment_type,
            "storage_uri": storage_uri,
            "content_type": content_type,
            "size_bytes": size_bytes,
        },
        "limitations": [],
    }
    _write_metadata(attachment_id, attachment)
    return attachment


def get_staged_attachment(attachment_id: str) -> dict[str, Any] | None:
    return _read_metadata(attachment_id)


def resolve_staged_attachment_references(payload: dict[str, Any]) -> dict[str, Any]:
    """Expand canonical scan-ready, staged, and inline attachment references."""

    enriched_payload = deepcopy(payload)
    resolved_attachments: list[dict[str, Any]] = []
    resolution = {
        "resolved_attachment_ids": [],
        "inline_attachment_ids": [],
        "metadata_missing_attachment_ids": [],
        "unresolved_attachment_ids": [],
    }
    for attachment in _coerce_attachment_refs(enriched_payload):
        attachment_id = _text(attachment.get("attachment_id"))
        if is_canonical_scan_ready_reference(attachment):
            resolved_attachments.append(merge_canonical_scan_ready_reference(attachment))
            if attachment_id:
                resolution["resolved_attachment_ids"].append(attachment_id)
            continue
        metadata = get_staged_attachment(attachment_id) if attachment_id else None
        if metadata:
            resolved_attachments.append(_merge_attachment_metadata(attachment, metadata))
            resolution["resolved_attachment_ids"].append(attachment_id)
            continue
        if _has_inline_metadata(attachment):
            inline = dict(attachment)
            inline.pop("_canonical_scan_gate", None)
            inline["resolution_status"] = "inline_metadata"
            resolved_attachments.append(inline)
            if attachment_id:
                resolution["inline_attachment_ids"].append(attachment_id)
                resolution["metadata_missing_attachment_ids"].append(attachment_id)
            continue
        unresolved = dict(attachment)
        unresolved.pop("_canonical_scan_gate", None)
        unresolved["resolution_status"] = "unresolved"
        resolved_attachments.append(unresolved)
        if attachment_id:
            resolution["unresolved_attachment_ids"].append(attachment_id)

    enriched_payload["attachments"] = resolved_attachments
    enriched_payload["attachment_resolution"] = resolution
    return enriched_payload


def _staging_root() -> Path:
    return staging_root()


def _validated_attachment_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
        raise ValueError("attachment_id must use the canonical safe identifier format")
    return value


def _write_upload(attachment_id: str, filename: str, upload_file: Any, *, max_bytes: int) -> int:
    size_bytes = 0
    try:
        with open_staged_attachment_file_for_write(attachment_id, filename) as handle:
            chunks = upload_file.chunks() if hasattr(upload_file, "chunks") else [upload_file.read()]
            for chunk in chunks:
                next_size = size_bytes + len(chunk)
                if next_size > max_bytes:
                    raise UploadTooLargeError(size_bytes=next_size, limit_bytes=max_bytes)
                handle.write(chunk)
                size_bytes = next_size
    except Exception:
        delete_staged_attachment_file(attachment_id, filename)
        raise
    return size_bytes


def _coerce_attachment_refs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    raw_attachments = payload.get("attachments") or []
    if isinstance(raw_attachments, list):
        for item in raw_attachments:
            if isinstance(item, dict):
                normalized = dict(item)
                if normalized.get("mime_type") and not normalized.get("content_type"):
                    normalized["content_type"] = normalized["mime_type"]
                attachments.append(normalized)
            elif item:
                attachments.append({"attachment_id": str(item)})
    raw_attachment_ids = payload.get("attachment_ids") or []
    if isinstance(raw_attachment_ids, str):
        raw_attachment_ids = [raw_attachment_ids]
    for attachment_id in raw_attachment_ids:
        if not any(item.get("attachment_id") == attachment_id for item in attachments):
            attachments.append({"attachment_id": str(attachment_id)})
    return attachments


def _merge_attachment_metadata(reference: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    handoff = metadata.get("agent_handoff") if isinstance(metadata.get("agent_handoff"), dict) else {}
    attachment = {
        **reference,
        **handoff,
        "original_filename": metadata.get("original_filename"),
        "filename": metadata.get("filename"),
        "staging_status": metadata.get("staging_status"),
        "created_at": metadata.get("created_at"),
        "resolution_status": "resolved",
        "metadata_source": "local_attachment_staging",
    }
    return {key: value for key, value in attachment.items() if value is not None}


def _has_inline_metadata(attachment: dict[str, Any]) -> bool:
    return any(attachment.get(field) for field in ("purpose", "type", "storage_uri", "content_type", "mime_type", "size_bytes", "filename", "original_filename"))


def _original_filename(payload: dict[str, Any], upload_file: Any | None) -> str:
    return _text(getattr(upload_file, "name", None) or payload.get("filename") or payload.get("original_filename")) or "attachment"


def _content_type(payload: dict[str, Any], upload_file: Any | None) -> str:
    return _text(getattr(upload_file, "content_type", None) or payload.get("content_type")) or "application/octet-stream"


def _safe_filename(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name.strip())[:120] or "attachment"


def _safe_segment(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", _text(value)) or "attachment"


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
    return "document" if suffix in {".doc", ".docx", ".hwp", ".hwpx"} else "file"


def _infer_purpose(filename: str, attachment_type: str) -> str:
    name = filename.lower()
    if "notice" in name or "fine" in name:
        return "fine_notice"
    if "blackbox" in name or attachment_type == "video":
        return "blackbox_video"
    if "statement" in name:
        return "accident_statement"
    return "accident_scene" if attachment_type == "image" else "unknown"


def _normalize_purpose(value: str) -> str:
    return value if value in SUPPORTED_PURPOSES else "unknown"


def _positive_upload_limit(value: int | None) -> int:
    normalized = _positive_int(value)
    return normalized or DEFAULT_MAX_STAGING_BYTES


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _write_metadata(attachment_id: str, attachment: dict[str, Any]) -> None:
    write_staged_attachment_metadata(attachment_id, json.dumps(attachment, ensure_ascii=False, indent=2))


def _read_metadata(attachment_id: str) -> dict[str, Any] | None:
    try:
        data = json.loads(read_staged_attachment_metadata(attachment_id))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
