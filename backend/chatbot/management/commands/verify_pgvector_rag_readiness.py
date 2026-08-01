"""Verify that each active RAG corpus is queryable through pgvector only."""

from __future__ import annotations

import json
from typing import Any, Callable

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def verify_pgvector_rag_readiness() -> dict[str, Any]:
    """Return a credential-safe readiness report for every required corpus."""

    domains = {
        "legal": _safe_verify(_verify_legal),
        "review_case": _safe_verify(_verify_review_case),
        "fault_ratio_precedent": _safe_verify(_verify_fault_ratio_precedent),
    }
    required_domains = ("legal", "review_case", "fault_ratio_precedent")
    for domain, payload in domains.items():
        payload["required"] = domain in required_domains

    shared_embedding_space = _shared_embedding_space(domains)
    required_ready = all(
        domains[domain].get("status") == "ready" for domain in required_domains
    )
    spaces_match = shared_embedding_space is not None

    return {
        "contract_version": "pgvector_rag_readiness.v1",
        "status": "ready" if required_ready and spaces_match else "fail",
        "error_code": (
            ""
            if required_ready and spaces_match
            else (
                "shared_embedding_space_mismatch"
                if required_ready
                else "required_pgvector_domain_not_ready"
            )
        ),
        "required_domains": list(required_domains),
        "shared_embedding_space": shared_embedding_space,
        "domains": domains,
    }


def _shared_embedding_space(
    domains: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    spaces = []
    for domain in ("legal", "review_case"):
        payload = domains[domain]
        if payload.get("status") != "ready":
            return None
        space = payload.get("embedding_space")
        if not isinstance(space, dict):
            return None
        spaces.append(
            {
                "provider": str(space.get("provider") or "").strip().lower(),
                "model": str(space.get("model") or "").strip(),
                "dimensions": int(space.get("dimensions") or 0),
            }
        )
    return spaces[0] if spaces[0] == spaces[1] else None


class Command(BaseCommand):
    help = (
        "Verify required legal, review-case, and fault-ratio pgvector stores "
        "without performing writes."
    )

    def add_arguments(self, parser):
        parser.add_argument("--format", choices=["json", "text"], default="json")

    def handle(self, *args, **options):
        result = verify_pgvector_rag_readiness()
        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            self.stdout.write(_text_result(result))
        if result["status"] != "ready":
            raise CommandError("pgvector RAG readiness verification failed.")


def _safe_verify(check: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return check()
    except Exception as exc:  # Database drivers and optional ETL dependencies vary by deployment.
        return {"status": "unavailable", "error_code": f"{exc.__class__.__name__}"}


def _verify_legal() -> dict[str, Any]:
    from app.services.legal_rag_service import _validate_configured_embedding_space

    embedding_space = _validate_configured_embedding_space()
    table_names = set(connection.introspection.table_names())
    if {"law_chunks", "law_embeddings"} - table_names:
        return {
            "status": "unavailable",
            "error_code": "missing_law_pgvector_tables",
            "embedding_space": embedding_space,
        }
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM law_embeddings
            WHERE embedding_provider = %s
              AND embedding_model = %s
              AND embedding_dimensions = %s
              AND embedding_vector IS NOT NULL
            """,
            (
                embedding_space["provider"],
                embedding_space["model"],
                embedding_space["dimensions"],
            ),
        )
        embedding_count = int(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename = 'law_embeddings'
                  AND indexdef ILIKE '%%USING hnsw%%'
            )
            """
        )
        hnsw_index = bool(cursor.fetchone()[0])
    return {
        "status": "ready" if embedding_count > 0 and hnsw_index else "unavailable",
        "error_code": "" if embedding_count > 0 and hnsw_index else "legal_pgvector_not_ready",
        "embedding_count": embedding_count,
        "hnsw_index": hnsw_index,
        "embedding_space": embedding_space,
    }


def _verify_review_case() -> dict[str, Any]:
    from etl.fault_cases.src.review_case.db_loading.db_config import (
        EMBEDDING_SETTINGS,
        PGVECTOR_INDEX_SETTINGS,
    )
    from etl.fault_cases.src.review_case.search.pgvector.create_index import (
        count_embedding_rows,
        index_exists,
    )

    embedding_count = count_embedding_rows()
    hnsw_index = index_exists(PGVECTOR_INDEX_SETTINGS.index_name)
    return {
        "status": "ready" if embedding_count > 0 and hnsw_index else "unavailable",
        "error_code": "" if embedding_count > 0 and hnsw_index else "review_case_pgvector_not_ready",
        "embedding_count": embedding_count,
        "hnsw_index": hnsw_index,
        "embedding_space": {
            "provider": EMBEDDING_SETTINGS.provider,
            "model": EMBEDDING_SETTINGS.model,
            "dimensions": EMBEDDING_SETTINGS.dim,
            "version": EMBEDDING_SETTINGS.version,
        },
    }


def _verify_fault_ratio_precedent() -> dict[str, Any]:
    from etl.fault_cases.src.traffic_precedents.precedent_search.newplusplus.config import (
        ServiceSettings,
    )
    from etl.fault_cases.src.traffic_precedents.precedent_search.newplusplus.db import (
        database_readiness,
    )

    settings = ServiceSettings()
    readiness = database_readiness()
    ready = bool(readiness.get("ready"))
    return {
        "status": "ready" if ready else "unavailable",
        "error_code": "" if ready else "fault_ratio_pgvector_not_ready",
        "embedding_count": int(readiness.get("blocks") or 0),
        "case_count": int(readiness.get("cases") or 0),
        "embedding_space": {
            "provider": "huggingface",
            "model": settings.qwen_model_id,
            "dimensions": settings.embedding_dimension,
            "revision": settings.qwen_revision,
        },
    }


def _text_result(result: dict[str, Any]) -> str:
    lines = [f"pgvector RAG readiness: {result['status']}"]
    for domain, payload in result["domains"].items():
        lines.append(
            f"- {domain}: {payload.get('status')} "
            f"(embeddings={payload.get('embedding_count')}, hnsw={payload.get('hnsw_index')})"
        )
    return "\n".join(lines)
