"""Production readiness checks for the canonical Django runtime."""

from __future__ import annotations

import importlib.util
import ipaddress
import os
from typing import Any

from django.conf import settings
from django.db import connection

from app.services.google_auth_service import (
    is_official_google_token_endpoint,
    is_official_google_userinfo_endpoint,
    is_google_web_client_id,
    normalize_google_web_origin,
)
from chatbot.file_scan_service import DEFAULT_MAX_SCAN_BYTES
from chatbot.object_storage import object_storage_policy


PASS = "pass"
WARN = "warn"
FAIL = "fail"
DEV_SECRET_KEY = "dev-only-change-before-deploy"
PLACEHOLDER_MARKERS = ("replace-with", "placeholder", "change-me", "example.com")


def build_production_readiness_report(*, include_database: bool = True) -> dict[str, Any]:
    database_state = _database_state(include_database=include_database)
    checks = [
        _django_security_check(),
        _database_check(include_database=include_database, database_state=database_state),
        _google_oauth_check(),
        _supervisor_llm_check(),
        _legal_rag_check(include_database=include_database, database_state=database_state),
        _law_ground_search_sync_check(),
        _text_ml_case_search_rag_check(),
        _worker_queue_check(include_database=include_database, database_state=database_state),
        _file_scan_check(),
        _object_storage_check(),
    ]
    return {
        "contract_version": "production_readiness.v1",
        "status": _overall_status(checks),
        "summary": _summary(checks),
        "checks": checks,
        "include_database": include_database,
    }


def _django_security_check() -> dict[str, Any]:
    details = []
    debug = bool(_setting("DEBUG", True))
    secret_key = str(_setting("SECRET_KEY", ""))
    allowed_hosts = list(_setting("ALLOWED_HOSTS", []))

    if debug:
        details.append(_detail(FAIL, "DJANGO_DEBUG must be 0 for production."))
    if not secret_key or secret_key == DEV_SECRET_KEY or len(secret_key) < 32 or _looks_placeholder(secret_key):
        details.append(_detail(FAIL, "DJANGO_SECRET_KEY must be a non-default secret with at least 32 characters."))
    if not allowed_hosts or set(allowed_hosts).issubset({"localhost", "127.0.0.1", "[::1]"}):
        details.append(_detail(FAIL, "DJANGO_ALLOWED_HOSTS must include the production host."))
    elif any(_looks_placeholder(host) for host in allowed_hosts):
        details.append(_detail(FAIL, "DJANGO_ALLOWED_HOSTS must not contain placeholder hosts."))

    return _check(
        "django_security",
        details,
        ok_message="Django security settings are production-shaped.",
    )


def _database_state(*, include_database: bool) -> dict[str, Any]:
    configured_engine = str(_setting("DJANGO_DATABASE_ENGINE", "")).lower()
    vendor = getattr(connection, "vendor", "unknown") if include_database else configured_engine or "not_checked"
    state = {
        "checked": include_database,
        "configured_engine": configured_engine,
        "vendor": vendor,
        "table_names": set(),
        "error": None,
    }
    if not include_database:
        return state

    try:
        state["table_names"] = set(connection.introspection.table_names())
    except Exception as exc:  # Database drivers surface connection failures through backend-specific exceptions.
        state["error"] = _format_exception(exc)
    return state


def _database_check(*, include_database: bool, database_state: dict[str, Any]) -> dict[str, Any]:
    details = []
    configured_engine = str(database_state.get("configured_engine") or "")
    vendor = str(database_state.get("vendor") or "unknown")
    introspection_error = str(database_state.get("error") or "")

    if configured_engine and configured_engine != "postgres":
        details.append(_detail(FAIL, "DJANGO_DATABASE_ENGINE must be postgres for production."))
    if include_database and introspection_error:
        details.append(_detail(FAIL, f"Database connection or introspection failed: {introspection_error}"))
    elif include_database and vendor != "postgresql":
        details.append(_detail(FAIL, f"Active Django database vendor must be postgresql, got {vendor}."))

    return _check(
        "database",
        details,
        ok_message="Database configuration targets PostgreSQL.",
        metadata={
            "vendor": vendor,
            "configured_engine": configured_engine or None,
            "introspection_error": introspection_error or None,
        },
    )


