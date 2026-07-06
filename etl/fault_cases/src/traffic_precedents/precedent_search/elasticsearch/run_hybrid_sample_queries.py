from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

from .hybrid_retriever import search_hybrid
from ..sample_queries import SAMPLE_QUERIES
from ..search_config import DATASET_SEARCH_CONFIGS, ELASTICSEARCH_SETTINGS, ensure_parent


def compact_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": row["rank"],
        "case_id": row["case_id"],
        "chunk_id": row["chunk_id"],
        "chunk_type": row["chunk_type"],
        "case_name": row.get("case_name"),
        "case_number": row.get("case_number"),
        "court_name": row.get("court_name"),
        "decision_date": row.get("decision_date"),
        "hybrid_score": row["hybrid_score"],
        "bm25_rank": row.get("bm25_rank"),
        "bm25_score": row.get("bm25_score"),
        "vector_rank": row.get("vector_rank"),
        "vector_score": row.get("vector_score"),
        "rrf_bm25": row["rrf_bm25"],
        "rrf_vector": row["rrf_vector"],
        "chunk_preview": row.get("chunk_text", "")[:400],
    }


def run_dataset_samples(dataset: str, top_k: int, candidate_k: int | None = None) -> dict[str, Any]:
    query_reports = []
    for query in SAMPLE_QUERIES[dataset]:
        results = search_hybrid(dataset=dataset, query=query, top_k=top_k, candidate_k=candidate_k)
        query_reports.append(
            {
                "query": query,
                "top_k": top_k,
                "candidate_k": candidate_k,
                "result_count": len(results),
                "results": [compact_result(row) for row in results],
            }
        )

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": dataset,
        "retriever": "elasticsearch_hybrid_bm25_vector_rrf",
        "elasticsearch_bm25_index": DATASET_SEARCH_CONFIGS[dataset]["elasticsearch_index"],
        "elasticsearch_vector_index": DATASET_SEARCH_CONFIGS[dataset]["elasticsearch_vector_index"],
        "rrf_k": ELASTICSEARCH_SETTINGS.hybrid_rrf_k,
        "queries": query_reports,
    }
    report_path = DATASET_SEARCH_CONFIGS[dataset]["elasticsearch_hybrid_sample_report_path"]
    ensure_parent(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run sample Elasticsearch BM25/vector hybrid queries.")
    parser.add_argument("--dataset", choices=["traffic", "fault_ratio", "all"], default="all")
    parser.add_argument("--top-k", type=int, default=ELASTICSEARCH_SETTINGS.default_top_k)
    parser.add_argument("--candidate-k", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    datasets = DATASET_SEARCH_CONFIGS.keys() if args.dataset == "all" else [args.dataset]
    reports = {
        dataset: run_dataset_samples(dataset=dataset, top_k=args.top_k, candidate_k=args.candidate_k)
        for dataset in datasets
    }
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
