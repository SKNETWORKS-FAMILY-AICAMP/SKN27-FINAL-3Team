from __future__ import annotations

from app.services.fine_notice_intake_service import reduce_fine_notice_intake


def test_empty_fine_notice_intake_requests_all_required_slots() -> None:
    intake = reduce_fine_notice_intake(
        {
            "message_id": "msg_e2e_3",
            "user_text": (
                "과태료 고지서를 받았는데 이의신청이나 의견제출은 "
                "어떤 순서로 하면 되나요?"
            ),
            "attachments": [],
        }
    )

    assert intake["contract_version"] == "fine_notice_intake.v1"
    assert intake["missing_fields"] == [
        "document_disposition_type",
        "issuing_authority",
        "response_deadline",
        "attachment_available",
    ]
    assert [item["field"] for item in intake["next_questions"]] == intake[
        "missing_fields"
    ]


def test_explicit_fine_notice_slots_are_confirmed_user_input() -> None:
    intake = reduce_fine_notice_intake(
        {
            "message_id": "msg_structured_notice",
            "fine_notice_slots": {
                "document_disposition_type": "과태료 사전통지서",
                "issuing_authority": "가상시청",
                "response_deadline": "2026-08-07",
                "attachment_available": True,
                "unsupported": "discard me",
            },
        }
    )

    assert intake["missing_fields"] == []
    assert intake["next_questions"] == []
    assert intake["slots"] == {
        "document_disposition_type": {
            "value": "과태료 사전통지서",
            "source_type": "user_structured_input",
            "source_message_id": "msg_structured_notice",
            "confidence": 1.0,
            "confirmed": True,
        },
        "issuing_authority": {
            "value": "가상시청",
            "source_type": "user_structured_input",
            "source_message_id": "msg_structured_notice",
            "confidence": 1.0,
            "confirmed": True,
        },
        "response_deadline": {
            "value": "2026-08-07",
            "source_type": "user_structured_input",
            "source_message_id": "msg_structured_notice",
            "confidence": 1.0,
            "confirmed": True,
        },
        "attachment_available": {
            "value": True,
            "source_type": "user_structured_input",
            "source_message_id": "msg_structured_notice",
            "confidence": 1.0,
            "confirmed": True,
        },
    }


def test_confirmed_ocr_fields_fill_only_matching_fine_notice_slots() -> None:
    intake = reduce_fine_notice_intake(
        {
            "message_id": "msg_confirmed_ocr",
            "ocr_confirmation": {
                "confirmed": True,
                "fields": {
                    "document_disposition_type": "과태료 사전통지서",
                    "issuing_authority": "가상시청",
                    "response_deadline": "2026-08-07",
                    "ocr_text": "must not be retained",
                },
            },
        }
    )

    assert intake["missing_fields"] == ["attachment_available"]
    assert set(intake["slots"]) == {
        "document_disposition_type",
        "issuing_authority",
        "response_deadline",
    }
    assert {
        record["source_type"] for record in intake["slots"].values()
    } == {"user_confirmed_ocr"}
    assert "ocr_text" not in repr(intake)


def test_confirmed_canonical_ocr_fields_fill_intake_alias_slots() -> None:
    intake = reduce_fine_notice_intake(
        {
            "message_id": "msg_canonical_ocr",
            "attachments": [{"attachment_id": "att_notice"}],
            "ocr_confirmation": {
                "confirmed": True,
                "fields": {
                    "fine_type": "과태료",
                    "notice_stage": "사전통지",
                    "issuing_authority": "경찰서장",
                    "opinion_deadline": "2026-08-10",
                },
            },
        }
    )

    assert intake["missing_fields"] == []
    assert intake["next_questions"] == []
    assert intake["slots"]["document_disposition_type"]["value"] == "과태료 사전통지"
    assert intake["slots"]["response_deadline"]["value"] == "2026-08-10"
    assert {
        intake["slots"][field]["source_type"]
        for field in (
            "document_disposition_type",
            "issuing_authority",
            "response_deadline",
        )
    } == {"user_confirmed_ocr"}


def test_registered_attachment_confirms_only_attachment_availability() -> None:
    intake = reduce_fine_notice_intake(
        {
            "session_id": "ses_with_attachment",
            "attachments": [
                {
                    "attachment_id": "att_notice",
                    "purpose": "fine_notice",
                    "status": "ready",
                }
            ],
        }
    )

    assert intake["missing_fields"] == [
        "document_disposition_type",
        "issuing_authority",
        "response_deadline",
    ]
    assert intake["slots"] == {
        "attachment_available": {
            "value": True,
            "source_type": "server_attachment",
            "source_message_id": "ses_with_attachment",
            "confidence": 1.0,
            "confirmed": True,
        }
    }


