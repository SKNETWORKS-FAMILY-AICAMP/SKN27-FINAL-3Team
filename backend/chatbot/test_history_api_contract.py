"""Runtime regressions for the canonical history API contract."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from chatbot.models import AnalysisJob, AuthSession, AuthSessionStatus, ChatSession, UserAccount


TEST_JWT_SIGNING_KEY = "history-api-contract-test-signing-key-is-long-enough"


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
class HistoryApiContractTests(TestCase):
    def setUp(self) -> None:
        self.owner_client = authenticated_client("usr_history_owner")
        self.other_client = authenticated_client("usr_history_other")
        owner_session = ChatSession.objects.create(
            session_id="ses_history_owner",
            owner_id="usr_history_owner",
        )
        ChatSession.objects.create(
            session_id="ses_history_other",
            owner_id="usr_history_other",
        )
        AnalysisJob.objects.create(
            job_id="job_history_owner",
            session=owner_session,
            owner_id="usr_history_owner",
        )

    def test_other_users_job_history_is_denied(self) -> None:
        response = self.other_client.get("/api/history/?job_id=job_history_owner")

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")

    def test_owner_job_history_is_allowed(self) -> None:
        response = self.owner_client.get("/api/history/?job_id=job_history_owner")

        self.assertEqual(response.status_code, 200, response.content)

    def test_other_users_history_filter_is_denied(self) -> None:
        response = self.other_client.get("/api/history/?user_id=usr_history_owner")

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")

    def test_other_session_is_denied(self) -> None:
        response = self.owner_client.get("/api/history/?session_id=ses_history_other")

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")

    def test_invalid_limit_keeps_the_existing_default_of_100(self) -> None:
        with patch("chatbot.views.list_history_event_records", return_value=[]) as records:
            response = self.owner_client.get("/api/history/?limit=0")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(records.call_args.kwargs["limit"], 100)
