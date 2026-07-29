"""Load legal RAG JSONL artifacts into the Django PostgreSQL/pgvector database."""

from __future__ import annotations

import json
from itertools import islice
from pathlib import Path
from typing import Any, Iterable, Iterator

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from app.services.legal_rag_service import search_legal_rag


DEFAULT_CHUNKS_PATH = Path("output/law_ingestion/chunks/law_chunks.jsonl")
DEFAULT_EMBEDDINGS_PATH = Path("output/law_ingestion/embeddings/law_embeddings_e5_large.jsonl")
DEFAULT_SCHEMA_PATH = Path("storage/schemas/law_db_schema.sql")


class Command(BaseCommand):
    help = "Create/load pgvector legal RAG tables and optionally run a retrieval smoke query."

    def add_arguments(self, parser):
        parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS_PATH), help="Path to law_chunks JSONL.")
        parser.add_argument("--embeddings", default=str(DEFAULT_EMBEDDINGS_PATH), help="Path to law_embeddings JSONL.")
        parser.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH), help="Path to pgvector schema SQL.")
        parser.add_argument("--schema-only", action="store_true", help="Create schema and indexes without loading data.")
        parser.add_argument("--skip-schema", action="store_true", help="Skip DDL when schema maintenance already ran.")
        parser.add_argument("--replace", action="store_true", help="Truncate legal RAG tables before loading JSONL data.")
        parser.add_argument("--batch-size", type=int, default=500, help="Rows per insert batch.")
        parser.add_argument("--smoke-query", default="", help="Optional query to run through legal_rag_service after load.")
        parser.add_argument("--top-k", type=int, default=3, help="Top K for the optional smoke query.")
        parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError(f"PostgreSQL is required for pgvector RAG loading, got {connection.vendor}.")

        chunks_path = Path(options["chunks"])
        embeddings_path = Path(options["embeddings"])
        schema_path = Path(options["schema"])
        schema_only = bool(options["schema_only"])
        skip_schema = bool(options["skip_schema"])

        if not schema_path.exists():
            raise CommandError(f"Schema file not found: {schema_path}")
        if not schema_only:
            if not chunks_path.exists():
                raise CommandError(f"Chunks file not found: {chunks_path}")
            if not embeddings_path.exists():
                raise CommandError(f"Embeddings file not found: {embeddings_path}")

        with transaction.atomic():
            if not skip_schema:
                _execute_schema(schema_path)
            if options["replace"] and not schema_only:
                with connection.cursor() as cursor:
                    cursor.execute("TRUNCATE TABLE law_embeddings CASCADE;")
                    cursor.execute("TRUNCATE TABLE law_chunks CASCADE;")
            loaded = (
                {"chunks": 0, "embeddings": 0}
                if schema_only
                else _load_jsonl_artifacts(
                    chunks_path=chunks_path,
                    embeddings_path=embeddings_path,
                    batch_size=max(1, int(options["batch_size"] or 500)),
                )
            )

        counts = _table_counts()
        smoke = None
        if str(options["smoke_query"] or "").strip():
            smoke = search_legal_rag(
                str(options["smoke_query"]),
                top_k=max(1, int(options["top_k"] or 3)),
            )

        result = {
            "contract_version": "legal_rag_pgvector_load.v1",
            "status": "loaded" if not schema_only else "schema_ready",
            "schema": str(schema_path),
            "chunks_path": str(chunks_path),
            "embeddings_path": str(embeddings_path),
            "loaded": loaded,
            "counts": counts,
            "smoke": smoke,
        }
        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        else:
            self.stdout.write(_text_result(result))


def _execute_schema(schema_path: Path) -> None:
    sql = schema_path.read_text(encoding="utf-8")
    with connection.cursor() as cursor:
        cursor.execute(sql)


