"""Create OpenAI embeddings for fault-standard search documents."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from etl.fault_cases.src.fault_standard.config import get_artifacts_dir

from .schema import (
    DEFAULT_EMBEDDING_API_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_DIMENSION,
    create_search_schema,
    table_ref,
)


DEFAULT_BATCH_SIZE = 64
DEFAULT_MAX_INPUT_CHARS = 8000
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_SLEEP_SECONDS = 2.0
DEFAULT_REPORT_PATH = get_artifacts_dir() / "postgres_exports" / "search" / "search_embeddings_load_report.json"


@dataclass(frozen=True)
class EmbeddingSettings:
    """Runtime settings for search document embedding generation."""

    api_model: str = DEFAULT_EMBEDDING_API_MODEL
    stored_model_label: str = DEFAULT_EMBEDDING_MODEL
    dimension: int = EMBEDDING_DIMENSION
    provider: str = "openai"
    batch_size: int = DEFAULT_BATCH_SIZE
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_sleep_seconds: float = DEFAULT_RETRY_SLEEP_SECONDS


@dataclass(frozen=True)
class EmbeddingBatchResult:
    """Embedding vectors and usage returned by one API request."""

    vectors: list[list[float]]
    response_model: str
    prompt_tokens: int | None
    total_tokens: int | None


class OpenAIEmbedder:
    """Thin wrapper around the OpenAI embeddings API."""

    def __init__(self, settings: EmbeddingSettings) -> None:
        self.settings = settings
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package is required to create search embeddings.") from exc
        self.client = OpenAI()

    def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatchResult:
        """Embed a batch of texts with retry handling."""
        if not texts:
            return EmbeddingBatchResult([], self.settings.api_model, 0, 0)

        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                response = self.client.embeddings.create(
                    model=self.settings.api_model,
                    input=list(texts),
                    dimensions=self.settings.dimension,
                    encoding_format="float",
                )
                usage = getattr(response, "usage", None)
                return EmbeddingBatchResult(
                    vectors=[item.embedding for item in response.data],
                    response_model=response.model or self.settings.api_model,
                    prompt_tokens=getattr(usage, "prompt_tokens", None),
                    total_tokens=getattr(usage, "total_tokens", None),
                )
            except Exception as exc:  # SDK exception classes vary by version.
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                time.sleep(self.settings.retry_sleep_seconds * attempt)

        raise RuntimeError(f"OpenAI embedding request failed after {self.settings.max_retries} attempts") from last_error


def ensure_report_parent(path: Path) -> None:
    """Create the report output directory."""
    path.parent.mkdir(parents=True, exist_ok=True)


def vector_to_pgvector(vector: Sequence[float]) -> str:
    """Serialize a float vector for pgvector text casting."""
    return "[" + ",".join(str(float(value)) for value in vector) + "]"


def prepare_embedding_input(text: str, max_chars: int) -> tuple[str, bool]:
    """Trim overly long inputs while keeping the original search document unchanged."""
    value = (text or "").strip()
    if len(value) <= max_chars:
        return value, False
    return value[:max_chars], True


def count_documents(conn, *, only_missing: bool, model_label: str | None = None) -> int:
    """Count search documents targeted by the embedding job."""
    where = ["NULLIF(search_text, '') IS NOT NULL"]
    params: list[Any] = []
    if only_missing:
        where.append("embedding IS NULL")
    if model_label:
        where.append("(embedding_model IS NULL OR embedding_model = %s)")
        params.append(model_label)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {table_ref("rule_search_documents")}
            WHERE {" AND ".join(where)};
            """,
            params,
        )
        return int(cur.fetchone()[0])