def _google_oauth_check() -> dict[str, Any]:
    details = []
    required = {
        "GOOGLE_CLIENT_ID": _setting("GOOGLE_CLIENT_ID", ""),
        "GOOGLE_CLIENT_SECRET": _setting("GOOGLE_CLIENT_SECRET", ""),
        "GOOGLE_POPUP_REDIRECT_URI": _setting("GOOGLE_POPUP_REDIRECT_URI", ""),
    }
    missing = [name for name, value in required.items() if not str(value or "").strip()]
    placeholder = [name for name, value in required.items() if _looks_placeholder(value)]
    if missing:
        details.append(_detail(FAIL, f"Missing Google OAuth settings: {', '.join(missing)}."))
    if placeholder:
        details.append(_detail(FAIL, f"Google OAuth settings still contain placeholders: {', '.join(placeholder)}."))

    client_id = str(required["GOOGLE_CLIENT_ID"] or "").strip()
    if client_id and not is_google_web_client_id(client_id):
        details.append(
            _detail(
                FAIL,
                "GOOGLE_CLIENT_ID must be a Google OAuth Web client ID ending in .apps.googleusercontent.com.",
            )
        )

    redirect_uri = str(required["GOOGLE_POPUP_REDIRECT_URI"] or "").strip()
    normalized_redirect_uri = normalize_google_web_origin(redirect_uri)
    if redirect_uri and not normalized_redirect_uri:
        details.append(
            _detail(
                FAIL,
                "GOOGLE_POPUP_REDIRECT_URI must be a secure web origin without a path, query, or fragment; HTTP is allowed only for loopback local development.",
            )
        )
    elif (
        redirect_uri
        and not bool(_setting("DEBUG", True))
        and not normalized_redirect_uri.startswith("https://")
    ):
        details.append(
            _detail(
                FAIL,
                "GOOGLE_POPUP_REDIRECT_URI must use HTTPS when DEBUG is false.",
            )
        )

    token_endpoint = str(_setting("GOOGLE_TOKEN_ENDPOINT", "") or "").strip()
    userinfo_endpoint = str(_setting("GOOGLE_USERINFO_ENDPOINT", "") or "").strip()
    if not is_official_google_token_endpoint(token_endpoint) or not is_official_google_userinfo_endpoint(
        userinfo_endpoint
    ):
        details.append(
            _detail(
                FAIL,
                "GOOGLE_TOKEN_ENDPOINT and GOOGLE_USERINFO_ENDPOINT must use the official Google HTTPS endpoints.",
            )
        )

    app_jwt_secret = str(_setting("APP_JWT_SECRET", ""))
    oauth_secret = str(_setting("OAUTH_TOKEN_SECRET", ""))
    if not app_jwt_secret or app_jwt_secret == DEV_SECRET_KEY or len(app_jwt_secret) < 32 or _looks_placeholder(app_jwt_secret):
        details.append(_detail(FAIL, "APP_JWT_SECRET must be a non-default secret with at least 32 characters."))
    if not oauth_secret or oauth_secret == DEV_SECRET_KEY or len(oauth_secret) < 32 or _looks_placeholder(oauth_secret):
        details.append(_detail(FAIL, "OAUTH_TOKEN_SECRET must be a non-default secret with at least 32 characters."))

    configured_proxy_cidrs = _setting("GOOGLE_OAUTH_TRUSTED_PROXY_CIDRS", [])
    proxy_cidrs = (
        configured_proxy_cidrs.split(",")
        if isinstance(configured_proxy_cidrs, str)
        else configured_proxy_cidrs
    )
    invalid_proxy_cidrs = []
    for value in proxy_cidrs:
        try:
            ipaddress.ip_network(str(value).strip(), strict=False)
        except ValueError:
            invalid_proxy_cidrs.append(str(value))
    if invalid_proxy_cidrs:
        details.append(
            _detail(
                FAIL,
                "GOOGLE_OAUTH_TRUSTED_PROXY_CIDRS contains an invalid trusted proxy CIDR.",
            )
        )

    return _check(
        "google_oauth",
        details,
        ok_message="Google Authorization Code Flow is configured.",
    )


