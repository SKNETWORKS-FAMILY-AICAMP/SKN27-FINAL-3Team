from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.config import (
    V2_FAULT_RATIO_PRECEDENT_QUOTA,
    V2_FINAL_TOP_K,
    V2_MERGE_STRATEGY,
    V2_REVIEW_CASE_QUOTA,
)


def merge_evidence_by_source_quota(
    *,
    review_case_evidence: list[dict[str, Any]],
    fault_ratio_precedent_evidence: list[dict[str, Any]],
    review_case_quota: int = V2_REVIEW_CASE_QUOTA,
    fault_ratio_precedent_quota: int = V2_FAULT_RATIO_PRECEDENT_QUOTA,
    final_top_k: int = V2_FINAL_TOP_K,
) -> dict[str, Any]:
    """Merge V2 evidence with fixed source quotas.

    Scores from independent pgvector stores are not directly comparable, so
    this merger keeps each source's own rank order and applies a fixed quota
    before producing the final evidence list.
    """

    review_selected = _take_unique(
        items=review_case_evidence,
        seen=set(),
        limit=max(review_case_quota, 0),
    )
    seen = {_source_reference(item) for item in review_selected if _source_reference(item)}
    precedent_selected = _take_unique(
        items=fault_ratio_precedent_evidence,
        seen=seen,
        limit=max(fault_ratio_precedent_quota, 0),
    )

    merged = (review_selected + precedent_selected)[: max(final_top_k, 0)]
    source_counts = _count_by_source_type(merged)

    return {
        "merge_strategy": V2_MERGE_STRATEGY,
        "review_case_quota": review_case_quota,
        "fault_ratio_precedent_quota": fault_ratio_precedent_quota,
        "final_top_k": final_top_k,
        "source_counts": source_counts,
        "input_counts": {
            "review_case": len(review_case_evidence),
            "fault_ratio_precedent": len(fault_ratio_precedent_evidence),
        },
        "output_count": len(merged),
        "evidence": merged,
    }


def _take_unique(
    *,
    items: list[dict[str, Any]],
    seen: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in items:
        if len(selected) >= limit:
            break
        reference = _source_reference(item)
        if reference and reference in seen:
            continue
        if reference:
            seen.add(reference)
        selected.append(item)
    return selected


def _count_by_source_type(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        source_type = str(item.get("source_type") or "unknown").strip() or "unknown"
        counts[source_type] = counts.get(source_type, 0) + 1
    return counts


def _source_reference(item: dict[str, Any]) -> str:
    return str(item.get("source_reference") or "").strip()
