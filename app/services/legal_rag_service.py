"""Runtime lookup helpers for legal RAG evidence."""

from __future__ import annotations

import hashlib
import math
import os
import re
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction


PGVECTOR_BACKEND = "postgres_pgvector"
DEFAULT_SENTENCE_TRANSFORMER_MODEL = "intfloat/multilingual-e5-large"
LEGAL_SOURCE_TYPES = (
    "law",
    "enforcement_decree",
    "enforcement_rule",
    "administrative_rule",
    "notice",
)
USABLE_LEGAL_EVIDENCE_SQL = (
    "c.source_url IS NOT NULL AND btrim(c.source_url) <> '' "
    "AND c.provision_text IS NOT NULL AND btrim(c.provision_text) <> ''"
)
LATENCY_BREAKDOWN_KEYS = (
    "preflight_ms",
    "embedding_ms",
    "vector_query_ms",
    "result_mapping_ms",
)
_STRICT_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LEGAL_TIME_ZONE = ZoneInfo("Asia/Seoul")


def search_legal_rag(
    query: str,
    *,
    top_k: int = 3,
    source_type: str = "law",
    temporal_basis: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    normalized_query = _text(query)
    if not normalized_query or top_k <= 0:
        return _search_response(
            status="empty_query",
            backend=PGVECTOR_BACKEND,
            query=normalized_query,
            top_k=top_k,
            results=[],
            started_at=started_at,
        )

    allowed_source_types, effective_at, filter_error = resolve_legal_search_filters(
        source_type=source_type,
        temporal_basis=temporal_basis,
        scope=scope,
    )
    if filter_error:
        return _search_response(
            status="invalid_filter",
            backend=PGVECTOR_BACKEND,
            query=normalized_query,
            top_k=top_k,
            results=[],
            started_at=started_at,
            error_code=filter_error,
        )

    return _search_pgvector(
        normalized_query,
        top_k=top_k,
        source_type=source_type,
        allowed_source_types=allowed_source_types,
        effective_at=effective_at,
    )


def resolve_legal_search_filters(
    *,
    source_type: str,
    temporal_basis: dict[str, Any] | None,
    scope: dict[str, Any] | None,
) -> tuple[tuple[str, ...], date | None, str]:
    normalized_source_type = _text(source_type)
    if normalized_source_type not in LEGAL_SOURCE_TYPES:
        return (), None, "unsupported_source_type"
    if scope is not None and not isinstance(scope, dict):
        return (), None, "invalid_scope"

    normalized_scope = scope or {}
    jurisdiction = _text(normalized_scope.get("jurisdiction", "KR")).upper()
    if jurisdiction != "KR":
        return (), None, "unsupported_jurisdiction"

    requested_types = (
        LEGAL_SOURCE_TYPES
        if normalized_source_type == "law"
        else (normalized_source_type,)
    )
    scoped_types = normalized_scope.get("allowed_source_types")
    if scoped_types is not None:
        if not isinstance(scoped_types, (list, tuple)) or not scoped_types:
            return (), None, "invalid_allowed_source_types"
        if any(not isinstance(item, str) or item not in LEGAL_SOURCE_TYPES for item in scoped_types):
            return (), None, "invalid_allowed_source_types"
        requested_set = set(requested_types) & set(scoped_types)
        requested_types = tuple(item for item in LEGAL_SOURCE_TYPES if item in requested_set)
        if not requested_types:
            return (), None, "empty_allowed_source_types"

    effective_at, temporal_error = _resolve_effective_at(temporal_basis)
    if temporal_error:
        return (), None, temporal_error
    return tuple(requested_types), effective_at, ""


def _resolve_search_filters(
    *,
    source_type: str,
    temporal_basis: dict[str, Any] | None,
    scope: dict[str, Any] | None,
) -> tuple[tuple[str, ...], date | None, str]:
    """Backward-compatible alias for callers that imported the private helper."""

    return resolve_legal_search_filters(
        source_type=source_type,
        temporal_basis=temporal_basis,
        scope=scope,
    )


def _resolve_effective_at(temporal_basis: dict[str, Any] | None) -> tuple[date | None, str]:
    if temporal_basis is None or temporal_basis == {}:
        return current_legal_date(), ""
    if not isinstance(temporal_basis, dict):
        return None, "invalid_temporal_basis"
    mode = _text(temporal_basis.get("mode"))
    if mode == "current":
        return current_legal_date(), ""
    if mode != "as_of":
        return None, "unsupported_temporal_mode"
    effective_at = _text(temporal_basis.get("effective_at"))
    if not _STRICT_ISO_DATE_PATTERN.fullmatch(effective_at):
        return None, "invalid_effective_at"
    try:
        return date.fromisoformat(effective_at), ""
    except ValueError:
        return None, "invalid_effective_at"


def current_legal_date(now: datetime | None = None) -> date:
    """Return the legal effective date in the service's Korean jurisdiction."""

    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(_LEGAL_TIME_ZONE).date()


def _search_pgvector(
    query: str,
    *,
    top_k: int,
    source_type: str,
    allowed_source_types: tuple[str, ...],
    effective_at: date | None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    latency_breakdown = _empty_latency_breakdown()
    if not _truthy(_setting("LEGAL_RAG_VECTOR_ENABLED", "0")):
        return _search_response(
            status="disabled",
            backend=PGVECTOR_BACKEND,
            query=query,
            top_k=top_k,
            results=[],
            started_at=started_at,
            error_code="vector_disabled",
            latency_breakdown_ms=latency_breakdown,
            effective_at=effective_at.isoformat() if effective_at else None,
        )
    if not allowed_source_types or effective_at is None:
        return _search_response(
            status="disabled",
            backend=PGVECTOR_BACKEND,
            query=query,
            top_k=top_k,
            results=[],
            started_at=started_at,
            error_code="source_type_not_supported",
            latency_breakdown_ms=latency_breakdown,
            effective_at=effective_at.isoformat() if effective_at else None,
        )

    try:
        phase_started_at = time.perf_counter()
        configured_space = _validate_configured_embedding_space()
        connection = _django_connection()
        if getattr(connection, "vendor", "") != "postgresql":
            raise RuntimeError("postgresql_connection_required")
        table_names = set(connection.introspection.table_names())
        missing_tables = [
            table
            for table in ("law_chunks", "law_embeddings")
            if table not in table_names
        ]
        if missing_tables:
            raise RuntimeError(f"missing_tables:{','.join(missing_tables)}")
        if not _pgvector_seed_space_has_eligible_row(
            connection,
            allowed_source_types=allowed_source_types,
            effective_at=effective_at,
            embedding_space=configured_space,
        ):
            raise RuntimeError("no_eligible_seed_embeddings")
        latency_breakdown["preflight_ms"] = _elapsed_ms(phase_started_at)

        phase_started_at = time.perf_counter()
        query_vector, embedding_metadata = _build_query_embedding(query)
        _validate_query_embedding_space(embedding_metadata)
        latency_breakdown["embedding_ms"] = _elapsed_ms(phase_started_at)

        phase_started_at = time.perf_counter()
        rows = _query_pgvector_rows(
            connection,
            query_vector=query_vector,
            top_k=top_k,
            source_type=source_type,
            allowed_source_types=allowed_source_types,
            effective_at=effective_at,
            embedding_space=embedding_metadata,
        )
        latency_breakdown["vector_query_ms"] = _elapsed_ms(phase_started_at)

        phase_started_at = time.perf_counter()
        results = [_pgvector_row_result(row) for row in rows]
        latency_breakdown["result_mapping_ms"] = _elapsed_ms(phase_started_at)
        return _search_response(
            status="ready" if results else "empty",
            backend=PGVECTOR_BACKEND,
            query=query,
            top_k=top_k,
            results=results,
            started_at=started_at,
            embedding=embedding_metadata,
            sql_tables=["law_chunks", "law_embeddings"],
            latency_breakdown_ms=latency_breakdown,
            effective_at=effective_at.isoformat(),
        )
    except Exception as exc:  # pragma: no cover - depends on configured PostgreSQL runtime.
        return _search_response(
            status="unavailable",
            backend=PGVECTOR_BACKEND,
            query=query,
            top_k=top_k,
            results=[],
            started_at=started_at,
            error_code=str(exc)[:120],
            latency_breakdown_ms=latency_breakdown,
            effective_at=effective_at.isoformat() if effective_at else None,
        )


@contextmanager
def _atomic_for_connection(connection: Any):
    alias = getattr(connection, "alias", "")
    if isinstance(alias, str) and alias:
        with transaction.atomic(using=alias):
            yield
        return
    yield


def _query_pgvector_rows(
    connection: Any,
    *,
    query_vector: list[float],
    top_k: int,
    source_type: str,
    allowed_source_types: tuple[str, ...],
    effective_at: date,
    embedding_space: dict[str, Any],
) -> list[dict[str, Any]]:
    vector_literal = _pgvector_literal(query_vector)
    params: list[Any] = [
        vector_literal,
        list(allowed_source_types),
        effective_at,
        effective_at,
        embedding_space["provider"],
        embedding_space["model"],
        embedding_space["dimensions"],
    ]
    params.extend([vector_literal, top_k])

    sql = f"""
        SELECT
            c.chunk_id,
            c.source_id,
            c.source_name,
            c.source_type,
            c.chunk_type,
            c.article_no,
            c.appendix_no,
            c.form_no,
            c.provision_text,
            c.normalized_text,
            c.source_url,
            c.enforce_date,
            c.expire_date,
            c.domain_tags,
            e.embedding_provider,
            e.embedding_model,
            e.embedding_dimensions,
            1 - (e.embedding_vector <=> %s::vector) AS score
        FROM law_embeddings e
        JOIN law_chunks c ON c.chunk_id = e.chunk_id
        WHERE c.is_searchable = TRUE
          AND c.source_type = ANY(%s)
          AND c.enforce_date IS NOT NULL
          AND c.enforce_date <= %s
          AND (c.expire_date IS NULL OR c.expire_date >= %s)
          AND {USABLE_LEGAL_EVIDENCE_SQL}
          AND e.embedding_vector IS NOT NULL
          AND e.embedding_provider = %s
          AND e.embedding_model = %s
          AND e.embedding_dimensions = %s
        ORDER BY e.embedding_vector <=> %s::vector
        LIMIT %s
    """
    with _atomic_for_connection(connection):
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL hnsw.ef_search = 400")
            cursor.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
            cursor.execute(sql, params)
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]


def _pgvector_seed_space_has_eligible_row(
    connection: Any,
    *,
    allowed_source_types: tuple[str, ...],
    effective_at: date,
    embedding_space: dict[str, Any],
) -> bool:
    sql = f"""
        SELECT 1
        FROM law_embeddings e
        JOIN law_chunks c ON c.chunk_id = e.chunk_id
        WHERE c.is_searchable = TRUE
          AND c.source_type = ANY(%s)
          AND c.enforce_date IS NOT NULL
          AND c.enforce_date <= %s
          AND (c.expire_date IS NULL OR c.expire_date >= %s)
          AND {USABLE_LEGAL_EVIDENCE_SQL}
          AND e.embedding_vector IS NOT NULL
          AND e.embedding_provider = %s
          AND e.embedding_model = %s
          AND e.embedding_dimensions = %s
        LIMIT 1
    """
    params = [
        list(allowed_source_types),
        effective_at,
        effective_at,
        embedding_space["provider"],
        embedding_space["model"],
        embedding_space["dimensions"],
    ]
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone() is not None


def _build_query_embedding(query: str) -> tuple[list[float], dict[str, Any]]:
    provider = _text(_setting("LEGAL_RAG_QUERY_EMBEDDING_PROVIDER", "openai")).lower()
    if provider in {"", "disabled", "none"}:
        raise RuntimeError("query_embedding_disabled")
    if provider == "hash":
        dimensions = _int_setting("LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS", 32)
        return _hash_embedding(query, dimensions=dimensions), {
            "provider": "hash",
            "model": "hashing-vectorizer",
            "dimensions": dimensions,
        }
    if provider == "sentence-transformers":
        model_id = _text(
            _setting("LEGAL_RAG_QUERY_EMBEDDING_MODEL", DEFAULT_SENTENCE_TRANSFORMER_MODEL)
        )
        vector = _sentence_transformer_embedding(query, model_id=model_id)
        return vector, {
            "provider": provider,
            "model": model_id,
            "dimensions": len(vector),
        }
    if provider == "openai":
        model_id = _text(_setting("LEGAL_RAG_QUERY_EMBEDDING_MODEL", "text-embedding-3-large"))
        dimensions = _int_setting("LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS", 0)
        vector = _openai_embedding(query, model_id=model_id, dimensions=dimensions)
        return vector, {
            "provider": provider,
            "model": model_id,
            "dimensions": len(vector),
        }
    raise RuntimeError(f"unsupported_embedding_provider:{provider}")


def _validate_query_embedding_space(metadata: dict[str, Any]) -> None:
    """Fail closed unless query and verified seed embeddings share one space."""

    seed_space = _validate_configured_embedding_space()
    query_provider = _text(metadata.get("provider")).lower()
    query_model = _text(metadata.get("model"))
    try:
        query_dimensions = int(metadata.get("dimensions"))
    except (TypeError, ValueError):
        raise RuntimeError("embedding_space_mismatch") from None

    if (
        query_provider != seed_space["provider"]
        or query_model != seed_space["model"]
        or query_dimensions != seed_space["dimensions"]
    ):
        raise RuntimeError("embedding_space_mismatch")


def _validate_configured_embedding_space() -> dict[str, Any]:
    """Validate query/seed configuration before any model or paid API call."""

    seed_provider = _text(_setting("LEGAL_RAG_SEED_EMBEDDING_PROVIDER", "")).lower()
    seed_model = _text(_setting("LEGAL_RAG_SEED_EMBEDDING_MODEL", ""))
    seed_dimensions = _int_setting("LEGAL_RAG_SEED_EMBEDDING_DIMENSIONS", 0)
    if not seed_provider or not seed_model or seed_dimensions <= 0:
        raise RuntimeError("query_embedding_space_not_configured")

    query_provider = _text(
        _setting("LEGAL_RAG_QUERY_EMBEDDING_PROVIDER", "openai")
    ).lower()
    query_model = _text(
        _setting("LEGAL_RAG_QUERY_EMBEDDING_MODEL", "text-embedding-3-large")
    )
    query_dimensions = _int_setting("LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS", 0)

    if (
        seed_dimensions != 1024
        or query_dimensions != seed_dimensions
        or query_provider != seed_provider
        or query_model != seed_model
    ):
        raise RuntimeError("embedding_space_mismatch")
    return {
        "provider": seed_provider,
        "model": seed_model,
        "dimensions": seed_dimensions,
    }


def _sentence_transformer_embedding(query: str, *, model_id: str) -> list[float]:
    device = _text(_setting("LEGAL_RAG_QUERY_EMBEDDING_DEVICE", "cpu")) or "cpu"
    model = _sentence_transformer_model(model_id, device)
    prefix = "query: " if "e5" in model_id.lower() else ""
    vector = model.encode(
        [prefix + query],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0]
    return [float(item) for item in vector.tolist()]


@lru_cache(maxsize=1)
def _sentence_transformer_model(model_id: str, device: str) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("sentence_transformers_unavailable") from exc
    return SentenceTransformer(model_id, device=device)


@lru_cache(maxsize=1)
def _openai_embedding_client() -> Any:
    api_key = _text(_setting("LEGAL_RAG_OPENAI_API_KEY", "")) or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("openai_api_key_required")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai_sdk_unavailable") from exc

    timeout = _int_setting("LEGAL_RAG_QUERY_EMBEDDING_TIMEOUT_SECONDS", 12)
    # Force the real OpenAI endpoint regardless of a global OPENAI_BASE_URL override
    # (e.g. a local-dev redirect to Ollama for chat completions) — the stored
    # law_embeddings vectors are real OpenAI text-embedding-3-large space, and
    # query embeddings must come from the same space or search silently breaks.
    return OpenAI(api_key=api_key, timeout=timeout, base_url="https://api.openai.com/v1")


def _openai_embedding(query: str, *, model_id: str, dimensions: int) -> list[float]:
    kwargs: dict[str, Any] = {
        "model": model_id,
        "input": query,
        "encoding_format": "float",
    }
    if dimensions > 0:
        kwargs["dimensions"] = dimensions
    response = _openai_embedding_client().embeddings.create(**kwargs)
    return _normalize_l2([float(item) for item in response.data[0].embedding])


def _hash_embedding(query: str, *, dimensions: int) -> list[float]:
    dimensions = max(1, dimensions)
    vector = [0.0] * dimensions
    tokens = _hash_tokens(query) or [query.lower()]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    return _normalize_l2(vector)


def _hash_tokens(value: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9\uac00-\ud7a3]+", value)
        if len(token) >= 2
    ]


