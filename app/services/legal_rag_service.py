"""Runtime lookup helpers for legal RAG evidence."""

from __future__ import annotations

import hashlib
import math
import os
import re
import time
from typing import Any


PGVECTOR_BACKEND = "postgres_pgvector"
DJANGO_RAG_BACKEND = "django_rag_tables"
DEFAULT_SENTENCE_TRANSFORMER_MODEL = "intfloat/multilingual-e5-large"


def search_legal_rag(
    query: str,
    *,
    top_k: int = 3,
    source_type: str = "law",
) -> dict[str, Any]:
    started_at = time.perf_counter()
    normalized_query = _text(query)
    if not normalized_query or top_k <= 0:
        return _search_response(
            status="empty_query",
            backend=DJANGO_RAG_BACKEND,
            query=normalized_query,
            top_k=top_k,
            results=[],
            started_at=started_at,
        )

    vector_response = _search_pgvector(normalized_query, top_k=top_k, source_type=source_type)
    vector_attempt = _attempt_summary(vector_response)
    if vector_response["status"] == "ready" and vector_response["results"]:
        vector_response["attempted_backends"] = [vector_attempt]
        return vector_response

    lexical_response = _search_django_rag_tables(
        normalized_query,
        top_k=top_k,
        source_type=source_type,
    )
    lexical_response["attempted_backends"] = [vector_attempt, _attempt_summary(lexical_response)]
    if vector_response["status"] not in {"disabled", "empty_query"}:
        lexical_response["fallback_from"] = {
            "backend": vector_response["backend"],
            "status": vector_response["status"],
            "error_code": vector_response.get("error_code", ""),
        }
    return lexical_response


def _search_pgvector(query: str, *, top_k: int, source_type: str) -> dict[str, Any]:
    started_at = time.perf_counter()
    if not _truthy(_setting("LEGAL_RAG_VECTOR_ENABLED", "0")):
        return _search_response(
            status="disabled",
            backend=PGVECTOR_BACKEND,
            query=query,
            top_k=top_k,
            results=[],
            started_at=started_at,
            error_code="vector_disabled",
        )
    if source_type and source_type != "law":
        return _search_response(
            status="disabled",
            backend=PGVECTOR_BACKEND,
            query=query,
            top_k=top_k,
            results=[],
            started_at=started_at,
            error_code="source_type_not_supported",
        )

    try:
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

        query_vector, embedding_metadata = _build_query_embedding(query)
        rows = _query_pgvector_rows(
            connection,
            query_vector=query_vector,
            top_k=top_k,
            source_type=source_type,
            provider_filter=_text(_setting("LEGAL_RAG_EMBEDDING_PROVIDER_FILTER", "")),
        )
        results = [_pgvector_row_result(row) for row in rows]
        return _search_response(
            status="ready" if results else "empty",
            backend=PGVECTOR_BACKEND,
            query=query,
            top_k=top_k,
            results=results,
            started_at=started_at,
            embedding=embedding_metadata,
            sql_tables=["law_chunks", "law_embeddings"],
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
        )


def _search_django_rag_tables(query: str, *, top_k: int, source_type: str) -> dict[str, Any]:
    started_at = time.perf_counter()
    try:
        connection = _django_connection()

        from chatbot.models import RagChunk

        if RagChunk._meta.db_table not in connection.introspection.table_names():
            raise RuntimeError("rag_chunks_table_missing")

        queryset = RagChunk.objects.filter(is_searchable=True)
        if source_type:
            queryset = queryset.filter(source_type=source_type)

        candidates = list(queryset.select_related("source_document").order_by("-updated_at")[:1000])
        results = _rank_chunks(query, candidates, top_k=top_k)
        return _search_response(
            status="ready" if results else "empty",
            backend=DJANGO_RAG_BACKEND,
            query=query,
            top_k=top_k,
            results=results,
            started_at=started_at,
            sql_tables=["rag_chunks", "source_documents"],
        )
    except Exception as exc:  # pragma: no cover - depends on configured Django runtime.
        return _search_response(
            status="unavailable",
            backend=DJANGO_RAG_BACKEND,
            query=query,
            top_k=top_k,
            results=[],
            started_at=started_at,
            error_code=str(exc)[:120],
        )


def _query_pgvector_rows(
    connection: Any,
    *,
    query_vector: list[float],
    top_k: int,
    source_type: str,
    provider_filter: str,
) -> list[dict[str, Any]]:
    vector_literal = _pgvector_literal(query_vector)
    provider_clause = ""
    params: list[Any] = [vector_literal, source_type, source_type]
    if provider_filter:
        provider_clause = " AND e.embedding_provider = %s"
        params.append(provider_filter)
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
            1 - (e.embedding_vector <=> %s::vector) AS score
        FROM law_embeddings e
        JOIN law_chunks c ON c.chunk_id = e.chunk_id
        WHERE c.is_searchable = TRUE
          AND (%s = '' OR c.source_type = %s)
          {provider_clause}
        ORDER BY e.embedding_vector <=> %s::vector
        LIMIT %s
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]


def _build_query_embedding(query: str) -> tuple[list[float], dict[str, Any]]:
    provider = _text(_setting("LEGAL_RAG_QUERY_EMBEDDING_PROVIDER", "sentence-transformers")).lower()
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


