"""RED-first characterization for the CreateChatSession application boundary."""

from __future__ import annotations

from datetime import timedelta
import importlib
from unittest.mock import patch

from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from app.services.guest_credential_service import issue_guest_credential
from chatbot.models import AuthSession, AuthSessionStatus, ChatSession, HistoryEvent, UserAccount
from chatbot.repositories import record_history_event_record


TEST_JWT_SIGNING_KEY = "phase-02-d9-create-chat-session-signing-key-is-long-enough"


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
class CreateChatSessionUseCaseCharacterizationTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_phase_02_d9_owner"
        self.client = authenticated_client(self.owner_id)

    def test_http_post_delegates_to_create_chat_session_application_with_trusted_identity_and_preserves_draft_response(
        self,
    ) -> None:
        captured: dict[str, object] = {}

        def application_spy(command: object) -> object:
            captured["command"] = command
            module = importlib.import_module("app.application.chat.create_session")
            return module.execute_create_chat_session(command)

        with patch(
            "chatbot.views.execute_create_chat_session",
            side_effect=application_spy,
            create=True,
        ) as execute_application:
            response = self.client.post(
                "/api/chat/sessions/",
                data={
                    "user_id": "usr_forged",
                    "owner_id": "usr_forged",
                    "guest_id": "gst_forged",
                    "subject_id": "user:usr_forged",
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["contract_version"], "chat_session.v1")
        self.assertTrue(body["session_id"].startswith("ses_"))
        self.assertEqual(body["user_id"], self.owner_id)
        self.assertEqual(body["status"], "draft")
        self.assertTrue(body["created_at"])
        execute_application.assert_called_once()
        self.assertEqual(
            captured["command"].identity_payload["auth_context"]["user_id"],
            self.owner_id,
        )

    def test_authenticated_identity_neutralizes_all_client_owned_identity_fields(self) -> None:
        response = self.client.post(
            "/api/chat/sessions/",
            data={
                "user_id": "usr_forged",
                "owner_id": "usr_forged",
                "guest_id": "gst_forged",
                "subject_id": "user:usr_forged",
                "subject_type": "user",
                "auth_session_id": "auth_forged",
                "auth_context": {
                    "user_id": "usr_forged",
                    "owner_id": "usr_forged",
                    "guest_id": "gst_forged",
                    "subject_id": "user:usr_forged",
                },
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["user_id"], self.owner_id)
        self.assertNotIn("usr_forged", repr(body))
        self.assertNotIn("gst_forged", repr(body))

    def test_valid_guest_cannot_select_a_user_through_the_request_body(self) -> None:
        credential, _claims = issue_guest_credential("phase_02_d9_guest")
        response = Client(
            HTTP_X_GUEST_ID="gst_phase_02_d9_guest",
            HTTP_X_GUEST_CREDENTIAL=credential,
        ).post(
            "/api/chat/sessions/",
            data={"user_id": self.owner_id, "owner_id": self.owner_id},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["user_id"])

    def test_invalid_guest_credential_keeps_the_current_401_contract(self) -> None:
        response = Client(
            HTTP_X_GUEST_ID="gst_phase_02_d9_guest",
            HTTP_X_GUEST_CREDENTIAL="invalid-credential",
        ).post("/api/chat/sessions/", data={}, content_type="application/json")

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["code"], "token_invalid")

    def test_history_event_uses_trusted_actor_subject_and_draft_metadata(self) -> None:
        captured: dict[str, object] = {}

        def record_history(**kwargs: object) -> object:
            captured.update(kwargs)
            return record_history_event_record(**kwargs)

        with patch(
            "chatbot.views.record_history_event_record",
            side_effect=record_history,
        ):
            response = self.client.post(
                "/api/chat/sessions/",
                data={"user_id": "usr_forged", "owner_id": "usr_forged"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content)
        session_id = response.json()["session_id"]
        self.assertEqual(captured["event_type"], "chat_session_created")
        self.assertEqual(captured["actor"]["user_id"], self.owner_id)
        self.assertNotEqual(captured["actor"]["user_id"], "usr_forged")
        self.assertEqual(captured["subject"]["session_id"], session_id)
        self.assertEqual(captured["metadata"], {"session_status": "draft"})
        self.assertTrue(
            HistoryEvent.objects.filter(
                event_type="chat_session_created",
                actor_user_id=self.owner_id,
                subject_session_id=session_id,
                metadata={"session_status": "draft"},
            ).exists()
        )

    def test_history_database_and_os_failures_keep_the_draft_response_successful(self) -> None:
        for failure in (DatabaseError("history unavailable"), OSError("history unavailable")):
            with self.subTest(failure_type=failure.__class__.__name__):
                with patch(
                    "chatbot.views.record_history_event_record",
                    side_effect=failure,
                ):
                    response = self.client.post(
                        "/api/chat/sessions/",
                        data={},
                        content_type="application/json",
                    )

                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["status"], "draft")

    def test_authenticated_invalid_json_keeps_the_optional_body_draft_contract(self) -> None:
        response = self.client.generic(
            "POST",
            "/api/chat/sessions/",
            data=b"{not-json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["user_id"], self.owner_id)
        self.assertEqual(body["status"], "draft")

    def test_anonymous_transport_keeps_the_existing_auth_required_contract(self) -> None:
        response = Client().post(
            "/api/chat/sessions/", data={}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["code"], "auth_required")

    def test_draft_issuance_does_not_create_a_chat_session_row(self) -> None:
        before = ChatSession.objects.count()

        response = self.client.post(
            "/api/chat/sessions/", data={}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "draft")
        self.assertEqual(ChatSession.objects.count(), before)
