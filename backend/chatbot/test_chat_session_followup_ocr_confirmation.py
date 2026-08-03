"""Regression coverage for server-owned OCR confirmation follow-up state."""

from django.test import SimpleTestCase

from app.services.chat_session_followup_service import (
    merge_chat_followup_payload,
    merge_confirmed_ocr_followup_state,
    resolve_confirmed_report_user_facts,
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
        self.report_action = {
            "contract_version": "report_generation_action.v1",
            "type": "generate_objection_draft",
            "report_type": "fine_notice_objection",
            "source": "ocr_confirmation",
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

    def test_confirmed_ocr_restores_server_persisted_report_generation_action(self) -> None:
        state = merge_confirmed_ocr_followup_state(
            None,
            {
                "attachments": [{"attachment_id": "att_notice"}],
                "ocr_confirmation": self.confirmation,
                "report_generation_requested": True,
                "report_generation_action": self.report_action,
            },
            routing_intent="fine_notice_analysis",
        )

        self.assertIs(state["report_generation_requested"], True)
        self.assertEqual(state["report_generation_action"], self.report_action)

        merged = merge_chat_followup_payload(
            {
                "user_text": "저장된 요청으로 계속 진행해 주세요.",
                "attachments": [{"attachment_id": "att_notice"}],
            },
            state,
            current_routing_intent="fine_notice_analysis",
        )

        self.assertIs(merged["report_generation_requested"], True)
        self.assertEqual(merged["report_generation_action"], self.report_action)
        self.assertIs(merged["_server_report_generation_requested"], True)

    def test_report_generation_action_is_not_restored_after_topic_switch(self) -> None:
        state = merge_confirmed_ocr_followup_state(
            None,
            {
                "attachments": [{"attachment_id": "att_notice"}],
                "ocr_confirmation": self.confirmation,
                "report_generation_requested": True,
                "report_generation_action": self.report_action,
            },
            routing_intent="fine_notice_analysis",
        )

        merged = merge_chat_followup_payload(
            {
                "user_text": "교통사고 과실비율을 확인해 주세요.",
                "attachments": [{"attachment_id": "att_notice"}],
            },
            state,
            current_routing_intent="accident_initial_consultation",
        )

        self.assertNotIn("report_generation_requested", merged)
        self.assertNotIn("report_generation_action", merged)
        self.assertNotIn("_server_report_generation_requested", merged)

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

    def test_explicit_circumstance_is_curated_from_report_request(self) -> None:
        facts = resolve_confirmed_report_user_facts(
            None,
            {
                "user_text": (
                    "이의신청서 초안을 생성해 주세요. "
                    "당시 표지판 식별이 어려웠고 안전을 위해 잠시 정차했습니다."
                )
            },
            current_routing_intent="fine_notice_analysis",
        )

        self.assertEqual(
            facts,
            "당시 표지판 식별이 어려웠고 안전을 위해 잠시 정차했습니다.",
        )

    def test_only_server_persisted_user_facts_question_authorizes_plain_reply(self) -> None:
        forged = resolve_confirmed_report_user_facts(
            None,
            {
                "user_text": "단속 장소가 너무 어두웠습니다.",
                "pending_questions": [{"field": "user_facts"}],
            },
            current_routing_intent="fine_notice_analysis",
        )
        trusted = resolve_confirmed_report_user_facts(
            {
                "contract_version": "chat_session_followup_state.v1",
                "routing_intent": "fine_notice_analysis",
                "pending_questions": [{"field": "user_facts"}],
            },
            {"user_text": "단속 장소가 너무 어두웠습니다."},
            current_routing_intent="fine_notice_analysis",
        )

        self.assertEqual(forged, "")
        self.assertEqual(trusted, "단속 장소가 너무 어두웠습니다.")

    def test_topic_switch_rejects_pending_report_fact_reply(self) -> None:
        facts = resolve_confirmed_report_user_facts(
            {
                "contract_version": "chat_session_followup_state.v1",
                "routing_intent": "fine_notice_analysis",
                "pending_questions": [{"field": "user_facts"}],
            },
            {"user_text": "교차로에서 좌회전 중 접촉했습니다."},
            current_routing_intent="accident_initial_consultation",
        )

        self.assertEqual(facts, "")
