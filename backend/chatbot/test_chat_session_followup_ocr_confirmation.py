"""Regression coverage for server-owned OCR confirmation follow-up state."""

from django.test import SimpleTestCase

from app.services.chat_session_followup_service import (
    merge_chat_followup_payload,
    merge_confirmed_ocr_followup_state,
)


class ChatSessionFollowupOcrConfirmationTests(SimpleTestCase):
    def setUp(self) -> None:
        self.confirmation = {
            "confirmed": True,
            "fields": {
                "fine_type": "과태료",
                "notice_stage": "사전통지",
                "law_code": "도로교통법 제32조 제1호",
                "violation_text": "소화전 5m 이내 정차 위반",
                "opinion_deadline": "2026-08-10",
                "issuing_authority": "경찰서장",
                "unexpected": "must-not-persist",
            },
        }

    def test_same_attachment_restores_only_allowed_confirmation_fields(self) -> None:
        state = merge_confirmed_ocr_followup_state(
            None,
            {
                "attachments": [{"attachment_id": "att_notice"}],
                "ocr_confirmation": self.confirmation,
            },
            routing_intent="fine_notice_analysis",
        )

        merged = merge_chat_followup_payload(
            {
                "user_text": "이의신청서 초안을 생성해 주세요.",
                "attachments": [{"attachment_id": "att_notice"}],
            },
            state,
            current_routing_intent="fine_notice_analysis",
        )

        self.assertEqual(
            merged["ocr_confirmation"],
            {
                "confirmed": True,
                "fields": {
                    "fine_type": "과태료",
                    "notice_stage": "사전통지",
                    "law_code": "도로교통법 제32조 제1호",
                    "violation_text": "소화전 5m 이내 정차 위반",
                    "opinion_deadline": "2026-08-10",
                    "issuing_authority": "경찰서장",
                },
            },
        )

    def test_replaced_attachment_does_not_restore_stale_confirmation(self) -> None:
        state = merge_confirmed_ocr_followup_state(
            None,
            {
                "attachments": [{"attachment_id": "att_notice_old"}],
                "ocr_confirmation": self.confirmation,
            },
            routing_intent="fine_notice_analysis",
        )

        merged = merge_chat_followup_payload(
            {
                "user_text": "새 고지서를 분석해 주세요.",
                "attachments": [{"attachment_id": "att_notice_new"}],
            },
            state,
            current_routing_intent="fine_notice_analysis",
        )

        self.assertNotIn("ocr_confirmation", merged)

    def test_topic_switch_drops_confirmation(self) -> None:
        state = merge_confirmed_ocr_followup_state(
            None,
            {
                "attachments": [{"attachment_id": "att_notice"}],
                "ocr_confirmation": self.confirmation,
            },
            routing_intent="fine_notice_analysis",
        )

        merged = merge_chat_followup_payload(
            {
                "user_text": "교통사고 과실 비율을 알려주세요.",
                "attachments": [{"attachment_id": "att_notice"}],
                "ocr_confirmation": self.confirmation,
            },
            state,
            current_routing_intent="accident_initial_consultation",
        )

        self.assertNotIn("ocr_confirmation", merged)
