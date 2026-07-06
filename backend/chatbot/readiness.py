"""Production readiness checks for the canonical Django runtime."""

from __future__ import annotations

import importlib.util
import os
from typing import Any

from django.conf import settings
from django.db import connection

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
    if bool(_setting("GOOGLE_AUTH_ALLOW_MOCK", True)):
        details.append(_detail(FAIL, "GOOGLE_AUTH_ALLOW_MOCK must be 0 for production."))
    if bool(_setting("APP_AUTH_ALLOW_MOCK_BEARER", True)):
        details.append(_detail(FAIL, "APP_AUTH_ALLOW_MOCK_BEARER must be 0 for production."))

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

    app_jwt_secret = str(_setting("APP_JWT_SECRET", ""))
    oauth_secret = str(_setting("OAUTH_TOKEN_SECRET", ""))
    if not app_jwt_secret or app_jwt_secret == DEV_SECRET_KEY or len(app_jwt_secret) < 32 or _looks_placeholder(app_jwt_secret):
        details.append(_detail(FAIL, "APP_JWT_SECRET must be a non-default secret with at least 32 characters."))
    if not oauth_secret or oauth_secret == DEV_SECRET_KEY or len(oauth_secret) < 32 or _looks_placeholder(oauth_secret):
        details.append(_detail(FAIL, "OAUTH_TOKEN_SECRET must be a non-default secret with at least 32 characters."))

    return _check(
        "google_oauth",
        details,
        ok_message="Google Authorization Code Flow is configured for non-mock mode.",
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
            "mock_off_smoke": "smoke_supervisor_llm --require-used --require-slot-state",
        },
    )


def _legal_rag_check(*, include_database: bool, database_state: dict[str, Any]) -> dict[str, Any]:
    details = []
    enabled = bool(_setting("LEGAL_RAG_VECTOR_ENABLED", False))
    provider = str(_setting("LEGAL_RAG_QUERY_EMBEDDING_PROVIDER", "") or "")
    model = str(_setting("LEGAL_RAG_QUERY_EMBEDDING_MODEL", "") or "")
    introspection_error = str(database_state.get("error") or "")

    if not enabled:
        details.append(_detail(WARN, "Legal RAG vector search is disabled; Django lexical fallback remains active."))
    else:
        if provider not in {"sentence-transformers", "openai", "hash"}:
            details.append(_detail(FAIL, f"Unsupported LEGAL_RAG_QUERY_EMBEDDING_PROVIDER: {provider}."))
        if provider in {"sentence-transformers", "openai"} and not model:
            details.append(_detail(FAIL, "LEGAL_RAG_QUERY_EMBEDDING_MODEL is required for vector search."))
        if provider == "sentence-transformers" and importlib.util.find_spec("sentence_transformers") is None:
            details.append(_detail(FAIL, "sentence-transformers package is not installed in the runtime."))
        legal_rag_openai_key = str(_setting("LEGAL_RAG_OPENAI_API_KEY", "") or "")
        if provider == "openai" and (not legal_rag_openai_key.strip() or _looks_placeholder(legal_rag_openai_key)):
            details.append(_detail(FAIL, "LEGAL_RAG_OPENAI_API_KEY or OPENAI_API_KEY is required for OpenAI embeddings."))
        if include_database:
            if introspection_error:
                details.append(
                    _detail(
                        FAIL,
                        f"Cannot verify pgvector RAG tables because database introspection failed: {introspection_error}",
                    )
                )
            else:
                table_names = set(database_state.get("table_names") or set())
                missing = [table for table in ("law_chunks", "law_embeddings") if table not in table_names]
                if missing:
                    details.append(_detail(FAIL, f"Missing pgvector RAG tables: {', '.join(missing)}."))

    return _check(
        "legal_rag",
        details,
        ok_message="Legal RAG vector search is configured.",
        metadata={"vector_enabled": enabled, "embedding_provider": provider or None, "embedding_model": model or None},
    )


