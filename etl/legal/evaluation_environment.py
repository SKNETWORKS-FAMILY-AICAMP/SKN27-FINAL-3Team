"""Evaluation-only environment loading and validation for legal RAG A/B runs."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path


REQUIRED_KEYS = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "LEGAL_RAG_VECTOR_ENABLED",
    "LEGAL_RAG_QUERY_EMBEDDING_PROVIDER",
    "LEGAL_RAG_QUERY_EMBEDDING_MODEL",
    "LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS",
    "LEGAL_RAG_SEED_EMBEDDING_PROVIDER",
    "LEGAL_RAG_SEED_EMBEDDING_MODEL",
    "LEGAL_RAG_SEED_EMBEDDING_DIMENSIONS",
)


def load_evaluation_environment(path: Path) -> dict[str, str]:
    """Read an explicit local evaluation env file without changing process state."""

    if not path.is_file():
        raise FileNotFoundError(f"evaluation environment file not found: {path}")
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid evaluation environment line: {line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"invalid evaluation environment key: {line_number}")
        values[key] = value.strip()
    return values


def validate_evaluation_environment(values: Mapping[str, str]) -> dict[str, object]:
    """Return a sanitized readiness result; secrets never leave this function."""

    missing = [key for key in REQUIRED_KEYS if not str(values.get(key, "")).strip()]
    if str(values.get("LEGAL_RAG_VECTOR_ENABLED", "")).strip() != "1":
        missing.append("LEGAL_RAG_VECTOR_ENABLED")
    missing = sorted(set(missing))
    if missing:
        return _not_ready("required_variables_missing", missing, values)

    query_space = _embedding_space(values, "LEGAL_RAG_QUERY_EMBEDDING")
    seed_space = _embedding_space(values, "LEGAL_RAG_SEED_EMBEDDING")
    if query_space["dimensions"] != 1024 or seed_space["dimensions"] != 1024:
        return _not_ready("embedding_dimensions_not_1024", [], values, query_space, seed_space)
    if query_space != seed_space:
        return _not_ready("embedding_space_mismatch", [], values, query_space, seed_space)
    return {
        "status": "ready",
        "reason": "",
        "missing": [],
        "postgres": _postgres_metadata(values),
        "query_embedding_space": query_space,
        "seed_embedding_space": seed_space,
        "openai_available": bool(str(values.get("OPENAI_API_KEY", "")).strip()),
        "law_provider_available": bool(
            str(values.get("LAW_GO_KR_OC", "")).strip()
            or str(values.get("LAW_API_KEY", "")).strip()
        ),
    }


def apply_evaluation_environment(values: Mapping[str, str]) -> None:
    """Apply an already-read local evaluation environment to this process only."""

    for key, value in values.items():
        os.environ[key] = value


def _not_ready(
    reason: str,
    missing: list[str],
    values: Mapping[str, str],
    query_space: dict[str, object] | None = None,
    seed_space: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "status": "not_ready",
        "reason": reason,
        "missing": missing,
        "postgres": _postgres_metadata(values),
        "query_embedding_space": query_space or _embedding_space(values, "LEGAL_RAG_QUERY_EMBEDDING"),
        "seed_embedding_space": seed_space or _embedding_space(values, "LEGAL_RAG_SEED_EMBEDDING"),
        "openai_available": bool(str(values.get("OPENAI_API_KEY", "")).strip()),
        "law_provider_available": bool(
            str(values.get("LAW_GO_KR_OC", "")).strip()
            or str(values.get("LAW_API_KEY", "")).strip()
        ),
    }


def _embedding_space(values: Mapping[str, str], prefix: str) -> dict[str, object]:
    dimensions = _int_or_zero(values.get(f"{prefix}_DIMENSIONS", ""))
    return {
        "provider": str(values.get(f"{prefix}_PROVIDER", "")).strip().lower(),
        "model": str(values.get(f"{prefix}_MODEL", "")).strip(),
        "dimensions": dimensions,
    }


def _postgres_metadata(values: Mapping[str, str]) -> dict[str, str]:
    return {
        "host": str(values.get("POSTGRES_HOST", "")).strip(),
        "port": str(values.get("POSTGRES_PORT", "")).strip(),
        "database": str(values.get("POSTGRES_DB", "")).strip(),
        "user": str(values.get("POSTGRES_USER", "")).strip(),
    }


def _int_or_zero(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
