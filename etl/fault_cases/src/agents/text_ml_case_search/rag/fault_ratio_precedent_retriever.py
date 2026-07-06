from __future__ import annotations

from typing import Any, Protocol

from etl.fault_cases.src.agents.text_ml_case_search.config import (
    BM25_TOP_K,
    FAULT_RATIO_PRECEDENT_BM25_FIELDS,
    FAULT_RATIO_PRECEDENT_INDEX,
)


class ElasticsearchLike(Protocol):
    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        ...


def build_fault_ratio_precedent_bm25_query(
    *,
    search_text: str,
    top_k: int = BM25_TOP_K,
) -> dict[str, Any]:
    """Build the Agent V2 BM25/Nori query for fault-ratio precedent chunks."""

    return {
        "query": {
            "multi_match": {
                "query": search_text,
                "fields": FAULT_RATIO_PRECEDENT_BM25_FIELDS,
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


def search_fault_ratio_precedent_bm25(
    *,
    es: ElasticsearchLike,
    search_text: str,
    index_name: str | None = None,
    top_k: int = BM25_TOP_K,
) -> list[dict[str, Any]]:
    query = search_text.strip()
    if not query:
        return []

    response = es.search(
        index=index_name or FAULT_RATIO_PRECEDENT_INDEX,
        body=build_fault_ratio_precedent_bm25_query(search_text=query, top_k=top_k),
    )

    return [
        _parse_fault_ratio_precedent_hit(hit=hit, rank=rank)
        for rank, hit in enumerate(response.get("hits", {}).get("hits", []), start=1)
    ]


def _parse_fault_ratio_precedent_hit(*, hit: dict[str, Any], rank: int) -> dict[str, Any]:
    source = hit.get("_source") or {}
    score = hit.get("_score")

    return {
        "rank": rank,
        "retriever": "fault_ratio_precedent_bm25_nori",
        "score_type": "bm25_score",
        "retriever_score": float(score) if score is not None else None,
        "index": hit.get("_index"),
        "source": source,
        "highlight": hit.get("highlight") or {},
        "case_id": source.get("case_id"),
        "raw_case_id": source.get("raw_case_id"),
        "chunk_id": source.get("chunk_id"),
        "chunk_index": source.get("chunk_index"),
        "chunk_type": source.get("chunk_type"),
        "chunk_strategy": source.get("chunk_strategy"),
        "case_name": source.get("case_name"),
        "case_number": source.get("case_number"),
        "court_name": source.get("court_name"),
        "decision_date": source.get("decision_date"),
        "chunk_text": source.get("chunk_text") or "",
        "search_text": source.get("search_text") or "",
        "metadata": source.get("metadata") or {},
    }
