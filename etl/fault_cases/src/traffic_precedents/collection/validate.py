from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from ..contracts import record_id_of


def validate_collected_records(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    materialized = list(rows)
    ids = [record_id_of(row) for row in materialized]
    counts = Counter(value for value in ids if value)
    duplicates = sorted(value for value, count in counts.items() if count > 1)
    missing_ids = [index for index, value in enumerate(ids, 1) if not value]
    empty_details = [
        record_id_of(row) or f"line:{index}"
        for index, row in enumerate(materialized, 1)
        if not str(
            row.get("판례내용")
            or row.get("full_text")
            or row.get("판결요지")
            or row.get("판시사항")
            or ""
        ).strip()
    ]
    passed = not duplicates and not missing_ids and not empty_details
    return {
        "status": "PASSED" if passed else "FAILED",
        "record_count": len(materialized),
        "duplicate_record_ids": duplicates,
        "missing_record_id_lines": missing_ids,
        "empty_detail_record_ids": empty_details,
    }