def _supervisor_llm_check() -> dict[str, Any]:
    details = []
    enabled = bool(_setting("SUPERVISOR_LLM_ENABLED", False))
    model = str(_setting("SUPERVISOR_LLM_MODEL", "") or "")
    api_key = str(_setting("SUPERVISOR_LLM_API_KEY", "") or _setting("OPENAI_API_KEY", "") or "")
    if enabled:
        if not model:
            details.append(_detail(FAIL, "SUPERVISOR_LLM_MODEL is required when Supervisor LLM is enabled."))
        if not api_key or _looks_placeholder(api_key):
            details.append(_detail(FAIL, "SUPERVISOR_LLM_API_KEY or OPENAI_API_KEY is required when Supervisor LLM is enabled."))
    else:
        details.append(_detail(WARN, "Supervisor LLM planner is disabled; mock/fallback planning remains active."))

    return _check(
        "supervisor_llm",
        details,
        ok_message="Supervisor LLM planner is configured.",
        metadata={
            "enabled": enabled,
            "model": model or None,
            "slot_state_contract": "slot_filling_state.v1",
            "production_smoke": (
                "smoke_supervisor_conversation_runtime --require-llm-used"
            ),
        },
    )


def _legal_rag_check(*, include_database: bool, database_state: dict[str, Any]) -> dict[str, Any]:
    details = []
    enabled = bool(_setting("LEGAL_RAG_VECTOR_ENABLED", False))
    provider = str(_setting("LEGAL_RAG_QUERY_EMBEDDING_PROVIDER", "") or "").strip().lower()
    model = str(_setting("LEGAL_RAG_QUERY_EMBEDDING_MODEL", "") or "").strip()
    query_dimensions_raw = _setting("LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS", "")
    seed_provider = str(_setting("LEGAL_RAG_SEED_EMBEDDING_PROVIDER", "") or "").strip().lower()
    seed_model = str(_setting("LEGAL_RAG_SEED_EMBEDDING_MODEL", "") or "").strip()
    seed_dimensions_raw = _setting("LEGAL_RAG_SEED_EMBEDDING_DIMENSIONS", "")
    introspection_error = str(database_state.get("error") or "")
    try:
        query_dimensions = int(query_dimensions_raw)
        seed_dimensions = int(seed_dimensions_raw)
    except (TypeError, ValueError):
        query_dimensions = 0
        seed_dimensions = 0

    if not enabled:
        details.append(
            _detail(
                FAIL,
                "Legal RAG pgvector search must be enabled in production.",
            )
        )
    else:
        if provider not in {"sentence-transformers", "openai"}:
            details.append(_detail(FAIL, f"Unsupported LEGAL_RAG_QUERY_EMBEDDING_PROVIDER: {provider}."))
        if provider in {"sentence-transformers", "openai"} and not model:
            details.append(_detail(FAIL, "LEGAL_RAG_QUERY_EMBEDDING_MODEL is required for vector search."))
        if provider == "sentence-transformers" and importlib.util.find_spec("sentence_transformers") is None:
            details.append(_detail(FAIL, "sentence-transformers package is not installed in the runtime."))
        legal_rag_openai_key = str(_setting("LEGAL_RAG_OPENAI_API_KEY", "") or "")
        if provider == "openai" and (not legal_rag_openai_key.strip() or _looks_placeholder(legal_rag_openai_key)):
            details.append(_detail(FAIL, "LEGAL_RAG_OPENAI_API_KEY or OPENAI_API_KEY is required for OpenAI embeddings."))
        if not seed_provider or not seed_model or seed_dimensions <= 0:
            details.append(
                _detail(
                    FAIL,
                    "LEGAL_RAG_SEED_EMBEDDING_PROVIDER/MODEL/DIMENSIONS must match the verified seed manifest.",
                )
            )
        elif seed_dimensions != 1024:
            details.append(_detail(FAIL, "Production legal RAG seed embeddings must have 1024 dimensions."))
        if (
            provider != seed_provider
            or model != seed_model
            or query_dimensions != seed_dimensions
        ):
            details.append(
                _detail(
                    FAIL,
                    "Legal RAG query embedding space does not match the configured seed embedding space.",
                )
            )

    if include_database:
        if introspection_error:
            details.append(
                _detail(
                    FAIL,
                    f"Cannot verify legal RAG tables because database introspection failed: {introspection_error}",
                )
            )
        else:
            table_names = set(database_state.get("table_names") or set())
            if "law_chunks" not in table_names:
                details.append(_detail(FAIL, "Missing legal RAG table: law_chunks."))
            else:
                try:
                    if not _current_legal_chunk_exists():
                        details.append(
                            _detail(
                                FAIL,
                                "No current searchable legal row exists for PostgreSQL pgvector retrieval.",
                            )
                        )
                except Exception as exc:
                    details.append(
                        _detail(
                            FAIL,
                            "Cannot verify current searchable legal rows: "
                            f"{_format_exception(exc)}",
                        )
                    )

            if enabled:
                if "law_embeddings" not in table_names:
                    details.append(_detail(FAIL, "Missing legal RAG table: law_embeddings."))
                elif (
                    seed_provider
                    and seed_model
                    and seed_dimensions == 1024
                    and provider == seed_provider
                    and model == seed_model
                    and query_dimensions == seed_dimensions
                    and "law_chunks" in table_names
                ):
                    try:
                        if not _configured_legal_embedding_exists(
                            provider=seed_provider,
                            model=seed_model,
                            dimensions=seed_dimensions,
                        ):
                            details.append(
                                _detail(
                                    FAIL,
                                    "No current searchable legal embedding exists in the configured seed space.",
                                )
                            )
                    except Exception as exc:
                        details.append(
                            _detail(
                                FAIL,
                                "Cannot verify configured legal embedding rows: "
                                f"{_format_exception(exc)}",
                            )
                        )

    return _check(
        "legal_rag",
        details,
        ok_message="Legal RAG vector search is configured.",
        metadata={
            "vector_enabled": enabled,
            "embedding_provider": provider or None,
            "embedding_model": model or None,
            "embedding_dimensions": query_dimensions_raw or None,
            "seed_embedding_provider": seed_provider or None,
            "seed_embedding_model": seed_model or None,
            "seed_embedding_dimensions": seed_dimensions_raw or None,
        },
    )


