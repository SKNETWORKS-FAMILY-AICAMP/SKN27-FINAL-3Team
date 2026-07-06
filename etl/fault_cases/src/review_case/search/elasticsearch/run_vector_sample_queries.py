from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any

from etl.fault_cases.src.review_case.db_loading.db_config import (
    ELASTICSEARCH_EXPORT_ROOT,
    ELASTICSEARCH_SETTINGS,
    EMBEDDING_SETTINGS,
    SETTINGS,
)
from etl.fault_cases.src.review_case.search.sample_queries import SAMPLE_QUERIES

from .vector_retriever import compact_result, search_vector


def run_samples(top_k: int, include_text: bool = False) -> dict[str, Any]:
    query_reports = []
    for query_info in SAMPLE_QUERIES:
        results = search_vector(query=query_info["query"], top_k=top_k)
        query_reports.append(
            {
                "query_id": query_info["query_id"],
                "query": query_info["query"],
                "expected_reference_chart_key": query_info.get("expected_reference_chart_key") or None,
                "top_k": top_k,
                "result_count": len(results),
                "results": [compact_result(row, include_text=include_text) for row in results],
            }
        )

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "db_name": SETTINGS.review_case_db,
        "retriever": "elasticsearch_vector_cosine",
        "elasticsearch_host": ELASTICSEARCH_SETTINGS.host,
        "elasticsearch_index": ELASTICSEARCH_SETTINGS.vector_index_name,
        "index_version": ELASTICSEARCH_SETTINGS.vector_index_version,
        "embedding_provider": EMBEDDING_SETTINGS.provider,
        "embedding_model": EMBEDDING_SETTINGS.model,
        "embedding_dim": EMBEDDING_SETTINGS.dim,
        "embedding_version": EMBEDDING_SETTINGS.version,
        "query_count": len(SAMPLE_QUERIES),
        "top_k": top_k,
        "queries": query_reports,
    }
    report_path = ELASTICSEARCH_EXPORT_ROOT / ELASTICSEARCH_SETTINGS.vector_sample_report_name
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run review_case Elasticsearch dense_vector sample queries.")
    parser.add_argument("--top-k", type=int, default=ELASTICSEARCH_SETTINGS.default_top_k)
    parser.add_argument("--include-text", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    print(json.dumps(run_samples(top_k=args.top_k, include_text=args.include_text), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
