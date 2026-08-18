from __future__ import annotations

from datetime import timedelta
import importlib
from pathlib import Path
import re
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.contracts.chat_session import ChatSaveStateResponse
from app.services.google_auth_service import issue_access_token
from app.services.guest_credential_service import issue_guest_credential
from chatbot.models import (
    AnalysisJob,
    AuthSession,
    AuthSessionStatus,
    ChatMessage,
    ChatSession,
    GuestIdentity,
    GuestIdentityStatus,
    HistoryEvent,
    MessageRole,
    Report,
    UserAccount,
)
from chatbot.progress_cache import read_chat_session_state


TEST_JWT_SIGNING_KEY = "phase-02-d4-save-state-signing-key-is-long-enough"


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
class ConversationSaveStateUseCaseCharacterizationTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_phase_02_d4_owner"
        self.foreign_owner_id = "usr_phase_02_d4_foreign"
        self.owner_client = authenticated_client(self.owner_id)
        self.foreign_client = authenticated_client(self.foreign_owner_id)

    def _create_owner_graph(self, session_id: str) -> tuple[ChatSession, ChatMessage, AnalysisJob, Report]:
        session = ChatSession.objects.create(
            session_id=session_id,
            owner_id=self.owner_id,
            metadata={"conversation_save_state": "pending"},
        )
        message = ChatMessage.objects.create(
            message_id=f"msg_{session_id}",
            session=session,
            role=MessageRole.USER,
            content="Phase 2 D4 fixture message",
            metadata={"conversation_save_state": "pending"},
        )
        job = AnalysisJob.objects.create(
            job_id=f"job_{session_id}",
            session=session,
            message=message,
            owner_id=self.owner_id,
            metadata={"conversation_save_state": "pending"},
        )
        report = Report.objects.create(
            report_id=f"rep_{session_id}",
            session=session,
            job=job,
            owner_id=self.owner_id,
            metadata={"conversation_save_state": "pending"},
        )
        HistoryEvent.objects.create(
            event_id=f"evt_{session_id}",
            event_type="chat_message_created",
            occurred_at=timezone.now(),
            subject_session_id=session_id,
            metadata={"conversation_save_state": "pending"},
        )
        return session, message, job, report

    def _post(self, client: Client, payload: dict[str, object]):
        return client.post(
            "/api/chat/save-state/",
            data=payload,
            content_type="application/json",
        )

    def test_http_post_delegates_to_application_with_trusted_identity_and_preserves_save_state_response(self) -> None:
        session, message, job, report = self._create_owner_graph("ses_phase_02_d4_saved")
        captured: dict[str, object] = {}
        payload = {
            "session_id": session.session_id,
            "conversation_save_state": "saved",
            "conversation_save_source": "phase_02_d4_characterization",
            "user_id": self.foreign_owner_id,
            "owner_id": self.foreign_owner_id,
            "guest_id": "gst_forged",
        }

        def application_spy(command: object) -> object:
            captured["command"] = command
            module = importlib.import_module("app.application.chat.update_save_state")
            return module.execute_update_conversation_save_state(command)

        with patch(
            "chatbot.views.execute_update_conversation_save_state",
            side_effect=application_spy,
            create=True,
        ) as execute_application:
            response = self._post(self.owner_client, payload)

        self.assertEqual(response.status_code, 200, response.content)
        ChatSaveStateResponse.model_validate(response.json())
        execute_application.assert_called_once()
        command = captured["command"]
        self.assertEqual(command.identity_payload["auth_context"]["user_id"], self.owner_id)
        self.assertEqual(command.raw_payload, payload)
        session.refresh_from_db()
        message.refresh_from_db()
        job.refresh_from_db()
        report.refresh_from_db()
        self.assertEqual(session.owner_id, self.owner_id)
        self.assertEqual(session.metadata["conversation_save_state"], "saved")
        self.assertEqual(message.metadata["conversation_save_state"], "saved")
        self.assertEqual(job.metadata["conversation_save_state"], "saved")
        self.assertEqual(report.metadata["conversation_save_state"], "saved")
        self.assertTrue(
            HistoryEvent.objects.filter(
                subject_session_id=session.session_id,
                event_type="conversation_saved",
            ).exists()
        )
        cache_state = read_chat_session_state(session.session_id)
        self.assertIn(cache_state["status"], {"hit", "miss_fallback"})
        self.assertEqual(cache_state["snapshot"]["owner_id"], self.owner_id)

    def test_unknown_session_keeps_200_skipped_contract(self) -> None:
        response = self._post(
            self.owner_client,
            {
                "session_id": "ses_phase_02_d4_missing",
                "conversation_save_state": "saved",
            },
        )

        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()["conversation_save"]
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["conversation_save_state"], "saved")
        self.assertEqual(result["reason"], "session_not_found")

    def test_owner_pending_and_session_only_preserve_propagation_without_saved_history_event(self) -> None:
        for state in ("pending", "session_only"):
            with self.subTest(state=state):
                session, message, job, report = self._create_owner_graph(
                    f"ses_phase_02_d4_owner_{state}"
                )
                response = self._post(
                    self.owner_client,
                    {"session_id": session.session_id, "conversation_save_state": state},
                )

                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(
                    response.json()["conversation_save"]["conversation_save_state"],
                    state,
                )
                for record in (session, message, job, report):
                    record.refresh_from_db()
                    self.assertEqual(record.metadata["conversation_save_state"], state)
                self.assertFalse(
                    HistoryEvent.objects.filter(
                        subject_session_id=session.session_id,
                        event_type="conversation_saved",
                    ).exists()
                )
    def test_guest_saved_is_rejected_without_mutation(self) -> None:
        guest_id = "gst_phase_02_d4_guest_saved"
        credential, _claims = issue_guest_credential("phase_02_d4_guest_saved")
        guest_client = Client(
            HTTP_X_GUEST_ID=guest_id,
            HTTP_X_GUEST_CREDENTIAL=credential,
        )
        session = ChatSession.objects.create(
            session_id="ses_phase_02_d4_guest_saved",
            metadata={
                "auth_context": {"guest_id": guest_id},
                "conversation_save_state": "pending",
            },
        )

        response = self._post(
            guest_client,
            {
                "session_id": session.session_id,
                "conversation_save_state": "saved",
            },
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "login_required")
        session.refresh_from_db()
        self.assertEqual(session.metadata["conversation_save_state"], "pending")

    def test_guest_pending_and_session_only_keep_existing_allowed_state_transitions(self) -> None:
        guest_id = "gst_phase_02_d4_guest_states"
        credential, _claims = issue_guest_credential("phase_02_d4_guest_states")
        guest_client = Client(
            HTTP_X_GUEST_ID=guest_id,
            HTTP_X_GUEST_CREDENTIAL=credential,
        )
        session = ChatSession.objects.create(
            session_id="ses_phase_02_d4_guest_states",
            metadata={"auth_context": {"guest_id": guest_id}},
        )

        for state in ("pending", "session_only"):
            with self.subTest(state=state):
                response = self._post(
                    guest_client,
                    {"session_id": session.session_id, "conversation_save_state": state},
                )
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(
                    response.json()["conversation_save"]["conversation_save_state"],
                    state,
                )
                session.refresh_from_db()
                self.assertEqual(session.metadata["conversation_save_state"], state)

    def test_foreign_owner_is_denied_before_mutation(self) -> None:
        session, message, job, report = self._create_owner_graph("ses_phase_02_d4_foreign")
        history_count = HistoryEvent.objects.filter(subject_session_id=session.session_id).count()

        response = self._post(
            self.foreign_client,
            {"session_id": session.session_id, "conversation_save_state": "saved"},
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")
        for record in (session, message, job, report):
            record.refresh_from_db()
            self.assertEqual(record.metadata["conversation_save_state"], "pending")
        self.assertEqual(
            HistoryEvent.objects.filter(subject_session_id=session.session_id).count(),
            history_count,
        )

    def test_expired_guest_keeps_guest_session_invalid_before_mutation(self) -> None:
        guest_id = "gst_phase_02_d4_expired"
        GuestIdentity.objects.create(
            guest_id=guest_id,
            status=GuestIdentityStatus.ACTIVE,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        credential, _claims = issue_guest_credential("phase_02_d4_expired")
        guest_client = Client(
            HTTP_X_GUEST_ID=guest_id,
            HTTP_X_GUEST_CREDENTIAL=credential,
        )
        session = ChatSession.objects.create(
            session_id="ses_phase_02_d4_expired",
            metadata={"auth_context": {"guest_id": guest_id}},
        )

        response = self._post(
            guest_client,
            {"session_id": session.session_id, "conversation_save_state": "pending"},
        )

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["code"], "guest_session_invalid")
        session.refresh_from_db()
        self.assertNotIn("conversation_save_state", session.metadata)

    def test_repeated_same_save_state_preserves_updated_result(self) -> None:
        session, _message, _job, _report = self._create_owner_graph("ses_phase_02_d4_repeat")

        first = self._post(
            self.owner_client,
            {"session_id": session.session_id, "conversation_save_state": "saved"},
        )
        second = self._post(
            self.owner_client,
            {"session_id": session.session_id, "conversation_save_state": "saved"},
        )

        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(second.json()["conversation_save"]["status"], "updated")
        self.assertEqual(second.json()["conversation_save"]["conversation_save_state"], "saved")

    def test_application_is_http_and_orm_transaction_free_and_view_has_no_direct_save_or_history_mutation(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        application_path = repository_root / "app/application/chat/update_save_state.py"
        if not application_path.exists():
            self.skipTest("Application module is intentionally absent during RED.")
        application_source = application_path.read_text(encoding="utf-8")
        view_source = (repository_root / "backend/chatbot/views.py").read_text(encoding="utf-8")
        view_start = view_source.index("def update_chat_save_state")
        view_end = view_source.index("\n\n@csrf_exempt", view_start)
        save_state_view = view_source[view_start:view_end]

        for prohibited in (
            "from django",
            "HttpRequest",
            "HttpResponse",
            "transaction.atomic",
            "chatbot.models",
            ".objects",
            "unittest.mock",
        ):
            self.assertNotIn(prohibited, application_source)
        self.assertIsNone(
            re.search(r"(?m)^\s*result\s*=\s*mark_conversation_save_state\(", save_state_view)
        )
        self.assertNotIn("_record_history_safely(", save_state_view)
