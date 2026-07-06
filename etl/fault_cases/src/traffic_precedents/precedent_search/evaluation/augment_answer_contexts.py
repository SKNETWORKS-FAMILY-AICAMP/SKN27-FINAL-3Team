from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from psycopg2.extras import RealDictCursor

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.db import get_connection

from ..search_config import DATASET_SEARCH_CONFIGS, RETRIEVAL_AB_EXPORT_ROOT, ensure_parent


METADATA_CHUNK_TYPES = {
    "case_overview",
    "traffic_metadata",
    "fault_ratio_metadata",
}

SUPPLEMENT_CHUNK_TYPES = ("holding_summary", "main_text", "fault_ratio_evidence")

ANSWER_CHUNK_PRIORITY = {
    "holding_summary": 1,
    "main_text": 2,
    "fault_ratio_evidence": 3,
    "traffic_metadata": 9,
    "fault_ratio_metadata": 9,
    "case_overview": 10,
}

DEFAULT_INPUT_PATH = RETRIEVAL_AB_EXPORT_ROOT / "retrieval_ab_reranker_scores.jsonl"
DEFAULT_OUTPUT_PATH = RETRIEVAL_AB_EXPORT_ROOT / "retrieval_ab_answer_contexts.jsonl"
DEFAULT_SUMMARY_PATH = RETRIEVAL_AB_EXPORT_ROOT / "retrieval_ab_answer_contexts_summary.json"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def group_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row[key] for key in keys)].append(row)
    return grouped


def select_winner_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query_retriever_groups = group_rows(rows, ("query_id", "retriever"))
    metrics: list[dict[str, Any]] = []
    for (query_id, retriever), group in query_retriever_groups.items():
        sorted_group = sorted(group, key=lambda item: item["rank"])
        avg_score = sum(row["local_reranker_score"] for row in sorted_group) / len(sorted_group)
        top1_score = sorted_group[0]["local_reranker_score"] if sorted_group else None
        metrics.append(
            {
                "query_id": query_id,
                "retriever": retriever,
                "dataset": sorted_group[0]["dataset"],
                "query": sorted_group[0]["query"],
                "avg_score_at_k": avg_score,
                "top1_score": top1_score,
                "rows": sorted_group,
            }
        )

    best_by_query: dict[str, dict[str, Any]] = {}
    for metric in metrics:
        current = best_by_query.get(metric["query_id"])
        if current is None or metric["avg_score_at_k"] > current["avg_score_at_k"]:
            best_by_query[metric["query_id"]] = metric
    return [best_by_query[query_id] for query_id in sorted(best_by_query)]


def fetch_supplement_chunks(
    dataset: str,
    case_ids: list[str],
    max_chunks_per_case: int,
) -> dict[str, list[dict[str, Any]]]:
    if not case_ids:
        return {}

    config = DATASET_SEARCH_CONFIGS[dataset]
    chunk_table = config["chunk_table"]
    placeholders = ", ".join(["%s"] * len(case_ids))

    sql = f"""
        SELECT
            case_id::text AS case_id,
            chunk_id,
            chunk_type,
            chunk_index,
            chunk_text
        FROM {chunk_table}
        WHERE case_id::text IN ({placeholders})
          AND chunk_type = ANY(%s)
        ORDER BY
            case_id,
            CASE chunk_type
                WHEN 'holding_summary' THEN 1
                WHEN 'main_text' THEN 2
                WHEN 'fault_ratio_evidence' THEN 3
                ELSE 9
            END,
            chunk_index
    """

    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with get_connection(config["db_name"]) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, [*case_ids, list(SUPPLEMENT_CHUNK_TYPES)])
            for row in cur.fetchall():
                case_id = str(row["case_id"])
                if len(result[case_id]) < max_chunks_per_case:
                    result[case_id].append(dict(row))
    return result


