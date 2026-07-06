from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any

from psycopg2.extras import RealDictCursor

from etl.fault_cases.src.review_case.db_loading.db_config import EMBEDDING_SETTINGS, POSTGRES_EXPORT_ROOT, SETTINGS
from etl.fault_cases.src.review_case.db_loading.db_connection import get_connection


def count_chunks() -> int:
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM review_case_chunks")
            return int(cur.fetchone()[0])


def count_embeddings() -> int:
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM review_case_chunk_embeddings
                WHERE embedding_model = %s
                  AND embedding_version = %s
                  AND embedding_dim = %s
                """,
                (EMBEDDING_SETTINGS.model, EMBEDDING_SETTINGS.version, EMBEDDING_SETTINGS.dim),
            )
            return int(cur.fetchone()[0])


def sample_embedding_rows() -> list[dict[str, Any]]:
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    chunk_id,
                    embedding_model,
                    embedding_dim,
                    embedding_version,
                    embedding_provider,
                    input_field,
                    embedding_vector IS NOT NULL AS has_vector
                FROM review_case_chunk_embeddings
                WHERE embedding_model = %s
                  AND embedding_version = %s
                ORDER BY chunk_id
                LIMIT 5
                """,
                (EMBEDDING_SETTINGS.model, EMBEDDING_SETTINGS.version),
            )
            return [dict(row) for row in cur.fetchall()]


def validate() -> dict[str, Any]:
    chunk_count = count_chunks()
    embedding_count = count_embeddings()
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "db_name": SETTINGS.review_case_db,
        "chunk_table": "review_case_chunks",
        "embedding_table": "review_case_chunk_embeddings",
        "embedding_model": EMBEDDING_SETTINGS.model,
        "embedding_dim": EMBEDDING_SETTINGS.dim,
        "embedding_version": EMBEDDING_SETTINGS.version,
        "chunk_count": chunk_count,
        "embedding_count": embedding_count,
        "missing_embedding_count": chunk_count - embedding_count,
        "is_complete": chunk_count == embedding_count,
        "sample_rows": sample_embedding_rows(),
    }
    report_path = POSTGRES_EXPORT_ROOT / "review_case_embeddings_validation_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(validate(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