def _load_jsonl_artifacts(*, chunks_path: Path, embeddings_path: Path, batch_size: int) -> dict[str, int]:
    chunk_sql = """
        INSERT INTO law_chunks (
            chunk_id, source_id, source_name, source_type, chunk_type,
            article_no, appendix_no, form_no, provision_text, normalized_text,
            source_url, enforce_date, expire_date, is_searchable, domain_tags
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (chunk_id) DO UPDATE SET
            source_id = EXCLUDED.source_id,
            source_name = EXCLUDED.source_name,
            source_type = EXCLUDED.source_type,
            chunk_type = EXCLUDED.chunk_type,
            article_no = EXCLUDED.article_no,
            appendix_no = EXCLUDED.appendix_no,
            form_no = EXCLUDED.form_no,
            provision_text = EXCLUDED.provision_text,
            normalized_text = EXCLUDED.normalized_text,
            source_url = EXCLUDED.source_url,
            enforce_date = EXCLUDED.enforce_date,
            expire_date = EXCLUDED.expire_date,
            is_searchable = EXCLUDED.is_searchable,
            domain_tags = EXCLUDED.domain_tags
    """
    embedding_sql = """
        INSERT INTO law_embeddings (
            chunk_id, embedding_vector, embedding_provider,
            embedding_model, embedding_dimensions
        )
        VALUES (%s, %s::vector, %s, %s, %s)
        ON CONFLICT (chunk_id) DO UPDATE SET
            embedding_vector = EXCLUDED.embedding_vector,
            embedding_provider = EXCLUDED.embedding_provider,
            embedding_model = EXCLUDED.embedding_model,
            embedding_dimensions = EXCLUDED.embedding_dimensions
    """

    loaded_chunks = 0
    loaded_embeddings = 0
    with connection.cursor() as cursor:
        for batch in _batches(_chunk_rows(chunks_path), batch_size):
            cursor.executemany(chunk_sql, batch)
            loaded_chunks += len(batch)
        for batch in _batches(_embedding_rows(embeddings_path), batch_size):
            cursor.executemany(embedding_sql, batch)
            loaded_embeddings += len(batch)
    return {"chunks": loaded_chunks, "embeddings": loaded_embeddings}


def _chunk_rows(path: Path):
    for row in _read_jsonl(path):
        is_searchable = row.get("is_searchable", True)
        if is_searchable is not True:
            raise CommandError("Legal RAG is_searchable must be true")
        domain_tags = row.get("domain_tags", [])
        if not isinstance(domain_tags, list) or any(
            not isinstance(tag, str) or not tag.strip() or tag != tag.strip()
            for tag in domain_tags
        ):
            raise CommandError("Legal RAG domain_tags must be a list of non-empty strings")
        yield (
            _required(row, "chunk_id"),
            _required(row, "source_id"),
            _required(row, "source_name"),
            _required(row, "source_type"),
            _required(row, "chunk_type"),
            row.get("article_no") or None,
            row.get("appendix_no") or None,
            row.get("form_no") or None,
            _required(row, "provision_text"),
            _required(row, "normalized_text"),
            row.get("source_url") or None,
            row.get("enforce_date") or None,
            row.get("expire_date") or None,
            is_searchable,
            domain_tags,
        )


def _embedding_rows(path: Path):
    for row in _read_jsonl(path):
        vector = row.get("embedding_vector") or []
        dimensions = _required(row, "embedding_dimensions")
        if isinstance(dimensions, bool) or not isinstance(dimensions, int):
            raise CommandError("Invalid legal RAG embedding_dimensions")
        if dimensions != 1024 or len(vector) != dimensions:
            raise CommandError("Legal RAG embeddings must contain exactly 1024 dimensions")
        yield (
            _required(row, "chunk_id"),
            f"[{','.join(str(float(item)) for item in vector)}]",
            _required(row, "embedding_provider"),
            _required(row, "embedding_model"),
            dimensions,
        )


def _read_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise CommandError(f"Invalid JSON in {path}:{line_no}: {exc}") from exc


def _required(row: dict[str, Any], key: str) -> Any:
    value = row.get(key)
    if value in {None, ""}:
        raise CommandError(f"Missing required legal RAG field: {key}")
    return value


def _batches(rows: Iterable[tuple[Any, ...]], size: int) -> Iterator[list[tuple[Any, ...]]]:
    iterator = iter(rows)
    while batch := list(islice(iterator, max(1, size))):
        yield batch


def _table_counts() -> dict[str, int]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM law_chunks WHERE is_searchable = TRUE;")
        searchable_chunks = int(cursor.fetchone()[0])
        cursor.execute("SELECT COUNT(*) FROM law_chunks;")
        chunks = int(cursor.fetchone()[0])
        cursor.execute("SELECT COUNT(*) FROM law_embeddings;")
        embeddings = int(cursor.fetchone()[0])
    return {
        "law_chunks": chunks,
        "searchable_law_chunks": searchable_chunks,
        "law_embeddings": embeddings,
        "embedding_dimensions": int(getattr(settings, "LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS", 1024) or 1024),
    }


def _text_result(result: dict[str, Any]) -> str:
    counts = result["counts"]
    lines = [
        f"Legal RAG pgvector load: {result['status']}",
        f"- law_chunks: {counts['law_chunks']}",
        f"- searchable_law_chunks: {counts['searchable_law_chunks']}",
        f"- law_embeddings: {counts['law_embeddings']}",
    ]
    smoke = result.get("smoke")
    if smoke:
        lines.extend(
            [
                f"- smoke_backend: {smoke.get('backend')}",
                f"- smoke_status: {smoke.get('status')}",
                f"- smoke_results: {len(smoke.get('results') or [])}",
            ]
        )
    return "\n".join(lines)
