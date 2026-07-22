from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.contracts.chat_session import (
    ChatMessageRequest,
    ChatSaveStateRequest,
    ChatSessionCreateRequest,
)


def test_public_chat_requests_do_not_model_client_owned_identity_or_credential() -> None:
    assert "user_id" not in ChatSessionCreateRequest.model_fields
    assert "guest_credential" not in ChatMessageRequest.model_fields
    assert "guest_credential" not in ChatSaveStateRequest.model_fields
    assert "auth_context" not in ChatMessageRequest.model_fields

    with pytest.raises(ValidationError):
        ChatSessionCreateRequest.model_validate({"user_id": "usr_spoof"})
    with pytest.raises(ValidationError):
        ChatMessageRequest.model_validate(
            {"session_id": "ses_1", "guest_credential": "secret"}
        )


def test_public_chat_message_request_accepts_documented_input_shape() -> None:
    request = ChatMessageRequest.model_validate(
        {
            "session_id": "ses_1",
            "user_text": "교차로 사고의 과실을 확인하고 싶습니다.",
            "attachments": [{"attachment_id": "att_1", "purpose": "evidence"}],
            "conversation_history": [{"role": "user", "content": "사고 상담"}],
            "conversation_save_state": "pending",
            "execution_mode": "async_worker",
        }
    )

    assert request.session_id == "ses_1"
    assert request.conversation_save_state == "pending"


def test_chat_message_contract_accepts_only_documented_ocr_confirmation_fields() -> None:
    request = ChatMessageRequest.model_validate(
        {
            "session_id": "ses_ocr_confirmation",
            "user_text": "OCR 값을 확인했습니다.",
            "ocr_confirmation": {
                "confirmed": True,
                "fields": {"fine_type": "과태료", "notice_stage": "사전통지"},
            },
        }
    )

    assert request.ocr_confirmation is not None
    assert request.ocr_confirmation.fields.fine_type == "과태료"

    with pytest.raises(ValidationError):
        ChatMessageRequest.model_validate(
            {
                "session_id": "ses_ocr_confirmation_invalid",
                "user_text": "OCR 값을 확인했습니다.",
                "ocr_confirmation": {
                    "confirmed": True,
                    "fields": {"fine_type": "과태료", "unexpected": "not_allowed"},
                },
            }
        )
