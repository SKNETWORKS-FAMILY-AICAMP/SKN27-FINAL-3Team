from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.db import get_connection

from ..search_config import DATASET_SEARCH_CONFIGS, SEARCH_SETTINGS, SearchSettings, ensure_parent


def count_embedding_rows(db_name: str, embedding_table: str, settings: SearchSettings) -> int:
    with get_connection(db_name) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM {embedding_table}
                WHERE embedding_model = %s
                  AND embedding_version = %s
                  AND embedding_dim = %s
                  AND embedding_vector IS NOT NULL
                """,
                (settings.embedding_model, settings.embedding_version, settings.embedding_dim),
            )
            return int(cur.fetchone()[0])


def create_dataset_index(dataset: str, settings: SearchSettings = SEARCH_SETTINGS) -> dict[str, Any]:
    config = DATASET_SEARCH_CONFIGS[dataset]
    db_name = config["db_name"]
    embedding_table = config["embedding_table"]
    index_name = config["index_name"]

    if settings.index_method != "hnsw":
        raise ValueError("Only hnsw is supported for the current pgvector baseline index")

    embedding_count = count_embedding_rows(db_name, embedding_table, settings)
    sql = f"""
        CREATE INDEX IF NOT EXISTS {index_name}
        ON {embedding_table}
        USING hnsw (embedding_vector vector_cosine_ops)
        WITH (m = {settings.hnsw_m}, ef_construction = {settings.hnsw_ef_construction})
        WHERE embedding_model = '{settings.embedding_model}'
          AND embedding_version = '{settings.embedding_version}'
          AND embedding_dim = {settings.embedding_dim}
          AND embedding_vector IS NOT NULL
    """

    with get_connection(db_name, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": dataset,
        "db_name": db_name,
        "embedding_table": embedding_table,
        "index_name": index_name,
        "index_method": settings.index_method,
        "operator_class": "vector_cosine_ops",
        "embedding_model": settings.embedding_model,
        "embedding_version": settings.embedding_version,
        "embedding_dim": settings.embedding_dim,
        "embedding_count": embedding_count,
        "hnsw_m": settings.hnsw_m,
        "hnsw_ef_construction": settings.hnsw_ef_construction,
    }
    report_path = config["index_report_path"]
    ensure_parent(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create pgvector cosine indexes for precedent embeddings.")
    parser.add_argument(
        "--dataset",
        choices=["traffic", "fault_ratio", "all"],
        default="all",
        help="Dataset to index. Defaults to all.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    datasets = DATASET_SEARCH_CONFIGS.keys() if args.dataset == "all" else [args.dataset]
    reports = {dataset: create_dataset_index(dataset) for dataset in datasets}
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
