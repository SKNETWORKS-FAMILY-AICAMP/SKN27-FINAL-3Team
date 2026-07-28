from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any

from psycopg2.extras import Json, RealDictCursor, execute_values

from etl.fault_cases.src.review_case.db_loading.db_config import (
    EMBEDDING_SETTINGS,
    POSTGRES_EXPORT_ROOT,
    SETTINGS,
    EmbeddingSettings,
)
from etl.fault_cases.src.review_case.db_loading.db_connection import get_connection

from .openai_embedder import OpenAIEmbedder


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.9g}" for value in vector) + "]"


def batched(items: list[dict[str, Any]], batch_size: int):
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def prepare_embedding_input(text: str, max_chars: int) -> tuple[str, bool]:
    normalized = " ".join(str(text).split())
    if max_chars <= 0 or len(normalized) <= max_chars:
        return normalized, False
    return normalized, True


def count_chunks() -> int:
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM review_case_chunks")
            return int(cur.fetchone()[0])


def count_embeddings(settings: EmbeddingSettings = EMBEDDING_SETTINGS) -> int:
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM review_case_chunk_embeddings AS embedding
                JOIN review_case_chunks AS chunk
                  ON chunk.chunk_id = embedding.chunk_id
                WHERE embedding.embedding_model = %s
                  AND embedding.embedding_version = %s
                  AND embedding.embedding_dim = %s
                  AND chunk.is_active IS TRUE
                  AND embedding.source_text_hash = chunk.text_hash
                """,
                (settings.model, settings.version, settings.dim),
            )
            return int(cur.fetchone()[0])


def fetch_pending_chunks(settings: EmbeddingSettings, limit: int | None = None) -> list[dict[str, Any]]:
    if settings.input_field not in {"chunk_text", "search_text"}:
        raise ValueError("OPENAI_EMBEDDING_INPUT_FIELD must be chunk_text or search_text")

    limit_sql = "LIMIT %s" if limit is not None else ""
    params: list[Any] = [
        settings.provider,
        settings.model,
        settings.version,
        settings.dim,
    ]
    if limit is not None:
        params.append(limit)

    sql = f"""
        SELECT
            c.chunk_id,
            c.review_case_id,
            c.review_no,
            c.chunk_type,
            c.{settings.input_field} AS input_text,
            c.char_count,
            c.token_count,
            c.text_hash
        FROM review_case_chunks c
        WHERE c.is_active IS TRUE
          AND c.{settings.input_field} IS NOT NULL
          AND btrim(c.{settings.input_field}) <> ''
          AND NOT EXISTS (
              SELECT 1
              FROM review_case_chunk_embeddings e
              WHERE e.chunk_id = c.chunk_id
                AND e.embedding_provider = %s
                AND e.embedding_model = %s
                AND e.embedding_version = %s
                AND e.embedding_dim = %s
                AND e.source_text_hash = c.text_hash
          )
        ORDER BY c.review_no, c.sequence_no
        {limit_sql}
    """
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def create_embedding_job(settings: EmbeddingSettings, target_count: int, dry_run: bool) -> str:
    job_id = "review_case_embedding_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    if dry_run:
        return job_id
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO review_case_embedding_jobs (
                    embedding_job_id, embedding_model, embedding_version, embedding_dim,
                    input_field, target_chunk_count, success_count, failed_count,
                    skipped_count, status, started_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, 0, 0, 0, 'running', now())
                """,
                (job_id, settings.model, settings.version, settings.dim, settings.input_field, target_count),
            )
    return job_id


