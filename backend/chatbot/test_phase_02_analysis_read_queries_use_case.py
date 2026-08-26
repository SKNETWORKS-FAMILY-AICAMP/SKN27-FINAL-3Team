"""Security characterization for the Phase 2-D11 AnalysisReadQueries boundary."""

from __future__ import annotations

from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.guest_credential_service import issue_guest_credential
from chatbot.models import AnalysisJob, ChatSession, GuestIdentity, GuestIdentityStatus
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
        with patch(
            "chatbot.views.read_analysis_job_progress",
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
