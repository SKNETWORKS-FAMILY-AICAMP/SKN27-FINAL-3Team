from __future__ import annotations

from etl.fault_cases.src.agents.text_ml_case_search.verify_bm25_alignment import (
    _mismatch_positions,
)


def test_mismatch_positions_returns_empty_when_chunk_ids_match() -> None:
    assert (
        _mismatch_positions(
            legacy_chunk_ids=["a", "b", "c"],
            agent_chunk_ids=["a", "b", "c"],
        )
        == []
    )


def test_mismatch_positions_reports_rank_and_values() -> None:
    assert _mismatch_positions(
        legacy_chunk_ids=["a", "b", "c"],
        agent_chunk_ids=["a", "x"],
    ) == [
        {"rank": 2, "legacy_chunk_id": "b", "agent_chunk_id": "x"},
        {"rank": 3, "legacy_chunk_id": "c", "agent_chunk_id": None},
    ]
