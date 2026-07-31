from __future__ import annotations

import pytest

from app.services.input_understanding_service import evaluate_input_understanding


@pytest.mark.parametrize(
    "user_text",
    (
        "아 진짜 짜증나네 씨발",
        "ㄱㅈㅅ ㅂㄹㅈ ㄴㅂㄱㅎ ㅁㄹㄱㅆㅇ",
        "help",
    ),
)
def test_low_information_input_requires_clarification(user_text: str) -> None:
    result = evaluate_input_understanding(user_text=user_text, attachments=[])

    assert result["contract_version"] == "input_understanding_gate.v1"
    assert result["status"] == "needs_clarification"
    assert result["safe_user_text"] == ""
    assert "고지서" in result["message"]
    assert "사고" in result["message"]
    assert "법령" in result["message"]
    assert user_text not in repr(result["public_metadata"])


def test_profanity_with_fine_notice_intent_is_sanitized_and_accepted() -> None:
    user_text = "과태료 고지서 받았는데 이게 대체 무슨 개소리야? 이의신청 할 수 있는지 알려줘."

    result = evaluate_input_understanding(user_text=user_text, attachments=[])

    assert result["status"] == "accepted"
    assert "과태료" in result["safe_user_text"]
    assert "이의신청" in result["safe_user_text"]
    assert "개소리" not in result["safe_user_text"]
    assert result["public_metadata"]["noise_removed"] is True


def test_typo_heavy_fine_notice_intent_is_accepted_without_guessing_facts() -> None:
    user_text = "과태료 고지서 잇는데 이의시처 됨? 기한 지낫는지 모르겟음"

    result = evaluate_input_understanding(user_text=user_text, attachments=[])

    assert result["status"] == "accepted"
    assert result["safe_user_text"] == user_text


def test_sensitive_identity_input_is_classified_without_echoing_raw_values() -> None:
    raw_identifier = "900101-1234567"

    result = evaluate_input_understanding(
        user_text=f"주민등록번호 {raw_identifier}입니다.",
        attachments=[],
    )

    assert result["status"] == "blocked_sensitive"
    assert raw_identifier not in repr(result["public_metadata"])


def test_explicit_non_traffic_domain_is_out_of_scope() -> None:
    result = evaluate_input_understanding(
        user_text="상속 분쟁을 해결해 주세요.",
        attachments=[],
    )

    assert result["status"] == "out_of_scope"

