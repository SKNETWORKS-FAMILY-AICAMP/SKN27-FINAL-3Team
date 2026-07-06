from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

from .bm25_retriever import search_bm25
from ..search_config import DATASET_SEARCH_CONFIGS, ELASTICSEARCH_SETTINGS, ensure_parent
from ..sample_queries import SAMPLE_QUERIES


def compact_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": row["rank"],
        "case_id": row["case_id"],
        "chunk_id": row["chunk_id"],
        "chunk_type": row["chunk_type"],
        "case_name": row["case_name"],
        "case_number": row["case_number"],
        "court_name": row["court_name"],
        "decision_date": row["decision_date"],
        "bm25_score": row["bm25_score"],
        "chunk_preview": row["chunk_text"][:400],
        "highlight": row["highlight"],
    }


def run_dataset_samples(dataset: str, top_k: int) -> dict[str, Any]:
    query_reports = []
    for query in SAMPLE_QUERIES[dataset]:
        results = search_bm25(dataset=dataset, query=query, top_k=top_k)
        query_reports.append(
            {
                "query": query,
                "top_k": top_k,
                "result_count": len(results),
                "results": [compact_result(row) for row in results],
            }
        )

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": dataset,
        "retriever": "elasticsearch_bm25_nori",
        "elasticsearch_host": ELASTICSEARCH_SETTINGS.host,
        "elasticsearch_index": DATASET_SEARCH_CONFIGS[dataset]["elasticsearch_index"],
        "index_version": ELASTICSEARCH_SETTINGS.bm25_index_version,
        "analyzer": "precedent_nori",
        "queries": query_reports,
    }
    report_path = DATASET_SEARCH_CONFIGS[dataset]["elasticsearch_sample_report_path"]
    ensure_parent(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run sample Elasticsearch BM25/Nori queries.")
    parser.add_argument("--dataset", choices=["traffic", "fault_ratio", "all"], default="all")
    parser.add_argument("--top-k", type=int, default=ELASTICSEARCH_SETTINGS.default_top_k)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    datasets = DATASET_SEARCH_CONFIGS.keys() if args.dataset == "all" else [args.dataset]
    reports = {dataset: run_dataset_samples(dataset=dataset, top_k=args.top_k) for dataset in datasets}
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
