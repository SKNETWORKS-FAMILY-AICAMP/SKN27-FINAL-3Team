from __future__ import annotations

from app.services.supervisor_control_service import (
    evaluate_case_promotion,
    merge_final_response,
    reduce_consultation_fact_state,
    validate_agent_results,
)
from app.services.supervisor_routing_service import agent_result_validation_policy


def test_agent_result_validation_rules_are_loaded_from_the_versioned_policy() -> None:
    policy = agent_result_validation_policy()

    assert "law_ground_search" in policy["evidence_required_node_codes"]
    assert policy["report_required_nodes"]["fine_notice_analysis"] == {
        "fine_notice_analysis",
        "law_ground_search",
        "appeal_decision_flow",
    }


def test_fact_reducer_maps_followup_answer_to_the_questioned_field() -> None:
    reduced = reduce_consultation_fact_state(
        {
            "session_id": "ses_followup",
            "conversation_history": [
                {"role": "user", "content": "사고 과실을 상담하고 싶어요."},
                {"role": "assistant", "content": "사고 장소의 도로 형태를 알려주세요."},
                {"role": "user", "content": "신호등이 있는 사거리 교차로입니다."},
            ],
        }
    )

    assert reduced["facts"]["road_layout"]["value"] == "신호등이 있는 사거리 교차로입니다."
    assert reduced["facts"]["road_layout"]["source_message_id"] == "history:2"
    assert reduced["facts"]["road_layout"]["confirmed"] is True
    assert "road_layout" not in reduced["missing_fields"]


def test_fact_reducer_preserves_conflicting_values_for_user_confirmation() -> None:
    reduced = reduce_consultation_fact_state(
        {
            "facts": {"road_layout": "교차로"},
            "conversation_history": [
                {"role": "assistant", "content": "사고 장소의 도로 형태를 알려주세요."},
                {"role": "user", "content": "직선 도로였습니다."},
            ],
        }
    )

    assert reduced["facts"]["road_layout"]["value"] == "교차로"
    assert reduced["conflicts"] == [
        {
            "field": "road_layout",
            "existing_value": "교차로",
            "candidate_value": "직선 도로였습니다.",
            "candidate_source_message_id": "history:1",
        }
    ]


def test_fact_reducer_accepts_unconfirmed_llm_candidates_without_treating_them_as_confirmed() -> None:
    reduced = reduce_consultation_fact_state(
        {
            "fact_candidates": [
                {
                    "field": "signal_priority",
                    "value": "직진 녹색 신호",
                    "confidence": 0.86,
                    "source_message_id": "msg_initial",
                }
            ]
        }
    )

    assert reduced["facts"]["signal_priority"] == {
        "field": "signal_priority",
        "value": "직진 녹색 신호",
        "source_message_id": "msg_initial",
        "confidence": 0.86,
        "confirmed": False,
    }


def test_case_promotion_gate_never_promotes_high_risk_or_incomplete_intake() -> None:
    high_risk = evaluate_case_promotion(
        {
            "risk_gate": {"level": "high_risk"},
            "readiness": {"missing_fields": []},
        },
        analysis_requested=True,
        authenticated=True,
        storage_consent=True,
    )
    incomplete = evaluate_case_promotion(
        {
            "risk_gate": {"level": "standard"},
            "readiness": {"missing_fields": ["signal_priority"]},
        },
        analysis_requested=True,
        authenticated=True,
        storage_consent=True,
    )

    assert high_risk["decision"] == "expert_handoff"
    assert incomplete["decision"] == "ask_more"


def test_case_promotion_gate_exposes_case_requirements_without_creating_a_case() -> None:
    result = evaluate_case_promotion(
        {
            "risk_gate": {"level": "standard"},
            "readiness": {"missing_fields": [], "ready_for_fault_range": True},
        },
        analysis_requested=True,
        authenticated=False,
        storage_consent=False,
        facts_confirmed=False,
    )

    assert result["decision"] == "ready_for_case"
    assert result["automatic_case_creation"] is False
    assert result["requirements"] == [
        "fact_confirmation",
        "authentication",
        "case_storage_consent",
    ]


def test_agent_result_validation_rejects_success_without_required_evidence() -> None:
    result = validate_agent_results(
        {
            "law_ground_search": {
                "status": "success",
                "summary": "근거를 찾았습니다.",
                "structured_result": {"matched_laws": []},
                "evidence": [],
                "limitations": [],
            }
        },
        routing_intent="traffic_law_search",
        expected_node_codes=["law_ground_search"],
        report_requested=False,
    )

    assert result["merge_ready"] is False
    assert result["report_ready"] is False
    assert result["accepted_results"] == []
    assert result["rejected_results"][0]["reason"] == "required_evidence_missing"


def test_final_response_merge_uses_only_validation_accepted_results() -> None:
    merged = merge_final_response(
        {
            "law_ground_search": {
                "status": "success",
                "summary": "도로교통법 근거 후보를 확인했습니다.",
                "structured_result": {"matched_laws": [{"law_name": "도로교통법"}]},
                "evidence": [{"source_reference": "law:1"}],
                "limitations": ["사건별 적용 여부를 확인해야 합니다."],
            },
            "fine_notice_analysis": {
                "status": "success",
                "summary": "이 문장은 검증에서 거절됐으므로 노출되면 안 됩니다.",
                "structured_result": {},
                "evidence": [],
                "limitations": [],
            },
            "agent_result_validation": {
                "status": "partial",
                "structured_result": {
                    "merge_ready": True,
                    "report_ready": False,
                    "accepted_results": ["law_ground_search"],
                    "rejected_results": [
                        {"node_code": "fine_notice_analysis", "reason": "required_evidence_missing"}
                    ],
                    "missing_fields": [],
                    "limitations": [],
                },
            },
        },
        pending_questions=[],
    )

    assert merged["assistant_message"]["answer"] == "도로교통법 근거 후보를 확인했습니다."
    assert "노출되면 안 됩니다" not in str(merged)
    assert merged["evidence"] == [{"source_reference": "law:1"}]
