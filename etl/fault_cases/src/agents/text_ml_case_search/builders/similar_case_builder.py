from __future__ import annotations

from typing import Any


def build_similar_cases(
    *,
    evidence: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Build compact similar_cases from validated RAG evidence."""

    similar_cases: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for item in evidence:
        metadata = item.get("metadata") or {}
        case_id = _clean(metadata.get("case_id") or metadata.get("review_case_id"))
        chunk_id = _clean(metadata.get("chunk_id"))
        source_type = _clean(item.get("source_type") or "review_case")
        key = (source_type, case_id, chunk_id)
        if key in seen:
            continue
        seen.add(key)

        similar_cases.append(
            {
                "source_type": source_type,
                "case_id": case_id,
                "review_no": _clean(metadata.get("review_no")),
                "case_number": _clean(metadata.get("case_number")),
                "court_name": _clean(metadata.get("court_name")),
                "decision_date": _clean(metadata.get("decision_date")),
                "title": _clean(item.get("title") or metadata.get("case_title")),
                "source_reference": _clean(item.get("source_reference")),
                "chunk_id": chunk_id,
                "chunk_type": _clean(metadata.get("chunk_type")),
                "reference_chart_key": _clean(metadata.get("reference_chart_key")),
                "decision_fault_ratio": _clean(metadata.get("decision_fault_ratio")),
                "claimant_final_ratio": _clean(metadata.get("claimant_final_ratio")),
                "respondent_final_ratio": _clean(metadata.get("respondent_final_ratio")),
                "score": metadata.get("score"),
                "score_type": _clean(metadata.get("score_type")),
                "rank": metadata.get("rank"),
                "summary": _preview(item.get("chunk_text")),
                "standard_context": metadata.get("standard_context") or {},
                "precedent_context": metadata.get("precedent_context") or {},
            }
        )

        if len(similar_cases) >= limit:
            break

    return similar_cases


def _preview(value: Any, limit: int = 220) -> str:
    text = " ".join(_clean(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _clean(value: Any) -> str:
    return str(value or "").strip()
