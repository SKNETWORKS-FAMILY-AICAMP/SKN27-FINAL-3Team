from __future__ import annotations

import argparse
import json
from typing import Any

from etl.fault_cases.src.traffic_precedents.precedent_embedding.openai_embedder import OpenAIEmbedder

from .client import get_elasticsearch_client
from ..search_config import DATASET_SEARCH_CONFIGS, ELASTICSEARCH_SETTINGS, SEARCH_SETTINGS


def embed_query(query: str) -> list[float]:
    result = OpenAIEmbedder().embed_texts([query])
    if not result.vectors:
        raise RuntimeError("Query embedding API returned no vector")
    return result.vectors[0]


def search_vector_by_embedding(
    dataset: str,
    query_vector: list[float],
    top_k: int | None = None,
    num_candidates: int | None = None,
) -> list[dict[str, Any]]:
    config = DATASET_SEARCH_CONFIGS[dataset]
    index_name = config["elasticsearch_vector_index"]
    limit = top_k or ELASTICSEARCH_SETTINGS.default_top_k
    candidate_count = num_candidates or max(ELASTICSEARCH_SETTINGS.vector_num_candidates, limit * 10)
    client = get_elasticsearch_client()
    response = client.search(
        index=index_name,
        size=limit,
        knn={
            "field": "embedding_vector",
            "query_vector": query_vector,
            "k": limit,
            "num_candidates": candidate_count,
        },
        source={"excludes": ["embedding_vector"]},
    )

    results = []
    for rank, hit in enumerate(response["hits"]["hits"], start=1):
        source = hit["_source"]
        results.append(
            {
                "dataset": dataset,
                "rank": rank,
                "case_id": source["case_id"],
                "chunk_id": source["chunk_id"],
                "chunk_index": source["chunk_index"],
                "chunk_type": source["chunk_type"],
                "chunk_strategy": source["chunk_strategy"],
                "case_name": source.get("case_name"),
                "case_number": source.get("case_number"),
                "court_name": source.get("court_name"),
                "decision_date": source.get("decision_date"),
                "vector_score": float(hit["_score"]),
                "chunk_text": source.get("chunk_text") or "",
                "search_text": source.get("search_text") or "",
                "metadata": source.get("metadata") or {},
                "embedding_model": source.get("embedding_model") or SEARCH_SETTINGS.embedding_model,
                "embedding_version": source.get("embedding_version") or SEARCH_SETTINGS.embedding_version,
                "embedding_dim": source.get("embedding_dim") or SEARCH_SETTINGS.embedding_dim,
            }
        )
    return results


def search_vector(dataset: str, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    return search_vector_by_embedding(dataset=dataset, query_vector=embed_query(query), top_k=top_k)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Elasticsearch dense_vector search for precedent chunks.")
    parser.add_argument("--dataset", choices=["traffic", "fault_ratio"], required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=ELASTICSEARCH_SETTINGS.default_top_k)
    parser.add_argument("--include-text", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = search_vector(dataset=args.dataset, query=args.query, top_k=args.top_k)
    if not args.include_text:
        for row in results:
            row["chunk_text"] = row["chunk_text"][:300]
            row["search_text"] = row["search_text"][:300]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
