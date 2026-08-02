from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from app.services.supervisor_control_service import (
    evaluate_case_promotion,
    merge_final_response,
    reduce_consultation_fact_state,
    validate_agent_results,
)
from app.services.supervisor_routing_service import agent_result_validation_policy
from app.services.fine_notice_intake_service import FINE_NOTICE_QUESTIONS


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
            "candidates": [
                {
                    "value": "교차로",
                    "source_message_id": "payload:facts",
                    "confidence": 1.0,
                },
                {
                    "value": "직선 도로였습니다.",
                    "source_message_id": "history:1",
                    "confidence": 1.0,
                },
            ],
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


def test_fact_reducer_does_not_conflict_on_confirmed_answer_sentence_ending() -> None:
    reduced = reduce_consultation_fact_state(
        {
            "fact_candidates": [
                {
                    "field": "road_layout",
                    "value": "왕복 4차선이고 신호등이 있는 사거리",
                    "confidence": 0.0,
                    "source_message_id": "msg_followup",
                }
            ],
            "conversation_history": [
                {"role": "assistant", "content": "사고 장소의 도로 형태를 알려주세요."},
                {"role": "user", "content": "왕복 4차선이고 신호등이 있는 사거리였습니다."},
            ],
        }
    )

    assert reduced["conflicts"] == []
    assert reduced["facts"]["road_layout"] == {
        "field": "road_layout",
        "value": "왕복 4차선이고 신호등이 있는 사거리였습니다.",
        "source_message_id": "history:1",
        "confidence": 1.0,
        "confirmed": True,
    }
    assert "road_layout" not in reduced["missing_fields"]


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
                "structured_result": {
                    "matched_laws": [
                        {
                            "law_name": "도로교통법",
                            "article": "제160조",
                            "source_reference": "law:verified",
                        }
                    ]
                },
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


def test_fine_notice_procedure_without_verified_results_still_gives_safe_next_steps() -> None:
    merged = merge_final_response(
        {
            "agent_result_validation": {
                "status": "partial",
                "structured_result": {
                    "merge_ready": False,
                    "report_ready": False,
                    "accepted_results": [],
                    "rejected_results": [
                        {
                            "node_code": "law_ground_search",
                            "reason": "required_evidence_missing",
                        }
                    ],
                    "missing_fields": [],
                    "limitations": [],
                },
            },
        },
        routing_intent="fine_notice_procedure",
        user_text="어린이보호구역에서 응급상황 때문에 잠깐 정차한 경우도 단속 대상이야?",
    )

    answer = merged["assistant_message"]["answer"]
    assert "단속 여부를 지금 확정할 수 없습니다" in answer
    assert "발급기관" in answer
    assert "응급상황을 확인할 자료" in answer
    assert merged["pending_questions"] == [
        *[
            {"field": field, "question": question}
            for field, question in FINE_NOTICE_QUESTIONS.items()
        ],
        {
            "field": "emergency_evidence",
            "question": "응급상황을 확인할 수 있는 진료기록이나 영수증이 있나요?",
        },
    ]
    assert "verified_law_evidence_unavailable" in merged["next_actions"]
    assert merged["limitations"]


def test_fine_notice_procedure_with_verified_result_does_not_use_fallback_guidance() -> None:
    merged = merge_final_response(
        {
            "law_ground_search": {
                "status": "success",
                "summary": "검증된 법령 근거를 확인했습니다.",
                "structured_result": {
                    "matched_laws": [
                        {
                            "law_name": "도로교통법",
                            "article": "제160조",
                            "source_reference": "law:verified",
                        }
                    ]
                },
                "evidence": [{"source_reference": "law:verified"}],
                "limitations": [],
            },
            "agent_result_validation": {
                "status": "success",
                "structured_result": {
                    "merge_ready": True,
                    "report_ready": False,
                    "accepted_results": ["law_ground_search"],
                    "rejected_results": [],
                    "missing_fields": [],
                    "limitations": [],
                },
            },
        },
        routing_intent="fine_notice_procedure",
        user_text="과태료 의견제출 절차를 알려줘.",
    )

    assert "관련 법령 근거(참고)" in merged["assistant_message"]["answer"]
    assert "도로교통법" in merged["assistant_message"]["answer"]
    assert merged["pending_questions"] == []
    assert merged["next_actions"] == ["review_verified_results"]


def test_fine_notice_procedure_renders_practical_guidance_from_verified_law_result() -> None:
    merged = merge_final_response(
        {
            "law_ground_search": {
                "status": "success",
                "summary": "조문 5건 검색됨 (관계 확장 포함)",
                "structured_result": {
                    "matched_laws": [
                        {
                            "law_name": "도로교통법",
                            "article": "제32조",
                            "summary": "정차 및 주차의 금지 장소에 관한 규정입니다.",
                            "source_reference": "law:verified:1",
                        }
                    ],
                    "applicable_conditions": [
                        "고지서의 위반 일시·장소·처분 문구와 대조해 적용 여부를 확인해야 합니다."
                    ],
                },
                "evidence": [{"source_reference": "law:verified:1"}],
                "limitations": [],
            },
            "agent_result_validation": {
                "status": "success",
                "structured_result": {
                    "merge_ready": True,
                    "report_ready": False,
                    "accepted_results": ["law_ground_search"],
                    "rejected_results": [],
                    "missing_fields": [],
                    "limitations": [],
                },
            },
        },
        routing_intent="fine_notice_procedure",
        user_text="과태료 고지서를 받았는데 어떻게 해야 하나요?",
    )

    answer = merged["assistant_message"]["answer"]
    assert "조문 5건 검색됨" not in answer
    assert "도로교통법 제32조" in answer
    assert "고지서에 적힌 처분명" in answer
    assert "고지서에 기재된 기한" in answer
    assert "확정할 수 없습니다" not in answer
    assert merged["cards"] == [
        {
            "card_type": "verified_law_result",
            "node_code": "law_ground_search",
            "status": "success",
            "title": "확인된 관련 법령",
            "summary": "도로교통법 제32조",
        }
    ]