def _text_ml_case_search_rag_check() -> dict[str, Any]:
    details = []
    enabled = _truthy(_runtime_setting("TEXT_ML_CASE_SEARCH_SYNC_USE_ES", ""))
    host = str(
        _runtime_setting(
            "TEXT_ML_CASE_SEARCH_ELASTICSEARCH_HOST",
            _runtime_setting("ELASTICSEARCH_HOST", "http://localhost:9200"),
        )
        or ""
    )
    user = str(
        _runtime_setting(
            "TEXT_ML_CASE_SEARCH_ELASTICSEARCH_USER",
            _runtime_setting("ELASTICSEARCH_USER", "elastic"),
        )
        or ""
    )
    password = str(
        _runtime_setting(
            "TEXT_ML_CASE_SEARCH_ELASTICSEARCH_PASSWORD",
            _runtime_setting("ELASTIC_PASSWORD", ""),
        )
        or ""
    )
    review_case_index = str(
        _runtime_setting("REVIEW_CASE_ES_BM25_INDEX", "review_case_chunks_bm25_nori_v1") or ""
    )
    fault_ratio_index = str(
        _runtime_setting("FAULT_RATIO_PRECEDENT_ES_BM25_INDEX", "precedent_fault_ratio_chunks_bm25_nori_v1") or ""
    )

    if not enabled:
        details.append(
            _detail(
                WARN,
                "TEXT_ML_CASE_SEARCH_SYNC_USE_ES is disabled; text_ml_case_search will use safe non-ES fallback.",
            )
        )
    else:
        if not host.strip():
            details.append(_detail(FAIL, "TEXT_ML_CASE_SEARCH_ELASTICSEARCH_HOST is required when ES RAG is enabled."))
        if _looks_placeholder(host):
            details.append(_detail(FAIL, "TEXT_ML_CASE_SEARCH_ELASTICSEARCH_HOST must not contain a placeholder."))
        if user.strip() and not password.strip():
            details.append(_detail(FAIL, "TEXT_ML_CASE_SEARCH_ELASTICSEARCH_PASSWORD is required when an Elasticsearch user is set."))
        if password and _looks_placeholder(password):
            details.append(_detail(FAIL, "TEXT_ML_CASE_SEARCH_ELASTICSEARCH_PASSWORD must not contain a placeholder."))
        missing_indexes = [
            name
            for name, value in {
                "REVIEW_CASE_ES_BM25_INDEX": review_case_index,
                "FAULT_RATIO_PRECEDENT_ES_BM25_INDEX": fault_ratio_index,
            }.items()
            if not value.strip()
        ]
        if missing_indexes:
            details.append(_detail(FAIL, f"Missing text ML Elasticsearch index settings: {', '.join(missing_indexes)}."))
        if importlib.util.find_spec("elasticsearch") is None:
            details.append(_detail(FAIL, "elasticsearch package is required when text_ml_case_search ES RAG is enabled."))

    return _check(
        "text_ml_case_search_rag",
        details,
        ok_message="text_ml_case_search Elasticsearch RAG settings are present.",
        metadata={
            "sync_use_es": enabled,
            "host": host or None,
            "user_set": bool(user.strip()),
            "review_case_index": review_case_index or None,
            "fault_ratio_precedent_index": fault_ratio_index or None,
            "smoke": "smoke_text_ml_case_search --require-es",
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
    if max_bytes <= 0:
        details.append(_detail(FAIL, "FILE_SCAN_MAX_BYTES must be a positive integer."))
    if timeout_seconds <= 0:
        details.append(_detail(FAIL, "FILE_SCAN_TIMEOUT_SECONDS must be a positive integer."))
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
            "smoke": "smoke_file_scan --require-clean",
        },
    )


def _object_storage_check() -> dict[str, Any]:
    provider = str(_setting("OBJECT_STORAGE_PROVIDER", "mock_s3") or "mock_s3")
    policy = object_storage_policy()
    details = []
    if provider == "mock_s3":
        details.append(_detail(WARN, "OBJECT_STORAGE_PROVIDER is mock_s3; replace with real object storage before production."))
    if not str(_setting("OBJECT_STORAGE_BUCKET", "") or "").strip():
        details.append(_detail(FAIL, "OBJECT_STORAGE_BUCKET is required."))
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