def _current_legal_chunk_exists() -> bool:
    from app.services.legal_rag_service import (
        LEGAL_SOURCE_TYPES,
        USABLE_LEGAL_EVIDENCE_SQL,
        current_legal_date,
    )

    effective_at = current_legal_date()
    sql = f"""
        SELECT 1
        FROM law_chunks c
        WHERE c.is_searchable = TRUE
          AND c.source_type = ANY(%s)
          AND c.enforce_date IS NOT NULL
          AND c.enforce_date <= %s
          AND (c.expire_date IS NULL OR c.expire_date >= %s)
          AND {USABLE_LEGAL_EVIDENCE_SQL}
        LIMIT 1
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [list(LEGAL_SOURCE_TYPES), effective_at, effective_at])
        return cursor.fetchone() is not None


def _configured_legal_embedding_exists(
    *,
    provider: str,
    model: str,
    dimensions: int,
) -> bool:
    from app.services.legal_rag_service import (
        LEGAL_SOURCE_TYPES,
        _pgvector_seed_space_has_eligible_row,
        current_legal_date,
    )

    return _pgvector_seed_space_has_eligible_row(
        connection,
        allowed_source_types=LEGAL_SOURCE_TYPES,
        effective_at=current_legal_date(),
        embedding_space={
            "provider": provider,
            "model": model,
            "dimensions": dimensions,
        },
    )


def _law_ground_search_sync_check() -> dict[str, Any]:
    details = []
    legal_rag_enabled = bool(_setting("LEGAL_RAG_VECTOR_ENABLED", False))
    neo4j_enabled = _truthy(_runtime_setting("LAW_GROUND_SEARCH_ENABLE_NEO4J", ""))
    neo4j_uri = str(_runtime_setting("NEO4J_URI", "") or "")

    if importlib.util.find_spec("ai.agents.law_ground_search") is None:
        details.append(_detail(FAIL, "law_ground_search agent package is not importable."))
    if importlib.util.find_spec("etl.legal.search") is None:
        details.append(_detail(FAIL, "etl.legal.search is required for law_ground_search sync retrieval."))
    if neo4j_enabled and not neo4j_uri.strip():
        details.append(_detail(FAIL, "NEO4J_URI is required when LAW_GROUND_SEARCH_ENABLE_NEO4J is enabled."))
    if not legal_rag_enabled:
        details.append(
            _detail(
                WARN,
                "LEGAL_RAG_VECTOR_ENABLED is disabled; law_ground_search sync smoke may return an empty or partial result.",
            )
        )

    return _check(
        "law_ground_search_sync",
        details,
        ok_message="law_ground_search sync adapter and legal search port are importable.",
        metadata={
            "legal_rag_vector_enabled": legal_rag_enabled,
            "neo4j_enabled": neo4j_enabled,
            "neo4j_uri_set": bool(neo4j_uri.strip()),
            "smoke": "smoke_law_ground_search --require-results",
        },
    )


def _text_ml_case_search_rag_check() -> dict[str, Any]:
    details = []
    required_modules = (
        "etl.fault_cases.src.agents.text_ml_case_search.rag.pgvector_unified_retriever",
        "etl.fault_cases.src.review_case.search.pgvector.retriever",
        "etl.fault_cases.src.traffic_precedents.precedent_search.pgvector.retriever",
    )
    for module_name in required_modules:
        if importlib.util.find_spec(module_name) is None:
            details.append(_detail(FAIL, f"Required pgvector retrieval module is not importable: {module_name}."))

    return _check(
        "text_ml_case_search_rag",
        details,
        ok_message="text_ml_case_search pgvector retrieval modules are importable.",
        metadata={
            "retrieval_backend": "unified_pgvector",
            "smoke": "smoke_text_ml_case_search --require-pgvector",
        },
    )


def _worker_queue_check(*, include_database: bool, database_state: dict[str, Any]) -> dict[str, Any]:
    details = []
    if include_database:
        introspection_error = str(database_state.get("error") or "")
        if introspection_error:
            details.append(
                _detail(
                    FAIL,
                    f"Cannot verify worker queue tables because database introspection failed: {introspection_error}",
                )
            )
        else:
            table_names = set(database_state.get("table_names") or set())
            required = {"analysis_jobs", "agent_invocations", "agent_work_items"}
            missing = sorted(required - table_names)
            if missing:
                details.append(_detail(FAIL, f"Missing worker queue tables: {', '.join(missing)}."))
    if not str(_setting("REDIS_URL", "") or "").strip():
        details.append(_detail(WARN, "REDIS_URL is not set; progress cache will use the local-memory fallback."))

    return _check(
        "worker_queue",
        details,
        ok_message="Agent worker queue persistence is available.",
    )


def _file_scan_check() -> dict[str, Any]:
    details = []
    provider = str(_setting("FILE_SCAN_PROVIDER", "local_policy") or "local_policy")
    try:
        max_bytes = int(_setting("FILE_SCAN_MAX_BYTES", DEFAULT_MAX_SCAN_BYTES))
    except (TypeError, ValueError):
        max_bytes = 0
    try:
        timeout_seconds = int(_setting("FILE_SCAN_TIMEOUT_SECONDS", 0))
    except (TypeError, ValueError):
        timeout_seconds = 0
    try:
        claim_stale_seconds = int(_setting("FILE_SCAN_CLAIM_STALE_AFTER_SECONDS", 0))
    except (TypeError, ValueError):
        claim_stale_seconds = 0
    try:
        retry_backoff_seconds = int(_setting("FILE_SCAN_RETRY_BACKOFF_SECONDS", 0))
    except (TypeError, ValueError):
        retry_backoff_seconds = 0
    try:
        upload_max_bytes = int(_setting("FILE_UPLOAD_MAX_BYTES", 0))
    except (TypeError, ValueError):
        upload_max_bytes = 0
    try:
        retention_purge_limit = int(_setting("FILE_RETENTION_PURGE_LIMIT", 0))
    except (TypeError, ValueError):
        retention_purge_limit = 0
    if max_bytes <= 0:
        details.append(_detail(FAIL, "FILE_SCAN_MAX_BYTES must be a positive integer."))
    if timeout_seconds <= 0:
        details.append(_detail(FAIL, "FILE_SCAN_TIMEOUT_SECONDS must be a positive integer."))
    if claim_stale_seconds <= 0:
        details.append(
            _detail(
                FAIL,
                "FILE_SCAN_CLAIM_STALE_AFTER_SECONDS must be a positive integer.",
            )
        )
    if retry_backoff_seconds <= 0:
        details.append(
            _detail(
                FAIL,
                "FILE_SCAN_RETRY_BACKOFF_SECONDS must be a positive integer.",
            )
        )
    if upload_max_bytes <= 0:
        details.append(_detail(FAIL, "FILE_UPLOAD_MAX_BYTES must be a positive integer."))
    if retention_purge_limit <= 0:
        details.append(
            _detail(
                FAIL,
                "FILE_RETENTION_PURGE_LIMIT must be a positive integer.",
            )
        )
    if provider not in {"local_policy", "clamav", "external"}:
        details.append(_detail(FAIL, f"Unsupported FILE_SCAN_PROVIDER: {provider}."))
    if provider == "local_policy":
        details.append(_detail(WARN, "FILE_SCAN_PROVIDER is local_policy; configure clamav or external scan API for production antivirus scanning."))
    if provider == "clamav" and not str(_setting("FILE_SCAN_CLAMAV_HOST", "") or "").strip():
        details.append(_detail(FAIL, "FILE_SCAN_CLAMAV_HOST is required when FILE_SCAN_PROVIDER=clamav."))
    if provider == "external":
        if not str(_setting("FILE_SCAN_EXTERNAL_URL", "") or "").strip():
            details.append(_detail(FAIL, "FILE_SCAN_EXTERNAL_URL is required when FILE_SCAN_PROVIDER=external."))
        external_api_key = str(_setting("FILE_SCAN_EXTERNAL_API_KEY", "") or "")
        if not external_api_key.strip() or _looks_placeholder(external_api_key):
            details.append(_detail(FAIL, "FILE_SCAN_EXTERNAL_API_KEY is required when FILE_SCAN_PROVIDER=external."))
    return _check(
        "file_scan",
        details,
        ok_message="Uploaded file scan policy is configured.",
        metadata={
            "contract_version": "file_scan_result.v1",
            "provider": provider,
            "max_bytes": max_bytes,
            "timeout_seconds": timeout_seconds,
            "claim_stale_seconds": claim_stale_seconds,
            "retry_backoff_seconds": retry_backoff_seconds,
            "upload_max_bytes": upload_max_bytes,
            "retention_purge_limit": retention_purge_limit,
            "smoke_phases": [
                "smoke_file_scan --phase upload --attachment-id att_release_scan",
                "smoke_file_scan --phase scan --attachment-id att_release_scan --require-clean",
            ],
        },
    )


def _object_storage_check() -> dict[str, Any]:
    provider = str(_setting("OBJECT_STORAGE_PROVIDER", "mock_s3") or "mock_s3")
    policy = object_storage_policy()
    details = []
    clean_bucket = str(_setting("OBJECT_STORAGE_BUCKET", "") or "").strip()
    quarantine_bucket = str(
        _setting("OBJECT_STORAGE_QUARANTINE_BUCKET", "") or ""
    ).strip()
    if provider == "mock_s3":
        details.append(_detail(WARN, "OBJECT_STORAGE_PROVIDER is mock_s3; replace with real object storage before production."))
    if not clean_bucket:
        details.append(_detail(FAIL, "OBJECT_STORAGE_BUCKET is required."))
    if not quarantine_bucket:
        details.append(
            _detail(FAIL, "OBJECT_STORAGE_QUARANTINE_BUCKET is required.")
        )
    elif quarantine_bucket == clean_bucket:
        details.append(
            _detail(
                FAIL,
                "OBJECT_STORAGE_QUARANTINE_BUCKET must differ from OBJECT_STORAGE_BUCKET.",
            )
        )
    if not policy.get("writes_binary"):
        details.append(_detail(FAIL, "Object storage adapter must support binary writes for production."))
    if provider == "s3" and importlib.util.find_spec("boto3") is None:
        details.append(_detail(FAIL, "boto3 package is required for OBJECT_STORAGE_PROVIDER=s3."))
    s3_placeholders = [
        name
        for name in (
            "OBJECT_STORAGE_ENDPOINT_URL",
            "OBJECT_STORAGE_REGION",
            "OBJECT_STORAGE_ACCESS_KEY_ID",
            "OBJECT_STORAGE_SECRET_ACCESS_KEY",
            "OBJECT_STORAGE_SESSION_TOKEN",
        )
        if _looks_placeholder(_setting(name, ""))
    ]
    if provider == "s3" and s3_placeholders:
        details.append(_detail(FAIL, f"S3 object storage settings still contain placeholders: {', '.join(s3_placeholders)}."))
    return _check(
        "object_storage",
        details,
        ok_message="Object storage adapter settings are present and binary-write capable.",
        metadata={
            "provider": provider,
            "quarantine_bucket_configured": bool(quarantine_bucket),
            "quarantine_bucket_isolated": bool(
                quarantine_bucket and quarantine_bucket != clean_bucket
            ),
            "writes_binary": policy.get("writes_binary"),
            "persistence_state": policy.get("persistence_state"),
            "smoke": "smoke_object_storage --require-binary",
        },
    )


def _check(
    name: str,
    details: list[dict[str, str]],
    *,
    ok_message: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not details:
        details = [_detail(PASS, ok_message)]
    return {
        "name": name,
        "status": _overall_status(details),
        "details": details,
        "metadata": metadata or {},
    }


def _detail(status: str, message: str) -> dict[str, str]:
    return {"status": status, "message": message}


def _overall_status(items: list[dict[str, Any]]) -> str:
    statuses = {str(item.get("status")) for item in items}
    if FAIL in statuses:
        return FAIL
    if WARN in statuses:
        return WARN
    return PASS


def _summary(checks: list[dict[str, Any]]) -> dict[str, int]:
    summary = {PASS: 0, WARN: 0, FAIL: 0}
    for check in checks:
        status = str(check.get("status"))
        if status in summary:
            summary[status] += 1
    return summary


def _setting(name: str, default: Any = "") -> Any:
    return getattr(settings, name, default)


def _runtime_setting(name: str, default: Any = "") -> Any:
    if hasattr(settings, name):
        return getattr(settings, name)
    return os.getenv(name, default)


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _looks_placeholder(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return bool(text) and any(marker in text for marker in PLACEHOLDER_MARKERS)


def _format_exception(exc: Exception) -> str:
    message = " ".join(str(exc).split()) or "no details"
    if len(message) > 180:
        message = f"{message[:177]}..."
    return f"{exc.__class__.__name__}: {message}"
