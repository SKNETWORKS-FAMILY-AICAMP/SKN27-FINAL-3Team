from __future__ import annotations


def build_review_case_source_reference(
    *,
    review_case_id: str | None,
    review_no: str | None,
    chunk_id: str | None,
) -> str:
    case_key = _clean(review_case_id) or _clean(review_no) or "unknown_review_case"
    chunk_key = _clean(chunk_id) or "unknown_chunk"
    return f"review_case_db:{case_key}#{chunk_key}"


def build_fault_ratio_precedent_source_reference(
    *,
    case_id: str | None,
    case_number: str | None,
    chunk_id: str | None,
) -> str:
    case_key = _clean(case_id) or _clean(case_number) or "unknown_fault_ratio_precedent"
    chunk_key = _clean(chunk_id) or "unknown_chunk"
    return f"fault_ratio_precedent_db:{case_key}#{chunk_key}"


def _clean(value: object) -> str:
    return str(value or "").strip()
