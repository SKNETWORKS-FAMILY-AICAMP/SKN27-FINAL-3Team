"""Characterization coverage for the Phase 2-D6 History read boundary."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.application.history.list_events import (
    ListHistoryEventsQuery,
    execute_list_history_events as execute_history_query,
)
from app.services.google_auth_service import issue_access_token
from chatbot.models import AnalysisJob, AuthSession, AuthSessionStatus, ChatSession, UserAccount
from chatbot.repositories import record_history_event_record


TEST_JWT_SIGNING_KEY = "phase-02-d6-history-list-events-signing-key-is-long-enough"


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
class HistoryListEventsUseCaseTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_phase_02_d6_history_owner"
        self.session_id = "ses_phase_02_d6_history_owner"
        self.job_id = "job_phase_02_d6_history_owner"
        self.owner_client = authenticated_client(self.owner_id)
        session = ChatSession.objects.create(
            session_id=self.session_id,
            owner_id=self.owner_id,
        )
        AnalysisJob.objects.create(
            job_id=self.job_id,
            session=session,
            owner_id=self.owner_id,
        )
        self.event = record_history_event_record(
            event_type="chat_message_created",
            status="success",
            summary="owner-visible history event",
            actor={"user_id": self.owner_id, "auth_state": "authenticated"},
            subject={"session_id": self.session_id, "job_id": self.job_id},
            source={"surface": "api", "execution_mode": "canonical"},
            metadata={"conversation_save_state": "saved"},
        )

    def test_http_get_delegates_to_application_with_trusted_identity_and_preserves_history_response(
        self,
    ) -> None:
        with patch(
            "chatbot.views.execute_list_history_events",
            wraps=execute_history_query,
        ) as execute_list_history_events:
            response = self.owner_client.get(f"/api/history/?job_id={self.job_id}")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["history_contract"], "history_event.v1")
        self.assertIn(
            self.event["event_id"],
            {event["event_id"] for event in response.json()["events"]},
        )
        execute_list_history_events.assert_called_once()
    def test_application_uses_auth_context_instead_of_top_level_identity(self) -> None:
        query = ListHistoryEventsQuery(
            identity_payload={
                "user_id": "usr_untrusted_top_level",
                "auth_context": {"user_id": self.owner_id, "subject_type": "user"},
            },
            session_id=None,
            user_id=None,
            guest_id=None,
            job_id=None,
            event_type=None,
            limit=None,
            canonical_request=False,
        )

        with patch(
            "app.application.history.list_events.list_history_event_records",
            return_value=[],
        ) as records:
            execute_history_query(query)

        self.assertEqual(records.call_args.kwargs["user_id"], self.owner_id)

    def test_application_module_is_transport_orm_transaction_cache_and_worker_free(self) -> None:
        source = (
            Path(__file__).resolve().parents[2]
            / "app"
            / "application"
            / "history"
            / "list_events.py"
        ).read_text(encoding="utf-8")

        for forbidden_import in (
            "from django.http",
            "from django.db",
            "from chatbot.models",
            "transaction.atomic",
            "django.core.cache",
            "from chatbot.views",
            "celery",
        ):
            self.assertNotIn(forbidden_import, source)
