from __future__ import annotations

from etl.fault_cases.src.agents.text_ml_case_search.builders.insurer_claim_review_builder import (
    build_insurer_claim_review,
)
from etl.fault_cases.src.agents.text_ml_case_search.builders.ratio_range_builder import (
    build_ratio_range_label,
)
from etl.fault_cases.src.agents.text_ml_case_search.builders.similar_case_builder import (
    build_similar_cases,
)


def _sample_evidence() -> list[dict]:
    return [
        {
            "source_type": "review_case",
            "title": "sample case",
            "source_reference": "review_case_db:rc_001#chunk_001",
            "chunk_text": "This is a long enough chunk text with reference facts and ratio 70:30.",
            "metadata": {
                "case_id": "rc_001",
                "review_case_id": "rc_001",
                "review_no": "2019-000001",
                "chunk_id": "chunk_001",
                "chunk_type": "decision",
                "reference_chart_key": "205",
                "decision_fault_ratio": "A 70 : B 30",
                "claimant_final_ratio": "70",
                "respondent_final_ratio": "30",
                "score": 10.5,
                "score_type": "bm25_score",
                "rank": 1,
                "standard_context": {"signal_condition": "none"},
            },
        }
    ]


def test_build_similar_cases_uses_evidence_metadata() -> None:
    similar_cases = build_similar_cases(evidence=_sample_evidence())

    assert similar_cases[0]["source_type"] == "review_case"
    assert similar_cases[0]["case_id"] == "rc_001"
    assert similar_cases[0]["review_no"] == "2019-000001"
    assert similar_cases[0]["source_reference"] == "review_case_db:rc_001#chunk_001"
    assert similar_cases[0]["decision_fault_ratio"] == "A 70 : B 30"
    assert similar_cases[0]["summary"]


def test_build_ratio_range_label_prefers_decision_fault_ratio() -> None:
    assert build_ratio_range_label(evidence=_sample_evidence()) == "A 70 : B 30"


def test_build_ratio_range_label_uses_regex_fallback() -> None:
    evidence = [
        {
            "chunk_text": "fallback ratio appears as 60:40 in the chunk",
            "metadata": {},
        }
    ]

    assert build_ratio_range_label(evidence=evidence) == "60 : 40"


def test_insurer_claim_review_includes_reference_evidence() -> None:
    review = build_insurer_claim_review(
        insurer_claim={"claimed_ratio": "70:30", "reason_text": "insurer reason"},
        issue_tags=["lane change"],
        evidence=_sample_evidence(),
        ratio_range_label="A 70 : B 30",
    )

    assert review is not None
    assert review["reference_ratio_label"] == "A 70 : B 30"
    assert review["reference_evidence_count"] == 1
    assert review["reference_evidence"][0]["source_reference"] == "review_case_db:rc_001#chunk_001"