def _sentence_transformer_embedding(query: str, *, model_id: str) -> list[float]:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("sentence_transformers_unavailable") from exc

    device = _text(_setting("LEGAL_RAG_QUERY_EMBEDDING_DEVICE", "cpu")) or "cpu"
    prefix = "query: " if "e5" in model_id.lower() else ""
    model = SentenceTransformer(model_id, device=device)
    vector = model.encode(
        [prefix + query],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0]
    return [float(item) for item in vector.tolist()]


def _openai_embedding(query: str, *, model_id: str, dimensions: int) -> list[float]:
    api_key = _text(_setting("LEGAL_RAG_OPENAI_API_KEY", "")) or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("openai_api_key_required")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai_sdk_unavailable") from exc

    kwargs: dict[str, Any] = {
        "model": model_id,
        "input": query,
        "encoding_format": "float",
    }
    if dimensions > 0:
        kwargs["dimensions"] = dimensions
    timeout = _int_setting("LEGAL_RAG_QUERY_EMBEDDING_TIMEOUT_SECONDS", 12)
    response = OpenAI(api_key=api_key, timeout=timeout).embeddings.create(**kwargs)
    return _normalize_l2([float(item) for item in response.data[0].embedding])


def _hash_embedding(query: str, *, dimensions: int) -> list[float]:
    dimensions = max(1, dimensions)
    vector = [0.0] * dimensions
    tokens = _tokens(query) or [query.lower()]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    return _normalize_l2(vector)


def _normalize_l2(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(item * item for item in vector))
    if norm <= 0:
        return vector
    return [item / norm for item in vector]


def _pgvector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{item:.9f}" for item in vector) + "]"


def _rank_chunks(query: str, chunks: list[Any], *, top_k: int) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    ranked = []
    for chunk in chunks:
        haystack = " ".join(
            [
                _text(getattr(chunk, "title", "")),
                _text(getattr(chunk, "article_no", "")),
                _text(getattr(chunk, "section_ref", "")),
                _text(getattr(chunk, "normalized_text", "")),
                _text(getattr(chunk, "content", "")),
            ]
        ).lower()
        if not haystack:
            continue
        score = 0.0
        if query.lower() in haystack:
            score += 5.0
        for token in query_tokens:
            if token in haystack:
                score += 1.0
                if token in _text(getattr(chunk, "title", "")).lower():
                    score += 1.5
                if token in _text(getattr(chunk, "article_no", "")).lower():
                    score += 1.5
        if score <= 0:
            continue
        ranked.append((score, chunk))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [_chunk_result(chunk, score) for score, chunk in ranked[:top_k]]


def _chunk_result(chunk: Any, score: float) -> dict[str, Any]:
    source_document = getattr(chunk, "source_document", None)
    source_name = _text(getattr(source_document, "source_name", "")) or _text(getattr(chunk, "source_id", ""))
    source_url = _text(getattr(source_document, "source_url", ""))
    effective_date = getattr(source_document, "effective_date", None)
    expire_date = getattr(source_document, "expire_date", None)
    content = _text(getattr(chunk, "content", ""))
    article_no = _text(getattr(chunk, "article_no", ""))
    title = _text(getattr(chunk, "title", "")) or "Legal source chunk"
    return {
        "source_reference": _text(getattr(chunk, "chunk_id", "")),
        "source_document_id": _text(getattr(source_document, "source_document_id", "")),
        "source_type": _text(getattr(chunk, "source_type", "")),
        "source_name": source_name,
        "title": title,
        "article": article_no,
        "section_ref": _text(getattr(chunk, "section_ref", "")),
        "summary": content[:240],
        "source_url": source_url,
        "effective_date": effective_date.isoformat() if effective_date else None,
        "expire_date": expire_date.isoformat() if expire_date else None,
        "domain_tags": _list(getattr(chunk, "domain_tags", [])),
        "score": round(score, 4),
    }


def _pgvector_row_result(row: dict[str, Any]) -> dict[str, Any]:
    article = _text(row.get("article_no") or row.get("appendix_no") or row.get("form_no"))
    source_name = _text(row.get("source_name") or row.get("source_id"))
    provision_text = _text(row.get("provision_text"))
    return {
        "source_reference": _text(row.get("chunk_id")),
        "source_document_id": "",
        "source_type": _text(row.get("source_type")),
        "source_name": source_name,
        "title": f"{source_name} {article}".strip() or "Legal source chunk",
        "article": article,
        "section_ref": article,
        "summary": provision_text[:240],
        "source_url": _text(row.get("source_url")),
        "effective_date": _date_iso(row.get("enforce_date")),
        "expire_date": _date_iso(row.get("expire_date")),
        "domain_tags": _list(row.get("domain_tags")),
        "embedding_provider": _text(row.get("embedding_provider")),
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
        "results": results,
        "error_code": error_code,
    }
    response.update({key: value for key, value in extra.items() if value not in (None, "", [])})
    return response


def _attempt_summary(response: dict[str, Any]) -> dict[str, Any]:
    return {
        "backend": response.get("backend"),
        "status": response.get("status"),
        "result_count": response.get("result_count", 0),
        "latency_ms": response.get("latency_ms", 0),
        "error_code": response.get("error_code", ""),
    }


def _django_connection() -> Any:
    from django.apps import apps
    from django.db import connection

    if not apps.ready:
        raise RuntimeError("django_apps_not_ready")
    return connection


def _tokens(value: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[\w\uac00-\ud7a3]+", value) if len(token) >= 2]


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