def finish_embedding_job(job_id: str, success_count: int, failed_count: int, skipped_count: int, status: str) -> None:
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE review_case_embedding_jobs
                SET success_count = %s,
                    failed_count = %s,
                    skipped_count = %s,
                    status = %s,
                    finished_at = now()
                WHERE embedding_job_id = %s
                """,
                (success_count, failed_count, skipped_count, status, job_id),
            )


def upsert_embedding_batch(
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
            "review_case_id": row.get("review_case_id"),
            "review_no": row.get("review_no"),
            "chunk_type": row.get("chunk_type"),
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
                settings.version,
                settings.dim,
                settings.provider,
                settings.input_field,
                row["text_hash"],
                vector_literal(vector),
                Json(meta, dumps=lambda obj: json.dumps(obj, ensure_ascii=False)),
            )
        )

    embedding_sql = """
        INSERT INTO review_case_chunk_embeddings (
            chunk_id,
            embedding_model,
            embedding_version,
            embedding_dim,
            embedding_provider,
            input_field,
            source_text_hash,
            embedding_vector,
            embedding_meta
        )
        VALUES %s
        ON CONFLICT (chunk_id, embedding_model, embedding_version, source_text_hash)
        DO NOTHING
    """
    update_sql = """
        UPDATE review_case_chunks
        SET embedding_status = 'embedded',
            updated_at = now()
        WHERE chunk_id = ANY(%s)
    """
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            execute_values(
                cur,
                embedding_sql,
                values,
                template="(%s,%s,%s,%s,%s,%s,%s,%s::vector,%s)",
            )
            cur.execute(update_sql, ([row["chunk_id"] for row in rows],))
    return len(values)


def create_embeddings(
    settings: EmbeddingSettings = EMBEDDING_SETTINGS,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    before_embedding_count = count_embeddings(settings)
    pending_rows = fetch_pending_chunks(settings, limit=limit)

    report: dict[str, Any] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "db_name": SETTINGS.review_case_db,
        "chunk_table": "review_case_chunks",
        "embedding_table": "review_case_chunk_embeddings",
        "embedding_provider": settings.provider,
        "embedding_model": settings.model,
        "embedding_dim": settings.dim,
        "embedding_version": settings.version,
        "input_field": settings.input_field,
        "batch_size": settings.batch_size,
        "max_input_chars": settings.max_input_chars,
        "limit": limit,
        "dry_run": dry_run,
        "chunk_count": count_chunks(),
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
                    "review_no": row.get("review_no"),
                    "chunk_type": row.get("chunk_type"),
                    "embedding_input_char_count": len(prepared_text),
                }
            )
    report["too_long_input_count"] = len(too_long_rows)
    report["too_long_input_samples"] = too_long_rows[:20]

    if too_long_rows:
        report["embedding_count_after"] = before_embedding_count
        write_report(report)
        raise RuntimeError(
            "Embedding input length check failed. Regenerate/split chunks so every embedding input is within "
            f"{settings.max_input_chars} chars. Sample chunk_id: {too_long_rows[0]['chunk_id']}"
        )

    job_id = create_embedding_job(settings, target_count=len(pending_rows), dry_run=dry_run)
    report["embedding_job_id"] = job_id

    if dry_run or not pending_rows:
        report["embedding_count_after"] = before_embedding_count
        write_report(report)
        return report

    embedder = OpenAIEmbedder(settings)
    inserted = 0
    prompt_tokens = 0
    total_tokens = 0
    status = "success"
    try:
        for batch in batched(pending_rows, settings.batch_size):
            texts = [str(row["embedding_input_text"]) for row in batch]
            result = embedder.embed_texts(texts)
            inserted += upsert_embedding_batch(
                rows=batch,
                vectors=result.vectors,
                settings=settings,
                response_model=result.model,
                prompt_tokens=result.prompt_tokens,
                total_tokens=result.total_tokens,
            )
            prompt_tokens += result.prompt_tokens or 0
            total_tokens += result.total_tokens or 0
    except Exception:
        status = "failed"
        finish_embedding_job(job_id, inserted, 1, len(pending_rows) - inserted, status)
        raise

    report["inserted_or_updated_embeddings"] = inserted
    report["prompt_tokens"] = prompt_tokens
    report["total_tokens"] = total_tokens
    report["embedding_count_after"] = count_embeddings(settings)
    finish_embedding_job(job_id, inserted, 0, len(pending_rows) - inserted, status)
    write_report(report)
    return report


def write_report(report: dict[str, Any]) -> None:
    report_path = POSTGRES_EXPORT_ROOT / "review_case_embeddings_load_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create OpenAI embeddings for review case chunks.")
    parser.add_argument("--limit", type=int, default=None, help="Only embed this many pending chunks.")
    parser.add_argument("--dry-run", action="store_true", help="Select pending chunks and write a report without API calls.")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    report = create_embeddings(limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


