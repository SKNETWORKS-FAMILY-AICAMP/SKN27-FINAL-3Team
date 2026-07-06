from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.config import ARTIFACT_ROOT
from etl.fault_cases.src.traffic_precedents.precedent_search.elasticsearch.client import (
    get_elasticsearch_client,
)
from etl.fault_cases.src.traffic_precedents.precedent_search.search_config import (
    ELASTICSEARCH_SETTINGS,
)
from etl.fault_cases.src.traffic_precedents.precedent_search.traffic_law.bm25_nori_retriever import (
    TRAFFIC_LAW_INDEX_NAME,
    search_traffic_law_bm25,
)
from etl.fault_cases.src.traffic_precedents.precedent_search.traffic_law.sample_queries import (
    get_traffic_law_sample_queries,
)


DEFAULT_OUTPUT_DIR = ARTIFACT_ROOT / "traffic_law_rag"
DEFAULT_OUTPUT_JSON = DEFAULT_OUTPUT_DIR / "traffic_law_bm25_sample_queries.json"
DEFAULT_SUMMARY_JSON = DEFAULT_OUTPUT_DIR / "traffic_law_bm25_summary.json"


def run_bm25_sample_queries(
    *,
    top_k: int = ELASTICSEARCH_SETTINGS.default_top_k,
    output_json: Path = DEFAULT_OUTPUT_JSON,
    summary_json: Path = DEFAULT_SUMMARY_JSON,
) -> dict[str, Any]:
    queries = get_traffic_law_sample_queries()
    es = get_elasticsearch_client()

    query_results: list[dict[str, Any]] = []
    total_result_count = 0
    zero_result_query_ids: list[str] = []

    for query in queries:
        results = search_traffic_law_bm25(
            query=query["query"],
            top_k=top_k,
            es=es,
            index_name=TRAFFIC_LAW_INDEX_NAME,
        )
        for result in results:
            result["query_id"] = query["query_id"]
            result["query"] = query["query"]
            result["issue_tags"] = query["issue_tags"]

        total_result_count += len(results)
        if not results:
            zero_result_query_ids.append(query["query_id"])

        query_results.append(
            {
                "query_id": query["query_id"],
                "query": query["query"],
                "issue_tags": query["issue_tags"],
                "purpose": query["purpose"],
                "top_k": top_k,
                "result_count": len(results),
                "results": results,
            }
        )

    created_at = datetime.now().isoformat(timespec="seconds")
    report = {
        "created_at": created_at,
        "retriever": "traffic_law_bm25_nori",
        "source_type": "traffic_precedent",
        "elasticsearch_index": TRAFFIC_LAW_INDEX_NAME,
        "top_k": top_k,
        "query_count": len(queries),
        "total_result_count": total_result_count,
        "zero_result_query_ids": zero_result_query_ids,
        "queries": query_results,
    }
    summary = {
        "created_at": created_at,
        "retriever": "traffic_law_bm25_nori",
        "source_type": "traffic_precedent",
        "elasticsearch_index": TRAFFIC_LAW_INDEX_NAME,
        "top_k": top_k,
        "query_count": len(queries),
        "total_result_count": total_result_count,
        "zero_result_query_count": len(zero_result_query_ids),
        "zero_result_query_ids": zero_result_query_ids,
        "output_json": str(output_json),
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "output_json": str(output_json),
        "summary_json": str(summary_json),
        "query_count": len(queries),
        "total_result_count": total_result_count,
        "zero_result_query_ids": zero_result_query_ids,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BM25/Nori sample queries for traffic law precedents.")
    parser.add_argument("--top-k", type=int, default=ELASTICSEARCH_SETTINGS.default_top_k)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--summary-json", default=str(DEFAULT_SUMMARY_JSON))
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    result = run_bm25_sample_queries(
        top_k=args.top_k,
        output_json=Path(args.output_json),
        summary_json=Path(args.summary_json),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

