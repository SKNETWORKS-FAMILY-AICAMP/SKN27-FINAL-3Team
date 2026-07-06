from __future__ import annotations

import argparse
import json
from typing import Any

from .bm25_retriever import search_bm25
from .vector_retriever import embed_query, search_vector_by_embedding
from ..search_config import ELASTICSEARCH_SETTINGS


def reciprocal_rank(rank: int, k: int) -> float:
    return 1.0 / (k + rank)


def search_hybrid(
    dataset: str,
    query: str,
    top_k: int | None = None,
    candidate_k: int | None = None,
    rrf_k: int | None = None,
) -> list[dict[str, Any]]:
    limit = top_k or ELASTICSEARCH_SETTINGS.default_top_k
    candidates = candidate_k or max(limit * 10, ELASTICSEARCH_SETTINGS.vector_num_candidates)
    fusion_k = rrf_k or ELASTICSEARCH_SETTINGS.hybrid_rrf_k
    query_vector = embed_query(query)

    bm25_results = search_bm25(dataset=dataset, query=query, top_k=candidates)
    vector_results = search_vector_by_embedding(
        dataset=dataset,
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
        row["dataset"] = dataset
    return fused[:limit]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Elasticsearch BM25/vector hybrid search for precedent chunks.")
    parser.add_argument("--dataset", choices=["traffic", "fault_ratio"], required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=ELASTICSEARCH_SETTINGS.default_top_k)
    parser.add_argument("--candidate-k", type=int, default=None)
    parser.add_argument("--include-text", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = search_hybrid(
        dataset=args.dataset,
        query=args.query,
        top_k=args.top_k,
        candidate_k=args.candidate_k,
    )
    if not args.include_text:
        for row in results:
            row["chunk_text"] = row["chunk_text"][:300]
            row["search_text"] = row["search_text"][:300]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
