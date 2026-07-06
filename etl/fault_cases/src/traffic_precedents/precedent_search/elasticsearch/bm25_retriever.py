from __future__ import annotations

import argparse
import json
from typing import Any

from .client import get_elasticsearch_client
from ..search_config import DATASET_SEARCH_CONFIGS, ELASTICSEARCH_SETTINGS


def search_bm25(dataset: str, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    config = DATASET_SEARCH_CONFIGS[dataset]
    index_name = config["elasticsearch_index"]
    limit = top_k or ELASTICSEARCH_SETTINGS.default_top_k
    client = get_elasticsearch_client()
    response = client.search(
        index=index_name,
        size=limit,
        query={
            "multi_match": {
                "query": query,
                "fields": [
                    "search_text^3",
                    "chunk_text^2",
                    "case_name^1.5",
                    "search_text_standard",
                    "chunk_text_standard",
                ],
                "type": "best_fields",
                "operator": "or",
            }
        },
        highlight={
            "fields": {
                "search_text": {"fragment_size": 160, "number_of_fragments": 2},
                "chunk_text": {"fragment_size": 160, "number_of_fragments": 2},
            }
        },
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
                "bm25_score": float(hit["_score"]),
                "chunk_text": source.get("chunk_text") or "",
                "search_text": source.get("search_text") or "",
                "highlight": hit.get("highlight") or {},
                "metadata": source.get("metadata") or {},
            }
        )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Elasticsearch BM25/Nori search for precedent chunks.")
    parser.add_argument("--dataset", choices=["traffic", "fault_ratio"], required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=ELASTICSEARCH_SETTINGS.default_top_k)
    parser.add_argument("--include-text", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = search_bm25(dataset=args.dataset, query=args.query, top_k=args.top_k)
    if not args.include_text:
        for row in results:
            row["chunk_text"] = row["chunk_text"][:300]
            row["search_text"] = row["search_text"][:300]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
