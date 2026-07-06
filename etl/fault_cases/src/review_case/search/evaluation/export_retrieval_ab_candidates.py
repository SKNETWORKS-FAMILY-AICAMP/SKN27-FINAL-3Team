from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from etl.fault_cases.src.review_case.db_loading.db_config import (
    ELASTICSEARCH_EXPORT_ROOT,
    ELASTICSEARCH_SETTINGS,
    PGVECTOR_SEARCH_SETTINGS,
    POSTGRES_EXPORT_ROOT,
    RETRIEVAL_AB_EXPORT_ROOT,
)


RETRIEVER_SPECS: dict[str, dict[str, Any]] = {
    "pgvector_cosine": {
        "retriever": "pgvector_cosine",
        "score_field": "cosine_similarity",
        "score_type": "cosine_similarity",
        "distance_field": "cosine_distance",
        "source_path": POSTGRES_EXPORT_ROOT / PGVECTOR_SEARCH_SETTINGS.sample_report_name,
    },
    "elasticsearch_bm25_nori": {
        "retriever": "elasticsearch_bm25_nori",
        "score_field": "bm25_score",
        "score_type": "bm25_score",
        "distance_field": None,
        "source_path": ELASTICSEARCH_EXPORT_ROOT / ELASTICSEARCH_SETTINGS.bm25_sample_report_name,
    },
    "elasticsearch_vector_cosine": {
        "retriever": "elasticsearch_vector_cosine",
        "score_field": "vector_score",
        "score_type": "elasticsearch_dense_vector_cosine_score",
        "distance_field": None,
        "source_path": ELASTICSEARCH_EXPORT_ROOT / ELASTICSEARCH_SETTINGS.vector_sample_report_name,
    },
    "elasticsearch_hybrid_bm25_vector_rrf": {
        "retriever": "elasticsearch_hybrid_bm25_vector_rrf",
        "score_field": "hybrid_score",
        "score_type": "rrf_bm25_vector_score",
        "distance_field": None,
        "source_path": ELASTICSEARCH_EXPORT_ROOT / ELASTICSEARCH_SETTINGS.hybrid_sample_report_name,
    },
}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing retrieval result file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_reports(retrievers: list[str]) -> dict[str, dict[str, Any]]:
    return {name: load_json(RETRIEVER_SPECS[name]["source_path"]) for name in retrievers}


