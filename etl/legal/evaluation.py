"""Deterministic, public-law-only legal RAG evaluation helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


MINIMUM_PUBLIC_LAW_QUERY_COUNT = 20
REQUIRED_QUERY_FIELDS = frozenset(
    {
        "query_id",
        "query",
        "temporal_basis",
        "scope",
        "expected_source_references",
        "reference_answer",
        "scenario",
        "data_classification",
    }
)


def load_public_law_queries(path: Path) -> list[dict[str, Any]]:
    """Load a checked-in evaluation fixture containing only public-law prompts."""

    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid public-law fixture JSON: {path}") from exc
    if not isinstance(rows, list):
        raise ValueError("public-law fixture must be a JSON array")
    if len(rows) < MINIMUM_PUBLIC_LAW_QUERY_COUNT:
        raise ValueError(
            f"public-law fixture must contain at least {MINIMUM_PUBLIC_LAW_QUERY_COUNT} rows"
        )

    normalized = [validate_public_law_query(row) for row in rows]
    query_ids = [row["query_id"] for row in normalized]
    if len(query_ids) != len(set(query_ids)):
        raise ValueError("public-law fixture query_id values must be unique")
    return normalized


def validate_public_law_query(row: Mapping[str, object]) -> dict[str, Any]:
    """Validate the fixed, public-only inputs accepted by the evaluator."""

    if row.get("data_classification") != "public_law":
        raise ValueError("data_classification must be public_law")
    missing = sorted(REQUIRED_QUERY_FIELDS - set(row))
    if missing:
        raise ValueError(f"public-law query is missing required fields: {', '.join(missing)}")

    query_id = _required_text(row, "query_id")
    query = _required_text(row, "query")
    reference_answer = _required_text(row, "reference_answer")
    scenario = _required_text(row, "scenario")
    temporal_basis = row["temporal_basis"]
    scope = row["scope"]
    expected = row["expected_source_references"]
    if not isinstance(temporal_basis, dict) or not temporal_basis:
        raise ValueError("temporal_basis must be a non-empty object")
    if not isinstance(scope, dict) or not scope:
        raise ValueError("scope must be a non-empty object")
    if not isinstance(expected, list) or not expected or not all(
        isinstance(item, str) and item.strip() for item in expected
    ):
        raise ValueError("expected_source_references must be a non-empty string array")

    return {
        "query_id": query_id,
        "query": query,
        "temporal_basis": dict(temporal_basis),
        "scope": dict(scope),
        "expected_source_references": [item.strip() for item in expected],
        "reference_answer": reference_answer,
        "scenario": scenario,
        "data_classification": "public_law",
    }


def _required_text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()
