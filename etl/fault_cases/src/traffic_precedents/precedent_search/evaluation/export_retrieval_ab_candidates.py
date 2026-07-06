from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ..search_config import DATASET_SEARCH_CONFIGS, RETRIEVAL_AB_EXPORT_ROOT, ensure_parent


RETRIEVER_SPECS = {
    "pgvector": {
        "retriever": "pgvector",
        "score_field": "cosine_similarity",
        "score_type": "cosine_similarity",
        "distance_field": "cosine_distance",
        "source_path_key": "sample_report_path",
    },
    "elasticsearch_bm25_nori": {
        "retriever": "elasticsearch_bm25_nori",
        "score_field": "bm25_score",
        "score_type": "bm25_score",
        "distance_field": None,
        "source_path_key": "elasticsearch_sample_report_path",
    },
    "elasticsearch_vector_cosine": {
        "retriever": "elasticsearch_vector_cosine",
        "score_field": "vector_score",
        "score_type": "elasticsearch_vector_score",
        "distance_field": None,
        "source_path_key": "elasticsearch_vector_sample_report_path",
    },
    "elasticsearch_hybrid_bm25_vector_rrf": {
        "retriever": "elasticsearch_hybrid_bm25_vector_rrf",
        "score_field": "hybrid_score",
        "score_type": "rrf_hybrid_score",
        "distance_field": None,
        "source_path_key": "elasticsearch_hybrid_sample_report_path",
    },
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def make_query_id(dataset: str, query_index: int) -> str:
    return f"{dataset}_q{query_index:03d}"


def normalize_result(
    dataset: str,
    query_id: str,
    query: str,
    retriever_name: str,
    result: dict[str, Any],
    source_file: Path,
) -> dict[str, Any]:
    spec = RETRIEVER_SPECS[retriever_name]
    score = result.get(spec["score_field"])
    distance = result.get(spec["distance_field"]) if spec["distance_field"] else None
    return {
        "query_id": query_id,
        "dataset": dataset,
        "query": query,
        "retriever": spec["retriever"],
        "rank": result.get("rank"),
        "case_id": str(result.get("case_id") or ""),
        "chunk_id": result.get("chunk_id"),
        "chunk_type": result.get("chunk_type"),
        "case_name": result.get("case_name"),
        "case_number": result.get("case_number"),
        "court_name": result.get("court_name"),
        "decision_date": result.get("decision_date"),
        "retriever_score": float(score) if score is not None else None,
        "score_type": spec["score_type"],
        "distance_score": float(distance) if distance is not None else None,
        "distance_type": spec["distance_field"],
        "chunk_preview": result.get("chunk_preview") or "",
        "highlight": result.get("highlight") or {},
        "bm25_rank": result.get("bm25_rank"),
        "bm25_score": result.get("bm25_score"),
        "vector_rank": result.get("vector_rank"),
        "vector_score": result.get("vector_score"),
        "rrf_bm25": result.get("rrf_bm25"),
        "rrf_vector": result.get("rrf_vector"),
        "source_file": str(source_file),
    }


def validate_query_alignment(dataset: str, reports: dict[str, dict[str, Any]]) -> list[str]:
    query_lists = {
        retriever: [query_block["query"] for query_block in report.get("queries", [])]
        for retriever, report in reports.items()
    }
    unique_query_lists = {tuple(queries) for queries in query_lists.values()}
    if len(unique_query_lists) == 1:
        return list(next(iter(unique_query_lists)))

    details = "\n".join(f"{retriever}: {queries}" for retriever, queries in query_lists.items())
    raise ValueError(f"Query set mismatch for dataset '{dataset}'.\n{details}")


def effective_top_k_for_query(
    reports: dict[str, dict[str, Any]],
    query_index: int,
    requested_top_k: int | None,
) -> int:
    available_counts = [
        len(report["queries"][query_index].get("results", []))
        for report in reports.values()
    ]
    common_top_k = min(available_counts)
    if requested_top_k is None:
        return common_top_k
    return min(requested_top_k, common_top_k)


def iter_dataset_candidates(
    dataset: str,
    requested_top_k: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = DATASET_SEARCH_CONFIGS[dataset]
    loaded_reports: dict[str, dict[str, Any]] = {}
    source_paths: dict[str, Path] = {}

    for retriever_name, spec in RETRIEVER_SPECS.items():
        source_path = config[spec["source_path_key"]]
        source_paths[retriever_name] = source_path
        loaded_reports[retriever_name] = load_json(source_path)

    queries = validate_query_alignment(dataset, loaded_reports)
    candidates: list[dict[str, Any]] = []
    query_top_k_meta: list[dict[str, Any]] = []

    for query_index, query in enumerate(queries, start=1):
        query_id = make_query_id(dataset, query_index)
        effective_top_k = effective_top_k_for_query(
            reports=loaded_reports,
            query_index=query_index - 1,
            requested_top_k=requested_top_k,
        )
        query_top_k_meta.append(
            {
                "dataset": dataset,
                "query_id": query_id,
                "query": query,
                "requested_top_k": requested_top_k,
                "effective_top_k": effective_top_k,
                "available_by_retriever": {
                    retriever_name: len(report["queries"][query_index - 1].get("results", []))
                    for retriever_name, report in loaded_reports.items()
                },
            }
        )
        for retriever_name, report in loaded_reports.items():
            query_block = report["queries"][query_index - 1]
            for result in query_block.get("results", [])[:effective_top_k]:
                candidates.append(
                    normalize_result(
                        dataset=dataset,
                        query_id=query_id,
                        query=query,
                        retriever_name=retriever_name,
                        result=result,
                        source_file=source_paths[retriever_name],
                    )
                )
    return candidates, query_top_k_meta


def build_summary(
    candidates: list[dict[str, Any]],
    output_path: Path,
    query_top_k_meta: list[dict[str, Any]],
) -> dict[str, Any]:
    dataset_counts = Counter(row["dataset"] for row in candidates)
    retriever_counts = Counter(row["retriever"] for row in candidates)
    query_counts: dict[str, int] = defaultdict(int)
    dataset_retriever_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for row in candidates:
        query_counts[row["query_id"]] += 1
        dataset_retriever_counts[row["dataset"]][row["retriever"]] += 1

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "output_path": str(output_path),
        "candidate_count": len(candidates),
        "dataset_counts": dict(dataset_counts),
        "retriever_counts": dict(retriever_counts),
        "query_count": len(query_counts),
        "query_ids": sorted(query_counts.keys()),
        "dataset_retriever_counts": {
            dataset: dict(counts) for dataset, counts in sorted(dataset_retriever_counts.items())
        },
        "query_top_k_meta": query_top_k_meta,
        "schema": {
            "retriever_score": "Raw score returned by each retriever. Do not compare values across score_type directly.",
            "score_type": "cosine_similarity, bm25_score, elasticsearch_vector_score, or rrf_hybrid_score.",
            "distance_score": "Optional distance value when the retriever exposes one.",
            "bm25_rank/vector_rank": "Hybrid-only source ranks used for RRF fusion when available.",
        },
    }


def export_candidates(datasets: list[str], requested_top_k: int | None = None) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    query_top_k_meta: list[dict[str, Any]] = []
    for dataset in datasets:
        dataset_candidates, dataset_top_k_meta = iter_dataset_candidates(
            dataset=dataset,
            requested_top_k=requested_top_k,
        )
        candidates.extend(dataset_candidates)
        query_top_k_meta.extend(dataset_top_k_meta)

    output_path = RETRIEVAL_AB_EXPORT_ROOT / "retrieval_ab_candidates.jsonl"
    summary_path = RETRIEVAL_AB_EXPORT_ROOT / "retrieval_ab_summary.json"
    ensure_parent(output_path)

    with output_path.open("w", encoding="utf-8") as handle:
        for row in candidates:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = build_summary(
        candidates,
        output_path=output_path,
        query_top_k_meta=query_top_k_meta,
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export pgvector/BM25 results into a common A/B JSONL format.")
    parser.add_argument("--dataset", choices=["traffic", "fault_ratio", "all"], default="all")
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Common top_k to export. Defaults to the minimum available top_k across retrievers per query.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    datasets = list(DATASET_SEARCH_CONFIGS.keys()) if args.dataset == "all" else [args.dataset]
    summary = export_candidates(datasets, requested_top_k=args.top_k)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
