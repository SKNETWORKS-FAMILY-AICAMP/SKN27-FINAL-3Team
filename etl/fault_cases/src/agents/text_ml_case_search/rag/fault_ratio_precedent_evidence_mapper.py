from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.rag.source_reference import (
    build_fault_ratio_precedent_source_reference,
)


def map_fault_ratio_precedent_hit_to_evidence(hit: dict[str, Any]) -> dict[str, Any]:
    row = hit.get("source") or {}

    case_id = _first_non_empty(hit.get("case_id"), row.get("case_id"), row.get("raw_case_id"))
    case_number = _first_non_empty(hit.get("case_number"), row.get("case_number"))
    chunk_id = _first_non_empty(hit.get("chunk_id"), row.get("chunk_id"))
    title = _first_non_empty(hit.get("case_name"), row.get("case_name"))
    chunk_type = _first_non_empty(hit.get("chunk_type"), row.get("chunk_type"))

    return {
        "source_type": "fault_ratio_precedent",
        "title": title,
        "source_reference": build_fault_ratio_precedent_source_reference(
            case_id=case_id,
            case_number=case_number,
            chunk_id=chunk_id,
        ),
        "metadata": {
            "case_id": case_id,
            "raw_case_id": _first_non_empty(hit.get("raw_case_id"), row.get("raw_case_id")),
            "case_number": case_number,
            "case_name": title,
            "court_name": _first_non_empty(hit.get("court_name"), row.get("court_name")),
            "decision_date": _first_non_empty(hit.get("decision_date"), row.get("decision_date")),
            "chunk_id": chunk_id,
            "chunk_index": _first_non_empty(hit.get("chunk_index"), row.get("chunk_index")),
            "chunk_type": chunk_type,
            "chunk_strategy": _first_non_empty(hit.get("chunk_strategy"), row.get("chunk_strategy")),
            "score": hit.get("retriever_score"),
            "score_type": hit.get("score_type") or "bm25_score",
            "retriever": hit.get("retriever") or "fault_ratio_precedent_bm25_nori",
            "index": hit.get("index"),
            "rank": hit.get("rank"),
            "highlight": hit.get("highlight") or {},
            "precedent_context": {
                "source_role": "fault_ratio_precedent",
                "source_label": "fault_ratio_precedent",
                "chunk_type": chunk_type,
            },
            "matched_facts": [],
            "different_facts": [],
        },
        "chunk_text": _first_non_empty(hit.get("chunk_text"), row.get("chunk_text")),
        "search_text": _first_non_empty(hit.get("search_text"), row.get("search_text")),
        "confidence": None,
    }


def map_fault_ratio_precedent_hits_to_evidence(
    hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [map_fault_ratio_precedent_hit_to_evidence(hit) for hit in hits]


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
