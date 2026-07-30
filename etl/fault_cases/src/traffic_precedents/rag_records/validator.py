from __future__ import annotations

from typing import Any, Iterable

from .contracts import ALLOWED_GRADES, FORBIDDEN_ROLES


def validate_rag_records(
    rows: Iterable[dict[str, Any]],
    *,
    expected_blocks: int,
    expected_cases: int,
) -> dict[str, Any]:
    records = list(rows)
    block_ids = [str(row.get("block_id") or "") for row in records]
    case_ids = {str(row.get("record_id") or "") for row in records}
    errors: list[str] = []
    if len(records) != expected_blocks:
        errors.append(f"BLOCK_COUNT:{len(records)}")
    if len(case_ids) != expected_cases:
        errors.append(f"CASE_COUNT:{len(case_ids)}")
    if any(not value for value in block_ids) or len(block_ids) != len(set(block_ids)):
        errors.append("BLOCK_ID_UNIQUENESS")
    if any(row.get("internal_grade") not in ALLOWED_GRADES for row in records):
        errors.append("GRADE_SCOPE")
    if any(row.get("semantic_role") in FORBIDDEN_ROLES for row in records):
        errors.append("FORBIDDEN_ROLE")
    if any(row.get("validator_status") != "PASSED" for row in records):
        errors.append("VALIDATOR_STATUS")
    return {
        "status": "PASSED" if not errors else "FAILED",
        "block_count": len(records),
        "case_count": len(case_ids),
        "errors": errors,
    }
