from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.db import get_connection

from .embedding_config import DATASET_EMBEDDING_CONFIGS, EMBEDDING_SETTINGS, ensure_report_parent
from .store_embeddings_common import count_chunks, count_embeddings


def sample_embedding_rows(db_name: str, embedding_table: str) -> list[dict[str, Any]]:
    with get_connection(db_name) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    chunk_id,
                    embedding_model,
                    embedding_dim,
                    embedding_version,
                    embedding_provider,
                    embedding_vector IS NOT NULL AS has_vector
                FROM {embedding_table}
                WHERE embedding_model = %s
                  AND embedding_version = %s
                ORDER BY chunk_id
                LIMIT 5
                """,
                (EMBEDDING_SETTINGS.model, EMBEDDING_SETTINGS.version),
            )
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def validate_dataset(dataset: str) -> dict[str, Any]:
    config = DATASET_EMBEDDING_CONFIGS[dataset]
    db_name = config["db_name"]
    chunk_table = config["chunk_table"]
    embedding_table = config["embedding_table"]
    chunk_count = count_chunks(db_name, chunk_table)
    embedding_count = count_embeddings(db_name, embedding_table, EMBEDDING_SETTINGS)
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": dataset,
        "db_name": db_name,
        "chunk_table": chunk_table,
        "embedding_table": embedding_table,
        "embedding_model": EMBEDDING_SETTINGS.model,
        "embedding_dim": EMBEDDING_SETTINGS.dim,
        "embedding_version": EMBEDDING_SETTINGS.version,
        "chunk_count": chunk_count,
        "embedding_count": embedding_count,
        "missing_embedding_count": chunk_count - embedding_count,
        "is_complete": chunk_count == embedding_count,
        "sample_rows": sample_embedding_rows(db_name, embedding_table),
    }
    report_path = config["validation_report_path"]
    ensure_report_parent(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    reports = {dataset: validate_dataset(dataset) for dataset in DATASET_EMBEDDING_CONFIGS}
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
