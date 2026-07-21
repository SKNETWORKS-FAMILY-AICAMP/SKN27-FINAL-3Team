"""Runtime regression tests for the promoted chat session API contract."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from app.services.guest_credential_service import issue_guest_credential
from chatbot.models import AuthSession, AuthSessionStatus, UserAccount


TEST_JWT_SIGNING_KEY = "chat-session-contract-test-signing-key-is-long-enough"


def authenticated_client(user_id: str) -> Client:
    issued_at = timezone.now()
    expires_at = issued_at + timedelta(hours=1)
    auth_session_id = f"auth_{user_id}"
    token, _claims = issue_access_token(
        user_id=user_id,
        auth_session_id=auth_session_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    user, _created = UserAccount.objects.get_or_create(user_id=user_id)
    AuthSession.objects.update_or_create(
        auth_session_id=auth_session_id,
        defaults={
            "user": user,
            "subject_type": "user",
            "subject_id": f"user:{user_id}",
            "status": AuthSessionStatus.ACTIVE,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "revoked_at": None,
        },
    )
    return Client(HTTP_AUTHORIZATION=f"Bearer {token}")


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class ChatSessionApiContractTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_chat_contract"
        self.client = authenticated_client(self.owner_id)

    def test_draft_session_uses_header_identity_not_body_user_id(self) -> None:
        response = self.client.post(
            "/api/chat/sessions/",
            data={"user_id": "usr_spoof"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["contract_version"], "chat_session.v1")
        self.assertEqual(body["user_id"], self.owner_id)
        self.assertNotEqual(body["user_id"], "usr_spoof")
        self.assertTrue(body["session_id"])

    def test_chat_message_keeps_immediate_scope_guidance_as_200(self) -> None:
        response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_chat_contract_scope",
                "user_text": "보행자와 충돌한 사고의 과실을 확정해 주세요.",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "scope_guidance")

    def test_chat_message_keeps_worker_polling_fields_for_queued_response(self) -> None:
        response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_chat_contract_queue",
                "user_text": "과태료 고지서 이의신청을 준비하고 싶습니다.",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
                "execution_mode": "async_worker",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 202, response.content)
        body = response.json()
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["execution_mode"], "async_worker")
        self.assertTrue(body["work_item"]["work_item_id"])
        self.assertTrue(body["supervisor_execution"])
        self.assertTrue(body["persistence"])

    def test_supervisor_unavailable_keeps_chat_response_shape_at_503(self) -> None:
        with patch(
            "chatbot.views.submit_message",
            return_value={
                "contract_version": "chat_message.v1",
                "session_id": "ses_chat_contract_unavailable",
                "message_id": "msg_chat_contract_unavailable",
                "status": "supervisor_unavailable",
            },
        ):
            response = self.client.post(
                "/api/chat/messages/",
                data={
                    "session_id": "ses_chat_contract_unavailable",
                    "user_text": "사고 상담을 시작합니다.",
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 503, response.content)
        self.assertEqual(response.json()["status"], "supervisor_unavailable")
        self.assertNotIn("error", response.json())

    def test_unknown_session_save_state_is_a_200_skipped_result(self) -> None:
        response = self.client.post(
            "/api/chat/save-state/",
            data={
                "session_id": "ses_missing_chat_contract",
                "conversation_save_state": "pending",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["conversation_save"]["status"], "skipped")

    def test_guest_cannot_save_and_credential_is_not_returned(self) -> None:
        credential, _claims = issue_guest_credential("chat_contract")
        guest_client = Client(
            HTTP_X_GUEST_ID="gst_chat_contract",
            HTTP_X_GUEST_CREDENTIAL=credential,
        )

        response = guest_client.post(
            "/api/chat/save-state/",
            data={
                "session_id": "ses_guest_chat_contract",
                "conversation_save_state": "saved",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertNotIn(credential, response.content.decode("utf-8"))
