"""Physical retention enforcement for expired uploaded files."""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from chatbot.models import UploadedFile, UploadedFileStatus
from chatbot.object_storage import (
    delete_object,
    delete_source_uri,
    object_storage_bucket,
    object_storage_prefix,
    object_storage_quarantine_bucket,
    storage_reference_from_uri,
)


FILE_RETENTION_PURGE_BATCH_VERSION = "file_retention_purge_batch.v1"
FILE_RETENTION_PURGE_RECORD_VERSION = "file_retention_purge_record.v1"
DEFAULT_FILE_RETENTION_PURGE_LIMIT = 100
PURGED_SCAN_STATUS = "purged"
RETRY_SCAN_STATUS = "retention_purge_retry"
SUCCESSFUL_DELETE_STATUSES = {"deleted", "not_found"}

logger = logging.getLogger(__name__)


def purge_expired_uploads(
    *,
    limit: int | None = None,
    dry_run: bool = False,
    now: Any | None = None,
) -> dict[str, Any]:
    """Delete expired upload objects and retain only a non-sensitive tombstone."""

    cutoff = now or timezone.now()
    resolved_limit = _purge_limit(limit)
    queryset = (
        UploadedFile.objects.filter(
            Q(retention_expires_at__lte=cutoff) | Q(deleted_at__isnull=False)
        )
        .exclude(scan_status=PURGED_SCAN_STATUS)
        .order_by("retention_expires_at", "pk")
        .values_list("pk", flat=True)
    )
    if resolved_limit > 0:
        queryset = queryset[:resolved_limit]
    selected_pks = list(queryset)

    result = {
        "contract_version": FILE_RETENTION_PURGE_BATCH_VERSION,
        "status": "pass",
        "dry_run": bool(dry_run),
        "selected": len(selected_pks),
        "purged": 0,
        "retryable": 0,
        "skipped": 0,
    }
    if dry_run:
        return result

    for uploaded_file_pk in selected_pks:
        outcome = _purge_expired_upload(
            uploaded_file_pk,
            cutoff=cutoff,
        )
        result[outcome] += 1

    if result["retryable"]:
        result["status"] = "warn"
        logger.warning(
            "expired upload purge incomplete selected=%s purged=%s retryable=%s skipped=%s",
            result["selected"],
            result["purged"],
            result["retryable"],
            result["skipped"],
        )
    elif result["purged"]:
        logger.info(
            "expired upload purge completed selected=%s purged=%s skipped=%s",
            result["selected"],
            result["purged"],
            result["skipped"],
        )
    return result


def _purge_expired_upload(uploaded_file_pk: int, *, cutoff: Any) -> str:
    with transaction.atomic():
        uploaded_file = (
            UploadedFile.objects.select_for_update()
            .filter(pk=uploaded_file_pk)
            .first()
        )
        if (
            uploaded_file is None
            or uploaded_file.scan_status == PURGED_SCAN_STATUS
            or (
                uploaded_file.deleted_at is None
                and (
                    uploaded_file.retention_expires_at is None
                    or uploaded_file.retention_expires_at > cutoff
                )
            )
        ):
            return "skipped"

        references = _canonical_retention_references(uploaded_file)
        _fence_and_scrub(uploaded_file, references=references, now=cutoff)
        cleanup = {
            name: _delete_retention_reference(
                reference,
                attachment_id=uploaded_file.attachment_id,
                expected_resource_type=expected_resource_type,
                expected_bucket=expected_bucket,
            )
            for name, reference, expected_resource_type, expected_bucket in (
                (
                    "quarantine",
                    references.get("quarantine"),
                    "uploaded_file_quarantine",
                    object_storage_quarantine_bucket(),
                ),
                (
                    "clean",
                    references.get("clean"),
                    "uploaded_file",
                    object_storage_bucket(),
                ),
            )
        }
        if references.get("legacy_without_lifecycle") and not references.get(
            "quarantine"
        ):
            cleanup["quarantine"] = {
                "status": "not_found",
                "reason": "legacy_quarantine_not_applicable",
            }
        cleanup["local_source"] = _delete_retention_source(
            str(references.get("source_uri") or ""),
            attachment_id=uploaded_file.attachment_id,
        )
        completed = all(
            item.get("status") in SUCCESSFUL_DELETE_STATUSES
            for item in cleanup.values()
        )
        attempted_at = cutoff.isoformat()
        if completed:
            uploaded_file.scan_status = PURGED_SCAN_STATUS
            uploaded_file.metadata = {
                "retention_purge": {
                    "contract_version": FILE_RETENTION_PURGE_RECORD_VERSION,
                    "status": "purged",
                    "completed_at": attempted_at,
                    "quarantine_status": cleanup["quarantine"]["status"],
                    "clean_status": cleanup["clean"]["status"],
                    "local_source_status": cleanup["local_source"]["status"],
                }
            }
        else:
            uploaded_file.scan_status = RETRY_SCAN_STATUS
            uploaded_file.metadata = {
                "upload_storage_lifecycle": references,
                "retention_purge": {
                    "contract_version": FILE_RETENTION_PURGE_RECORD_VERSION,
                    "status": "retryable",
                    "attempted_at": attempted_at,
                    "quarantine": _safe_cleanup_summary(cleanup["quarantine"]),
                    "clean": _safe_cleanup_summary(cleanup["clean"]),
                    "local_source": _safe_cleanup_summary(
                        cleanup["local_source"]
                    ),
                },
            }
        uploaded_file.save(update_fields=_tombstone_update_fields())
        return "purged" if completed else "retryable"


