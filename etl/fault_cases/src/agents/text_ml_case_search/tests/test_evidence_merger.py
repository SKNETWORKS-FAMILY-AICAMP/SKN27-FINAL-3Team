from __future__ import annotations

from etl.fault_cases.src.agents.text_ml_case_search.rag.evidence_merger import (
    merge_evidence_by_source_quota,
)


def _evidence(source_type: str, reference: str) -> dict:
    return {
        "source_type": source_type,
        "source_reference": reference,
        "metadata": {},
        "chunk_text": "valid evidence text " * 5,
    }


def test_merge_evidence_by_source_quota_keeps_source_balance() -> None:
    result = merge_evidence_by_source_quota(
        review_case_evidence=[
            _evidence("review_case", f"review_case_db:rc_{idx}#chunk")
            for idx in range(1, 7)
        ],
        fault_ratio_precedent_evidence=[
            _evidence("fault_ratio_precedent", f"fault_ratio_precedent_db:pc_{idx}#chunk")
            for idx in range(1, 7)
        ],
    )

    assert result["merge_strategy"] == "source_quota"
    assert result["review_case_quota"] == 5
    assert result["fault_ratio_precedent_quota"] == 5
    assert result["final_top_k"] == 10
    assert result["source_counts"] == {
        "review_case": 5,
        "fault_ratio_precedent": 5,
    }
    assert result["output_count"] == 10
    assert result["evidence"][0]["source_type"] == "review_case"
    assert result["evidence"][5]["source_type"] == "fault_ratio_precedent"


def test_merge_evidence_by_source_quota_deduplicates_source_reference() -> None:
    duplicate = "shared:case#chunk"

    result = merge_evidence_by_source_quota(
        review_case_evidence=[
            _evidence("review_case", duplicate),
            _evidence("review_case", "review_case_db:rc_2#chunk"),
        ],
        fault_ratio_precedent_evidence=[
            _evidence("fault_ratio_precedent", duplicate),
            _evidence("fault_ratio_precedent", "fault_ratio_precedent_db:pc_2#chunk"),
        ],
        review_case_quota=5,
        fault_ratio_precedent_quota=5,
        final_top_k=10,
    )

    references = [item["source_reference"] for item in result["evidence"]]
    assert references.count(duplicate) == 1
    assert result["source_counts"] == {
        "review_case": 2,
        "fault_ratio_precedent": 1,
    }