def _normalize_l2(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(item * item for item in vector))
    if norm <= 0:
        return vector
    return [item / norm for item in vector]


def _pgvector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{item:.9f}" for item in vector) + "]"


def _pgvector_row_result(row: dict[str, Any]) -> dict[str, Any]:
    article = _text(row.get("article_no") or row.get("appendix_no") or row.get("form_no"))
    source_name = _text(row.get("source_name") or row.get("source_id"))
    provision_text = _text(row.get("provision_text"))
    return {
        "source_reference": _text(row.get("chunk_id")),
        "source_document_id": "",
        "source_id": _text(row.get("source_id")),
        "source_type": _text(row.get("source_type")),
        "source_name": source_name,
        "title": f"{source_name} {article}".strip() or "Legal source chunk",
        "article": article,
        "section_ref": article,
        "summary": provision_text[:240],
        "provision_text": provision_text,
        "source_url": _text(row.get("source_url")),
        "effective_date": _date_iso(row.get("enforce_date")),
        "expire_date": _date_iso(row.get("expire_date")),
        "domain_tags": _list(row.get("domain_tags")),
        "embedding_provider": _text(row.get("embedding_provider")),
        "embedding_model": _text(row.get("embedding_model")),
        "embedding_dimensions": int(row.get("embedding_dimensions") or 0),
        "score": round(float(row.get("score") or 0.0), 6),
    }


