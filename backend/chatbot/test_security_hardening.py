from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import decode_access_token, issue_access_token
from chatbot.models import (
    AnalysisJob,
    AuthSession,
    AuthSessionStatus,
    ChatMessage,
    ChatSession,
    ChatSessionStatus,
    UsageEvent,
    UserAccount,
    UserAccountStatus,
)
from chatbot.repositories import AuthSessionStateError, persist_current_auth_subject


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

    def test_job_creation_rejects_another_users_session_before_orchestration(self) -> None:
        with patch("chatbot.views.submit_message") as submit_message:
            response = self.other_client.post(
                "/api/analysis/jobs/",
                data={
                    "session_id": self.owner_session.session_id,
                    "user_text": "attempt cross-owner analysis",
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")
        submit_message.assert_not_called()

    def test_scan_blocked_chat_rejects_cross_owner_session_before_scan_or_write(self) -> None:
        with (
            patch("chatbot.views.apply_attachment_scan_gate") as scan_gate,
            patch("chatbot.views.submit_message") as submit_message,
            patch("chatbot.views.record_usage_event") as record_usage,
        ):
            response = self.other_client.post(
                "/api/chat/messages/",
                data={
                    "session_id": self.owner_session.session_id,
                    "message_id": "msg_attacker_controlled",
                    "job_id": self.owner_job.job_id,
                    "attachments": [{"attachment_id": "att_attacker_unscanned"}],
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")
        scan_gate.assert_not_called()
        submit_message.assert_not_called()
        record_usage.assert_not_called()
        self.owner_job.refresh_from_db()
        self.assertEqual(self.owner_job.owner_id, self.owner_id)
        self.assertEqual(self.owner_job.session_id, self.owner_session.pk)
        self.assertFalse(ChatMessage.objects.filter(message_id="msg_attacker_controlled").exists())

    def test_scan_blocked_chat_does_not_persist_client_controlled_message_or_job_ids(self) -> None:
        original_metadata = dict(self.owner_job.metadata)

        with (
            patch(
                "chatbot.views.apply_attachment_scan_gate",
                side_effect=lambda payload: {
                    **payload,
                    "attachments": [],
                    "blocked_attachments": [
                        {
                            "attachment_id": "att_owner_unscanned",
                            "required_action": "wait_for_file_scan",
                        }
                    ],
                },
            ),
            patch("chatbot.views.submit_message") as submit_message,
            patch("chatbot.views.record_usage_event") as record_usage,
        ):
            response = self.owner_client.post(
                "/api/chat/messages/",
                data={
                    "session_id": self.owner_session.session_id,
                    "message_id": "msg_client_controlled",
                    "job_id": self.owner_job.job_id,
                    "attachments": [{"attachment_id": "att_owner_unscanned"}],
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["persistence"]["status"], "skipped")
        self.assertNotEqual(body["message_id"], "msg_client_controlled")
        submit_message.assert_not_called()
        record_usage.assert_not_called()
        self.owner_job.refresh_from_db()
        self.assertEqual(self.owner_job.metadata, original_metadata)
        self.assertFalse(ChatMessage.objects.filter(message_id="msg_client_controlled").exists())

    def test_job_creation_uses_authenticated_owner_not_forged_body_owner(self) -> None:
        session_id = "ses_analysis_new_owned"
        chat_response = {
            "session_id": session_id,
            "message_id": "msg_analysis_new_owned",
            "routing_intent": "traffic_law_search",
            "status": "queued",
            "progress": {"status": "queued", "active_node": "law_ground_search"},
            "analysis_plan": {
                "plan_id": "plan_analysis_new_owned",
                "steps": [
                    {
                        "order": 1,
                        "node_code": "law_ground_search",
                        "status": "queued",
                    }
                ],
            },
            "attachments": [],
            "blocked_attachments": [],
            "limitations": [],
        }

        with patch("chatbot.views.submit_message", return_value=chat_response):
            response = self.owner_client.post(
                "/api/analysis/jobs/",
                data={
                    "session_id": session_id,
                    "owner_id": self.other_id,
                    "user_id": self.other_id,
                    "user_text": "create under forged owner",
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 202)
        job = AnalysisJob.objects.get(job_id=response.json()["job"]["job_id"])
        self.assertEqual(job.owner_id, self.owner_id)
        self.assertEqual(job.session.owner_id, self.owner_id)
        usage_event = UsageEvent.objects.get(scope="agent_run")
        self.assertEqual(usage_event.subject_id, f"user:{self.owner_id}")

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
        case_list = client.get("/api/cases/")
        refresh = client.post("/api/auth/refresh/", data={}, content_type="application/json")
        auth_me = client.get("/api/auth/me/")

        self.assertEqual(logout.status_code, 200)
        self.assertEqual(protected.status_code, 401)
        self.assertEqual(case_list.status_code, 401)
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

    def test_suspended_user_cannot_use_active_session(self) -> None:
        token, _auth_session_id = persisted_session_token("usr_suspended_session")
        UserAccount.objects.filter(user_id="usr_suspended_session").update(
            status=UserAccountStatus.SUSPENDED
        )
        client = Client(HTTP_AUTHORIZATION=f"Bearer {token}")

        mypage = client.get("/api/mypage/summary/")
        cases = client.get("/api/cases/")
        refresh = client.post("/api/auth/refresh/", data={}, content_type="application/json")

        for response in (mypage, cases, refresh):
            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()["error"]["auth"]["reason"],
                "user_account_inactive",
            )

    def test_auth_session_with_deleted_user_relation_is_rejected(self) -> None:
        token, auth_session_id = persisted_session_token("usr_deleted_session")
        UserAccount.objects.get(user_id="usr_deleted_session").delete()
        client = Client(HTTP_AUTHORIZATION=f"Bearer {token}")

        mypage = client.get("/api/mypage/summary/")
        refresh = client.post(
            "/api/auth/refresh/",
            data={},
            content_type="application/json",
        )

        for response in (mypage, refresh):
            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()["error"]["auth"]["reason"],
                "auth_session_user_missing",
            )
        self.assertIsNone(AuthSession.objects.get(auth_session_id=auth_session_id).user)

    def test_user_subject_without_user_id_cannot_be_persisted(self) -> None:
        with self.assertRaises(AuthSessionStateError) as error:
            persist_current_auth_subject(
                {
                    "contract_version": "google_auth_code.v1",
                    "subject": {
                        "subject_type": "user",
                        "subject_id": "user:missing",
                        "auth_session_id": "auth_missing_user_id",
                    },
                }
            )

        self.assertEqual(error.exception.reason, "auth_session_user_missing")
        self.assertFalse(
            AuthSession.objects.filter(auth_session_id="auth_missing_user_id").exists()
        )
