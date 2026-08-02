from __future__ import annotations

from app.services.supervisor_input_normalization_service import (
    normalize_supervisor_input,
)
from app.services.supervisor_input_projection_service import (
    accident_fact_candidates,
    accident_fact_sources,
    normalization_pending_questions,
    normalization_routing_hints,
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
