from __future__ import annotations

from app.services.supervisor_input_normalization_service import (
    normalize_supervisor_input,
)
from app.services.supervisor_input_projection_service import (
    accident_fact_candidates,
    accident_fact_sources,
    fine_notice_intake_slots,
    normalization_pending_questions,
    normalization_routing_hints,
    normalized_slot_state,
    policy_allowed_llm_facts,
)


def test_projects_auto_applied_domains_to_ordered_routing_hints() -> None:
    normalized = {
        "candidates": [
            {"domain": "fine_notice", "decision": "auto_applied"},
            {"domain": "objection", "decision": "auto_applied"},
            {"domain": "accident", "decision": "confirmation_required"},
        ]
    }

    assert normalization_routing_hints(normalized) == ["fine_notice_procedure"]


def test_projects_confirmation_and_clarification_to_unique_questions() -> None:
    normalized = {
        "candidates": [
            {
                "field": "vehicle_actions.other",
                "decision": "confirmation_required",
            }
        ],
        "clarifications": [
            {
                "field": "vehicle_actions.other",
                "decision": "confirmation_required",
            },
            {"field": "notice_stage", "decision": "clarification_required"},
        ],
    }

    questions = normalization_pending_questions(normalized)

    assert [item["field"] for item in questions] == [
        "vehicle_actions.other",
        "notice_stage",
    ]


def test_projects_both_vehicle_actions_as_one_accident_fact() -> None:
    normalized = normalize_supervisor_input(
        user_text="저는 직진했고 상대 차량은 좌해전했습니다.",
        source_message_id="msg_accident_projection",
    )

    assert accident_fact_candidates(
        normalized,
        source_message_id="msg_accident_projection",
    ) == [
        {
            "field": "vehicle_actions",
            "value": "본인 차량 직진, 상대 차량 좌회전",
            "source_message_id": "msg_accident_projection",
            "confidence": 0.99,
            "confirmed": False,
        }
    ]


def test_negated_vehicle_action_is_not_projected() -> None:
    normalized = normalize_supervisor_input(
        user_text="상대 차량은 좌회전하지 않았습니다.",
        source_message_id="msg_accident_negated",
    )

    assert accident_fact_candidates(
        normalized,
        source_message_id="msg_accident_negated",
    ) == []


def test_accident_fact_sources_keep_rule_provenance_without_raw_text() -> None:
    normalized = normalize_supervisor_input(
        user_text="저는 직진했고 상대 차량은 좌해전했습니다.",
        source_message_id="msg_accident_source",
    )

    sources = accident_fact_sources(
        normalized,
        source_message_id="msg_accident_source",
    )

    assert {item["rule_id"] for item in sources} == {
        "accident.vehicle_actions.self.straight.exact_01",
        "accident.vehicle_actions.other.left_turn.typo_01",
    }
    assert all(item["source_type"] == "rule_normalization" for item in sources)
    assert all("source_text" not in item for item in sources)


def test_projects_notice_and_objection_slots_without_legal_conclusions() -> None:
    normalized = normalize_supervisor_input(
        user_text="과태료 1챠 고지서를 받아서 이의 재기하려고 합니다.",
        source_message_id="msg_notice_projection",
    )

    slot_state = normalized_slot_state(normalized)

    assert slot_state["contract_version"] == "slot_filling_state.v1"
    assert slot_state["slots"]["fine_type"]["value"] == "fine"
    assert slot_state["slots"]["notice_stage"]["value"] == "first_notice"
    assert slot_state["slots"]["requested_action"]["value"] == "objection"
    assert "legal_conclusion" not in slot_state["slots"]
    assert "law_article" not in slot_state["slots"]
    assert fine_notice_intake_slots(normalized)["document_disposition_type"][
        "value"
    ] == "first_notice"


def test_policy_allowlist_discards_unknown_accident_llm_fact() -> None:
    assert policy_allowed_llm_facts(
        [
            {"field": "road_layout", "value": "교차로"},
            {"field": "legal_conclusion", "value": "상대방이 전적으로 위법"},
        ],
        scenario="accident_initial_consultation",
    ) == [{"field": "road_layout", "value": "교차로"}]


def test_policy_allowlist_does_not_expand_general_consultation() -> None:
    facts = [{"field": "user_text", "value": "일반 교통 문의"}]

    assert policy_allowed_llm_facts(
        facts,
        scenario="general_consultation",
    ) == facts
