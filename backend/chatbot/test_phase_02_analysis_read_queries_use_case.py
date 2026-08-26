"""Security characterization for the Phase 2-D11 AnalysisReadQueries boundary."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from app.services.guest_credential_service import issue_guest_credential
from chatbot.models import (
    AnalysisJob,
    AuthSession,
    AuthSessionStatus,
    ChatSession,
    GuestIdentity,
    GuestIdentityStatus,
    UserAccount,
)

from chatbot.repositories import (
    authorize_resource_access,
    get_analysis_job_access_metadata,
)


TEST_JWT_SIGNING_KEY = "phase-02-d11-analysis-read-queries-signing-key-is-long-enough"


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class AnalysisReadQueriesSecurityTests(TestCase):
    def setUp(self) -> None:
        self.guest_id = "gst_d11_owner_session"
        self.session_id = "ses_d11_owner_session"
        self.job_id = "job_d11_owner_session"
        GuestIdentity.objects.create(
            guest_id=self.guest_id,
            status=GuestIdentityStatus.ACTIVE,
        )
        self.session = ChatSession.objects.create(
            session_id=self.session_id,
            metadata={"auth_context": {"guest_id": self.guest_id}},
        )
        self.job = AnalysisJob.objects.create(
            job_id=self.job_id,
            session=self.session,
            owner_id="usr_d11_foreign_owner",
            status="queued",
        )
        credential, _claims = issue_guest_credential(self.guest_id)
        self.guest_client = Client(
            HTTP_X_GUEST_ID=self.guest_id,
            HTTP_X_GUEST_CREDENTIAL=credential,
        )

    def test_direct_job_metadata_authorization_keeps_explicit_owner_precedence(self) -> None:
        access = authorize_resource_access(
            get_analysis_job_access_metadata(self.job_id),
            {"auth_context": {"guest_id": self.guest_id}},
        )

        self.assertFalse(access["allowed"])
        self.assertEqual(access["reason"], "owner_mismatch")

    def test_guest_session_cannot_read_foreign_owner_analysis_job_detail_even_when_session_matches(self) -> None:
        response = self.guest_client.get(f"/api/analysis/jobs/{self.job_id}/")

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")

    def test_guest_session_cannot_read_foreign_owner_analysis_result_even_when_session_matches(self) -> None:
        response = self.guest_client.get(f"/api/analysis/results/{self.job_id}/")

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")

    def test_analysis_job_detail_discards_cache_snapshot_with_mismatched_identity(self) -> None:
        AnalysisJob.objects.filter(job_id=self.job_id).update(owner_id="")
        with patch(
            "app.application.analysis.read_queries.read_analysis_job_progress",
            return_value={
                "status": "hit",
                "snapshot": {
                    "job_id": "job_d11_foreign_cache",
                    "session_id": "ses_d11_foreign_cache",
                    "status": "failed",
                    "progress_message": "foreign cache state",
                    "status_counts": {"failed": 99},
                    "owner_id": "usr_d11_foreign_cache",
                },
            },
        ):
            response = self.guest_client.get(f"/api/analysis/jobs/{self.job_id}/")

        self.assertEqual(response.status_code, 200, response.content)
        rendered = repr(response.json()["job"])
        self.assertNotIn("job_d11_foreign_cache", rendered)
        self.assertNotIn("ses_d11_foreign_cache", rendered)
        self.assertNotIn("foreign cache state", rendered)


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class AnalysisReadQueriesGuestPolicyTests(TestCase):
    def test_expired_guest_cannot_list_analysis_jobs(self) -> None:
        guest_id = "gst_d11_expired"
        GuestIdentity.objects.create(
            guest_id=guest_id,
            status=GuestIdentityStatus.EXPIRED,
            expires_at=timezone.now(),
        )
        credential, _claims = issue_guest_credential(guest_id)

        response = Client(
            HTTP_X_GUEST_ID=guest_id,
            HTTP_X_GUEST_CREDENTIAL=credential,
        ).get("/api/analysis/jobs/")

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["code"], "guest_session_invalid")


def _authenticated_client(user_id: str) -> Client:
    issued_at = timezone.now()
    expires_at = issued_at + timedelta(hours=1)
    auth_session_id = f"auth_{user_id}"
    token, _claims = issue_access_token(
        user_id=user_id,
        auth_session_id=auth_session_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    user = UserAccount.objects.create(user_id=user_id)
    AuthSession.objects.create(
        auth_session_id=auth_session_id,
        user=user,
        subject_type="user",
        subject_id=f"user:{user_id}",
        status=AuthSessionStatus.ACTIVE,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    return Client(HTTP_AUTHORIZATION=f"Bearer {token}")


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class AnalysisReadQueriesApplicationSeamTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_d11_application_owner"
        self.session_id = "ses_d11_application_owner"
        self.job_id = "job_d11_application_owner"
        self.owner_client = _authenticated_client(self.owner_id)
        self.session = ChatSession.objects.create(
            session_id=self.session_id,
            owner_id=self.owner_id,
        )
        AnalysisJob.objects.create(
            job_id=self.job_id,
            session=self.session,
            owner_id=self.owner_id,
            status="queued",
        )

    def test_analysis_job_list_delegates_to_execute_list_analysis_jobs(self) -> None:
        with patch(
            "chatbot.views.execute_list_analysis_jobs",
            create=True,
            return_value=SimpleNamespace(payload={"jobs": []}),
        ) as execute_list_analysis_jobs:
            response = self.owner_client.get("/api/analysis/jobs/")

        self.assertEqual(response.status_code, 200, response.content)
        execute_list_analysis_jobs.assert_called_once()

    def test_analysis_job_detail_delegates_to_execute_get_analysis_job_detail(self) -> None:
        with patch(
            "chatbot.views.execute_get_analysis_job_detail",
            create=True,
            return_value=SimpleNamespace(payload={"job_id": self.job_id}),
        ) as execute_get_analysis_job_detail:
            response = self.owner_client.get(f"/api/analysis/jobs/{self.job_id}/")

        self.assertEqual(response.status_code, 200, response.content)
        execute_get_analysis_job_detail.assert_called_once()

    def test_analysis_result_delegates_to_execute_get_analysis_result(self) -> None:
        with patch(
            "chatbot.views.execute_get_analysis_result",
            create=True,
            return_value=SimpleNamespace(payload={"job_id": self.job_id}, pending=True),
        ) as execute_get_analysis_result:
            response = self.owner_client.get(f"/api/analysis/results/{self.job_id}/")

        self.assertEqual(response.status_code, 202, response.content)
        execute_get_analysis_result.assert_called_once()


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class AnalysisReadQueriesContractTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_d11_contract_owner"
        self.other_owner_id = "usr_d11_other_owner"
        self.session_id = "ses_d11_contract_owner"
        self.job_id = "job_d11_contract_owner"
        self.owner_client = _authenticated_client(self.owner_id)
        self.owner_session = ChatSession.objects.create(
            session_id=self.session_id,
            owner_id=self.owner_id,
        )
        AnalysisJob.objects.create(
            job_id=self.job_id,
            session=self.owner_session,
            owner_id=self.owner_id,
            status="queued",
            metadata={
                "storage_uri": "s3://private-d11/job.json",
                "access_token": "d11-private-token",
                "raw_output": "d11-private-output",
            },
        )

    def test_authenticated_owner_list_is_scoped_to_owner(self) -> None:
        other_session = ChatSession.objects.create(
            session_id="ses_d11_other_owner",
            owner_id=self.other_owner_id,
        )
        AnalysisJob.objects.create(
            job_id="job_d11_other_owner",
            session=other_session,
            owner_id=self.other_owner_id,
            status="queued",
        )

        response = self.owner_client.get("/api/analysis/jobs/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            [job["job_id"] for job in response.json()["jobs"]],
            [self.job_id],
        )

    def test_valid_guest_without_session_lists_no_jobs(self) -> None:
        guest_id = "gst_d11_valid_no_session"
        GuestIdentity.objects.create(
            guest_id=guest_id,
            status=GuestIdentityStatus.ACTIVE,
        )
        credential, _claims = issue_guest_credential(guest_id)

        response = Client(
            HTTP_X_GUEST_ID=guest_id,
            HTTP_X_GUEST_CREDENTIAL=credential,
        ).get("/api/analysis/jobs/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"jobs": []})

    def test_analysis_job_detail_excludes_private_metadata(self) -> None:
        response = self.owner_client.get(f"/api/analysis/jobs/{self.job_id}/")

        self.assertEqual(response.status_code, 200, response.content)
        rendered = repr(response.json()["job"])
        self.assertNotIn("s3://private-d11/job.json", rendered)
        self.assertNotIn("d11-private-token", rendered)
        self.assertNotIn("d11-private-output", rendered)

    def test_analysis_result_preserves_pending_and_terminal_http_status(self) -> None:
        pending = self.owner_client.get(f"/api/analysis/results/{self.job_id}/")
        AnalysisJob.objects.filter(job_id=self.job_id).update(status="success")
        terminal = self.owner_client.get(f"/api/analysis/results/{self.job_id}/")

        self.assertEqual(pending.status_code, 202, pending.content)
        self.assertEqual(terminal.status_code, 200, terminal.content)
