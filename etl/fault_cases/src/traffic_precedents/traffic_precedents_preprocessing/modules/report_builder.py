from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from .normalizer import TARGET_FIELDS


JsonDict = dict[str, Any]


def count_non_empty(rows: list[JsonDict], field: str) -> int:
    """Count rows where field has a non-empty value."""

    count = 0

    for row in rows:
        value = row.get(field)

        if isinstance(value, list):
            if value:
                count += 1
        elif value not in (None, ""):
            count += 1

    return count


def count_missing_fields(rows: list[JsonDict]) -> dict[str, int]:
    """Count missing values for target fields."""

    missing_counts: Counter[str] = Counter()

    for row in rows:
        for field in TARGET_FIELDS:
            value = row.get(field)

            if value is None or value == [] or value == "":
                missing_counts[field] += 1

    return dict(missing_counts)


def count_invalid_reasons(invalid_rows: list[JsonDict]) -> dict[str, int]:
    """Count invalid rows by reason label."""

    return dict(Counter(row.get("_invalid_reason", "unknown") for row in invalid_rows))


def count_fault_ratio_confidence(rows: list[JsonDict]) -> dict[str, int]:
    """Count extracted fault-ratio candidates by confidence."""

    counts: Counter[str] = Counter()

    for row in rows:
        for candidate in row.get("_fault_ratio_candidates", []) or []:
            counts[str(candidate.get("confidence", "unknown"))] += 1

    return dict(counts)


def build_preprocess_report(
    raw_count: int,
    valid_count: int,
    invalid_rows: list[JsonDict],
    duplicate_removed_rows: list[JsonDict],
    final_rows: list[JsonDict],
    extra_stats: dict[str, Any] | None = None,
) -> JsonDict:
    """Build the final preprocessing report."""

    extra_stats = extra_stats or {}

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "row_counts": {
            "raw": raw_count,
            "valid_before_dedup": valid_count,
            "invalid": len(invalid_rows),
            "duplicate_removed": len(duplicate_removed_rows),
            "final": len(final_rows),
        },
        "extraction_counts": {
            "order_extracted": count_non_empty(final_rows, "주문"),
            "reason_extracted": count_non_empty(final_rows, "이유"),
            "fault_ratio_extracted": count_non_empty(final_rows, "과실비율"),
        },
        "invalid_reason_counts": count_invalid_reasons(invalid_rows),
        "missing_field_counts": count_missing_fields(final_rows),
        "fault_ratio_candidate_confidence_counts": count_fault_ratio_confidence(final_rows),
        "extra_stats": extra_stats,
    }
