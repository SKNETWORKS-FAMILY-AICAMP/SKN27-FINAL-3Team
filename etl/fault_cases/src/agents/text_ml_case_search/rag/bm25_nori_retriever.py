from __future__ import annotations

from typing import Any, Protocol

from etl.fault_cases.src.agents.text_ml_case_search.config import (
    BM25_SEARCH_FIELDS,
    BM25_TOP_K,
    EVIDENCE_INDEX_NAMES,
)


class ElasticsearchLike(Protocol):
    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        ...


def build_bm25_query(*, search_text: str, top_k: int = BM25_TOP_K) -> dict[str, Any]:
    """Build the Agent V1 BM25/Nori query body.

    This file is the Agent-side operational retriever. It does not import or
    call the review_case test retriever. The search condition is copied here so
    this package owns the runtime behavior.
    """

    return {
        "query": {
            "multi_match": {
                "query": search_text,
                "fields": BM25_SEARCH_FIELDS,
                "type": "best_fields",
                "operator": "or",
            }
        },
        "size": top_k,
        "highlight": {
            "fields": {
                "search_text": {"fragment_size": 180, "number_of_fragments": 2},
                "chunk_text": {"fragment_size": 180, "number_of_fragments": 2},
            }
        },
    }


def search_bm25_nori(
    *,
    es: ElasticsearchLike,
    search_text: str,
    index_names: list[str] | None = None,
    top_k: int = BM25_TOP_K,
) -> list[dict[str, Any]]:
    query = search_text.strip()
    if not query:
        return []

    indexes = index_names or EVIDENCE_INDEX_NAMES
    if not indexes:
        return []

    response = es.search(
        index=",".join(indexes),
        body=build_bm25_query(search_text=query, top_k=top_k),
    )

    return [
        _parse_bm25_hit(hit=hit, rank=rank)
        for rank, hit in enumerate(response.get("hits", {}).get("hits", []), start=1)
    ]


def _parse_bm25_hit(*, hit: dict[str, Any], rank: int) -> dict[str, Any]:
    source = hit.get("_source") or {}
    score = hit.get("_score")

    return {
        "rank": rank,
        "retriever": "bm25_nori",
        "score_type": "bm25_score",
        "retriever_score": float(score) if score is not None else None,
        "index": hit.get("_index"),
        "source": source,
        "highlight": hit.get("highlight") or {},
        "review_case_id": source.get("review_case_id"),
        "review_no": source.get("review_no"),
        "chunk_id": source.get("chunk_id"),
        "chunk_type": source.get("chunk_type"),
        "case_title": source.get("case_title"),
        "reference_chart_key": source.get("reference_chart_key"),
        "decision_fault_ratio": source.get("decision_fault_ratio"),
        "claimant_final_ratio": source.get("claimant_final_ratio"),
        "respondent_final_ratio": source.get("respondent_final_ratio"),
        "signal_condition": source.get("signal_condition"),
        "road_feature": source.get("road_feature"),
        "standard_a_behavior": source.get("standard_a_behavior"),
        "standard_b_behavior": source.get("standard_b_behavior"),
        "chunk_text": source.get("chunk_text") or "",
        "search_text": source.get("search_text") or "",
    }
