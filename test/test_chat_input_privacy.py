from __future__ import annotations

from copy import deepcopy

import pytest

from app.security.chat_input_privacy import (
    ChatInputPrivacyPolicy,
    ChatInputRejected,
    protect_chat_input_payload,
)
from app.security.pii_masking import MASK_TOKEN
from app.services import chat_orchestration_service, chatbot_mock_service


def test_gateway_blocks_secrets_without_echoing_the_value() -> None:
    credential_sample = "sk-synthetic123456789"

    with pytest.raises(ChatInputRejected) as captured:
        protect_chat_input_payload({"user_text": f"API key is {credential_sample}"})

    error = captured.value
    assert credential_sample not in str(error)
    assert credential_sample not in repr(error.decision.public_metadata())
    assert error.decision.status == "blocked"
    assert error.decision.blocked_categories == ("secret",)


def test_gateway_masks_pii_and_only_exposes_category_counts() -> None:
    payload = {
        "user_text": (
            "성명: 홍길동, 전화 010-1234-5678, 이메일 user@example.com, "
            "차량 12가3456, 주소: 서울시 중구 세종대로 1"
        )
    }
    original = deepcopy(payload)

    protected = protect_chat_input_payload(payload)

    assert payload == original
    assert protected["user_text"].count(MASK_TOKEN) >= 5
    assert "홍길동" not in repr(protected)
    assert "010-1234-5678" not in repr(protected)
    assert "user@example.com" not in repr(protected)
    assert "12가3456" not in repr(protected)
    assert protected["privacy_gateway"]["category_counts"] == {
        "address": 1,
        "email": 1,
        "name": 1,
        "phone": 1,
        "vehicle_number": 1,
    }


def test_gateway_sanitizes_conversation_and_agent_context_boundaries() -> None:
    protected = protect_chat_input_payload(
        {
            "user_text": "도로교통법을 알려주세요",
            "conversation_history": [
                {"role": "user", "content": "전화 010-1234-5678"}
            ],
            "facts": {"driver_name": "홍길동", "road_layout": "교차로"},
            "context": {"query": "차량 12가3456 사고"},
        }
    )

    serialized = repr(protected)
    assert "010-1234-5678" not in serialized
    assert "홍길동" not in serialized
    assert "12가3456" not in serialized
    assert protected["facts"]["road_layout"] == "교차로"


def test_gateway_rejects_input_over_the_configured_limit() -> None:
    policy = ChatInputPrivacyPolicy(max_chars=10)

    with pytest.raises(ChatInputRejected) as captured:
        protect_chat_input_payload({"user_text": "가" * 11}, policy=policy)

    assert captured.value.decision.blocked_categories == ("input_too_long",)


def test_canonical_supervisor_receives_only_safe_text(monkeypatch) -> None:
    captured: dict = {}

    def build_state(*, payload, scenario, fallback_builder):
        captured.update(deepcopy(payload))
        return fallback_builder(payload, scenario)

    monkeypatch.setattr(
        chat_orchestration_service,
        "build_supervisor_state_with_optional_llm",
        build_state,
    )

    response = chat_orchestration_service.submit_message(
        {"user_text": "도로교통법 문의, 전화 010-1234-5678"}
    )

    assert response["status"] == "queued"
    assert "010-1234-5678" not in repr(captured)
    assert MASK_TOKEN in captured["user_text"]


def test_legacy_mock_supervisor_cannot_bypass_gateway(monkeypatch) -> None:
    captured: dict = {}

    def build_state(*, payload, scenario, fallback_builder):
        captured.update(deepcopy(payload))
        return fallback_builder(payload, scenario)

    monkeypatch.setattr(
        chatbot_mock_service,
        "build_supervisor_state_with_optional_llm",
        build_state,
    )

    chatbot_mock_service.submit_message(
        {
            "mock_scenario": "fine_notice",
            "mock_status": "success",
            "user_text": "고지서 문의, 전화 010-1234-5678",
        }
    )

    assert "010-1234-5678" not in repr(captured)
    assert MASK_TOKEN in captured["user_text"]
