from __future__ import annotations

from app.services.supervisor_input_projection_service import (
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
