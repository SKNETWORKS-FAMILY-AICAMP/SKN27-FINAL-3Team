from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from etl.fault_cases.src.traffic_precedents.precedent_search.pgvector.retriever import (
    search_query,
)


REQUIRED_ROW_KEYS = {
    "case_id",
    "case_number",
    "chunk_id",
    "chunk_index",
    "chunk_type",
    "chunk_strategy",
    "case_name",
    "court_name",
    "decision_date",
    "chunk_text",
    "search_text",
    "cosine_similarity",
    "rank",
    "metadata",
}


def assert_agent_row_contract(row: dict[str, Any]) -> None:
    assert REQUIRED_ROW_KEYS <= row.keys()


def test_search_query_signature_is_stable() -> None:
    assert list(inspect.signature(search_query).parameters) == [
        "dataset",
        "query",
        "top_k",
    ]


def test_active_code_does_not_import_old() -> None:
    active_root = Path(__file__).parents[1]
    for path in active_root.rglob("*.py"):
        if "old" in path.parts or "tests" in path.parts:
            continue
        assert "traffic_precedents.old" not in path.read_text(encoding="utf-8")
