from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


ATTACHMENT_WORKFLOW_STATES = frozenset(
    {
        "scan_running",
        "classification_running",
        "classified_waiting_confirmation",
        "ocr_running",
        "ocr_needs_confirmation",
        "analysis_ready",
        "partial",
        "failed",
    }
)

_SAFE_UPLOAD_STATUSES = frozenset({"pending", "uploaded", "scanning", "ready"})
_UNSAFE_UPLOAD_STATUSES = frozenset({"rejected", "deleted", "failed"})
_SAFE_SCAN_STATUSES = frozenset({"", "pending", "scanning", "clean", "ready"})
_UNSAFE_SCAN_STATUSES = frozenset({"infected", "failed", "rejected"})


def _for_attachment(value: Any, attachment_id: str) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        value_attachment_id = str(value.get("attachment_id") or "").strip()
        if not value_attachment_id or value_attachment_id == attachment_id:
            return value
        return {}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("attachment_id") or "").strip() == attachment_id:
                return item
    return {}


def _safe_missing_fields(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        return []
    return [
        str(item).strip()
        for item in value
        if isinstance(item, str) and str(item).strip()
    ]


def _workflow(
    *,
    attachment_id: str,
    state: str,
    next_action: str,
    retryable: bool = False,
    missing_fields: Sequence[str] = (),
    limitations: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "contract_version": "attachment_workflow.v1",
        "attachment_id": attachment_id,
        "state": state if state in ATTACHMENT_WORKFLOW_STATES else "failed",
        "next_action": next_action,
        "retryable": retryable,
        "missing_fields": list(missing_fields),
        "limitations": list(limitations),
    }


def build_attachment_workflows(
    *,
    attachments: Sequence[Mapping[str, Any]],
    structured_results: Mapping[str, Any] | None = None,
    active_node: str = "",
    overall_status: str = "",
    ocr_confirmation: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    structured = structured_results if isinstance(structured_results, Mapping) else {}
    classification_results = structured.get("attachment_document_classification")
    ocr_results = structured.get("fine_notice_analysis")
    workflows: list[dict[str, Any]] = []

    for attachment in attachments:
        if not isinstance(attachment, Mapping):
            continue
        attachment_id = str(attachment.get("attachment_id") or "").strip()
        if not attachment_id:
            continue

        upload_status = str(attachment.get("status") or "").strip().lower()
        scan_status = str(attachment.get("scan_status") or "").strip().lower()
        classification = _for_attachment(classification_results, attachment_id)
        if not classification:
            server_confirmation = attachment.get("classification_confirmation")
            if (
                isinstance(server_confirmation, Mapping)
                and server_confirmation.get("source") == "server_record"
                and str(server_confirmation.get("classification") or "").strip()
            ):
                classification = {"status": "success"}
        ocr = _for_attachment(ocr_results, attachment_id)
        confirmation = _for_attachment(ocr_confirmation, attachment_id)

        if (
            upload_status in _UNSAFE_UPLOAD_STATUSES
            or scan_status in _UNSAFE_SCAN_STATUSES
            or upload_status not in _SAFE_UPLOAD_STATUSES
            or scan_status not in _SAFE_SCAN_STATUSES
        ):
            workflows.append(
                _workflow(
                    attachment_id=attachment_id,
                    state="failed",
                    next_action="reattach_file",
                    retryable=True,
                    limitations=[
                        "현재 파일은 안전한 분석 대상으로 사용할 수 없습니다."
                    ],
                )
            )
            continue

        if upload_status != "ready" or scan_status not in {"clean", "ready"}:
            workflows.append(
                _workflow(
                    attachment_id=attachment_id,
                    state="scan_running",
                    next_action="wait_for_scan",
                )
            )
            continue

        if classification.get("requires_confirmation") is True:
            workflows.append(
                _workflow(
                    attachment_id=attachment_id,
                    state="classified_waiting_confirmation",
                    next_action="confirm_classification",
                )
            )
            continue

        classification_status = str(classification.get("status") or "").lower()
        if classification_status in {"partial", "failed"}:
            workflows.append(
                _workflow(
                    attachment_id=attachment_id,
                    state="partial",
                    next_action=(
                        str(classification.get("next_action") or "").strip()
                        or "rerun_classification"
                    ),
                    retryable=True,
                    limitations=["자료 종류를 확정하지 못했습니다."],
                )
            )
            continue

        if not classification:
            workflows.append(
                _workflow(
                    attachment_id=attachment_id,
                    state="classification_running",
                    next_action="wait_for_classification",
                )
            )
            continue

        if ocr.get("requires_confirmation") is True:
            workflows.append(
                _workflow(
                    attachment_id=attachment_id,
                    state="ocr_needs_confirmation",
                    next_action="confirm_ocr_fields",
                    missing_fields=_safe_missing_fields(ocr.get("missing_fields")),
                )
            )
            continue

        if active_node == "fine_notice_analysis":
            workflows.append(
                _workflow(
                    attachment_id=attachment_id,
                    state="ocr_running",
                    next_action="wait_for_ocr",
                )
            )
            continue

        if confirmation.get("confirmed") is True and overall_status == "success":
            workflows.append(
                _workflow(
                    attachment_id=attachment_id,
                    state="analysis_ready",
                    next_action="review_analysis",
                )
            )
            continue

        if overall_status == "failed":
            workflows.append(
                _workflow(
                    attachment_id=attachment_id,
                    state="failed",
                    next_action="retry_or_reupload",
                    retryable=True,
                    limitations=["고지서 분석을 완료하지 못했습니다."],
                )
            )
            continue

        if overall_status == "partial":
            workflows.append(
                _workflow(
                    attachment_id=attachment_id,
                    state="partial",
                    next_action="provide_missing_information",
                    retryable=True,
                    limitations=["일부 고지서 정보를 추가로 확인해야 합니다."],
                )
            )
            continue

        workflows.append(
            _workflow(
                attachment_id=attachment_id,
                state="classification_running",
                next_action="wait_for_classification",
            )
        )

    return workflows
