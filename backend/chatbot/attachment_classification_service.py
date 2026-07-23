"""Server-owned persistence and confirmation for attachment classification."""

from __future__ import annotations

from typing import Any, Mapping

from django.db import transaction
from django.utils import timezone

from chatbot.models import UploadedFile, UploadedFileStatus


CLASSIFICATION_RECORD_KEY = "attachment_document_classification"
CLASSIFICATION_CONTRACT_VERSION = "attachment_document_classification.v1"
CONFIRMABLE_CLASSIFICATIONS = frozenset({"fine_notice", "accident_evidence"})
CONFIRMABLE_CONFIDENCE_BANDS = frozenset({"high", "medium"})


class AttachmentClassificationPersistenceError(RuntimeError):
    """Raised when a classification cannot be bound to the current clean file."""


class AttachmentClassificationConfirmationError(RuntimeError):
    """Raised when a requested confirmation has no current trusted record."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def persist_attachment_document_classification(
    *,
    attachment_id: str,
    storage_uri: str,
    execution_id: str,
    structured_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Lock a clean attachment and store only its narrow classification record."""

    normalized_attachment_id = str(attachment_id or "").strip()
    normalized_storage_uri = str(storage_uri or "").strip()
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
        if uploaded_file is None or uploaded_file.storage_uri != normalized_storage_uri:
            raise AttachmentClassificationPersistenceError("attachment_not_scan_ready")

        metadata = dict(uploaded_file.metadata or {})
        snapshot_sha256 = _current_snapshot_sha256(metadata)
        if not snapshot_sha256:
            raise AttachmentClassificationPersistenceError("scan_snapshot_unavailable")

        record = _classification_record(
            snapshot_sha256=snapshot_sha256,
            execution_id=execution_id,
            structured_result=structured_result,
        )
        existing = metadata.get(CLASSIFICATION_RECORD_KEY)
        if _is_same_successful_record(existing, record):
            return dict(existing)

        metadata[CLASSIFICATION_RECORD_KEY] = record
        uploaded_file.metadata = metadata
        uploaded_file.save(update_fields=["metadata", "updated_at"])
        return dict(record)


def resolve_confirmed_attachment_classification(
    *,
    session_id: str,
    attachment_id: str,
) -> dict[str, str]:
    """Resolve one current server record; the client cannot provide a category."""

    with transaction.atomic():
        uploaded_file = (
            UploadedFile.objects.select_for_update()
            .filter(
                attachment_id=str(attachment_id or "").strip(),
                session__session_id=str(session_id or "").strip(),
                status=UploadedFileStatus.READY,
                scan_status="clean",
                deleted_at__isnull=True,
            )
            .first()
        )
        if uploaded_file is None:
            raise AttachmentClassificationConfirmationError("classification_stale_or_unavailable")

        metadata = dict(uploaded_file.metadata or {})
        record = metadata.get(CLASSIFICATION_RECORD_KEY)
        snapshot_sha256 = _current_snapshot_sha256(metadata)
        if not _is_confirmable_current_record(record, snapshot_sha256):
            raise AttachmentClassificationConfirmationError("classification_stale_or_unavailable")

        record = dict(record)
        record["confirmed_at"] = timezone.now().isoformat()
        metadata[CLASSIFICATION_RECORD_KEY] = record
        uploaded_file.metadata = metadata
        uploaded_file.save(update_fields=["metadata", "updated_at"])
        return {
            "attachment_id": uploaded_file.attachment_id,
            "classification": str(record["classification"]),
            "confidence_band": str(record["confidence_band"]),
        }


def _classification_record(
    *,
    snapshot_sha256: str,
    execution_id: str,
    structured_result: Mapping[str, Any],
) -> dict[str, Any]:
    classification = str(structured_result.get("classification") or "unknown")
    confidence_band = str(structured_result.get("confidence_band") or "low")
    is_confirmable = (
        classification in CONFIRMABLE_CLASSIFICATIONS
        and confidence_band in CONFIRMABLE_CONFIDENCE_BANDS
        and structured_result.get("requires_confirmation") is True
    )
    status = "success" if is_confirmable else "partial"
    next_action = "confirm_classification" if is_confirmable else "change_purpose"
    return {
        "contract_version": CLASSIFICATION_CONTRACT_VERSION,
        "scan_snapshot_sha256": snapshot_sha256,
        "status": status,
        "classification": classification if is_confirmable else "unknown",
        "confidence_band": confidence_band,
        "requires_confirmation": is_confirmable,
        "next_action": next_action,
        "error_code": "",
        "execution_id": str(execution_id or "").strip(),
        "classified_at": timezone.now().isoformat(),
        "confirmed_at": None,
    }


def _current_snapshot_sha256(metadata: Mapping[str, Any]) -> str:
    promotion = metadata.get("object_storage_write")
    promotion = promotion if isinstance(promotion, Mapping) else {}
    return str(promotion.get("snapshot_sha256") or "").strip()


def _is_same_successful_record(existing: Any, candidate: Mapping[str, Any]) -> bool:
    if not isinstance(existing, Mapping):
        return False
    return bool(
        existing.get("status") == "success"
        and existing.get("scan_snapshot_sha256") == candidate.get("scan_snapshot_sha256")
        and existing.get("classification") == candidate.get("classification")
        and existing.get("confidence_band") == candidate.get("confidence_band")
        and existing.get("requires_confirmation") is True
    )


def _is_confirmable_current_record(record: Any, snapshot_sha256: str) -> bool:
    return bool(
        isinstance(record, Mapping)
        and record.get("contract_version") == CLASSIFICATION_CONTRACT_VERSION
        and record.get("scan_snapshot_sha256") == snapshot_sha256
        and record.get("status") == "success"
        and record.get("classification") in CONFIRMABLE_CLASSIFICATIONS
        and record.get("confidence_band") in CONFIRMABLE_CONFIDENCE_BANDS
        and record.get("requires_confirmation") is True
    )
