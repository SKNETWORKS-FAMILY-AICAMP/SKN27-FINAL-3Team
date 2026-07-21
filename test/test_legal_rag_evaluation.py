from __future__ import annotations

import json
from pathlib import Path

import pytest

from etl.legal import evaluation


def test_load_public_law_queries_requires_twenty_public_law_rows(tmp_path: Path) -> None:
    fixture = tmp_path / "queries.json"
    fixture.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="at least 20"):
        evaluation.load_public_law_queries(fixture)


def test_validate_public_law_query_rejects_non_public_classification() -> None:
    with pytest.raises(ValueError, match="data_classification"):
        evaluation.validate_public_law_query(
            {
                "query_id": "law-q001",
                "data_classification": "ocr",
            }
        )


def test_load_public_law_queries_reads_valid_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "queries.json"
    query = {
        "query_id": "law-q001",
        "query": "신호 지시를 따라야 하는 근거는 무엇인가?",
        "temporal_basis": {"mode": "as_of", "effective_at": "2026-07-21"},
        "scope": {"allowed_source_types": ["law"]},
        "expected_source_references": ["도로교통법|제5조"],
        "reference_answer": "도로교통법 제5조를 확인한다.",
        "scenario": "신호 지시 준수",
        "data_classification": "public_law",
    }
    fixture.write_text(
        json.dumps(
            [{**query, "query_id": f"law-q{index:03d}"} for index in range(1, 21)],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = evaluation.load_public_law_queries(fixture)

    assert len(loaded) == 20
    assert loaded[0]["query_id"] == "law-q001"
