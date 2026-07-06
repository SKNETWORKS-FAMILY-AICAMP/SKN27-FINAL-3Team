from __future__ import annotations

from etl.fault_cases.src.agents.text_ml_case_search.agent import run_text_ml_case_search
from etl.fault_cases.src.agents.text_ml_case_search.input.context_builder import build_context


class FakeElasticsearch:
    def __init__(self) -> None:
        self.calls = []

    def search(self, *, index, body):
        self.calls.append({"index": index, "body": body})
        if index == "precedent_fault_ratio_chunks_bm25_nori_v1":
            return {
                "hits": {
                    "hits": [
                        {
                            "_index": "precedent_fault_ratio_chunks_bm25_nori_v1",
                            "_score": 31.5,
                            "_source": {
                                "case_id": "616249",
                                "chunk_id": "616249:structured_1500_250:0001",
                                "chunk_type": "fault_ratio_evidence",
                                "case_name": "precedent title",
                                "case_number": "2022da287284",
                                "court_name": "Supreme Court",
                                "decision_date": "2025-05-15",
                                "chunk_text": "valid precedent evidence text " * 5,
                                "search_text": "sample search text",
                            },
                        }
                    ]
                }
            }
        return {
            "hits": {
                "hits": [
                    {
                        "_index": "review_case_chunks_bm25_nori_v1",
                        "_score": 10.1,
                        "_source": {
                            "review_case_id": "rc_001",
                            "review_no": "2017-032889",
                            "chunk_id": "rc_001:case_overview",
                            "chunk_type": "case_overview",
                            "case_title": "sample case",
                            "decision_fault_ratio": "A 70 : B 30",
                            "claimant_final_ratio": "70",
                            "respondent_final_ratio": "30",
                            "chunk_text": "valid review case evidence text " * 4,
                            "search_text": "sample search text",
                        },
                    }
                ]
            }
        }


def test_agent_skeleton_partial_without_rag() -> None:
    result = run_text_ml_case_search(
        {
            "session_id": "s1",
            "message_id": "m1",
            "job_id": "j1",
            "node_code": "text_ml_case_search",
            "query_text": "신호 없는 교차로 직진 차량과 우측 진입 차량 충돌 사고",
            "vision_evidence": None,
            "ocr_evidence": None,
            "insurer_claim": None,
        }
    )

    assert result["node_code"] == "text_ml_case_search"
    assert result["status"] == "partial"
    assert result["evidence"] == []
    assert result["missing_fields"] == []
    assert result["structured_result"]["normalized_description"]
    assert "신호 없는 교차로" in result["structured_result"]["issue_tags"]
    assert result["structured_result"]["recommended_evidence"]


def test_agent_skeleton_failed_without_query_text() -> None:
    result = run_text_ml_case_search(
        {
            "session_id": "s1",
            "message_id": "m1",
            "job_id": "j1",
            "node_code": "text_ml_case_search",
        }
    )

    assert result["status"] == "failed"
    assert "query_text" in result["missing_fields"]


def test_agent_skeleton_builds_insurer_claim_review_without_rag() -> None:
    result = run_text_ml_case_search(
        {
            "session_id": "s1",
            "message_id": "m1",
            "job_id": "j1",
            "node_code": "text_ml_case_search",
            "query_text": "차로변경 중 후행 차량 충돌 사고",
            "insurer_claim": {
                "claimed_ratio": "사용자 70 : 상대 30",
                "reason_text": "보험사는 진로변경 주의의무가 크다고 설명했습니다.",
                "source_text": "보험사는 제 과실을 70이라고 합니다.",
            },
        }
    )

    review = result["structured_result"]["insurer_claim_review"]
    assert result["status"] == "partial"
    assert review is not None
    assert review["claimed_ratio"] == "사용자 70 : 상대 30"
    assert "차로 변경" in result["structured_result"]["issue_tags"]


def test_recommended_evidence_uses_extended_schema() -> None:
    result = run_text_ml_case_search(
        {
            "session_id": "s1",
            "message_id": "m1",
            "job_id": "j1",
            "node_code": "text_ml_case_search",
            "query_text": "차로 변경 중 후행 차량 충돌 사고",
        }
    )

    recommendation = result["structured_result"]["recommended_evidence"][0]
    assert recommendation["type"]
    assert recommendation["title"]
    assert recommendation["description"]
    assert recommendation["related_issue"]
    assert recommendation["priority"] in {"high", "medium", "low"}
    assert isinstance(recommendation["based_on"], list)