def build_answer_contexts(
    input_path: Path = DEFAULT_INPUT_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    summary_path: Path = DEFAULT_SUMMARY_PATH,
    max_chunks_per_case: int = 2,
) -> dict[str, Any]:
    rows = load_jsonl(input_path)
    winners = select_winner_groups(rows)

    case_ids_by_dataset: dict[str, set[str]] = defaultdict(set)
    for winner in winners:
        for row in winner["rows"]:
            if row.get("chunk_type") in METADATA_CHUNK_TYPES:
                case_id = str(row.get("case_id") or "")
                if case_id:
                    case_ids_by_dataset[winner["dataset"]].add(case_id)

    supplements: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for dataset, case_ids in case_ids_by_dataset.items():
        fetched = fetch_supplement_chunks(
            dataset=dataset,
            case_ids=sorted(case_ids),
            max_chunks_per_case=max_chunks_per_case,
        )
        for case_id, chunks in fetched.items():
            supplements[(dataset, case_id)] = chunks

    output_rows: list[dict[str, Any]] = []
    metadata_top1_count = 0
    supplemented_metadata_rows = 0
    metadata_top1_missing_supplement_count = 0

    for winner in winners:
        contexts: list[dict[str, Any]] = []
        for row in winner["rows"]:
            contexts.append(
                {
                    "source": "retrieved",
                    "case_id": row.get("case_id"),
                    "chunk_id": row.get("chunk_id"),
                    "chunk_type": row.get("chunk_type"),
                    "rank": row.get("rank"),
                    "local_reranker_score": row.get("local_reranker_score"),
                    "text": row.get("chunk_text") or row.get("chunk_preview") or "",
                }
            )

            if row.get("chunk_type") not in METADATA_CHUNK_TYPES:
                continue

            case_id = str(row.get("case_id") or "")
            supplement_chunks = supplements.get((winner["dataset"], case_id), [])
            if row.get("rank") == 1:
                metadata_top1_count += 1
                if not supplement_chunks:
                    metadata_top1_missing_supplement_count += 1

            if supplement_chunks:
                supplemented_metadata_rows += 1
                for chunk in supplement_chunks:
                    contexts.append(
                        {
                            "source": "same_case_supplement",
                            "case_id": chunk.get("case_id"),
                            "chunk_id": chunk.get("chunk_id"),
                            "chunk_type": chunk.get("chunk_type"),
                            "rank": None,
                            "local_reranker_score": None,
                            "text": chunk.get("chunk_text") or "",
                        }
                    )

        contexts.sort(
            key=lambda item: (
                0 if item["source"] == "retrieved" else 1,
                ANSWER_CHUNK_PRIORITY.get(str(item.get("chunk_type")), 99),
                item.get("rank") or 999,
            )
        )
        output_rows.append(
            {
                "query_id": winner["query_id"],
                "dataset": winner["dataset"],
                "query": winner["query"],
                "winner_retriever": winner["retriever"],
                "winner_avg_score_at_k": winner["avg_score_at_k"],
                "winner_top1_score": winner["top1_score"],
                "context_count": len(contexts),
                "contexts": contexts,
            }
        )

    ensure_parent(output_path)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in output_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input_path": str(input_path),
        "output_path": str(output_path),
        "query_count": len(output_rows),
        "metadata_top1_count": metadata_top1_count,
        "supplemented_metadata_rows": supplemented_metadata_rows,
        "metadata_top1_missing_supplement_count": metadata_top1_missing_supplement_count,
        "rule": {
            "metadata_chunk_types": sorted(METADATA_CHUNK_TYPES),
            "supplement_chunk_types": list(SUPPLEMENT_CHUNK_TYPES),
            "max_chunks_per_case": max_chunks_per_case,
            "purpose": "Use metadata chunks as retrieval hints, then attach same-case body chunks for answer grounding.",
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build answer contexts by supplementing metadata winners with same-case body chunks."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--max-chunks-per-case", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_answer_contexts(
        input_path=args.input,
        output_path=args.output,
        summary_path=args.summary,
        max_chunks_per_case=args.max_chunks_per_case,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
