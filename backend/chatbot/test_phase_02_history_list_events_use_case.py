"""Characterization coverage for the Phase 2-D6 History read boundary."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

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
            create=True,
        ) as execute_list_history_events:
            response = self.owner_client.get(f"/api/history/?job_id={self.job_id}")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["history_contract"], "history_event.v1")
        self.assertIn(
            self.event["event_id"],
            {event["event_id"] for event in response.json()["events"]},
        )
        execute_list_history_events.assert_called_once()