def test_source_ref_alias_is_normalized_to_source_reference() -> None:
    context = build_context(
        {
            "session_id": "s1",
            "message_id": "m1",
            "job_id": "j1",
            "node_code": "text_ml_case_search",
            "query_text": "신호 없는 교차로 사고",
            "vision_evidence": [{"source_ref": "att_video_001#00:00:01"}],
            "insurer_claim": {"source_ref": "claim_001", "claimed_ratio": "70:30"},
        }
    )

    assert context["vision_evidence"][0]["source_reference"] == "att_video_001#00:00:01"
    assert "source_ref" not in context["vision_evidence"][0]
    assert context["insurer_claim"]["source_reference"] == "claim_001"
    assert "source_ref" not in context["insurer_claim"]


def test_agent_builds_search_text_variants_without_search_call() -> None:
    result = run_text_ml_case_search(
        {
            "session_id": "s1",
            "message_id": "m1",
            "job_id": "j1",
            "node_code": "text_ml_case_search",
            "query_text": "신호 없는 교차로 직진 차량과 우측 진입 차량 충돌 사고",
            "raw_user_text": "보험사는 사용자 과실이 더 높다고 설명했습니다.",
            "vision_evidence": [
                {
                    "source_reference": "att_video_001#00:00:05-00:00:12",
                    "description": "상대 차량이 우측에서 진입하고 사용자 차량은 직진 중으로 보임",
                    "observations": ["우측 차량 진입", "직진 차량 진행"],
                }
            ],
            "ocr_evidence": {
                "accident_type": "신호 없는 교차로 차량 간 충돌 사고",
                "accident_cause": "우측 차량 우선, 선진입 여부",
            },
            "insurer_claim": {
                "claimed_ratio": "사용자 70 : 상대 30",
                "reason_text": "우측 차량 진입 상황 때문에 사용자 과실이 높다고 설명함",
            },
        }
    )

    search_text = result["structured_result"]["search_text"]
    assert search_text["natural_query_text"]
    assert search_text["schema_search_text"]
    assert search_text["full_optional_context"]
    assert "[사고유형]" in search_text["full_optional_context"]
    assert "[Vision 단서]" in search_text["full_optional_context"]
    assert search_text["input_sections"]["has_vision_evidence"] is True
    assert search_text["input_sections"]["has_ocr_evidence"] is True
    assert search_text["input_sections"]["has_insurer_claim"] is True


def test_agent_uses_retrieval_pipeline_when_es_client_is_provided() -> None:
    fake_es = FakeElasticsearch()

    result = run_text_ml_case_search(
        {
            "session_id": "s1",
            "message_id": "m1",
            "job_id": "j1",
            "node_code": "text_ml_case_search",
            "query_text": "signal intersection crash",
        },
        es_client=fake_es,
    )

    rag_debug = result["structured_result"]["rag_debug"]
    assert len(fake_es.calls) == 2
    assert result["status"] == "success"
    assert len(result["evidence"]) == 2
    assert result["evidence"][0]["source_reference"] == "review_case_db:rc_001#rc_001:case_overview"
    assert result["evidence"][1]["source_reference"] == (
        "fault_ratio_precedent_db:616249#616249:structured_1500_250:0001"
    )
    assert result["structured_result"]["similar_cases"][0]["source_reference"] == "review_case_db:rc_001#rc_001:case_overview"
    assert result["structured_result"]["ratio_range_label"] == "A 70 : B 30"
    assert result["structured_result"]["display_evidence"][0]["source_reference"] == "review_case_db:rc_001#rc_001:case_overview"
    assert result["structured_result"]["display_evidence"][0]["ratio_label"] == "A 70 : B 30"
    assert result["structured_result"]["source_summary"]["source_counts"] == {
        "review_case": 1,
        "fault_ratio_precedent": 1,
    }
    assert rag_debug["retriever"] == "unified_bm25_nori"
    assert rag_debug["source_results"]["review_case"]["valid_evidence_count"] == 1
    assert rag_debug["source_results"]["fault_ratio_precedent"]["valid_evidence_count"] == 1
