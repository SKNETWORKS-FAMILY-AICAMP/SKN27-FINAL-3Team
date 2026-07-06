from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from etl.fault_cases.src.review_case.db_loading.db_config import ELASTICSEARCH_SETTINGS

from .client import get_elasticsearch_client


def search_bm25(query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    limit = top_k or ELASTICSEARCH_SETTINGS.default_top_k
    client = get_elasticsearch_client()
    response = client.search(
        index=ELASTICSEARCH_SETTINGS.bm25_index_name,
        size=limit,
        query={
            "multi_match": {
                "query": query,
                "fields": [
                    "search_text^4",
                    "chunk_text^2",
                    "case_title^2",
                    "header_road_context^1.5",
                    "search_text_standard",
                    "chunk_text_standard",
                ],
                "type": "best_fields",
                "operator": "or",
            }
        },
        highlight={
            "fields": {
                "search_text": {"fragment_size": 180, "number_of_fragments": 2},
                "chunk_text": {"fragment_size": 180, "number_of_fragments": 2},
            }
        },
    )

    results: list[dict[str, Any]] = []
    for rank, hit in enumerate(response["hits"]["hits"], start=1):
        source = hit["_source"]
        results.append(
            {
                "rank": rank,
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
                "bm25_score": float(hit["_score"]),
                "chunk_text": source.get("chunk_text") or "",
                "search_text": source.get("search_text") or "",
                "highlight": hit.get("highlight") or {},
            }
        )
    return results


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
        "bm25_score": row["bm25_score"],
        "chunk_preview": str(row.get("chunk_text") or "")[:500],
        "search_preview": str(row.get("search_text") or "")[:500],
        "highlight": row.get("highlight") or {},
    }
    if include_text:
        result["chunk_text"] = row.get("chunk_text")
        result["search_text"] = row.get("search_text")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Elasticsearch BM25/Nori search for review case chunks.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=ELASTICSEARCH_SETTINGS.default_top_k)
    parser.add_argument("--include-text", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    results = search_bm25(query=args.query, top_k=args.top_k)
    print(
        json.dumps(
            [compact_result(row, include_text=args.include_text) for row in results],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