def validate_query_alignment(reports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    query_lists = {
        retriever: [
            {
                "query_id": query_block.get("query_id"),
                "query": query_block.get("query"),
                "expected_reference_chart_key": query_block.get("expected_reference_chart_key"),
            }
            for query_block in report.get("queries", [])
        ]
        for retriever, report in reports.items()
    }
    unique_query_lists = {json.dumps(queries, ensure_ascii=False, sort_keys=True) for queries in query_lists.values()}
    if len(unique_query_lists) == 1:
        return next(iter(query_lists.values()))

    details = "\n".join(f"{retriever}: {queries}" for retriever, queries in query_lists.items())
    raise ValueError(f"Review case query set mismatch.\n{details}")


def effective_top_k_for_query(
    reports: dict[str, dict[str, Any]],
    query_index: int,
    requested_top_k: int | None,
) -> int:
    available_counts = [len(report["queries"][query_index].get("results", [])) for report in reports.values()]
    common_top_k = min(available_counts)
    if requested_top_k is None:
        return common_top_k
    return min(requested_top_k, common_top_k)


def normalize_result(
    query_meta: dict[str, Any],
    retriever_name: str,
    result: dict[str, Any],
    source_file: Path,
) -> dict[str, Any]:
    spec = RETRIEVER_SPECS[retriever_name]
    score = result.get(spec["score_field"])
    distance = result.get(spec["distance_field"]) if spec["distance_field"] else None
    return {
        "query_id": query_meta.get("query_id"),
        "query": query_meta.get("query"),
        "expected_reference_chart_key": query_meta.get("expected_reference_chart_key"),
        "retriever": spec["retriever"],
        "rank": result.get("rank"),
        "review_case_id": result.get("review_case_id"),
        "review_no": result.get("review_no"),
        "chunk_id": result.get("chunk_id"),
        "chunk_type": result.get("chunk_type"),
        "case_title": result.get("case_title"),
        "reference_chart_key": result.get("reference_chart_key"),
        "decision_fault_ratio": result.get("decision_fault_ratio"),
        "claimant_final_ratio": result.get("claimant_final_ratio"),
        "respondent_final_ratio": result.get("respondent_final_ratio"),
        "signal_condition": result.get("signal_condition"),
        "road_feature": result.get("road_feature"),
        "standard_a_behavior": result.get("standard_a_behavior"),
        "standard_b_behavior": result.get("standard_b_behavior"),
        "retriever_score": float(score) if score is not None else None,
        "score_type": spec["score_type"],
        "distance_score": float(distance) if distance is not None else None,
        "distance_type": spec["distance_field"],
        "chunk_preview": result.get("chunk_preview") or "",
        "search_preview": result.get("search_preview") or "",
        "highlight": result.get("highlight") or {},
        "bm25_rank": result.get("bm25_rank"),
        "bm25_score": result.get("bm25_score"),
        "vector_rank": result.get("vector_rank"),
        "vector_score": result.get("vector_score"),
        "rrf_bm25": result.get("rrf_bm25"),
        "rrf_vector": result.get("rrf_vector"),
        "source_file": str(source_file),
    }


def build_candidates(retrievers: list[str], requested_top_k: int | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reports = load_reports(retrievers)
    query_metas = validate_query_alignment(reports)
    candidates: list[dict[str, Any]] = []
    query_top_k_meta: list[dict[str, Any]] = []

    for query_index, query_meta in enumerate(query_metas):
        effective_top_k = effective_top_k_for_query(reports, query_index, requested_top_k)
        query_top_k_meta.append(
            {
                "query_id": query_meta.get("query_id"),
                "query": query_meta.get("query"),
                "requested_top_k": requested_top_k,
                "effective_top_k": effective_top_k,
                "available_by_retriever": {
                    retriever_name: len(report["queries"][query_index].get("results", []))
                    for retriever_name, report in reports.items()
                },
            }
        )
        for retriever_name, report in reports.items():
            source_file = RETRIEVER_SPECS[retriever_name]["source_path"]
            for result in report["queries"][query_index].get("results", [])[:effective_top_k]:
                candidates.append(
                    normalize_result(
                        query_meta=query_meta,
                        retriever_name=retriever_name,
                        result=result,
                        source_file=source_file,
                    )
                )
    return candidates, query_top_k_meta


def build_summary(
    candidates: list[dict[str, Any]],
    output_path: Path,
    query_top_k_meta: list[dict[str, Any]],
) -> dict[str, Any]:
    retriever_counts = Counter(row["retriever"] for row in candidates)
    query_counts = Counter(row["query_id"] for row in candidates)
    chunk_type_counts = Counter(row["chunk_type"] for row in candidates)
    expected_chart_top1_hits = []
    for query_meta in query_top_k_meta:
        expected = query_meta.get("query")
        expected_chart = next(
            (
                row.get("expected_reference_chart_key")
                for row in candidates
                if row.get("query_id") == query_meta.get("query_id")
            ),
            None,
        )
        if not expected_chart:
            continue
        top1_by_retriever = {
            row["retriever"]: row.get("reference_chart_key") == expected_chart
            for row in candidates
            if row.get("query_id") == query_meta.get("query_id") and row.get("rank") == 1
        }
        expected_chart_top1_hits.append(
            {
                "query_id": query_meta.get("query_id"),
                "query": expected,
                "expected_reference_chart_key": expected_chart,
                "top1_hit_by_retriever": top1_by_retriever,
            }
        )

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "output_path": str(output_path),
        "candidate_count": len(candidates),
        "retriever_counts": dict(retriever_counts),
        "query_count": len(query_counts),
        "query_ids": sorted(query_counts.keys()),
        "chunk_type_counts": dict(chunk_type_counts),
        "query_top_k_meta": query_top_k_meta,
        "expected_chart_top1_hits": expected_chart_top1_hits,
        "schema": {
            "retriever_score": "Raw score returned by each retriever. Do not compare across score_type directly.",
            "score_type": "cosine_similarity for pgvector, bm25_score for BM25/Nori, Elasticsearch vector score for dense_vector, or RRF fused score for hybrid.",
            "distance_score": "Cosine distance only when provided by pgvector.",
            "chunk_preview": "Human-readable short context for quick inspection.",
            "search_preview": "Search-enriched text preview used for retrieval.",
        },
    }


def export_candidates(retrievers: list[str], requested_top_k: int | None = None) -> dict[str, Any]:
    candidates, query_top_k_meta = build_candidates(retrievers=retrievers, requested_top_k=requested_top_k)
    output_path = RETRIEVAL_AB_EXPORT_ROOT / "review_case_retrieval_ab_candidates.jsonl"
    summary_path = RETRIEVAL_AB_EXPORT_ROOT / "review_case_retrieval_ab_summary.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as handle:
        for row in candidates:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = build_summary(candidates, output_path=output_path, query_top_k_meta=query_top_k_meta)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export review_case retrieval results into a common A/B JSONL format.")
    parser.add_argument(
        "--retriever",
        choices=[
            "pgvector_cosine",
            "elasticsearch_bm25_nori",
            "elasticsearch_vector_cosine",
            "elasticsearch_hybrid_bm25_vector_rrf",
            "all",
        ],
        action="append",
        default=None,
        help="Retriever to include. Use multiple times or omit for all.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Common top_k to export. Defaults to the minimum available top_k across retrievers per query.",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    retrievers = args.retriever or ["all"]
    if "all" in retrievers:
        retrievers = list(RETRIEVER_SPECS.keys())
    summary = export_candidates(retrievers=retrievers, requested_top_k=args.top_k)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
