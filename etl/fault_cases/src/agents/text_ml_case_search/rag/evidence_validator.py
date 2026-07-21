from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.config import MIN_CHUNK_TEXT_LEN


def validate_evidence(
    *,
    evidence: list[dict[str, Any]],
    min_text_len: int = MIN_CHUNK_TEXT_LEN,
) -> list[dict[str, Any]]:
    valid_items: list[dict[str, Any]] = []
    for item in evidence:
        result = validate_evidence_item(item=item, min_text_len=min_text_len)
        if not result["is_valid"]:
            continue
        valid_items.append(result["item"])
    return valid_items


def validate_evidence_item(
    *,
    item: dict[str, Any],
    min_text_len: int = MIN_CHUNK_TEXT_LEN,
) -> dict[str, Any]:
    reasons = _collect_invalid_reasons(item=item, min_text_len=min_text_len)
    copied = dict(item)
    metadata = dict(copied.get("metadata") or {})

    metadata["validation"] = {
        "is_valid": not reasons,
        "invalid_reasons": reasons,
        "min_text_len": min_text_len,
        "chunk_text_len": len(_clean(copied.get("chunk_text"))),
    }
    copied["metadata"] = metadata

    return {
        "is_valid": not reasons,
        "invalid_reasons": reasons,
        "item": copied,
    }


def build_evidence_validation_report(
    *,
    evidence: list[dict[str, Any]],
    min_text_len: int = MIN_CHUNK_TEXT_LEN,
) -> dict[str, Any]:
    results = [
        validate_evidence_item(item=item, min_text_len=min_text_len)
        for item in evidence
    ]
    invalid_reasons: dict[str, int] = {}
    for result in results:
        for reason in result["invalid_reasons"]:
            invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1

    return {
        "input_count": len(evidence),
        "valid_count": sum(1 for result in results if result["is_valid"]),
        "invalid_count": sum(1 for result in results if not result["is_valid"]),
        "invalid_reason_counts": invalid_reasons,
        "min_text_len": min_text_len,
    }


def _collect_invalid_reasons(*, item: dict[str, Any], min_text_len: int) -> list[str]:
    reasons: list[str] = []

    if not _clean(item.get("source_type")):
        reasons.append("source_type_missing")

    if not _clean(item.get("source_reference")):
        reasons.append("source_reference_missing")

    if not isinstance(item.get("metadata"), dict):
        reasons.append("metadata_missing")

    chunk_text = _clean(item.get("chunk_text"))
    if not chunk_text:
        reasons.append("chunk_text_missing")
    elif len(chunk_text) < min_text_len:
        reasons.append("chunk_text_too_short")

    return reasons


def _clean(value: Any) -> str:
    return str(value or "").strip()
