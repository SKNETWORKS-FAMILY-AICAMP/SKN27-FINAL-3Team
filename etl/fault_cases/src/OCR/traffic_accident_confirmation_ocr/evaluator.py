from __future__ import annotations

from typing import Any

from .constants import (
    FAILURE_REASON_NOT_TARGET_DOCUMENT,
    FAILURE_REASON_OCR_FAILED,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_SUCCESS,
)


CRITICAL_FIELDS = [
    "accident_datetime",
    "accident_location",
    "accident_type.value",
    "accident_description",
]

IMPORTANT_FIELDS = [
    "receipt_number",
    "issue_number",
    "police_station",
    "accident_cause",
    "damage.raw_text",
    "usage",
]


def evaluate_ocr_result(
    extracted_fields: dict[str, Any] | None,
    document_check: dict[str, Any] | None = None,
    format_errors: list[str] | None = None,
) -> dict[str, Any]:
    fields = extracted_fields or {}
    check = document_check or {}
    errors = format_errors or []

    if check.get("is_target_document") is False:
        return {
            "status": STATUS_FAILED,
            "failure_reason": FAILURE_REASON_NOT_TARGET_DOCUMENT,
            "missing_fields": [],
            "limitations": ["교통사고사실확인원으로 판정되지 않았습니다."],
        }

    missing_critical = _missing_fields(fields, CRITICAL_FIELDS)
    missing_important = _missing_fields(fields, IMPORTANT_FIELDS)
    missing_fields = missing_critical + missing_important

    if errors:
        return {
            "status": STATUS_FAILED,
            "failure_reason": FAILURE_REASON_OCR_FAILED,
            "missing_fields": missing_fields,
            "limitations": errors,
        }

    if missing_critical:
        return {
            "status": STATUS_PARTIAL,
            "failure_reason": None,
            "missing_fields": missing_fields,
            "limitations": [
                "교통사고사실확인원으로 보이나 핵심 필드 일부가 비어 있습니다.",
                "서비스 단계에서는 Supervisor가 재업로드 또는 추가 질문 필요 여부를 판단해야 합니다.",
            ],
        }

    if missing_important:
        return {
            "status": STATUS_PARTIAL,
            "failure_reason": None,
            "missing_fields": missing_important,
            "limitations": ["핵심 필드는 추출되었지만 보조 필드 일부가 비어 있습니다."],
        }

    return {
        "status": STATUS_SUCCESS,
        "failure_reason": None,
        "missing_fields": [],
        "limitations": [],
    }


def _missing_fields(fields: dict[str, Any], field_paths: list[str]) -> list[str]:
    return [field_path for field_path in field_paths if _is_missing(_get_nested(fields, field_path))]


def _get_nested(value: dict[str, Any], field_path: str) -> Any:
    current: Any = value
    for key in field_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False
