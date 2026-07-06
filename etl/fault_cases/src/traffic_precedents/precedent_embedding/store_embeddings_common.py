from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

from psycopg2.extras import Json, RealDictCursor, execute_values

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.db import get_connection

from .embedding_config import (
    DATASET_EMBEDDING_CONFIGS,
    EMBEDDING_SETTINGS,
    EmbeddingSettings,
    ensure_report_parent,
)
from .openai_embedder import OpenAIEmbedder


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.9g}" for value in vector) + "]"


def batched(items: list[dict[str, Any]], batch_size: int):
    for start in range(0, len(items), batch_size):
        yield start, items[start : start + batch_size]


def prepare_embedding_input(text: str, max_chars: int) -> tuple[str, bool]:
    normalized = " ".join(str(text).split())
    if max_chars <= 0 or len(normalized) <= max_chars:
        return normalized, False
    return normalized, True


def fetch_pending_chunks(
    db_name: str,
    chunk_table: str,
    embedding_table: str,
    settings: EmbeddingSettings,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if settings.input_field not in {"chunk_text", "search_text"}:
        raise ValueError("OPENAI_EMBEDDING_INPUT_FIELD must be chunk_text or search_text")

    limit_sql = "LIMIT %s" if limit is not None else ""
    params: list[Any] = [settings.model, settings.version]
    if limit is not None:
        params.append(limit)

    sql = f"""
        SELECT
            c.chunk_id,
            c.case_id,
            c.chunk_index,
            c.chunk_type,
            c.chunk_strategy,
            c.{settings.input_field} AS input_text,
            c.char_count,
            c.token_count,
            c.text_hash
        FROM {chunk_table} c
        WHERE c.{settings.input_field} IS NOT NULL
          AND btrim(c.{settings.input_field}) <> ''
          AND NOT EXISTS (
              SELECT 1
              FROM {embedding_table} e
              WHERE e.chunk_id = c.chunk_id
                AND e.embedding_model = %s
                AND e.embedding_version = %s
          )
        ORDER BY c.case_id, c.chunk_index
        {limit_sql}
    """

    with get_connection(db_name) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def count_chunks(db_name: str, chunk_table: str) -> int:
    with get_connection(db_name) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {chunk_table}")
            return int(cur.fetchone()[0])


def count_embeddings(db_name: str, embedding_table: str, settings: EmbeddingSettings) -> int:
    with get_connection(db_name) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM {embedding_table}
                WHERE embedding_model = %s
                  AND embedding_version = %s
                  AND embedding_dim = %s
                """,
                (settings.model, settings.version, settings.dim),
            )
            return int(cur.fetchone()[0])


def upsert_embedding_batch(
    db_name: str,
    chunk_table: str,
    embedding_table: str,
    rows: list[dict[str, Any]],
    vectors: list[list[float]],
    settings: EmbeddingSettings,
    response_model: str,
    prompt_tokens: int | None,
    total_tokens: int | None,
) -> int:
    values = []
    for row, vector in zip(rows, vectors, strict=True):
        if len(vector) != settings.dim:
            raise ValueError(
                f"Unexpected embedding dim for {row['chunk_id']}: got {len(vector)}, expected {settings.dim}"
            )
        meta = {
            "input_field": settings.input_field,
            "chunk_type": row.get("chunk_type"),
            "chunk_strategy": row.get("chunk_strategy"),
            "char_count": row.get("char_count"),
            "token_count": row.get("token_count"),
            "text_hash": row.get("text_hash"),
            "embedding_input_char_count": row.get("embedding_input_char_count"),
            "embedding_input_exceeds_limit": row.get("embedding_input_exceeds_limit", False),
            "embedding_max_input_chars": settings.max_input_chars,
            "response_model": response_model,
            "batch_prompt_tokens": prompt_tokens,
            "batch_total_tokens": total_tokens,
        }
        values.append(
            (
                row["chunk_id"],
                settings.model,
                settings.dim,
                settings.version,
                settings.provider,
                vector_literal(vector),
                Json(meta, dumps=lambda obj: json.dumps(obj, ensure_ascii=False)),
            )
        )

    embedding_sql = f"""
        INSERT INTO {embedding_table} (
            chunk_id,
            embedding_model,
            embedding_dim,
            embedding_version,
            embedding_provider,
            embedding_vector,
            embedding_meta
        )
        VALUES %s
        ON CONFLICT (chunk_id, embedding_model, embedding_version) DO UPDATE SET
            embedding_dim = EXCLUDED.embedding_dim,
            embedding_provider = EXCLUDED.embedding_provider,
            embedding_vector = EXCLUDED.embedding_vector,
            embedding_meta = EXCLUDED.embedding_meta,
            updated_at = now()
    """
    update_sql = f"""
        UPDATE {chunk_table}
        SET embedding_status = 'embedded',
            updated_at = now()
        WHERE chunk_id = ANY(%s)
    """

    with get_connection(db_name) as conn:
        with conn.cursor() as cur:
            execute_values(cur, embedding_sql, values, template="(%s,%s,%s,%s,%s,%s::vector,%s)")
            cur.execute(update_sql, ([row["chunk_id"] for row in rows],))
    return len(values)


def create_embeddings(
    dataset: str,
    settings: EmbeddingSettings = EMBEDDING_SETTINGS,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    dataset_config = DATASET_EMBEDDING_CONFIGS[dataset]
    db_name = dataset_config["db_name"]
    chunk_table = dataset_config["chunk_table"]
    embedding_table = dataset_config["embedding_table"]

    before_embedding_count = count_embeddings(db_name, embedding_table, settings)
    pending_rows = fetch_pending_chunks(db_name, chunk_table, embedding_table, settings, limit=limit)

    report: dict[str, Any] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": dataset,
        "db_name": db_name,
        "chunk_table": chunk_table,
        "embedding_table": embedding_table,
        "embedding_provider": settings.provider,
        "embedding_model": settings.model,
        "embedding_dim": settings.dim,
        "embedding_version": settings.version,
        "input_field": settings.input_field,
        "batch_size": settings.batch_size,
        "max_input_chars": settings.max_input_chars,
        "limit": limit,
        "dry_run": dry_run,
        "chunk_count": count_chunks(db_name, chunk_table),
        "existing_embedding_count_before": before_embedding_count,
        "pending_chunk_count_selected": len(pending_rows),
        "inserted_or_updated_embeddings": 0,
        "too_long_input_count": 0,
        "prompt_tokens": 0,
        "total_tokens": 0,
    }

    too_long_rows = []
    for row in pending_rows:
        prepared_text, exceeds_limit = prepare_embedding_input(str(row["input_text"]), settings.max_input_chars)
        row["embedding_input_text"] = prepared_text
        row["embedding_input_char_count"] = len(prepared_text)
        row["embedding_input_exceeds_limit"] = exceeds_limit
        if exceeds_limit:
            too_long_rows.append(
                {
                    "chunk_id": row["chunk_id"],
                    "chunk_type": row.get("chunk_type"),
                    "char_count": len(prepared_text),
                }
            )
    report["too_long_input_count"] = len(too_long_rows)
    report["too_long_input_samples"] = too_long_rows[:20]

    if too_long_rows:
        report["embedding_count_after"] = before_embedding_count
        write_report(dataset_config["report_path"], report)
        raise RuntimeError(
            "Embedding input length check failed. Regenerate chunks so every embedding input is within "
            f"{settings.max_input_chars} chars. Sample chunk_id: {too_long_rows[0]['chunk_id']}"
        )

    if dry_run or not pending_rows:
        report["embedding_count_after"] = before_embedding_count
        write_report(dataset_config["report_path"], report)
        return report

    embedder = OpenAIEmbedder(settings)
    inserted = 0
    prompt_tokens = 0
    total_tokens = 0
    for _, batch in batched(pending_rows, settings.batch_size):
        texts = [str(row["embedding_input_text"]) for row in batch]
        result = embedder.embed_texts(texts)
        inserted += upsert_embedding_batch(
            db_name=db_name,
            chunk_table=chunk_table,
            embedding_table=embedding_table,
            rows=batch,
            vectors=result.vectors,
            settings=settings,
            response_model=result.model,
            prompt_tokens=result.prompt_tokens,
            total_tokens=result.total_tokens,
        )
        prompt_tokens += result.prompt_tokens or 0
        total_tokens += result.total_tokens or 0

    report["inserted_or_updated_embeddings"] = inserted
    report["prompt_tokens"] = prompt_tokens
    report["total_tokens"] = total_tokens
    report["embedding_count_after"] = count_embeddings(db_name, embedding_table, settings)
    write_report(dataset_config["report_path"], report)
    return report


def write_report(path, report: dict[str, Any]) -> None:
    ensure_report_parent(path)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(description: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--limit", type=int, default=None, help="Only embed this many pending chunks.")
    parser.add_argument("--dry-run", action="store_true", help="Select pending chunks and write a report without API calls.")
    return parser.parse_args()