def _search_response(
    *,
    status: str,
    backend: str,
    query: str,
    top_k: int,
    results: list[dict[str, Any]],
    started_at: float,
    error_code: str = "",
    **extra: Any,
) -> dict[str, Any]:
    response = {
        "contract_version": "legal_rag_search.v1",
        "status": status,
        "backend": backend,
        "query": query,
        "top_k": top_k,
        "result_count": len(results),
        "latency_ms": max(0, round((time.perf_counter() - started_at) * 1000)),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "error_code": error_code,
    }
    response.update({key: value for key, value in extra.items() if value not in (None, "", [])})
    return response


def _empty_latency_breakdown() -> dict[str, int]:
    return {key: 0 for key in LATENCY_BREAKDOWN_KEYS}


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


def _django_connection() -> Any:
    from django.apps import apps
    from django.db import connection

    if not apps.ready:
        raise RuntimeError("django_apps_not_ready")
    return connection


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        stripped = value.strip("{}")
        return [item for item in stripped.split(",") if item]
    return []


def _date_iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int_setting(name: str, default: int) -> int:
    try:
        value = int(_setting(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _setting(name: str, default: Any = "") -> Any:
    if name in os.environ:
        return os.environ[name]
    try:
        from django.conf import settings
    except Exception:
        return os.environ.get(name, default)
    if settings.configured and hasattr(settings, name):
        return getattr(settings, name)
    return os.environ.get(name, default)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""
