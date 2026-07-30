from __future__ import annotations

from app.services.public_consultation_routing_service import (
    resolve_public_consultation_intent,
)


def test_public_consultation_type_maps_only_to_fixed_top_level_intents() -> None:
    assert resolve_public_consultation_intent("general") == "general_consultation"
    assert (
        resolve_public_consultation_intent("fault_ratio")
        == "accident_initial_consultation"
    )
    assert resolve_public_consultation_intent("fine_notice") == "fine_notice_procedure"


def test_unknown_public_consultation_type_cannot_select_an_agent_or_plan() -> None:
    assert resolve_public_consultation_intent("text_ml_case_search") == ""
    assert resolve_public_consultation_intent("../../custom-agent") == ""
    assert resolve_public_consultation_intent(None) == ""
