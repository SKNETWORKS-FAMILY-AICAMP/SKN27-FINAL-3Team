from __future__ import annotations

from etl.fault_cases.src.traffic_precedents.precedent_search.newplusplus.result_adapter import (
    to_agent_row,
)
from etl.fault_cases.src.traffic_precedents.precedent_search.pgvector import retriever
from etl.fault_cases.src.traffic_precedents.tests.test_agent_connection_contract import (
    assert_agent_row_contract,
)


def test_newplusplus_result_adapts_to_existing_agent_row() -> None:
    row = to_agent_row(
        {
            "record_id": "1",
            "case_number": "2024다1",
            "case_name": "손해배상",
            "court_name": "대법원",
            "decision_date": "20240101",
            "candidate_block_id": "b1",
            "candidate_block_type": "ACCIDENT_FACT",
            "evidence_text": "사고 사실",
            "retrieval_score": 0.8,
            "rerank_score": 7.5,
            "candidate_rank": 3,
        },
        rank=1,
    )
    assert_agent_row_contract(row)
    assert row["metadata"]["rerank_score"] == 7.5


def test_public_search_query_runs_newplusplus_behind_stable_contract(
    monkeypatch,
) -> None:
    candidate = {
        "record_id": "1",
        "case_number": "2024다1",
        "case_name": "손해배상",
        "court_name": "대법원",
        "decision_date": "20240101",
        "candidate_block_id": "b1",
        "candidate_block_type": "ACCIDENT_FACT",
        "evidence_text": "사고 사실",
        "retrieval_score": 0.8,
        "rerank_score": 7.5,
        "candidate_rank": 1,
    }

    class FakeService:
        def rank(self, request):
            assert request["query_text"] == "교차로 사고"
            return {"ranked_candidates": [candidate]}

    monkeypatch.setattr(retriever, "_service", lambda: FakeService())
    rows = retriever.search_query("fault_ratio", "교차로 사고", 1)
    assert len(rows) == 1
    assert_agent_row_contract(rows[0])