def test_fine_notice_procedure_normalizes_persisted_agent_law_fields_before_rendering() -> None:
    merged = merge_final_response(
        {
            "law_ground_search": {
                "status": "success",
                "summary": "조문 5건 검색됨 (관계 확장 포함)",
                "structured_result": {
                    "law_provisions": [
                        {
                            "source_name": "도로교통법",
                            "article_no": "제32조",
                            "provision_text": "정차 및 주차의 금지 장소에 관한 규정입니다.",
                            "source_reference": "law:raw-agent:1",
                        }
                    ]
                },
                "evidence": [{"source_reference": "law:raw-agent:1"}],
                "limitations": [],
            },
            "agent_result_validation": {
                "status": "success",
                "structured_result": {
                    "merge_ready": True,
                    "report_ready": False,
                    "accepted_results": ["law_ground_search"],
                    "rejected_results": [],
                    "missing_fields": [],
                    "limitations": [],
                },
            },
        },
        routing_intent="fine_notice_procedure",
        user_text="과태료 고지서를 받았는데 어떻게 해야 하나요?",
    )

    answer = merged["assistant_message"]["answer"]

    assert "조문 5건 검색됨" not in answer
    assert "도로교통법 제32조" in answer
    assert "정차 및 주차의 금지 장소" not in answer
    assert "provision_text" not in repr(merged)


def test_final_response_merge_prepends_deadline_guidance_card() -> None:
    deadline = (date.today() + timedelta(days=2)).isoformat()
    merged = merge_final_response(
        {
            "appeal_decision_flow": {
                "status": "success",
                "summary": "기한을 확인했습니다.",
                "structured_result": {
                    "computed_deadline": deadline,
                    "deadline_passed": False,
                },
                "evidence": [{"source_reference": "notice:1"}],
                "limitations": [],
            },
            "agent_result_validation": {
                "structured_result": {
                    "accepted_results": ["appeal_decision_flow"],
                },
            },
        }
    )

    assert merged["deadline_guidance"]["status"] == "due_soon"
    assert merged["deadline_guidance"]["deadline"] == deadline
    assert merged["cards"][0]["card_type"] == "deadline_guidance"


def test_final_response_merge_falls_back_when_deadline_guidance_helper_raises() -> None:
    with patch(
        "app.services.supervisor_control_service.build_deadline_guidance",
        side_effect=RuntimeError("boom"),
    ):
        merged = merge_final_response(
            {
                "appeal_decision_flow": {
                    "status": "success",
                    "summary": "Deadline review completed.",
                    "structured_result": {
                        "computed_deadline": (date.today() + timedelta(days=2)).isoformat(),
                        "deadline_passed": False,
                    },
                    "evidence": [{"source_reference": "notice:1"}],
                    "limitations": [],
                },
                "agent_result_validation": {
                    "structured_result": {
                        "accepted_results": ["appeal_decision_flow"],
                    },
                },
            }
        )

    assert merged["assistant_message"]["answer"] == "Deadline review completed."
    assert merged["deadline_guidance"] is None
    assert merged["cards"] == [
        {
            "card_type": "verified_agent_result",
            "node_code": "appeal_decision_flow",
            "status": "success",
            "summary": "Deadline review completed.",
        }
    ]
    assert (
        "Verified deadline guidance is temporarily unavailable; review persisted agent results."
        in merged["limitations"]
    )


def test_final_response_merge_falls_back_when_post_processing_raises() -> None:
    with patch(
        "app.services.supervisor_control_service._dedupe_evidence",
        side_effect=RuntimeError("boom"),
    ):
        merged = merge_final_response(
            {
                "law_ground_search": {
                    "status": "success",
                    "summary": "Verified law search completed.",
                    "structured_result": {
                        "matched_laws": [{"law_name": "Road Traffic Act"}],
                    },
                    "evidence": [{"source_reference": "law:verified"}],
                    "limitations": [],
                },
                "agent_result_validation": {
                    "structured_result": {
                        "accepted_results": ["law_ground_search"],
                    },
                },
            }
        )

    assert merged["assistant_message"]["answer"] == "Verified law search completed."
    assert merged["assistant_message"]["summary"] == "Verified law search completed."
    assert merged["structured_results"] == {
        "law_ground_search": {
            "matched_laws": [{"law_name": "Road Traffic Act"}],
        }
    }
    assert merged["evidence"] == [{"source_reference": "law:verified"}]
    assert merged["cards"] == []
    assert merged["deadline_guidance"] is None
    assert merged["next_actions"] == ["review_verified_results"]
    assert (
        "Verified response aggregation is temporarily unavailable; review persisted agent results."
        in merged["limitations"]
    )
