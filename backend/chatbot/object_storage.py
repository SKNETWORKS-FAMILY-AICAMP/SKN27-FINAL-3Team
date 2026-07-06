"""Object storage adapter envelopes for canonical file and report metadata."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from django.conf import settings

OBJECT_STORAGE_POLICY_VERSION = "object_storage_adapter.v1"
DEFAULT_OBJECT_STORAGE_PROVIDER = "mock_s3"
DEFAULT_OBJECT_STORAGE_BUCKET = "skn27-demo-object-storage"
DEFAULT_OBJECT_STORAGE_PREFIX = "canonical"
DEFAULT_SIGNED_URL_TTL_SECONDS = 900
DEFAULT_LOCAL_OBJECT_STORAGE_ROOT = "backend/media/mock_object_storage"


def object_storage_policy() -> dict[str, Any]:
    provider = object_storage_provider()
    writes_binary = provider in {"mock_s3", "s3"}
    return {
        "policy_version": OBJECT_STORAGE_POLICY_VERSION,
        "backend": "object_storage",
        "provider": provider,
        "bucket": object_storage_bucket(),
        "prefix": object_storage_prefix(),
        "signed_url_ttl_seconds": signed_url_ttl_seconds(),
        "writes_binary": writes_binary,
        "persistence_state": "binary_adapter" if writes_binary else "metadata_only_adapter",
        "fallback": "django_response_body",
        "local_root": str(local_object_storage_root()) if provider == "mock_s3" else "",
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


def local_object_storage_root() -> Path:
    return Path(
        _settings_text("OBJECT_STORAGE_LOCAL_ROOT", DEFAULT_LOCAL_OBJECT_STORAGE_ROOT)
    )


def write_object(
    reference: dict[str, Any],
    data: bytes | str,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = _text(reference.get("provider")) or object_storage_provider()
    body = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    if provider == "mock_s3":
        return _write_mock_s3(reference, body, metadata=metadata)
    if provider == "s3":
        return _write_s3(reference, body, metadata=metadata)
    return _write_skipped(reference, reason="unsupported_provider")


def write_object_from_source_uri(
    reference: dict[str, Any],
    *,
    fallback_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_uri = _text(reference.get("source_uri"))
    source_path = _mock_upload_path_from_uri(source_uri)
    if source_path and source_path.exists():
        data = source_path.read_bytes()
    else:
        data = json.dumps(fallback_payload or reference, ensure_ascii=False, default=str).encode("utf-8")
    return write_object(
        reference,
        data,
        metadata={
            "source_uri": source_uri,
            "resource_type": reference.get("resource_type"),
            "resource_id": reference.get("resource_id"),
        },
    )


def copy_object(source_reference: dict[str, Any], target_reference: dict[str, Any]) -> dict[str, Any]:
    provider = _text(target_reference.get("provider")) or object_storage_provider()
    if provider == "mock_s3":
        source_path = _local_object_path(source_reference)
        target_path = _local_object_path(target_reference)
        if not source_path.exists():
            return _write_skipped(target_reference, reason="source_object_missing")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)
        return _write_result(target_reference, status="copied", size_bytes=target_path.stat().st_size)
    if provider == "s3":
        client = _boto3_client()
        if client is None:
            return _write_skipped(target_reference, reason="boto3_unavailable")
        try:
            client.copy_object(
                Bucket=_text(target_reference.get("bucket")) or object_storage_bucket(),
                Key=_text(target_reference.get("key")),
                CopySource={
                    "Bucket": _text(source_reference.get("bucket")) or object_storage_bucket(),
                    "Key": _text(source_reference.get("key")),
                },
            )
        except Exception as exc:
            return _write_skipped(target_reference, **_storage_error_kwargs(exc))
        return _write_result(target_reference, status="copied", size_bytes=0)
    return _write_skipped(target_reference, reason="unsupported_provider")


def object_exists(reference: dict[str, Any]) -> bool:
    provider = _text(reference.get("provider")) or object_storage_provider()
    if provider == "mock_s3":
        return _local_object_path(reference).exists()
    if provider == "s3":
        client = _boto3_client()
        if client is None:
            return False
        try:
            client.head_object(
                Bucket=_text(reference.get("bucket")) or object_storage_bucket(),
                Key=_text(reference.get("key")),
            )
        except Exception:
            return False
        return True
    return False


def read_object_bytes(reference: dict[str, Any]) -> bytes | None:
    provider = _text(reference.get("provider")) or object_storage_provider()
    if provider == "mock_s3":
        object_path = _local_object_path(reference)
        if object_path.exists() and object_path.is_file():
            return object_path.read_bytes()
        return None
    if provider == "s3":
        client = _boto3_client()
        if client is None:
            return None
        try:
            response = client.get_object(
                Bucket=_text(reference.get("bucket")) or object_storage_bucket(),
                Key=_text(reference.get("key")),
            )
        except Exception:
            return None
        body = response.get("Body")
        if body is None:
            return None
        return body.read()
    return None


def presign_get(reference: dict[str, Any], *, ttl_seconds: int | None = None) -> dict[str, Any]:
    provider = _text(reference.get("provider")) or object_storage_provider()
    ttl = ttl_seconds or signed_url_ttl_seconds()
    if provider == "mock_s3":
        return {
            "status": "ready",
            "provider": provider,
            "url": f"mock-s3://{reference.get('bucket')}/{reference.get('key')}?ttl={ttl}",
            "ttl_seconds": ttl,
        }
    if provider == "s3":
        client = _boto3_client()
        if client is None:
            return {"status": "unavailable", "provider": provider, "reason": "boto3_unavailable"}
        try:
            url = client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": _text(reference.get("bucket")) or object_storage_bucket(),
                    "Key": _text(reference.get("key")),
                },
                ExpiresIn=ttl,
            )
        except Exception as exc:
            return {"status": "unavailable", "provider": provider, **_storage_error_kwargs(exc)}
        return {"status": "ready", "provider": provider, "url": url, "ttl_seconds": ttl}
    return {"status": "unavailable", "provider": provider, "reason": "unsupported_provider"}


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
        "writes_binary": object_storage_policy()["writes_binary"] if backend == "object_storage" else False,
        "persistence_state": object_storage_policy()["persistence_state"] if backend == "object_storage" else "metadata_only_adapter",
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
        "writes_binary": object_storage_policy()["writes_binary"],
        "persistence_state": object_storage_policy()["persistence_state"],
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
    value = _text(getattr(settings, name, "") or os.environ.get(name, "") or default)
    return value or default


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _positive_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _write_mock_s3(
    reference: dict[str, Any],
    body: bytes,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    object_path = _local_object_path(reference)
    object_path.parent.mkdir(parents=True, exist_ok=True)
    object_path.write_bytes(body)
    if metadata is not None:
        object_path.with_suffix(object_path.suffix + ".metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    return _write_result(reference, status="written", size_bytes=len(body), local_path=object_path)


def _write_s3(
    reference: dict[str, Any],
    body: bytes,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    client = _boto3_client()
    if client is None:
        return _write_skipped(reference, reason="boto3_unavailable")
    try:
        client.put_object(
            Bucket=_text(reference.get("bucket")) or object_storage_bucket(),
            Key=_text(reference.get("key")),
            Body=body,
            ContentType=_text(reference.get("content_type")) or "application/octet-stream",
            Metadata={key: _text(value) for key, value in (metadata or {}).items() if value is not None},
        )
    except Exception as exc:
        return _write_skipped(reference, **_storage_error_kwargs(exc))
    return _write_result(reference, status="written", size_bytes=len(body))


def _write_result(
    reference: dict[str, Any],
    *,
    status: str,
    size_bytes: int,
    local_path: Path | None = None,
) -> dict[str, Any]:
    result = {
        "contract_version": "object_storage_write.v1",
        "status": status,
        "provider": _text(reference.get("provider")) or object_storage_provider(),
        "bucket": _text(reference.get("bucket")) or object_storage_bucket(),
        "key": _text(reference.get("key")),
        "storage_uri": _text(reference.get("storage_uri")),
        "writes_binary": True,
        "persistence_state": "binary_adapter",
        "size_bytes": size_bytes,
        "exists": object_exists(reference),
    }
    if local_path is not None:
        result["local_path"] = str(local_path)
    return result


def _write_skipped(
    reference: dict[str, Any],
    *,
    reason: str,
    error_class: str = "",
    message: str = "",
) -> dict[str, Any]:
    error: dict[str, str] = {"reason": reason}
    if error_class:
        error["class"] = error_class
    if message:
        error["message"] = message
    return {
        "contract_version": "object_storage_write.v1",
        "status": "skipped",
        "reason": reason,
        "error": error,
        "provider": _text(reference.get("provider")) or object_storage_provider(),
        "bucket": _text(reference.get("bucket")) or object_storage_bucket(),
        "key": _text(reference.get("key")),
        "storage_uri": _text(reference.get("storage_uri")),
        "writes_binary": False,
        "persistence_state": "metadata_only_adapter",
        "exists": False,
    }


def _storage_error_kwargs(exc: Exception) -> dict[str, str]:
    class_name = exc.__class__.__name__
    reason_by_class = {
        "NoCredentialsError": "no_credentials",
        "PartialCredentialsError": "partial_credentials",
        "NoRegionError": "missing_region",
        "EndpointConnectionError": "endpoint_connection_failed",
        "ConnectionClosedError": "connection_closed",
        "ConnectTimeoutError": "connection_timeout",
        "ReadTimeoutError": "read_timeout",
        "ClientError": "s3_client_error",
    }
    return {
        "reason": reason_by_class.get(class_name, "s3_operation_failed"),
        "error_class": class_name,
        "message": _truncate_error_message(exc),
    }


def _truncate_error_message(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    if not message:
        return ""
    if len(message) > 180:
        return f"{message[:177]}..."
    return message


def _local_object_path(reference: dict[str, Any]) -> Path:
    root = local_object_storage_root().resolve()
    bucket = _key_component(reference.get("bucket") or object_storage_bucket(), "bucket")
    key = PurePosixPath(_text(reference.get("key"))).as_posix().lstrip("/")
    object_path = (root / bucket / Path(*PurePosixPath(key).parts)).resolve()
    if root != object_path and root not in object_path.parents:
        raise ValueError("object storage key escaped local root")
    return object_path


def _mock_upload_path_from_uri(source_uri: str) -> Path | None:
    if not source_uri.startswith("mock://uploads/"):
        return None
    relative = source_uri.removeprefix("mock://uploads/").strip("/")
    if not relative:
        return None
    root = Path(
        getattr(settings, "MOCK_UPLOAD_ROOT", "")
        or os.environ.get("MOCK_UPLOAD_ROOT", "backend/media/mock_uploads")
    ).resolve()
    source_path = (root / Path(*PurePosixPath(relative).parts)).resolve()
    if root != source_path and root not in source_path.parents:
        return None
    return source_path


def _boto3_client():
    try:
        import boto3  # type: ignore
    except ImportError:
        return None
    kwargs: dict[str, Any] = {}
    endpoint_url = _settings_text("OBJECT_STORAGE_ENDPOINT_URL", "")
    region_name = _settings_text("OBJECT_STORAGE_REGION", "") or os.environ.get("AWS_DEFAULT_REGION", "")
    access_key_id = _settings_text("OBJECT_STORAGE_ACCESS_KEY_ID", "")
    secret_access_key = _settings_text("OBJECT_STORAGE_SECRET_ACCESS_KEY", "")
    session_token = _settings_text("OBJECT_STORAGE_SESSION_TOKEN", "")
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    if region_name:
        kwargs["region_name"] = region_name
    if access_key_id:
        kwargs["aws_access_key_id"] = access_key_id
    if secret_access_key:
        kwargs["aws_secret_access_key"] = secret_access_key
    if session_token:
        kwargs["aws_session_token"] = session_token
    return boto3.client("s3", **kwargs)


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
