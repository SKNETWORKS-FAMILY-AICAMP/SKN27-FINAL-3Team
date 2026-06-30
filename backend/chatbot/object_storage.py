"""Object storage adapter envelopes for canonical file and report metadata."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from django.conf import settings

OBJECT_STORAGE_POLICY_VERSION = "object_storage_adapter.v1"
DEFAULT_OBJECT_STORAGE_PROVIDER = "mock_s3"
DEFAULT_OBJECT_STORAGE_BUCKET = "skn27-demo-object-storage"
DEFAULT_OBJECT_STORAGE_PREFIX = "canonical"
DEFAULT_SIGNED_URL_TTL_SECONDS = 900


def object_storage_policy() -> dict[str, Any]:
    return {
        "policy_version": OBJECT_STORAGE_POLICY_VERSION,
        "backend": "object_storage",
        "provider": object_storage_provider(),
        "bucket": object_storage_bucket(),
        "prefix": object_storage_prefix(),
        "signed_url_ttl_seconds": signed_url_ttl_seconds(),
        "writes_binary": False,
        "persistence_state": "metadata_only_adapter",
        "fallback": "django_response_body",
    }


def object_storage_provider() -> str:
    return _settings_text("OBJECT_STORAGE_PROVIDER", DEFAULT_OBJECT_STORAGE_PROVIDER)


def object_storage_bucket() -> str:
    return _settings_text("OBJECT_STORAGE_BUCKET", DEFAULT_OBJECT_STORAGE_BUCKET)


def object_storage_prefix() -> str:
    return _settings_text("OBJECT_STORAGE_PREFIX", DEFAULT_OBJECT_STORAGE_PREFIX)


def signed_url_ttl_seconds() -> int:
    raw_value = getattr(
        settings,
        "OBJECT_STORAGE_SIGNED_URL_TTL_SECONDS",
        DEFAULT_SIGNED_URL_TTL_SECONDS,
    )
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_SIGNED_URL_TTL_SECONDS
    return value if value > 0 else DEFAULT_SIGNED_URL_TTL_SECONDS


def build_upload_storage_reference(
    attachment: dict[str, Any],
    *,
    owner_id: str = "",
) -> dict[str, Any]:
    attachment_id = _text(attachment.get("attachment_id")) or "attachment"
    session_id = _text(attachment.get("session_id")) or "unbound"
    filename = _safe_filename(
        attachment.get("filename")
        or attachment.get("original_filename")
        or f"{attachment_id}.bin"
    )
    key = _object_key(
        "uploads",
        _principal_key(owner_id),
        _key_component(session_id, "session"),
        _key_component(attachment_id, "attachment"),
        filename,
    )
    return _reference(
        resource_type="uploaded_file",
        resource_id=attachment_id,
        key=key,
        filename=filename,
        content_type=_text(attachment.get("content_type")) or "application/octet-stream",
        size_bytes=_positive_int(attachment.get("size_bytes")),
        source_uri=_text(attachment.get("storage_uri")),
    )


def build_report_storage_reference(
    *,
    report_id: str,
    owner_id: str = "",
    session_id: str = "",
    job_id: str = "",
    source_uri: str = "",
) -> dict[str, Any]:
    filename = _safe_filename(f"{report_id}.txt")
    key = _object_key(
        "reports",
        _principal_key(owner_id),
        _key_component(session_id or job_id or "unbound", "scope"),
        filename,
    )
    return _reference(
        resource_type="report",
        resource_id=report_id,
        key=key,
        filename=filename,
        content_type="text/plain; charset=utf-8",
        size_bytes=0,
        source_uri=source_uri,
    )


def storage_reference_from_uri(
    storage_uri: str,
    *,
    resource_type: str,
    resource_id: str,
    filename: str = "",
    content_type: str = "",
    size_bytes: int | None = None,
) -> dict[str, Any]:
    backend = storage_backend_for_uri(storage_uri)
    return {
        "policy_version": OBJECT_STORAGE_POLICY_VERSION,
        "backend": backend,
        "provider": _provider_for_backend(backend),
        "bucket": _bucket_from_uri(storage_uri),
        "key": _key_from_uri(storage_uri),
        "storage_uri": storage_uri,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "filename": filename,
        "content_type": content_type,
        "size_bytes": size_bytes or 0,
        "status": "legacy_reference" if backend != "object_storage" else "metadata_ready",
        "source_uri": "",
        "signed_url_ttl_seconds": signed_url_ttl_seconds(),
        "writes_binary": False,
        "persistence_state": "metadata_only_adapter",
    }


def storage_backend_for_uri(storage_uri: str) -> str:
    if storage_uri.startswith("s3://"):
        return "object_storage"
    if storage_uri.startswith("file://"):
        return "local_file"
    if storage_uri.startswith("mock://"):
        return "mock_placeholder"
    return "unknown"


def _reference(
    *,
    resource_type: str,
    resource_id: str,
    key: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    source_uri: str,
) -> dict[str, Any]:
    return {
        "policy_version": OBJECT_STORAGE_POLICY_VERSION,
        "backend": "object_storage",
        "provider": object_storage_provider(),
        "bucket": object_storage_bucket(),
        "key": key,
        "storage_uri": f"s3://{object_storage_bucket()}/{key}",
        "resource_type": resource_type,
        "resource_id": resource_id,
        "filename": filename,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "status": "metadata_ready",
        "source_uri": source_uri,
        "signed_url_ttl_seconds": signed_url_ttl_seconds(),
        "writes_binary": False,
        "persistence_state": "metadata_only_adapter",
    }


def _object_key(*parts: str) -> str:
    prefix = object_storage_prefix()
    key_parts = [_key_component(part, "object") for part in parts if part]
    if prefix:
        key_parts = [_key_component(part, "prefix") for part in prefix.split("/") if part] + key_parts
    return PurePosixPath(*key_parts).as_posix()


def _principal_key(owner_id: str) -> str:
    return _key_component(owner_id, "unowned")


def _key_component(value: Any, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._=-]+", "_", _text(value)).strip("._-")
    return (normalized[:100] or fallback)


def _safe_filename(value: Any) -> str:
    filename = PurePosixPath(_text(value)).name or "object.bin"
    return _key_component(filename, "object.bin")


def _settings_text(name: str, default: str) -> str:
    value = _text(getattr(settings, name, default))
    return value or default


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _positive_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _provider_for_backend(backend: str) -> str:
    if backend == "object_storage":
        return object_storage_provider()
    if backend == "local_file":
        return "local_file"
    if backend == "mock_placeholder":
        return "mock_sidecar"
    return "unknown"


def _bucket_from_uri(storage_uri: str) -> str:
    if not storage_uri.startswith("s3://"):
        return ""
    remainder = storage_uri.removeprefix("s3://")
    return remainder.split("/", 1)[0]


def _key_from_uri(storage_uri: str) -> str:
    if not storage_uri.startswith("s3://"):
        return ""
    remainder = storage_uri.removeprefix("s3://")
    parts = remainder.split("/", 1)
    return parts[1] if len(parts) == 2 else ""
