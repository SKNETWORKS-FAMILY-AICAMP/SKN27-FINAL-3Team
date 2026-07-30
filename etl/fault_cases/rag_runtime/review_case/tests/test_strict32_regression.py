from __future__ import annotations

import json
from pathlib import Path

from etl.fault_cases.rag_runtime.review_case.reranker import (
    rerank_with_scores,
)


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "strict32_reranker_contract.json"
)


def test_frozen_strict32_scores_reproduce_bge_order() -> None:
    contract = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert contract["contract_version"] == (
        "review_case_strict32_bge_v1"
    )
    assert contract["metrics"] == {
        "query_count": 32,
        "candidate_count_per_query": 5,
        "first_stage_hit_at_1_count": 20,
        "reranker_hit_at_1_count": 24,
        "reranker_recall_at_5_count": 32,
    }
    assert len(contract["queries"]) == 32

    first_stage_hit_at_1_count = 0
    reranker_hit_at_1_count = 0
    reranker_recall_at_5_count = 0

    for query in contract["queries"]:
        relevant_ids = set(query["approved_relevant_case_ids"])
        candidates = [
            {
                "document_id": row["review_case_id"],
                "rank": row["first_stage_rank"],
                "cosine_similarity": row["first_stage_score"],
                "metadata": {
                    "review_case_id": row["review_case_id"],
                },
            }
            for row in query["candidates"]
        ]
        scores = [
            row["reranker_score"]
            for row in query["candidates"]
        ]
        reproduced = rerank_with_scores(candidates, scores)
        expected = sorted(
            query["candidates"],
            key=lambda row: row["expected_rank"],
        )

        assert {
            row["document_id"] for row in reproduced
        } == {
            row["review_case_id"] for row in query["candidates"]
        }
        assert [
            row["document_id"] for row in reproduced
        ] == [
            row["review_case_id"] for row in expected
        ]
        first_stage = sorted(
            query["candidates"],
            key=lambda row: row["first_stage_rank"],
        )
        first_stage_hit_at_1_count += (
            first_stage[0]["review_case_id"] in relevant_ids
        )
        reranker_hit_at_1_count += (
            reproduced[0]["document_id"] in relevant_ids
        )
        reranker_recall_at_5_count += bool(
            {row["document_id"] for row in reproduced}
            & relevant_ids
        )

    assert first_stage_hit_at_1_count == 20
    assert reranker_hit_at_1_count == 24
    assert reranker_recall_at_5_count == 32