def fetch_pending_documents(
    conn,
    *,
    limit: int | None,
    only_missing: bool,
    model_label: str,
) -> list[dict[str, Any]]:
    """Fetch search documents that should receive embeddings."""
    where = ["NULLIF(search_text, '') IS NOT NULL"]
    params: list[Any] = []
    if only_missing:
        where.append("embedding IS NULL")
    where.append("(embedding_model IS NULL OR embedding_model = %s)")
    params.append(model_label)

    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT %s"
        params.append(limit)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT document_id, search_text
            FROM {table_ref("rule_search_documents")}
            WHERE {" AND ".join(where)}
            ORDER BY document_type, document_id
            {limit_sql};
            """,
            params,
        )
        return [{"document_id": row[0], "search_text": row[1]} for row in cur.fetchall()]


def update_embedding_batch(
    conn,
    *,
    document_rows: Sequence[dict[str, Any]],
    vectors: Sequence[Sequence[float]],
    settings: EmbeddingSettings,
) -> int:
    """Update a batch of search documents with generated vectors."""
    if len(document_rows) != len(vectors):
        raise ValueError(f"Embedding row/vector count mismatch: {len(document_rows)} rows, {len(vectors)} vectors")

    values: list[tuple[str, str, str]] = []
    for row, vector in zip(document_rows, vectors):
        if len(vector) != settings.dimension:
            raise ValueError(
                f"Unexpected embedding dim for {row['document_id']}: "
                f"got {len(vector)}, expected {settings.dimension}"
            )
        values.append((vector_to_pgvector(vector), settings.stored_model_label, row["document_id"]))

    with conn.cursor() as cur:
        cur.executemany(
            f"""
            UPDATE {table_ref("rule_search_documents")}
            SET
                embedding = %s::vector,
                embedding_model = %s,
                embedding_created_at = now(),
                updated_at = now()
            WHERE document_id = %s;
            """,
            values,
        )
        return int(cur.rowcount)


def create_vector_index(conn, *, index_method: str = "hnsw") -> str:
    """Create a pgvector cosine index on search document embeddings."""
    method = index_method.lower().strip()
    index_name = f"idx_rule_search_documents_embedding_{method}_cosine"
    if method == "hnsw":
        ddl = f"""
        CREATE INDEX IF NOT EXISTS {index_name}
        ON {table_ref("rule_search_documents")}
        USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL;
        """
    elif method == "ivfflat":
        ddl = f"""
        CREATE INDEX IF NOT EXISTS {index_name}
        ON {table_ref("rule_search_documents")}
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        WHERE embedding IS NOT NULL;
        """
    else:
        raise ValueError(f"Unsupported vector index method: {index_method}")

    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()
    return index_name


def write_report(path: Path, report: dict[str, Any]) -> None:
    """Write an embedding load report as UTF-8 JSON."""
    ensure_report_parent(path)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def create_search_embeddings(
    conn,
    *,
    settings: EmbeddingSettings,
    limit: int | None = None,
    dry_run: bool = False,
    only_missing: bool = True,
    create_index: bool = True,
    index_method: str = "hnsw",
    report_path: Path = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    """Create and store embeddings for search.rule_search_documents."""
    create_search_schema(conn)
    before_missing = count_documents(conn, only_missing=True)
    target_count = count_documents(conn, only_missing=only_missing, model_label=settings.stored_model_label)
    pending_rows = fetch_pending_documents(
        conn,
        limit=limit,
        only_missing=only_missing,
        model_label=settings.stored_model_label,
    )

    report: dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "embedding_provider": settings.provider,
        "embedding_api_model": settings.api_model,
        "embedding_model": settings.stored_model_label,
        "embedding_dim": settings.dimension,
        "batch_size": settings.batch_size,
        "max_input_chars": settings.max_input_chars,
        "only_missing": only_missing,
        "limit": limit,
        "dry_run": dry_run,
        "missing_embedding_before": before_missing,
        "target_document_count": target_count,
        "selected_document_count": len(pending_rows),
        "updated_embeddings": 0,
        "trimmed_input_count": 0,
        "prompt_tokens": 0,
        "total_tokens": 0,
        "vector_index_created": None,
        "report_path": str(report_path),
    }

    if dry_run or not pending_rows:
        report["missing_embedding_after"] = before_missing
        report["finished_at"] = datetime.now().isoformat(timespec="seconds")
        write_report(report_path, report)
        return report

    embedder = OpenAIEmbedder(settings)
    updated = 0
    prompt_tokens = 0
    total_tokens = 0
    trimmed = 0

    for start in range(0, len(pending_rows), settings.batch_size):
        batch_rows = pending_rows[start : start + settings.batch_size]
        prepared_texts: list[str] = []
        for row in batch_rows:
            prepared_text, was_trimmed = prepare_embedding_input(str(row["search_text"]), settings.max_input_chars)
            prepared_texts.append(prepared_text)
            if was_trimmed:
                trimmed += 1

        result = embedder.embed_texts(prepared_texts)
        updated += update_embedding_batch(conn, document_rows=batch_rows, vectors=result.vectors, settings=settings)
        conn.commit()

        if result.prompt_tokens is not None:
            prompt_tokens += int(result.prompt_tokens)
        if result.total_tokens is not None:
            total_tokens += int(result.total_tokens)

    if create_index:
        report["vector_index_created"] = create_vector_index(conn, index_method=index_method)

    report["updated_embeddings"] = updated
    report["trimmed_input_count"] = trimmed
    report["prompt_tokens"] = prompt_tokens
    report["total_tokens"] = total_tokens
    report["missing_embedding_after"] = count_documents(conn, only_missing=True)
    report["finished_at"] = datetime.now().isoformat(timespec="seconds")
    write_report(report_path, report)
    return report
