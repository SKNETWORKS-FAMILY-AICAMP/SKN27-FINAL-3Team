from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.rag.source_reference import (
    build_review_case_source_reference,
)


def map_review_case_hit_to_evidence(hit: dict[str, Any]) -> dict[str, Any]:
    row = hit.get("source") or {}

    review_case_id = _first_non_empty(hit.get("review_case_id"), row.get("review_case_id"))
    review_no = _first_non_empty(hit.get("review_no"), row.get("review_no"))
    chunk_id = _first_non_empty(hit.get("chunk_id"), row.get("chunk_id"))
    title = _first_non_empty(hit.get("case_title"), row.get("case_title"))

    return {
        "source_type": "review_case",
        "title": title,
        "source_reference": build_review_case_source_reference(
            review_case_id=review_case_id,
            review_no=review_no,
            chunk_id=chunk_id,
        ),
        "metadata": {
            "case_id": review_case_id,
            "review_case_id": review_case_id,
            "review_no": review_no,
            "chunk_id": chunk_id,
            "chunk_type": _first_non_empty(hit.get("chunk_type"), row.get("chunk_type")),
            "case_title": title,
            "reference_chart_key": _first_non_empty(
                hit.get("reference_chart_key"),
                row.get("reference_chart_key"),
            ),
            "decision_fault_ratio": _first_non_empty(
                hit.get("decision_fault_ratio"),
                row.get("decision_fault_ratio"),
            ),
            "claimant_final_ratio": _first_non_empty(
                hit.get("claimant_final_ratio"),
                row.get("claimant_final_ratio"),
            ),
            "respondent_final_ratio": _first_non_empty(
                hit.get("respondent_final_ratio"),
                row.get("respondent_final_ratio"),
            ),
            "standard_context": {
                "signal_condition": _first_non_empty(
                    hit.get("signal_condition"),
                    row.get("signal_condition"),
                ),
                "road_feature": _first_non_empty(
                    hit.get("road_feature"),
                    row.get("road_feature"),
                ),
                "standard_a_behavior": _first_non_empty(
                    hit.get("standard_a_behavior"),
                    row.get("standard_a_behavior"),
                ),
                "standard_b_behavior": _first_non_empty(
                    hit.get("standard_b_behavior"),
                    row.get("standard_b_behavior"),
                ),
            },
            "score": hit.get("retriever_score"),
            "score_type": hit.get("score_type") or "cosine_similarity",
            "retriever": hit.get("retriever") or "review_case_pgvector",
            "index": hit.get("index"),
            "rank": hit.get("rank"),
            "highlight": hit.get("highlight") or {},
            "matched_facts": [],
            "different_facts": [],
        },
        "chunk_text": _first_non_empty(hit.get("chunk_text"), row.get("chunk_text")),
        "search_text": _first_non_empty(hit.get("search_text"), row.get("search_text")),
        "confidence": None,
    }


def map_review_case_hits_to_evidence(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [map_review_case_hit_to_evidence(hit) for hit in hits]


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