def _fence_and_scrub(
    uploaded_file: UploadedFile,
    *,
    references: dict[str, Any],
    now: Any,
) -> None:
    uploaded_file.status = UploadedFileStatus.DELETED
    uploaded_file.deleted_at = uploaded_file.deleted_at or now
    uploaded_file.owner_id = ""
    uploaded_file.session = None
    uploaded_file.case = None
    uploaded_file.purpose = "deleted"
    uploaded_file.file_type = ""
    uploaded_file.original_filename = ""
    uploaded_file.content_type = ""
    uploaded_file.size_bytes = None
    uploaded_file.storage_uri = ""
    uploaded_file.privacy_risk = False
    uploaded_file.agent_handoff = {}
    uploaded_file.metadata = {"upload_storage_lifecycle": references}


def _canonical_retention_references(uploaded_file: UploadedFile) -> dict[str, Any]:
    metadata = uploaded_file.metadata if isinstance(uploaded_file.metadata, dict) else {}
    lifecycle = metadata.get("upload_storage_lifecycle")
    lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
    clean = lifecycle.get("clean") or metadata.get("object_storage")
    if not isinstance(clean, dict) and uploaded_file.storage_uri:
        clean = storage_reference_from_uri(
            uploaded_file.storage_uri,
            resource_type="uploaded_file",
            resource_id=uploaded_file.attachment_id,
            filename=uploaded_file.original_filename,
            content_type=uploaded_file.content_type,
            size_bytes=uploaded_file.size_bytes,
        )
    legacy_without_lifecycle = bool(
        lifecycle.get("legacy_without_lifecycle")
    ) or not bool(lifecycle)
    return {
        "contract_version": "upload_storage_lifecycle.v1",
        "quarantine": _minimal_storage_reference(lifecycle.get("quarantine")),
        "clean": _minimal_storage_reference(clean),
        "source_uri": str(
            lifecycle.get("source_uri")
            or metadata.get("source_storage_uri")
            or ""
        ),
        "legacy_without_lifecycle": legacy_without_lifecycle,
    }


def _delete_retention_source(
    source_uri: str,
    *,
    attachment_id: str,
) -> dict[str, Any]:
    try:
        return delete_source_uri(source_uri, attachment_id=attachment_id)
    except Exception as exc:  # pragma: no cover - defensive local storage boundary.
        return {
            "status": "skipped",
            "reason": "local_source_delete_failed",
            "error_code": exc.__class__.__name__,
        }


def _minimal_storage_reference(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed_keys = {
        "policy_version",
        "backend",
        "provider",
        "bucket",
        "key",
        "resource_type",
        "resource_id",
    }
    return {
        key: value[key]
        for key in allowed_keys
        if value.get(key) not in (None, "")
    }


def _delete_retention_reference(
    reference: Any,
    *,
    attachment_id: str,
    expected_resource_type: str,
    expected_bucket: str,
) -> dict[str, Any]:
    reason = _reference_validation_error(
        reference,
        attachment_id=attachment_id,
        expected_resource_type=expected_resource_type,
        expected_bucket=expected_bucket,
    )
    if reason:
        return {"status": "skipped", "reason": reason}
    try:
        result = delete_object(dict(reference))
    except Exception as exc:  # pragma: no cover - defensive storage boundary.
        return {
            "status": "skipped",
            "reason": "storage_delete_failed",
            "error_code": exc.__class__.__name__,
        }
    if (
        expected_resource_type == "uploaded_file"
        and str(reference.get("provider") or "") == "s3"
        and result.get("status") in SUCCESSFUL_DELETE_STATUSES
        and not result.get("permanent")
    ):
        return {
            "status": "skipped",
            "reason": "permanent_delete_unverified",
        }
    return result


def _reference_validation_error(
    reference: Any,
    *,
    attachment_id: str,
    expected_resource_type: str,
    expected_bucket: str,
) -> str:
    if not isinstance(reference, dict) or not reference:
        return "storage_reference_missing"
    if str(reference.get("resource_type") or "") != expected_resource_type:
        return "storage_resource_type_mismatch"
    if str(reference.get("resource_id") or "") != attachment_id:
        return "storage_resource_id_mismatch"
    if str(reference.get("bucket") or "") != expected_bucket:
        return "storage_bucket_mismatch"
    key = str(reference.get("key") or "")
    prefix = str(object_storage_prefix() or "").strip("/")
    expected_key_prefix = f"{prefix}/uploads/" if prefix else "uploads/"
    if (
        not key.startswith(expected_key_prefix)
        or ".." in key.split("/")
        or "\\" in key
    ):
        return "storage_key_out_of_scope"
    return ""


def _safe_cleanup_summary(result: dict[str, Any]) -> dict[str, str]:
    return {
        "status": str(result.get("status") or "skipped"),
        "reason": str(result.get("reason") or ""),
        "error_code": str(result.get("error_code") or ""),
    }


def _purge_limit(value: int | None) -> int:
    raw_value = (
        value
        if value is not None
        else getattr(
            settings,
            "FILE_RETENTION_PURGE_LIMIT",
            DEFAULT_FILE_RETENTION_PURGE_LIMIT,
        )
    )
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_FILE_RETENTION_PURGE_LIMIT
    return parsed if parsed > 0 else DEFAULT_FILE_RETENTION_PURGE_LIMIT


def _tombstone_update_fields() -> list[str]:
    return [
        "status",
        "scan_status",
        "deleted_at",
        "owner_id",
        "session",
        "case",
        "purpose",
        "file_type",
        "original_filename",
        "content_type",
        "size_bytes",
        "storage_uri",
        "privacy_risk",
        "agent_handoff",
        "metadata",
        "updated_at",
    ]
