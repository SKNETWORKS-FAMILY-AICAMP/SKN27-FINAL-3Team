from __future__ import annotations

from datetime import date, timedelta

from app.services.deadline_guidance_service import build_deadline_guidance


def test_due_soon_deadline_is_explicitly_highlighted() -> None:
    result = build_deadline_guidance(
        {
            "computed_deadline": (date.today() + timedelta(days=3)).isoformat(),
            "deadline_passed": False,
        },
        source_node_code="appeal_decision_flow",
    )

    assert result["contract_version"] == "deadline_guidance.v1"
    assert result["status"] == "due_soon"
    assert result["days_remaining"] == 3


def test_missing_deadline_requests_confirmation_without_guessing() -> None:
    result = build_deadline_guidance(
        {},
        source_node_code="appeal_decision_flow",
    )

    assert result["status"] == "needs_confirmation"
    assert result["deadline"] is None
