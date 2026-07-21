"""Deterministic, public-law-only legal RAG evaluation helpers."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Sequence


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


def normalize_backend_response(
    query_id: str,
    response: Mapping[str, object],
) -> dict[str, Any]:
    """Keep only reproducible, non-sensitive candidate metadata for one backend."""

    raw_results = response.get("results")
    results = raw_results if isinstance(raw_results, list) else []
    normalized_results = [
        _normalize_candidate(result, rank)
        for rank, result in enumerate(results, start=1)
        if isinstance(result, Mapping)
    ]
    return {
        "query_id": query_id,
        "backend": _text(response.get("backend")),
        "status": _text(response.get("status")),
        "latency_ms": _nonnegative_int(response.get("latency_ms")),
        "error_code": _text(response.get("error_code")),
        "result_count": len(normalized_results),
        "results": normalized_results,
    }


def summarize_backend_runs(
    runs: Sequence[Mapping[str, object]],
    queries: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, Any]]:
    """Calculate deterministic retrieval metrics by backend without raw law text."""

    expected_by_query = {
        _text(query.get("query_id")): {
            item.strip()
            for item in query.get("expected_source_references", [])
            if isinstance(item, str) and item.strip()
        }
        for query in queries
        if _text(query.get("query_id"))
    }
    by_backend: dict[str, list[Mapping[str, object]]] = {}
    for run in runs:
        backend = _text(run.get("backend"))
        query_id = _text(run.get("query_id"))
        if backend and query_id in expected_by_query:
            by_backend.setdefault(backend, []).append(run)

    return {
        backend: _summarize_single_backend(backend_runs, expected_by_query)
        for backend, backend_runs in sorted(by_backend.items())
    }


def candidate_reference(result: Mapping[str, object]) -> str:
    """Return a stable citation identity instead of the mutable ingestion chunk id."""

    return f"{_text(result.get('source_name'))}|{_text(result.get('article'))}"


def _normalize_candidate(result: Mapping[str, object], rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "source_reference": _text(result.get("source_reference")),
        "source_name": _text(result.get("source_name")),
        "article": _text(result.get("article")),
        "source_type": _text(result.get("source_type")),
        "source_url": _text(result.get("source_url")),
        "effective_date": _optional_text(result.get("effective_date")),
        "expire_date": _optional_text(result.get("expire_date")),
        "score": _number_or_none(result.get("score")),
    }


def _summarize_single_backend(
    runs: Sequence[Mapping[str, object]],
    expected_by_query: Mapping[str, set[str]],
) -> dict[str, Any]:
    run_by_query = {_text(run.get("query_id")): run for run in runs}
    recall_at: dict[int, list[float]] = {1: [], 3: [], 5: []}
    reciprocal_ranks: list[float] = []
    ndcg_scores: list[float] = []
    latencies: list[int] = []
    empty_count = 0
    unavailable_count = 0
    candidate_count = 0
    complete_metadata_count = 0

    for query_id, expected in expected_by_query.items():
        run = run_by_query.get(query_id, {})
        status = _text(run.get("status"))
        results = run.get("results") if isinstance(run.get("results"), list) else []
        if status == "unavailable":
            unavailable_count += 1
        if not results:
            empty_count += 1
        if run:
            latencies.append(_nonnegative_int(run.get("latency_ms")))

        ranked_relevance = [
            candidate_reference(result) in expected
            for result in results
            if isinstance(result, Mapping)
        ]
        for top_k in recall_at:
            recall_at[top_k].append(float(any(ranked_relevance[:top_k])))
        reciprocal_ranks.append(_reciprocal_rank(ranked_relevance))
        ndcg_scores.append(_binary_ndcg_at_five(ranked_relevance))
        for result in results:
            if isinstance(result, Mapping):
                candidate_count += 1
                complete_metadata_count += int(_has_complete_metadata(result))

    total_queries = len(expected_by_query)
    return {
        "query_count": total_queries,
        "completed_run_count": len(run_by_query),
        "recall_at_1": _mean(recall_at[1]),
        "recall_at_3": _mean(recall_at[3]),
        "recall_at_5": _mean(recall_at[5]),
        "mrr": _mean(reciprocal_ranks),
        "ndcg_at_5": _mean(ndcg_scores),
        "no_result_rate": _ratio(empty_count, total_queries),
        "unavailable_rate": _ratio(unavailable_count, total_queries),
        "p50_latency_ms": _percentile(latencies, 0.50),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "metadata_complete_rate": _ratio(complete_metadata_count, candidate_count),
    }


def _reciprocal_rank(ranked_relevance: Sequence[bool]) -> float:
    for rank, relevant in enumerate(ranked_relevance, start=1):
        if relevant:
            return 1.0 / rank
    return 0.0


def _binary_ndcg_at_five(ranked_relevance: Sequence[bool]) -> float:
    for rank, relevant in enumerate(ranked_relevance[:5], start=1):
        if relevant:
            return 1.0 / math.log2(rank + 1)
    return 0.0


def _has_complete_metadata(result: Mapping[str, object]) -> bool:
    return all(
        _text(result.get(key))
        for key in ("source_reference", "source_name", "article", "source_url", "effective_date")
    )


def _percentile(values: Sequence[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * fraction) - 1]


def _mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_text(value: object) -> str | None:
    text = _text(value)
    return text or None


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _number_or_none(value: object) -> float | None:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None
