from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.agent import run_text_ml_case_search


def _base_input(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "session_id": "flow_case_session",
        "message_id": "flow_case_message",
        "job_id": "flow_case_job",
        "node_code": "text_ml_case_search",
        "query_text": "signal intersection crash between straight vehicle and right-side entering vehicle",
        "raw_user_text": "The insurer says my liability is high after a signal intersection crash.",
        "vision_evidence": None,
        "ocr_evidence": None,
        "insurer_claim": None,
    }
    payload.update(overrides)
    return payload


def _insurer_claim() -> dict[str, Any]:
    return {
        "claimed_ratio": "user 70 : opponent 30",
        "reason_text": "The insurer says the right-side entering vehicle issue increases user liability.",
        "source_text": "The insurer explained user 70 and opponent 30.",
        "source_reference": "claim_001",
    }


def _valid_evidence() -> list[dict[str, Any]]:
    return [
        {
            "source_type": "review_case",
            "title": "signal intersection review case",
            "source_reference": "review_case_db:rc_001#chunk_001",
            "chunk_text": (
                "This review case discusses entry timing, collision position, "
                "and right-side vehicle priority at an intersection."
            ),
            "metadata": {
                "case_id": "rc_001",
                "review_case_id": "rc_001",
                "review_no": "2019-000001",
                "chunk_id": "chunk_001",
                "chunk_type": "decision",
                "case_title": "signal intersection review case",
                "reference_chart_key": "249",
                "decision_fault_ratio": "A 70 : B 30",
                "claimant_final_ratio": "70",
                "respondent_final_ratio": "30",
                "score": 13.5,
                "score_type": "bm25_score",
                "rank": 1,
                "highlight": {
                    "chunk_text": ["<em>intersection</em> entry timing"],
                },
            },
        }
    ]


def test_flow_case_0_missing_query_returns_failed_contract() -> None:
    payload = _base_input()
    payload.pop("query_text")

    result = run_text_ml_case_search(payload)

    assert result["status"] == "failed"
    assert "query_text" in result["missing_fields"]
    assert result["evidence"] == []
    assert result["structured_result"]["similar_cases"] == []
    assert result["structured_result"]["ratio_range_label"] == ""
    assert result["structured_result"]["display_evidence"] == []


def test_flow_case_1_no_insurer_claim_and_no_rag_returns_prefill_only() -> None:
    result = run_text_ml_case_search(_base_input(insurer_claim=None))

    structured = result["structured_result"]
    assert result["status"] == "partial"
    assert result["evidence"] == []
    assert structured["similar_cases"] == []
    assert structured["ratio_range_label"] == ""
    assert structured["insurer_claim_review"] is None
    assert structured["recommended_evidence"]
    assert structured["display_evidence"] == []


def test_flow_case_2_no_insurer_claim_with_rag_returns_reference_fields() -> None:
    result = run_text_ml_case_search(
        _base_input(insurer_claim=None),
        mock_evidence=_valid_evidence(),
    )

    structured = result["structured_result"]
    assert result["status"] == "success"
    assert len(result["evidence"]) == 1
    assert structured["similar_cases"]
    assert structured["ratio_range_label"] == "A 70 : B 30"
    assert structured["insurer_claim_review"] is None
    assert structured["display_evidence"][0]["source_reference"] == "review_case_db:rc_001#chunk_001"
    assert structured["display_evidence"][0]["matched_snippets"] == ["intersection entry timing"]


def test_flow_case_3_insurer_claim_without_rag_returns_limited_review() -> None:
    result = run_text_ml_case_search(_base_input(insurer_claim=_insurer_claim()))

    structured = result["structured_result"]
    review = structured["insurer_claim_review"]
    assert result["status"] == "partial"
    assert result["evidence"] == []
    assert structured["similar_cases"] == []
    assert structured["ratio_range_label"] == ""
    assert structured["display_evidence"] == []
    assert review is not None
    assert review["claimed_ratio"] == "user 70 : opponent 30"
    assert review["reference_evidence_count"] == 0
    assert review["reference_evidence"] == []
    assert any("No RAG evidence" in item for item in review["limitations"])


def test_flow_case_4_insurer_claim_with_rag_returns_comparison_materials() -> None:
    result = run_text_ml_case_search(
        _base_input(insurer_claim=_insurer_claim()),
        mock_evidence=_valid_evidence(),
    )

    structured = result["structured_result"]
    review = structured["insurer_claim_review"]
    assert result["status"] == "success"
    assert len(result["evidence"]) == 1
    assert structured["similar_cases"][0]["source_reference"] == "review_case_db:rc_001#chunk_001"
    assert structured["ratio_range_label"] == "A 70 : B 30"
    assert structured["display_evidence"][0]["ratio_label"] == "A 70 : B 30"
    assert review is not None
    assert review["reference_ratio_label"] == "A 70 : B 30"
    assert review["reference_evidence_count"] == 1
    assert review["reference_evidence"][0]["source_reference"] == "review_case_db:rc_001#chunk_001"
