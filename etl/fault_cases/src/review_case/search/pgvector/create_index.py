from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any

from psycopg2 import sql

from etl.fault_cases.src.review_case.db_loading.db_config import (
    EMBEDDING_SETTINGS,
    PGVECTOR_INDEX_SETTINGS,
    POSTGRES_EXPORT_ROOT,
    SETTINGS,
)
from etl.fault_cases.src.review_case.db_loading.db_connection import get_connection


EMBEDDING_TABLE = "review_case_chunk_embeddings"
VECTOR_COLUMN = "embedding_vector"


def count_embedding_rows() -> int:
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    SELECT COUNT(*)
                    FROM {embedding_table} AS embedding
                    JOIN review_case_chunks AS chunk
                      ON chunk.chunk_id = embedding.chunk_id
                    WHERE embedding.embedding_provider = %s
                      AND embedding.embedding_model = %s
                      AND embedding.embedding_version = %s
                      AND embedding.embedding_dim = %s
                      AND embedding.embedding_vector IS NOT NULL
                      AND chunk.is_active IS TRUE
                      AND embedding.source_text_hash = chunk.text_hash
                    """
                ).format(embedding_table=sql.Identifier(EMBEDDING_TABLE)),
                (
                    EMBEDDING_SETTINGS.provider,
                    EMBEDDING_SETTINGS.model,
                    EMBEDDING_SETTINGS.version,
                    EMBEDDING_SETTINGS.dim,
                ),
            )
            return int(cur.fetchone()[0])


def index_exists(index_name: str) -> bool:
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND indexname = %s
                )
                """,
                (index_name,),
            )
            return bool(cur.fetchone()[0])


def create_hnsw_index() -> dict[str, Any]:
    settings = PGVECTOR_INDEX_SETTINGS
    if settings.index_method != "hnsw":
        raise ValueError("Only hnsw is supported for the review_case pgvector index")

    embedding_count = count_embedding_rows()
    if embedding_count == 0:
        raise RuntimeError("No embedded review_case chunks found. Run embedding first.")

    create_index_sql = sql.SQL(
        """
        CREATE INDEX IF NOT EXISTS {index_name}
        ON {embedding_table}
        USING hnsw ({vector_column} vector_cosine_ops)
        WITH (m = {hnsw_m}, ef_construction = {hnsw_ef_construction})
        WHERE embedding_provider = {embedding_provider}
          AND embedding_model = {embedding_model}
          AND embedding_version = {embedding_version}
          AND embedding_dim = {embedding_dim}
          AND embedding_vector IS NOT NULL
        """
    ).format(
        index_name=sql.Identifier(settings.index_name),
        embedding_table=sql.Identifier(EMBEDDING_TABLE),
        vector_column=sql.Identifier(VECTOR_COLUMN),
        hnsw_m=sql.Literal(settings.hnsw_m),
        hnsw_ef_construction=sql.Literal(settings.hnsw_ef_construction),
        embedding_provider=sql.Literal(EMBEDDING_SETTINGS.provider),
        embedding_model=sql.Literal(EMBEDDING_SETTINGS.model),
        embedding_version=sql.Literal(EMBEDDING_SETTINGS.version),
        embedding_dim=sql.Literal(EMBEDDING_SETTINGS.dim),
    )

    with get_connection(SETTINGS.review_case_db, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(create_index_sql)

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "db_name": SETTINGS.review_case_db,
        "embedding_table": EMBEDDING_TABLE,
        "index_name": settings.index_name,
        "index_exists": index_exists(settings.index_name),
        "index_method": settings.index_method,
        "operator_class": "vector_cosine_ops",
        "embedding_provider": EMBEDDING_SETTINGS.provider,
        "embedding_model": EMBEDDING_SETTINGS.model,
        "embedding_dim": EMBEDDING_SETTINGS.dim,
        "embedding_version": EMBEDDING_SETTINGS.version,
        "embedding_count": embedding_count,
        "hnsw_m": settings.hnsw_m,
        "hnsw_ef_construction": settings.hnsw_ef_construction,
        "report_path": str(POSTGRES_EXPORT_ROOT / "review_case_pgvector_index_report.json"),
    }

    report_path = POSTGRES_EXPORT_ROOT / "review_case_pgvector_index_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(create_hnsw_index(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