def test_exact_fine_notice_question_maps_the_followup_answer_to_its_slot() -> None:
    intake = reduce_fine_notice_intake(
        {
            "session_id": "ses_notice_followup",
            "conversation_history": [
                {
                    "role": "assistant",
                    "content": "고지서를 발급한 기관을 알려주세요.",
                },
                {
                    "role": "user",
                    "content": "가상시청입니다.",
                    "message_id": "msg_notice_authority",
                },
            ],
        }
    )

    assert intake["slots"] == {
        "issuing_authority": {
            "value": "가상시청입니다.",
            "source_type": "user_confirmation",
            "source_message_id": "msg_notice_authority",
            "confidence": 1.0,
            "confirmed": True,
        }
    }
    assert "issuing_authority" not in intake["missing_fields"]


def test_pending_question_field_routes_short_answer_without_exact_prompt_text() -> None:
    intake = reduce_fine_notice_intake(
        {
            "message_id": "msg_authority_short_answer",
            "user_text": "서울시",
            "pending_questions": [
                {
                    "field": "issuing_authority",
                    "question": "확인 안내를 포함한 다른 발급기관 문구입니다.",
                }
            ],
        }
    )

    assert intake["slots"]["issuing_authority"] == {
        "value": "서울시",
        "source_type": "user_confirmation",
        "source_message_id": "msg_authority_short_answer",
        "confidence": 1.0,
        "confirmed": True,
    }
    assert "issuing_authority" not in intake["missing_fields"]


def test_uncertain_slot_values_remain_missing_instead_of_becoming_facts() -> None:
    intake = reduce_fine_notice_intake(
        {
            "message_id": "msg_e2e_11",
            "user_text": "과태료 고지서 잇는데 이의시처 됨? 기한 지낫는지 모르겟음",
            "fine_notice_slots": {
                "document_disposition_type": "",
                "issuing_authority": "모르겠음",
                "response_deadline": "기한 지났는지 모르겠음",
                "attachment_available": "unknown",
            },
            "ocr_confirmation": {
                "confirmed": False,
                "fields": {
                    "document_disposition_type": "추정 과태료",
                    "issuing_authority": "추정 기관",
                    "response_deadline": "2026-08-07",
                },
            },
        }
    )

    assert intake["slots"] == {}
    assert intake["missing_fields"] == [
        "document_disposition_type",
        "issuing_authority",
        "response_deadline",
        "attachment_available",
    ]
    assert "추정" not in repr(intake)


def test_confirmed_ocr_and_structured_slots_outrank_rule_normalization() -> None:
    result = reduce_fine_notice_intake(
        {
            "message_id": "msg_notice_priority",
            "fine_notice_slots": {"document_disposition_type": "사전통지"},
            "normalized_slots": {
                "document_disposition_type": {
                    "value": "first_notice",
                    "source_type": "rule_normalization",
                    "confidence": 0.99,
                    "confirmed": False,
                }
            },
        }
    )

    assert result["slots"]["document_disposition_type"]["value"] == "사전통지"


def test_server_stored_slots_survive_followup_and_keep_provenance() -> None:
    result = reduce_fine_notice_intake(
        {
            "message_id": "msg_notice_followup",
            "fine_notice_slots": {"document_disposition_type": "client overwrite"},
            "stored_fine_notice_intake_slots": {
                "document_disposition_type": {
                    "value": "pre_notice",
                    "source_type": "rule_normalization",
                    "source_message_id": "msg_notice_first",
                    "confidence": 1.0,
                    "confirmed": False,
                }
            },
            "normalized_slots": {
                "issuing_authority": {
                    "value": "서울특별시",
                    "source_type": "rule_normalization",
                    "source_message_id": "msg_notice_followup",
                    "confidence": 0.99,
                    "confirmed": False,
                }
            },
        }
    )

    assert result["slots"]["document_disposition_type"] == {
        "value": "pre_notice",
        "source_type": "rule_normalization",
        "source_message_id": "msg_notice_first",
        "confidence": 1.0,
        "confirmed": False,
    }
    assert result["slots"]["issuing_authority"]["value"] == "서울특별시"
