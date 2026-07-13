from __future__ import annotations

from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import decode_access_token, issue_access_token
from chatbot.models import (
    AnalysisJob,
    AuthSession,
    AuthSessionStatus,
    ChatSession,
    ChatSessionStatus,
    UserAccount,
)


TEST_JWT_SIGNING_KEY = "security-hardening-test-signing-key-is-long-enough"


def authenticated_client(user_id: str) -> Client:
    token, _auth_session_id = persisted_session_token(user_id)
    return Client(HTTP_AUTHORIZATION=f"Bearer {token}")


def persisted_session_token(
    user_id: str,
    *,
    auth_session_id: str | None = None,
) -> tuple[str, str]:
    auth_session_id = auth_session_id or f"auth_{user_id}"
    issued_at = timezone.now()
    expires_at = issued_at + timedelta(hours=1)
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
    return token, auth_session_id


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


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class AuthSessionRotationSecurityTests(TestCase):
    def test_refresh_rotates_jti_revokes_old_session_and_accepts_new_token(self) -> None:
        token, old_session_id = persisted_session_token(
            "usr_refresh_rotation",
            auth_session_id="auth_refresh_rotation_old",
        )

        response = Client().post(
            "/api/auth/refresh/",
            data={},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 200)
        new_token = response.json()["access_token"]
        valid, new_claims = decode_access_token(new_token)
        self.assertTrue(valid)
        self.assertNotEqual(new_claims["jti"], old_session_id)
        old_session = AuthSession.objects.get(auth_session_id=old_session_id)
        new_session = AuthSession.objects.get(auth_session_id=new_claims["jti"])
        self.assertEqual(old_session.status, AuthSessionStatus.REVOKED)
        self.assertIsNotNone(old_session.revoked_at)
        self.assertEqual(new_session.status, AuthSessionStatus.ACTIVE)

        old_access = Client(HTTP_AUTHORIZATION=f"Bearer {token}").get(
            "/api/analysis/jobs/"
        )
        new_access = Client(HTTP_AUTHORIZATION=f"Bearer {new_token}").get(
            "/api/analysis/jobs/"
        )
        self.assertEqual(old_access.status_code, 401)
        self.assertEqual(new_access.status_code, 200)

    def test_refresh_credential_is_single_use(self) -> None:
        token, _old_session_id = persisted_session_token(
            "usr_refresh_once",
            auth_session_id="auth_refresh_once_old",
        )
        client = Client(HTTP_AUTHORIZATION=f"Bearer {token}")

        first = client.post("/api/auth/refresh/", data={}, content_type="application/json")
        second = client.post("/api/auth/refresh/", data={}, content_type="application/json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 401)
        self.assertEqual(second.json()["error"]["code"], "token_invalid")
        self.assertNotIn("access_token", second.json())

    def test_logout_revokes_access_refresh_and_auth_me_without_reactivation(self) -> None:
        token, auth_session_id = persisted_session_token(
            "usr_logout_revoke",
            auth_session_id="auth_logout_revoke",
        )
        client = Client(HTTP_AUTHORIZATION=f"Bearer {token}")

        logout = client.post("/api/auth/logout/", data={}, content_type="application/json")
        protected = client.get("/api/analysis/jobs/")
        refresh = client.post("/api/auth/refresh/", data={}, content_type="application/json")
        auth_me = client.get("/api/auth/me/")

        self.assertEqual(logout.status_code, 200)
        self.assertEqual(protected.status_code, 401)
        self.assertEqual(refresh.status_code, 401)
        self.assertEqual(auth_me.status_code, 401)
        session = AuthSession.objects.get(auth_session_id=auth_session_id)
        self.assertEqual(session.status, AuthSessionStatus.REVOKED)
        self.assertIsNotNone(session.revoked_at)

    def test_refresh_rejects_valid_jwt_without_persisted_active_session(self) -> None:
        token, _claims = issue_access_token(
            user_id="usr_unpersisted_refresh",
            auth_session_id="auth_unpersisted_refresh",
        )

        response = Client().post(
            "/api/auth/refresh/",
            data={},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "token_invalid")
        self.assertFalse(
            AuthSession.objects.filter(
                auth_session_id="auth_unpersisted_refresh"
            ).exists()
        )
