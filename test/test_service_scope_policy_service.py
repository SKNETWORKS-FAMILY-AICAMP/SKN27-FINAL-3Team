from __future__ import annotations

from app.services.service_scope_policy_service import evaluate_service_scope


def test_vehicle_pedestrian_collision_requires_expert_handoff() -> None:
    result = evaluate_service_scope(
        user_text="차가 보행자와 충돌한 사고의 과실을 확정해 주세요.",
        attachments=[],
        routing_intent="accident_initial_consultation",
    )

    assert result["decision"] == "expert_handoff"
    assert result["scope_code"] == "vehicle_pedestrian_collision"
    assert result["next_actions"]


def test_vehicle_to_vehicle_accident_is_within_supported_scope() -> None:
    result = evaluate_service_scope(
        user_text="교차로에서 두 차량이 충돌한 과실 쟁점을 정리해 주세요.",
        attachments=[],
        routing_intent="accident_initial_consultation",
    )

    assert result["decision"] == "proceed"
    assert result["scope_code"] == "vehicle_to_vehicle_accident"


def test_unknown_intent_returns_guidance_without_claiming_support() -> None:
    result = evaluate_service_scope(
        user_text="상속 분쟁을 해결해 주세요.",
        attachments=[],
        routing_intent="general_consultation",
    )

    assert result["decision"] == "guidance_only"
    assert result["scope_code"] == "unsupported_consultation"


def test_unclassified_input_is_left_for_the_existing_clarifying_question_flow() -> None:
    result = evaluate_service_scope(
        user_text="help",
        attachments=[],
        routing_intent="general_consultation",
    )

    assert result["decision"] == "proceed"
    assert result["scope_code"] == "scope_confirmation_required"


def test_high_risk_accident_keeps_the_existing_emergency_handoff_flow() -> None:
    result = evaluate_service_scope(
        user_text="보행자가 크게 다쳐 구급차를 기다리고 있습니다.",
        attachments=[],
        routing_intent="accident_initial_consultation",
    )

    assert result["decision"] == "proceed"
