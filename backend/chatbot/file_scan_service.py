"""File scan policy service for canonical upload handoff gating."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import socket
import struct
from contextlib import closing
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
from urllib import error as urllib_error
from urllib import request as urllib_request
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from app.security.pii_masking import sanitize_pii
from app.services.attachment_mock_service import CANONICAL_SCAN_GATE_MARKER
from chatbot.models import UploadedFile, UploadedFileStatus
from chatbot.object_storage import (
    delete_object,
    read_object_bytes,
    write_object,
)
from chatbot.repositories import access_subject_from_payload


FILE_SCAN_RESULT_VERSION = "file_scan_result.v1"
ATTACHMENT_SCAN_GATE_VERSION = "attachment_scan_gate.v1"
DEFAULT_MAX_SCAN_BYTES = 50 * 1024 * 1024
DEFAULT_SCAN_TIMEOUT_SECONDS = 10
DEFAULT_EXTERNAL_INLINE_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_SCAN_CLAIM_STALE_AFTER_SECONDS = 300
DEFAULT_SCAN_RETRY_BACKOFF_SECONDS = 60
DEFAULT_MAX_ATTACHMENTS_PER_REQUEST = 20
DANGEROUS_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".exe",
    ".jar",
    ".js",
    ".msi",
    ".ps1",
    ".scr",
    ".vbs",
}
PII_PATTERNS = (
    re.compile(r"01[016789]-?\d{3,4}-?\d{4}"),
    re.compile(r"\d{6}-[1-4]\d{6}"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)

logger = logging.getLogger(__name__)
_SOURCE_BYTES_UNSET = object()


def scan_uploaded_file(uploaded_file: UploadedFile) -> dict[str, Any]:
    """Claim, scan, and promote one quarantined upload with fencing."""

    claimed_file, claim_token, skip_reason = _claim_uploaded_file_scan(uploaded_file.pk)
    if claimed_file is None:
        return _skipped_scan_result(uploaded_file, reason=skip_reason)

    source_bytes = _source_snapshot_for_scan(claimed_file)
    try:
        result = build_file_scan_result(
            claimed_file,
            source_bytes=source_bytes,
        )
    except Exception as exc:  # pragma: no cover - defensive provider boundary.
        logger.warning("file scan failed error_type=%s", exc.__class__.__name__)
        result = _scan_operational_error_result(claimed_file, reason="scan_failed")
    if result["status"] == "clean":
        if not _renew_file_scan_claim(uploaded_file.pk, claim_token=claim_token):
            return {
                **result,
                "status": "skipped",
                "scan_status": "scanning",
                "reason": "scan_claim_lost",
            }

    if not _persist_file_scan_result(
        uploaded_file.pk,
        claim_token=claim_token,
        result=result,
        source_bytes=source_bytes,
    ):
        return {
            **result,
            "status": "skipped",
            "scan_status": "scanning",
            "reason": "scan_claim_lost",
        }
    return result


def process_uploaded_file_scans(*, limit: int = 20) -> dict[str, Any]:
    now = timezone.now()
    stale_cutoff = now - timedelta(seconds=_scan_claim_stale_after_seconds())
    retry_cutoff = now - timedelta(seconds=_scan_retry_backoff_seconds())
    queryset = (
        UploadedFile.objects.filter(deleted_at__isnull=True)
        .filter(
            Q(retention_expires_at__isnull=True)
            | Q(retention_expires_at__gt=now)
        )
        .filter(
            Q(status=UploadedFileStatus.UPLOADED, scan_status="not_started")
            | Q(
                status=UploadedFileStatus.UPLOADED,
                scan_status="error",
                updated_at__lte=retry_cutoff,
            )
            | Q(
                status=UploadedFileStatus.SCANNING,
                scan_status="scanning",
                updated_at__lte=stale_cutoff,
            )
        )
        .order_by("created_at")
    )
    if limit > 0:
        queryset = queryset[:limit]

    results = []
    clean_count = 0
    rejected_count = 0
    error_count = 0
    skipped_count = 0
    for uploaded_file in queryset:
        result = scan_uploaded_file(uploaded_file)
        if result["status"] == "skipped":
            skipped_count += 1
            continue
        results.append(result)
        if result["status"] == "rejected":
            rejected_count += 1
        elif result["status"] == "error":
            error_count += 1
        else:
            clean_count += 1

    return {
        "contract_version": "file_scan_batch.v1",
        "status": "pass" if rejected_count == 0 and error_count == 0 else "warn",
        "processed": len(results),
        "clean": clean_count,
        "rejected": rejected_count,
        "error": error_count,
        "skipped": skipped_count,
        "results": results,
    }


def read_scan_ready_attachment_bytes(
    attachment_id: str,
    *,
    expected_storage_uri: str,
) -> bytes | None:
    """Read a clean object while fencing concurrent retention or deletion."""

    normalized_attachment_id = str(attachment_id or "").strip()
    normalized_storage_uri = str(expected_storage_uri or "").strip()
    if not normalized_attachment_id or not normalized_storage_uri.startswith("s3://"):
        return None
    with transaction.atomic():
        uploaded_file = (
            UploadedFile.objects.select_for_update()
            .filter(
                attachment_id=normalized_attachment_id,
                status=UploadedFileStatus.READY,
                scan_status="clean",
                deleted_at__isnull=True,
            )
            .first()
        )
        if (
            uploaded_file is None
            or _inactive_upload_reason(uploaded_file, now=timezone.now())
            or uploaded_file.storage_uri != normalized_storage_uri
        ):
            return None
        reference = _clean_storage_reference(uploaded_file)
        if (
            not reference
            or str(reference.get("storage_uri") or "") != normalized_storage_uri
            or str(reference.get("resource_type") or "") != "uploaded_file"
            or str(reference.get("resource_id") or "") != normalized_attachment_id
        ):
            return None
        return read_object_bytes(reference)


def build_file_scan_result(
    uploaded_file: UploadedFile,
    *,
    source_bytes: bytes | None | object = _SOURCE_BYTES_UNSET,
) -> dict[str, Any]:
    findings = []
    max_bytes = int(getattr(settings, "FILE_SCAN_MAX_BYTES", DEFAULT_MAX_SCAN_BYTES))
    size_bytes = uploaded_file.size_bytes or 0
    extension = Path(uploaded_file.original_filename or "").suffix.lower()
    if source_bytes is _SOURCE_BYTES_UNSET:
        source_bytes = (
            _quarantine_object_bytes(uploaded_file)
            if size_bytes <= max_bytes
            else None
        )
    elif source_bytes is not None:
        source_bytes = bytes(source_bytes)
    searchable_text = _searchable_metadata(uploaded_file)
    if source_bytes is not None:
        searchable_text = f"{searchable_text}\n{source_bytes.decode('utf-8', errors='ignore')}"
    provider = str(getattr(settings, "FILE_SCAN_PROVIDER", "local_policy") or "local_policy")

    if size_bytes > max_bytes:
        findings.append(
            {
                "category": "policy",
                "code": "file_too_large",
                "severity": "high",
                "message": "File size exceeds the configured scan limit.",
            }
        )
    if extension in DANGEROUS_EXTENSIONS:
        findings.append(
            {
                "category": "policy",
                "code": "dangerous_extension",
                "severity": "high",
                "message": "Executable or script-like files are not accepted.",
                "extension": extension,
            }
        )
    if source_bytes is not None and b"eicar" in source_bytes.lower():
        findings.append(
            {
                "category": "virus",
                "code": "eicar_signature",
                "severity": "critical",
                "message": "Mock virus signature detected.",
            }
        )

    pii_matches = []
    for pattern in PII_PATTERNS:
        if pattern.search(searchable_text):
            pii_matches.append(pattern.pattern)
    if pii_matches:
        findings.append(
            {
                "category": "pii",
                "code": "pii_pattern_detected",
                "severity": "medium",
                "message": "Potential personal information pattern detected in metadata.",
                "pattern_count": len(pii_matches),
            }
        )

    reject_pii = bool(getattr(settings, "FILE_SCAN_REJECT_PII", False))
    rejected = any(item["severity"] in {"high", "critical"} for item in findings)
    if reject_pii and any(item["category"] == "pii" for item in findings):
        rejected = True

    provider_findings = (
        []
        if rejected
        else _provider_scan_findings(
            uploaded_file,
            provider=provider,
            source_bytes=source_bytes,
        )
    )
    findings.extend(provider_findings)
    scanner_error = any(item.get("code") == "scanner_unavailable" for item in provider_findings)
    if any(
        item["severity"] in {"high", "critical"}
        and item.get("code") != "scanner_unavailable"
        for item in provider_findings
    ):
        rejected = True

    result_status = "rejected" if rejected else "error" if scanner_error else "clean"

    return {
        "contract_version": FILE_SCAN_RESULT_VERSION,
        "scanner": provider,
        "attachment_id": uploaded_file.attachment_id,
        "status": result_status,
        "scan_status": result_status,
        "privacy_risk": bool(pii_matches),
        "findings": findings,
        "scanned_at": timezone.now().isoformat(),
        "policy": {
            "max_bytes": max_bytes,
            "dangerous_extensions": sorted(DANGEROUS_EXTENSIONS),
            "reject_pii": reject_pii,
            "provider": provider,
        },
    }


def _provider_scan_findings(
    uploaded_file: UploadedFile,
    *,
    provider: str,
    source_bytes: bytes | None,
) -> list[dict[str, Any]]:
    if source_bytes is None:
        return [_scanner_unavailable_finding(provider=provider, reason="source_object_unavailable")]
    if provider == "local_policy":
        return []
    if provider == "clamav":
        return _clamav_scan_findings(source_bytes)
    if provider == "external":
        return _external_scan_findings(uploaded_file, source_bytes=source_bytes)
    return [_scanner_unavailable_finding(provider=provider, reason="unsupported_provider")]


def _clamav_scan_findings(source_bytes: bytes) -> list[dict[str, Any]]:
    host = str(getattr(settings, "FILE_SCAN_CLAMAV_HOST", "") or "").strip()
    port = int(getattr(settings, "FILE_SCAN_CLAMAV_PORT", 3310) or 3310)
    if not host:
        return [_scanner_unavailable_finding(provider="clamav", reason="missing_host")]

    try:
        response = _clamav_instream_scan(host=host, port=port, source_bytes=source_bytes)
    except Exception as exc:
        return [_scanner_unavailable_finding(provider="clamav", reason=_exception_reason(exc), exc=exc)]
    return _clamav_findings_from_response(response)


def _external_scan_findings(
    uploaded_file: UploadedFile,
    *,
    source_bytes: bytes,
) -> list[dict[str, Any]]:
    url = str(getattr(settings, "FILE_SCAN_EXTERNAL_URL", "") or "").strip()
    api_key = str(getattr(settings, "FILE_SCAN_EXTERNAL_API_KEY", "") or "").strip()
    if not url:
        return [_scanner_unavailable_finding(provider="external", reason="missing_url")]
    if not api_key:
        return [_scanner_unavailable_finding(provider="external", reason="missing_api_key")]
    inline_max = int(
        getattr(settings, "FILE_SCAN_EXTERNAL_INLINE_MAX_BYTES", DEFAULT_EXTERNAL_INLINE_MAX_BYTES)
        or DEFAULT_EXTERNAL_INLINE_MAX_BYTES
    )
    if len(source_bytes) > inline_max:
        return [
            _scanner_unavailable_finding(
                provider="external",
                reason="source_exceeds_inline_limit",
            )
        ]

    try:
        response = _post_external_scan_request(
            uploaded_file,
            url=url,
            api_key=api_key,
            source_bytes=source_bytes,
        )
    except Exception as exc:
        return [_scanner_unavailable_finding(provider="external", reason=_exception_reason(exc), exc=exc)]
    return _external_findings_from_response(response)


def _claim_uploaded_file_scan(
    uploaded_file_pk: int,
) -> tuple[UploadedFile | None, str, str]:
    now = timezone.now()
    stale_cutoff = now - timedelta(seconds=_scan_claim_stale_after_seconds())
    with transaction.atomic():
        uploaded_file = UploadedFile.objects.select_for_update().get(pk=uploaded_file_pk)
        retention_reason = _inactive_upload_reason(uploaded_file, now=now)
        if retention_reason:
            return None, "", retention_reason
        if uploaded_file.status in {UploadedFileStatus.READY, UploadedFileStatus.REJECTED}:
            return None, "", "scan_already_terminal"
        if uploaded_file.status == UploadedFileStatus.PENDING:
            return None, "", "upload_not_ready"
        if (
            uploaded_file.status == UploadedFileStatus.SCANNING
            and uploaded_file.scan_status == "scanning"
            and uploaded_file.updated_at > stale_cutoff
        ):
            return None, "", "scan_in_progress"
        if uploaded_file.status not in {
            UploadedFileStatus.UPLOADED,
            UploadedFileStatus.SCANNING,
        }:
            return None, "", "upload_not_scannable"

        claim_token = uuid4().hex
        metadata = dict(uploaded_file.metadata or {})
        metadata["scan_started_at"] = now.isoformat()
        metadata["scan_claim"] = {
            "contract_version": "file_scan_claim.v1",
            "token": claim_token,
            "status": "active",
            "claimed_at": now.isoformat(),
        }
        uploaded_file.status = UploadedFileStatus.SCANNING
        uploaded_file.scan_status = "scanning"
        uploaded_file.metadata = metadata
        uploaded_file.save(
            update_fields=["status", "scan_status", "metadata", "updated_at"]
        )
    return uploaded_file, claim_token, ""


def _persist_file_scan_result(
    uploaded_file_pk: int,
    *,
    claim_token: str,
    result: dict[str, Any],
    source_bytes: bytes | None,
) -> bool:
    with transaction.atomic():
        scanned_file = UploadedFile.objects.select_for_update().get(pk=uploaded_file_pk)
        metadata = dict(scanned_file.metadata or {})
        scan_claim = dict(metadata.get("scan_claim") or {})
        if (
            scanned_file.status != UploadedFileStatus.SCANNING
            or scanned_file.scan_status != "scanning"
            or scan_claim.get("token") != claim_token
            or _inactive_upload_reason(scanned_file, now=timezone.now())
        ):
            return False

        if result.get("status") == "clean":
            try:
                promotion = _promote_scanned_snapshot(
                    scanned_file,
                    source_bytes=source_bytes,
                )
            except Exception as exc:  # pragma: no cover - defensive storage boundary.
                logger.warning(
                    "file scan promotion failed error_type=%s",
                    exc.__class__.__name__,
                )
                promotion = _promotion_result(
                    verified=False,
                    reason="promotion_failed",
                )
            result["promotion"] = promotion
            if not promotion["verified"]:
                result["status"] = "error"
                result["scan_status"] = "error"
                result["findings"].append(
                    {
                        "category": "storage",
                        "code": "clean_promotion_failed",
                        "severity": "high",
                        "message": "Scanned file could not be promoted to clean object storage.",
                        "reason": promotion["reason"],
                    }
                )

        result_status = str(result.get("status") or "error")
        final_status = {
            "clean": UploadedFileStatus.READY,
            "rejected": UploadedFileStatus.REJECTED,
            "error": UploadedFileStatus.UPLOADED,
        }.get(result_status, UploadedFileStatus.UPLOADED)
        final_scan_status = (
            result_status if result_status in {"clean", "rejected"} else "error"
        )

        checks = dict(metadata.get("checks") or {})
        checks["file_scan"] = {
            "contract_version": FILE_SCAN_RESULT_VERSION,
            "status": result_status,
            "scan_status": final_scan_status,
            "finding_count": len(result.get("findings") or []),
        }
        metadata["checks"] = checks
        metadata["scan_result"] = result
        metadata["scan_completed_at"] = result["scanned_at"]
        metadata["scan_claim"] = {
            **scan_claim,
            "status": "completed",
            "completed_at": result["scanned_at"],
            "result": result_status,
        }
        lifecycle = dict(metadata.get("upload_storage_lifecycle") or {})
        lifecycle["state"] = {
            "clean": "promoted",
            "rejected": "rejected",
            "error": "scan_error",
        }.get(result_status, "scan_error")
        if result_status != "clean":
            clean_reference = _clean_storage_reference(scanned_file)
            lifecycle["clean_cleanup"] = (
                delete_object(clean_reference)
                if clean_reference
                else {"status": "skipped", "reason": "clean_reference_missing"}
            )
        if isinstance(result.get("promotion"), dict):
            lifecycle["promotion"] = result["promotion"]
        if result_status == "clean":
            clean_reference = _clean_storage_reference(scanned_file)
            clean_reference.update(
                {
                    "status": "ready",
                    "writes_binary": True,
                    "persistence_state": "binary_adapter",
                    "write_result": result.get("promotion") or {},
                }
            )
            lifecycle["clean"] = clean_reference
            lifecycle["promoted_at"] = result["scanned_at"]
            metadata["object_storage"] = clean_reference
            metadata["object_storage_write"] = result.get("promotion") or {}
        metadata["upload_storage_lifecycle"] = lifecycle

        scanned_file.metadata = metadata
        scanned_file.status = final_status
        scanned_file.scan_status = final_scan_status
        scanned_file.privacy_risk = bool(result.get("privacy_risk"))
        scanned_file.agent_handoff = _handoff_with_scan(
            scanned_file.agent_handoff,
            result,
        )
        if result_status == "clean":
            scanned_file.agent_handoff = {
                **scanned_file.agent_handoff,
                "storage_uri": scanned_file.storage_uri,
                "object_storage": metadata["object_storage"],
            }
        scanned_file.save(
            update_fields=[
                "status",
                "scan_status",
                "privacy_risk",
                "agent_handoff",
                "metadata",
                "updated_at",
            ]
        )
    return True


def _renew_file_scan_claim(
    uploaded_file_pk: int,
    *,
    claim_token: str,
) -> bool:
    now = timezone.now()
    with transaction.atomic():
        uploaded_file = UploadedFile.objects.select_for_update().get(pk=uploaded_file_pk)
        metadata = dict(uploaded_file.metadata or {})
        scan_claim = dict(metadata.get("scan_claim") or {})
        if (
            uploaded_file.status != UploadedFileStatus.SCANNING
            or uploaded_file.scan_status != "scanning"
            or scan_claim.get("token") != claim_token
            or _inactive_upload_reason(uploaded_file, now=now)
        ):
            return False
        metadata["scan_claim"] = {
            **scan_claim,
            "renewed_at": now.isoformat(),
        }
        uploaded_file.metadata = metadata
        uploaded_file.save(update_fields=["metadata", "updated_at"])
    return True


def _promote_scanned_snapshot(
    uploaded_file: UploadedFile,
    *,
    source_bytes: bytes | None,
) -> dict[str, Any]:
    if source_bytes is None:
        return _promotion_result(verified=False, reason="scanned_snapshot_missing")
    target_reference = _clean_storage_reference(uploaded_file)
    if not target_reference:
        return _promotion_result(verified=False, reason="storage_reference_missing")
    snapshot_sha256 = hashlib.sha256(source_bytes).hexdigest()
    write_result = write_object(
        target_reference,
        source_bytes,
        metadata={
            "resource_type": "uploaded_file",
            "resource_id": uploaded_file.attachment_id,
            "snapshot_sha256": snapshot_sha256,
        },
    )
    if write_result.get("status") != "written" or not write_result.get(
        "writes_binary"
    ):
        return _promotion_result(
            verified=False,
            reason=str(write_result.get("reason") or "write_failed"),
            write_result=write_result,
        )
    promoted_bytes = read_object_bytes(target_reference)
    if (
        promoted_bytes is None
        or hashlib.sha256(promoted_bytes).hexdigest() != snapshot_sha256
    ):
        delete_object(target_reference)
        return _promotion_result(
            verified=False,
            reason="clean_object_verification_failed",
            write_result=write_result,
        )
    return _promotion_result(
        verified=True,
        reason="promoted",
        write_result=write_result,
        snapshot_sha256=snapshot_sha256,
    )


def _inactive_upload_reason(
    uploaded_file: UploadedFile,
    *,
    now: Any,
) -> str:
    if uploaded_file.deleted_at is not None:
        return "upload_deleted"
    if (
        uploaded_file.retention_expires_at is not None
        and uploaded_file.retention_expires_at <= now
    ):
        return "upload_retention_expired"
    return ""


def _promotion_result(
    *,
    verified: bool,
    reason: str,
    write_result: dict[str, Any] | None = None,
    snapshot_sha256: str = "",
) -> dict[str, Any]:
    safe_write = {
        key: value
        for key, value in (write_result or {}).items()
        if key not in {"local_path", "storage_uri", "key"}
    }
    promotion = {
        "contract_version": "file_scan_promotion.v1",
        "status": "promoted" if verified else "error",
        "verified": verified,
        "reason": reason,
        "write": safe_write,
    }
    if snapshot_sha256:
        promotion["snapshot_sha256"] = snapshot_sha256
    return promotion


def _source_snapshot_for_scan(uploaded_file: UploadedFile) -> bytes | None:
    max_bytes = int(getattr(settings, "FILE_SCAN_MAX_BYTES", DEFAULT_MAX_SCAN_BYTES))
    if (uploaded_file.size_bytes or 0) > max_bytes:
        return None
    return _quarantine_object_bytes(uploaded_file)


def _quarantine_object_bytes(uploaded_file: UploadedFile) -> bytes | None:
    reference = _quarantine_storage_reference(uploaded_file)
    return read_object_bytes(reference) if reference else None


def _quarantine_storage_reference(uploaded_file: UploadedFile) -> dict[str, Any]:
    lifecycle = _upload_storage_lifecycle(uploaded_file)
    reference = lifecycle.get("quarantine")
    return dict(reference) if isinstance(reference, dict) else {}


def _clean_storage_reference(uploaded_file: UploadedFile) -> dict[str, Any]:
    metadata = uploaded_file.metadata if isinstance(uploaded_file.metadata, dict) else {}
    lifecycle = _upload_storage_lifecycle(uploaded_file)
    reference = lifecycle.get("clean") or metadata.get("object_storage")
    return dict(reference) if isinstance(reference, dict) else {}


def _upload_storage_lifecycle(uploaded_file: UploadedFile) -> dict[str, Any]:
    metadata = uploaded_file.metadata if isinstance(uploaded_file.metadata, dict) else {}
    lifecycle = metadata.get("upload_storage_lifecycle")
    return dict(lifecycle) if isinstance(lifecycle, dict) else {}


def _scan_claim_stale_after_seconds() -> int:
    return _positive_scan_setting(
        "FILE_SCAN_CLAIM_STALE_AFTER_SECONDS",
        DEFAULT_SCAN_CLAIM_STALE_AFTER_SECONDS,
    )


def _scan_retry_backoff_seconds() -> int:
    return _positive_scan_setting(
        "FILE_SCAN_RETRY_BACKOFF_SECONDS",
        DEFAULT_SCAN_RETRY_BACKOFF_SECONDS,
    )


def _positive_scan_setting(name: str, default: int) -> int:
    try:
        value = int(getattr(settings, name, default) or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _skipped_scan_result(
    uploaded_file: UploadedFile,
    *,
    reason: str,
) -> dict[str, Any]:
    return {
        "contract_version": FILE_SCAN_RESULT_VERSION,
        "scanner": str(getattr(settings, "FILE_SCAN_PROVIDER", "local_policy")),
        "attachment_id": uploaded_file.attachment_id,
        "status": "skipped",
        "scan_status": uploaded_file.scan_status,
        "privacy_risk": uploaded_file.privacy_risk,
        "findings": [],
        "reason": reason,
        "scanned_at": timezone.now().isoformat(),
        "policy": {},
    }


def _scan_operational_error_result(
    uploaded_file: UploadedFile,
    *,
    reason: str,
) -> dict[str, Any]:
    provider = str(getattr(settings, "FILE_SCAN_PROVIDER", "local_policy"))
    return {
        "contract_version": FILE_SCAN_RESULT_VERSION,
        "scanner": provider,
        "attachment_id": uploaded_file.attachment_id,
        "status": "error",
        "scan_status": "error",
        "privacy_risk": uploaded_file.privacy_risk,
        "findings": [
            _scanner_unavailable_finding(provider=provider, reason=reason)
        ],
        "scanned_at": timezone.now().isoformat(),
        "policy": {"provider": provider},
    }


def apply_attachment_scan_gate(payload: dict[str, Any]) -> dict[str, Any]:
    enriched = deepcopy(payload)
    attachments, malformed_count, has_attachment_input = (
        _canonical_attachment_references(enriched)
    )
    if not has_attachment_input:
        return enriched

    max_count = _max_attachments_per_request()
    if len(attachments) + malformed_count > max_count:
        enriched["attachments"] = []
        enriched["blocked_attachments"] = [
            {
                "contract_version": ATTACHMENT_SCAN_GATE_VERSION,
                "attachment_id": "",
                "status": "blocked",
                "scan_status": "blocked",
                "reason": "attachment_limit_exceeded",
            }
        ]
        enriched["attachment_scan_policy"] = {
            "contract_version": ATTACHMENT_SCAN_GATE_VERSION,
            "allowed_count": 0,
            "blocked_count": 1,
            "max_count": max_count,
        }
        return enriched

    allowed_attachments = []
    blocked_attachments = [
        _blocked_malformed_attachment() for _index in range(malformed_count)
    ]
    ordered_attachment_ids = []
    seen_attachment_ids = set()
    for attachment in attachments:
        attachment_id = str(attachment.get("attachment_id") or "").strip()
        if not attachment_id:
            blocked_attachments.append(_blocked_malformed_attachment())
            continue
        if attachment_id in seen_attachment_ids:
            continue
        seen_attachment_ids.add(attachment_id)
        ordered_attachment_ids.append(attachment_id)

    uploaded_files = {
        item.attachment_id: item
        for item in UploadedFile.objects.filter(
            attachment_id__in=ordered_attachment_ids,
            deleted_at__isnull=True,
        ).select_related("session", "case")
    }
    for attachment_id in ordered_attachment_ids:
        uploaded_file = uploaded_files.get(attachment_id)
        if uploaded_file is None or not _attachment_access_allowed(
            uploaded_file,
            enriched,
        ):
            blocked_attachments.append(_blocked_unknown_attachment(attachment_id))
            continue
        if uploaded_file.status == UploadedFileStatus.READY and uploaded_file.scan_status == "clean":
            allowed_attachments.append(_attachment_handoff(uploaded_file))
            continue
        blocked_attachments.append(_blocked_attachment(uploaded_file))

    enriched["attachments"] = allowed_attachments
    enriched["blocked_attachments"] = blocked_attachments
    enriched["attachment_scan_policy"] = {
        "contract_version": ATTACHMENT_SCAN_GATE_VERSION,
        "allowed_count": len(allowed_attachments),
        "blocked_count": len(blocked_attachments),
        "max_count": max_count,
    }
    return enriched


def _max_attachments_per_request() -> int:
    return _positive_scan_setting(
        "FILE_MAX_ATTACHMENTS_PER_REQUEST",
        DEFAULT_MAX_ATTACHMENTS_PER_REQUEST,
    )


def _canonical_attachment_references(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], int, bool]:
    has_attachments = "attachments" in payload
    has_attachment_ids = "attachment_ids" in payload
    if not has_attachments and not has_attachment_ids:
        return [], 0, False

    references: list[dict[str, Any]] = []
    malformed_count = 0
    raw_attachments = payload.get("attachments")
    if has_attachments:
        if isinstance(raw_attachments, list):
            for item in raw_attachments:
                if isinstance(item, dict):
                    references.append(item)
                else:
                    malformed_count += 1
        else:
            malformed_count += 1

    raw_attachment_ids = payload.pop("attachment_ids", None)
    if has_attachment_ids:
        if isinstance(raw_attachment_ids, str):
            raw_attachment_ids = [raw_attachment_ids]
        if isinstance(raw_attachment_ids, list):
            for attachment_id in raw_attachment_ids:
                if isinstance(attachment_id, str) and attachment_id.strip():
                    references.append({"attachment_id": attachment_id.strip()})
                else:
                    malformed_count += 1
        else:
            malformed_count += 1

    return references, malformed_count, True


def _handoff_with_scan(agent_handoff: Any, result: dict[str, Any]) -> dict[str, Any]:
    handoff = dict(agent_handoff or {})
    handoff["scan_status"] = result["scan_status"]
    handoff["file_scan_result"] = {
        "contract_version": result["contract_version"],
        "status": result["status"],
        "privacy_risk": result["privacy_risk"],
        "finding_count": len(result["findings"]),
    }
    return handoff


def _attachment_handoff(uploaded_file: UploadedFile) -> dict[str, Any]:
    metadata = uploaded_file.metadata if isinstance(uploaded_file.metadata, dict) else {}
    object_storage = metadata.get("object_storage")
    return {
        "_canonical_scan_gate": CANONICAL_SCAN_GATE_MARKER,
        "attachment_id": uploaded_file.attachment_id,
        "purpose": uploaded_file.purpose,
        "type": uploaded_file.file_type,
        "original_filename": uploaded_file.original_filename,
        "storage_uri": uploaded_file.storage_uri,
        "object_storage": dict(object_storage) if isinstance(object_storage, dict) else {},
        "content_type": uploaded_file.content_type,
        "size_bytes": uploaded_file.size_bytes or 0,
        "status": uploaded_file.status,
        "scan_status": uploaded_file.scan_status,
        "privacy_risk": uploaded_file.privacy_risk,
        "resolution_status": "scan_ready",
    }


def _attachment_access_allowed(
    uploaded_file: UploadedFile,
    payload: dict[str, Any],
) -> bool:
    if (
        uploaded_file.retention_expires_at
        and uploaded_file.retention_expires_at <= timezone.now()
    ):
        return False
    subject = access_subject_from_payload(payload)["subject"]
    requester_owner_id = str(subject.get("user_id") or "")
    if uploaded_file.owner_id:
        if not requester_owner_id or uploaded_file.owner_id != requester_owner_id:
            return False
    elif requester_owner_id:
        return False

    requested_session_id = str(payload.get("session_id") or "")
    file_session_id = (
        uploaded_file.session.session_id if uploaded_file.session_id else ""
    )
    if file_session_id and requested_session_id != file_session_id:
        return False

    requested_case_id = str(payload.get("case_id") or "")
    file_case_id = uploaded_file.case.case_id if uploaded_file.case_id else ""
    if requested_case_id and requested_case_id != file_case_id:
        return False

    if not uploaded_file.owner_id:
        requester_guest_id = str(subject.get("guest_id") or "")
        session_metadata = (
            uploaded_file.session.metadata
            if uploaded_file.session_id
            and isinstance(uploaded_file.session.metadata, dict)
            else {}
        )
        session_auth_context = session_metadata.get("auth_context")
        session_auth_context = (
            session_auth_context
            if isinstance(session_auth_context, dict)
            else {}
        )
        session_guest_id = str(
            session_metadata.get("guest_id")
            or session_auth_context.get("guest_id")
            or ""
        )
        if not session_guest_id or requester_guest_id != session_guest_id:
            return False
    return True


def _blocked_unknown_attachment(attachment_id: str) -> dict[str, Any]:
    return {
        "contract_version": ATTACHMENT_SCAN_GATE_VERSION,
        "attachment_id": attachment_id,
        "status": "unavailable",
        "scan_status": "unknown",
        "reason": "attachment_not_found_or_forbidden",
        "required_action": "select_owned_scanned_file",
    }


def _blocked_malformed_attachment() -> dict[str, Any]:
    return {
        "contract_version": ATTACHMENT_SCAN_GATE_VERSION,
        "attachment_id": "",
        "status": "unavailable",
        "scan_status": "unknown",
        "reason": "malformed_attachment_reference",
        "required_action": "provide_attachment_id",
    }


def _blocked_attachment(uploaded_file: UploadedFile) -> dict[str, Any]:
    reason = "scan_rejected" if uploaded_file.status == UploadedFileStatus.REJECTED else "scan_not_ready"
    return {
        "contract_version": ATTACHMENT_SCAN_GATE_VERSION,
        "attachment_id": uploaded_file.attachment_id,
        "purpose": uploaded_file.purpose,
        "type": uploaded_file.file_type,
        "status": uploaded_file.status,
        "scan_status": uploaded_file.scan_status,
        "reason": reason,
        "required_action": "replace_file" if reason == "scan_rejected" else "wait_for_file_scan",
    }


def _clamav_instream_scan(*, host: str, port: int, source_bytes: bytes) -> str:
    timeout = int(getattr(settings, "FILE_SCAN_TIMEOUT_SECONDS", DEFAULT_SCAN_TIMEOUT_SECONDS) or DEFAULT_SCAN_TIMEOUT_SECONDS)
    with closing(socket.create_connection((host, port), timeout=timeout)) as sock:
        sock.settimeout(timeout)
        sock.sendall(b"zINSTREAM\0")
        for offset in range(0, len(source_bytes), 1024 * 1024):
            chunk = source_bytes[offset : offset + 1024 * 1024]
            sock.sendall(struct.pack("!I", len(chunk)))
            sock.sendall(chunk)
        sock.sendall(struct.pack("!I", 0))
        response = sock.recv(4096)
    return response.decode("utf-8", errors="replace").strip("\0\r\n ")


def _post_external_scan_request(
    uploaded_file: UploadedFile,
    *,
    url: str,
    api_key: str,
    source_bytes: bytes,
) -> dict[str, Any]:
    timeout = int(getattr(settings, "FILE_SCAN_TIMEOUT_SECONDS", DEFAULT_SCAN_TIMEOUT_SECONDS) or DEFAULT_SCAN_TIMEOUT_SECONDS)
    payload = _external_scan_payload(uploaded_file, source_bytes=source_bytes)
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    request = urllib_request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib_request.urlopen(request, timeout=timeout) as response:
        response_body = response.read()
    if not response_body:
        return {}
    decoded = json.loads(response_body.decode("utf-8"))
    return decoded if isinstance(decoded, dict) else {}


def _external_scan_payload(
    uploaded_file: UploadedFile,
    *,
    source_bytes: bytes,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": "file_scan_external_request.v1",
        "attachment_id": uploaded_file.attachment_id,
        "filename": uploaded_file.original_filename,
        "content_type": uploaded_file.content_type,
        "size_bytes": uploaded_file.size_bytes or 0,
        "storage_uri": uploaded_file.storage_uri,
        "metadata": _safe_external_metadata(uploaded_file.metadata or {}),
    }
    payload["file_base64"] = base64.b64encode(source_bytes).decode("ascii")
    return payload


def _safe_external_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    private_storage_keys = {
        "object_storage_write",
        "source_storage_uri",
        "upload_storage_lifecycle",
    }
    return sanitize_pii(
        {
            key: value
            for key, value in metadata.items()
            if key not in private_storage_keys
        }
    )


def _clamav_findings_from_response(response: str) -> list[dict[str, Any]]:
    normalized = response.strip()
    if normalized.endswith(": OK") or normalized == "OK":
        return []
    if not normalized:
        return [
            _scanner_unavailable_finding(
                provider="clamav",
                reason="empty_response",
                message="ClamAV returned an empty response.",
            )
        ]
    if "FOUND" in normalized:
        signature = normalized.rsplit(":", 1)[-1].replace("FOUND", "").strip()
        return [
            {
                "category": "virus",
                "code": "clamav_signature_found",
                "severity": "critical",
                "message": "ClamAV reported a malware signature.",
                "signature": signature,
            }
        ]
    return [
        _scanner_unavailable_finding(
            provider="clamav",
            reason="unexpected_response",
            message="ClamAV returned an unexpected response.",
        )
    ]


def _external_findings_from_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    raw_findings = response.get("findings")
    findings = []
    if raw_findings is not None and not isinstance(raw_findings, list):
        return [
            _scanner_unavailable_finding(
                provider="external",
                reason="invalid_findings",
                message="External scan provider returned invalid findings.",
            )
        ]
    if isinstance(raw_findings, list):
        if any(not isinstance(item, dict) for item in raw_findings):
            return [
                _scanner_unavailable_finding(
                    provider="external",
                    reason="invalid_findings",
                    message="External scan provider returned invalid findings.",
                )
            ]
        findings = [
            _normalize_provider_finding(item, provider="external")
            for item in raw_findings
        ]

    raw_status = response.get("status") or response.get("verdict")
    if raw_status is None:
        return [
            _scanner_unavailable_finding(
                provider="external",
                reason="missing_verdict",
                message="External scan provider did not return a verdict.",
            )
        ]
    status = str(raw_status).strip().lower()
    if status in {"clean", "pass", "ok", "allowed"}:
        return findings
    if status in {"malicious", "infected", "rejected", "blocked", "fail", "failed"}:
        return findings + [
            {
                "category": "virus",
                "code": "external_scan_rejected",
                "severity": "critical",
                "message": "External scan provider rejected the file.",
            }
        ]
    return [
        _scanner_unavailable_finding(
            provider="external",
            reason="unexpected_response",
            message="External scan provider returned an unexpected response.",
        )
    ]


def _normalize_provider_finding(item: dict[str, Any], *, provider: str) -> dict[str, Any]:
    category = str(item.get("category") or "provider").lower()
    if category not in {"malware", "policy", "provider", "scanner", "virus"}:
        category = "provider"
    severity = str(item.get("severity") or "").lower()
    if severity not in {"low", "medium", "high", "critical"}:
        severity = "critical" if category in {"virus", "malware"} else "medium"
    return {
        "category": category,
        "code": f"{provider}_finding",
        "severity": severity,
        "message": "File scan provider returned a finding.",
    }


def _scanner_unavailable_finding(
    *,
    provider: str,
    reason: str,
    exc: Exception | None = None,
    message: str = "",
) -> dict[str, Any]:
    finding = {
        "category": "scanner",
        "code": "scanner_unavailable",
        "severity": "critical",
        "message": message or "Configured file scan provider could not scan the uploaded file.",
        "provider": provider,
        "reason": reason,
    }
    if exc is not None:
        finding["error_class"] = exc.__class__.__name__
    return finding


def _exception_reason(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, urllib_error.HTTPError):
        return f"http_{exc.code}"
    if isinstance(exc, urllib_error.URLError):
        return "url_error"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json_response"
    if isinstance(exc, OSError):
        return "connection_failed"
    return "provider_error"


def _searchable_metadata(uploaded_file: UploadedFile) -> str:
    values = [
        uploaded_file.attachment_id,
        uploaded_file.original_filename,
        uploaded_file.content_type,
        uploaded_file.storage_uri,
        json.dumps(uploaded_file.metadata or {}, ensure_ascii=False, default=str),
    ]
    return "\n".join(str(value or "") for value in values)
