from __future__ import annotations

from etl.fault_cases.src.agents.text_ml_case_search import agent as text_ml_agent
from etl.fault_cases.src.agents.text_ml_case_search.agent import run_text_ml_case_search
from etl.fault_cases.src.agents.text_ml_case_search.input.context_builder import build_context


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


def test_agent_uses_pgvector_pipeline(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_pgvector_pipeline(*, search_text, search_variant):
        calls.append({"search_text": search_text, "search_variant": search_variant})
        return {
            "retriever": "unified_pgvector",
            "requested_search_variant": search_variant,
            "search_variant": "schema_search_text",
            "top_k": 5,
            "final_top_k": 10,
            "active_sources": ["review_case", "fault_ratio_precedent"],
            "standby_sources": ["traffic_precedent"],
            "excluded_sources": ["standard"],
            "source_results": {},
            "merge_result": {
                "merge_strategy": "source_quota",
                "review_case_quota": 5,
                "fault_ratio_precedent_quota": 5,
                "final_top_k": 10,
                "source_counts": {
                    "review_case": 0,
                    "fault_ratio_precedent": 0,
                },
                "input_counts": {
                    "review_case": 0,
                    "fault_ratio_precedent": 0,
                },
                "output_count": 0,
            },
            "source_summary": {
                "active_sources": ["review_case", "fault_ratio_precedent"],
                "source_counts": {
                    "review_case": 0,
                    "fault_ratio_precedent": 0,
                },
            },
            "evidence": [],
        }

    monkeypatch.setattr(
        text_ml_agent,
        "run_unified_pgvector_pipeline",
        fake_pgvector_pipeline,
        raising=False,
    )

    result = text_ml_agent.run_text_ml_case_search(
        {
            "session_id": "s1",
            "message_id": "m1",
            "job_id": "j1",
            "node_code": "text_ml_case_search",
            "query_text": "신호 없는 교차로 직진 차량과 우측 진입 차량 충돌 사고",
        }
    )

    assert len(calls) == 1
    assert result["contract_version"] == "text_ml_case_search_v2"
    assert result["structured_result"]["rag_debug"]["retriever"] == "unified_pgvector"


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
