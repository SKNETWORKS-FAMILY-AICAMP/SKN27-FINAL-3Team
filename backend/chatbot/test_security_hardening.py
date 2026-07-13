from __future__ import annotations

from django.test import Client, TestCase, override_settings

from app.services.google_auth_service import issue_access_token
from chatbot.models import AnalysisJob, ChatSession, ChatSessionStatus


TEST_JWT_SIGNING_KEY = "security-hardening-test-signing-key-is-long-enough"


def authenticated_client(user_id: str) -> Client:
    token, _claims = issue_access_token(
        user_id=user_id,
        auth_session_id=f"auth_{user_id}",
    )
    return Client(HTTP_AUTHORIZATION=f"Bearer {token}")


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class AnalysisJobOwnershipSecurityTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_analysis_owner"
        self.other_id = "usr_analysis_other"
        self.owner_client = authenticated_client(self.owner_id)
        self.other_client = authenticated_client(self.other_id)
        self.owner_session = ChatSession.objects.create(
            session_id="ses_analysis_owner",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        self.other_session = ChatSession.objects.create(
            session_id="ses_analysis_other",
            owner_id=self.other_id,
            status=ChatSessionStatus.ACTIVE,
        )
        self.owner_job = AnalysisJob.objects.create(
            job_id="job_analysis_owner",
            session=self.owner_session,
            owner_id=self.owner_id,
            status="queued",
        )
        self.other_job = AnalysisJob.objects.create(
            job_id="job_analysis_other",
            session=self.other_session,
            owner_id=self.other_id,
            status="queued",
        )

    def test_job_list_is_scoped_to_the_authenticated_owner(self) -> None:
        response = self.owner_client.get("/api/analysis/jobs/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [job["job_id"] for job in response.json()["jobs"]],
            [self.owner_job.job_id],
        )

    def test_job_list_rejects_another_users_session_filter(self) -> None:
        response = self.other_client.get(
            f"/api/analysis/jobs/?session_id={self.owner_session.session_id}"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")

    def test_job_detail_rejects_another_user(self) -> None:
        response = self.other_client.get(
            f"/api/analysis/jobs/{self.owner_job.job_id}/"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")

    def test_analysis_result_rejects_another_user(self) -> None:
        response = self.other_client.get(
            f"/api/analysis/results/{self.owner_job.job_id}/"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")

    def test_owner_can_read_detail_and_pending_result(self) -> None:
        detail = self.owner_client.get(
            f"/api/analysis/jobs/{self.owner_job.job_id}/"
        )
        result = self.owner_client.get(
            f"/api/analysis/results/{self.owner_job.job_id}/"
        )

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["job"]["job_id"], self.owner_job.job_id)
        self.assertEqual(result.status_code, 202)
        self.assertEqual(result.json()["result"]["job_id"], self.owner_job.job_id)
