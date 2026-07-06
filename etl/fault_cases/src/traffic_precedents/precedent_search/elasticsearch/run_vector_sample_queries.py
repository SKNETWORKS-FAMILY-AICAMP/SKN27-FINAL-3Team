from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

from .vector_retriever import search_vector
from ..sample_queries import SAMPLE_QUERIES
from ..search_config import DATASET_SEARCH_CONFIGS, ELASTICSEARCH_SETTINGS, SEARCH_SETTINGS, ensure_parent


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
        "vector_score": row["vector_score"],
        "chunk_preview": row["chunk_text"][:400],
    }


def run_dataset_samples(dataset: str, top_k: int) -> dict[str, Any]:
    query_reports = []
    for query in SAMPLE_QUERIES[dataset]:
        results = search_vector(dataset=dataset, query=query, top_k=top_k)
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
        "retriever": "elasticsearch_vector_cosine",
        "elasticsearch_host": ELASTICSEARCH_SETTINGS.host,
        "elasticsearch_index": DATASET_SEARCH_CONFIGS[dataset]["elasticsearch_vector_index"],
        "index_version": ELASTICSEARCH_SETTINGS.vector_index_version,
        "embedding_model": SEARCH_SETTINGS.embedding_model,
        "embedding_version": SEARCH_SETTINGS.embedding_version,
        "embedding_dim": SEARCH_SETTINGS.embedding_dim,
        "queries": query_reports,
    }
    report_path = DATASET_SEARCH_CONFIGS[dataset]["elasticsearch_vector_sample_report_path"]
    ensure_parent(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run sample Elasticsearch vector queries.")
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
