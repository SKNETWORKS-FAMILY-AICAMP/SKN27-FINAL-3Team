from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from etl.fault_cases.src.review_case.db_loading.db_config import ELASTICSEARCH_SETTINGS

from .bm25_retriever import search_bm25
from .vector_retriever import embed_query, search_vector_by_embedding


def reciprocal_rank(rank: int, k: int) -> float:
    return 1.0 / (k + rank)


def search_hybrid(
    query: str,
    top_k: int | None = None,
    candidate_k: int | None = None,
    rrf_k: int | None = None,
) -> list[dict[str, Any]]:
    limit = top_k or ELASTICSEARCH_SETTINGS.default_top_k
    candidates = candidate_k or max(limit * 10, ELASTICSEARCH_SETTINGS.vector_num_candidates)
    fusion_k = rrf_k or ELASTICSEARCH_SETTINGS.hybrid_rrf_k
    query_vector = embed_query(query)

    bm25_results = search_bm25(query=query, top_k=candidates)
    vector_results = search_vector_by_embedding(
        query_vector=query_vector,
        top_k=candidates,
        num_candidates=max(candidates * 2, ELASTICSEARCH_SETTINGS.vector_num_candidates),
    )

    merged: dict[str, dict[str, Any]] = {}
    for row in bm25_results:
        chunk_id = row["chunk_id"]
        merged.setdefault(chunk_id, row.copy())
        merged[chunk_id]["bm25_rank"] = row["rank"]
        merged[chunk_id]["bm25_score"] = row["bm25_score"]
        merged[chunk_id]["rrf_bm25"] = reciprocal_rank(row["rank"], fusion_k)

    for row in vector_results:
        chunk_id = row["chunk_id"]
        merged.setdefault(chunk_id, row.copy())
        merged[chunk_id]["vector_rank"] = row["rank"]
        merged[chunk_id]["vector_score"] = row["vector_score"]
        merged[chunk_id]["rrf_vector"] = reciprocal_rank(row["rank"], fusion_k)

    fused = []
    for row in merged.values():
        row["rrf_bm25"] = row.get("rrf_bm25", 0.0)
        row["rrf_vector"] = row.get("rrf_vector", 0.0)
        row["hybrid_score"] = row["rrf_bm25"] + row["rrf_vector"]
        fused.append(row)

    fused.sort(
        key=lambda row: (
            row["hybrid_score"],
            row.get("vector_score") or 0.0,
            row.get("bm25_score") or 0.0,
        ),
        reverse=True,
    )
    for rank, row in enumerate(fused[:limit], start=1):
        row["rank"] = rank
    return fused[:limit]


def compact_result(row: dict[str, Any], include_text: bool = False) -> dict[str, Any]:
    result = {
        "rank": row["rank"],
        "review_case_id": row.get("review_case_id"),
        "review_no": row.get("review_no"),
        "chunk_id": row.get("chunk_id"),
        "chunk_type": row.get("chunk_type"),
        "case_title": row.get("case_title"),
        "reference_chart_key": row.get("reference_chart_key"),
        "decision_fault_ratio": row.get("decision_fault_ratio"),
        "claimant_final_ratio": row.get("claimant_final_ratio"),
        "respondent_final_ratio": row.get("respondent_final_ratio"),
        "signal_condition": row.get("signal_condition"),
        "road_feature": row.get("road_feature"),
        "standard_a_behavior": row.get("standard_a_behavior"),
        "standard_b_behavior": row.get("standard_b_behavior"),
        "hybrid_score": row["hybrid_score"],
        "bm25_rank": row.get("bm25_rank"),
        "bm25_score": row.get("bm25_score"),
        "vector_rank": row.get("vector_rank"),
        "vector_score": row.get("vector_score"),
        "rrf_bm25": row["rrf_bm25"],
        "rrf_vector": row["rrf_vector"],
        "chunk_preview": str(row.get("chunk_text") or "")[:500],
        "search_preview": str(row.get("search_text") or "")[:500],
    }
    if include_text:
        result["chunk_text"] = row.get("chunk_text")
        result["search_text"] = row.get("search_text")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Elasticsearch BM25/vector hybrid search for review case chunks.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=ELASTICSEARCH_SETTINGS.default_top_k)
    parser.add_argument("--candidate-k", type=int, default=None)
    parser.add_argument("--include-text", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    results = search_hybrid(query=args.query, top_k=args.top_k, candidate_k=args.candidate_k)
    print(
        json.dumps(
            [compact_result(row, include_text=args.include_text) for row in results],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
