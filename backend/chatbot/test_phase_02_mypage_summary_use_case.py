"""Characterization coverage for the Phase 2-D7 MyPage summary boundary."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from app.services.guest_credential_service import issue_guest_credential
from chatbot.models import (
    AnalysisJob,
    AuthSession,
    AuthSessionStatus,
    ChatSession,
    Report,
    ReportStatus,
    UserAccount,
)
from chatbot.progress_cache import chat_session_state_key, read_chat_session_state


TEST_JWT_SIGNING_KEY = "phase-02-d7-mypage-summary-signing-key-is-long-enough"


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


def response_surface(value: object) -> object:
    """Characterize response key/type shape without coupling to dynamic values."""

    if isinstance(value, dict):
        return {key: response_surface(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [response_surface(item) for item in value]
    return type(value).__name__


def assert_no_sensitive_values(test_case: TestCase, value: object) -> None:
    serialized = repr(value).lower()
    for forbidden in (
        "bearer ",
        "credential",
        "access_token",
        "refresh_token",
        "raw_ocr",
        "private reasoning",
        "private_reasoning",
        "private prompt",
        "api_key",
        "password",
        "secret",
    ):
        test_case.assertNotIn(forbidden, serialized)


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class MyPageSummaryUseCaseTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_phase_02_d7_mypage_owner"
        self.foreign_owner_id = "usr_phase_02_d7_mypage_foreign"
        self.owner_session_id = "ses_phase_02_d7_mypage_owner"
        self.foreign_session_id = "ses_phase_02_d7_mypage_foreign"
        self.owner_client = authenticated_client(self.owner_id)
        self.foreign_client = authenticated_client(self.foreign_owner_id)
        self.owner_session = ChatSession.objects.create(
            session_id=self.owner_session_id,
            owner_id=self.owner_id,
            status="active",
            current_intent="fine_notice_analysis",
            metadata={"conversation_save_state": "saved"},
        )
        self.foreign_session = ChatSession.objects.create(
            session_id=self.foreign_session_id,
            owner_id=self.foreign_owner_id,
            metadata={"conversation_save_state": "saved"},
        )
        self.saved_job = AnalysisJob.objects.create(
            job_id="job_phase_02_d7_mypage_saved",
            session=self.owner_session,
            owner_id=self.owner_id,
            status="running",
            progress_message="owner-visible progress",
            metadata={"conversation_save_state": "saved"},
        )
        AnalysisJob.objects.create(
            job_id="job_phase_02_d7_mypage_pending",
            session=self.owner_session,
            owner_id=self.owner_id,
            metadata={"conversation_save_state": "pending", "raw_ocr_text": "private OCR"},
        )
        AnalysisJob.objects.create(
            job_id="job_phase_02_d7_mypage_session_only",
            session=self.owner_session,
            owner_id=self.owner_id,
            metadata={"conversation_save_state": "session_only", "private_reasoning": "private reasoning"},
        )
        AnalysisJob.objects.create(
            job_id="job_phase_02_d7_mypage_foreign",
            session=self.foreign_session,
            owner_id=self.foreign_owner_id,
            metadata={"conversation_save_state": "saved"},
        )
        Report.objects.create(
            report_id="rep_phase_02_d7_mypage_saved",
            owner_id=self.owner_id,
            session=self.owner_session,
            job=self.saved_job,
            status=ReportStatus.READY,
            metadata={"conversation_save_state": "saved"},
        )
        Report.objects.create(
            report_id="rep_phase_02_d7_mypage_pending",
            owner_id=self.owner_id,
            session=self.owner_session,
            job=self.saved_job,
            status=ReportStatus.READY,
            metadata={"conversation_save_state": "pending", "storage_uri": "s3://private"},
        )
        cache.delete(chat_session_state_key(self.owner_session_id))

    def test_http_get_requires_the_new_application_seam(self) -> None:
        """Catches a future View bypass of the D7 Application boundary."""

        with patch(
            "chatbot.views.execute_get_mypage_summary",
            create=True,
            return_value=SimpleNamespace(payload={"active_cases": 1}),
        ) as execute_get_mypage_summary:
            response = self.owner_client.get("/api/mypage/summary/")

        self.assertEqual(response.status_code, 200, response.content)
        execute_get_mypage_summary.assert_called_once()

    def test_owner_and_legacy_user_precedence_preserve_the_owned_summary(self) -> None:
        response = self.owner_client.get(
            f"/api/mypage/summary/?owner_id={self.owner_id}&user_id={self.foreign_owner_id}"
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            {case["job_id"] for case in response.json()["cases"]},
            {self.saved_job.job_id},
        )

    def test_foreign_owner_and_legacy_user_requests_are_denied(self) -> None:
        for query in (
            f"owner_id={self.owner_id}",
            f"user_id={self.owner_id}",
        ):
            with self.subTest(query=query):
                response = self.foreign_client.get(f"/api/mypage/summary/?{query}")
                self.assertEqual(response.status_code, 403, response.content)
                self.assertEqual(response.json()["error"]["code"], "object_access_denied")

    def test_own_session_is_allowed_and_foreign_session_is_denied(self) -> None:
        own_response = self.owner_client.get(
            f"/api/mypage/summary/?session_id={self.owner_session_id}"
        )
        foreign_response = self.owner_client.get(
            f"/api/mypage/summary/?session_id={self.foreign_session_id}"
        )

        self.assertEqual(own_response.status_code, 200, own_response.content)
        self.assertEqual(foreign_response.status_code, 403, foreign_response.content)
        self.assertEqual(foreign_response.json()["error"]["code"], "object_access_denied")

    def test_limit_defaults_to_ten_for_missing_invalid_zero_and_negative_values(self) -> None:
        for query in ("", "limit=invalid", "limit=0", "limit=-1"):
            with self.subTest(query=query):
                separator = "?" if query else ""
                response = self.owner_client.get(f"/api/mypage/summary/{separator}{query}")
                self.assertEqual(response.status_code, 200, response.content)
                self.assertLessEqual(response.json()["recent_analysis_count"], 10)

    def test_pending_and_session_only_rows_are_hidden_while_saved_rows_are_visible(self) -> None:
        response = self.owner_client.get(
            f"/api/mypage/summary/?session_id={self.owner_session_id}"
        )

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        case_ids = {case["job_id"] for case in body["cases"]}
        self.assertEqual(case_ids, {self.saved_job.job_id})
        self.assertEqual(body["saved_reports"], 1)

    def test_cache_miss_keeps_the_db_fallback_surface_and_excludes_sensitive_values(self) -> None:
        response = self.owner_client.get(
            f"/api/mypage/summary/?session_id={self.owner_session_id}"
        )

        self.assertEqual(response.status_code, 200, response.content)
        session_cache = response.json()["session_cache"]
        self.assertEqual(session_cache["status"], "miss_fallback")
        self.assertEqual(session_cache["snapshot"]["session_id"], self.owner_session_id)
        self.assertEqual(session_cache["snapshot"]["owner_id"], self.owner_id)
        assert_no_sensitive_values(self, response.json())

    def test_cache_hit_preserves_the_baseline_surface_without_expansion(self) -> None:
        self.maxDiff = None
        read_chat_session_state(self.owner_session_id)
        response = self.owner_client.get(
            f"/api/mypage/summary/?session_id={self.owner_session_id}"
        )

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["session_cache"]["status"], "hit")
        self.assertEqual(
            response_surface(body),
            {
                "active_cases": "int",
                "cases": [
                    {
                        "active_node": "str",
                        "agent_invocation_count": "int",
                        "agent_invocation_status_counts": {},
                        "agent_result_count": "int",
                        "agent_status_counts": {"failed": "int", "partial": "int", "success": "int"},
                        "ai_session_ids": [],
                        "analysis_plan_id": "str",
                        "case_id": "str",
                        "case_status": "str",
                        "display_result_id": "NoneType",
                        "job_id": "str",
                        "last_event_at": "str",
                        "latest_report_id": "str",
                        "latest_report_status": "str",
                        "limitations": [],
                        "message_id": "NoneType",
                        "next_actions": [],
                        "progress_message": "str",
                        "report_count": "int",
                        "routing_intent": "str",
                        "session_id": "str",
                        "title": "str",
                    }
                ],
                "conversation_save_policy": {"hidden_states": ["str", "str"], "policy_version": "str", "saved_state": "str"},
                "due_soon_cases": "int",
                "limitations": ["str", "str"],
                "object_storage": {"backend": "str", "bucket": "str", "fallback": "str", "local_root": "str", "persistence_state": "str", "policy_version": "str", "prefix": "str", "provider": "str", "signed_url_ttl_seconds": "int", "writes_binary": "bool"},
                "progress_cache": {"backend": "str", "cache_role": "str", "fallback": "str", "key_patterns": {"analysis_job_progress": "str", "chat_session_state": "str"}, "policy_version": "str", "stores_agent_reasoning": "bool", "stores_raw_user_input": "bool", "ttl_seconds": "int"},
                "recent_analysis_count": "int",
                "saved_reports": "int",
                "session_cache": {"backend": "str", "fallback": "str", "key": "str", "policy_version": "str", "snapshot": {"cache_role": "str", "current_intent": "str", "fallback": "str", "key": "str", "latest_job_id": "str", "latest_job_status": "str", "owner_id": "str", "policy_version": "str", "session_id": "str", "source_tables": ["str", "str"], "status": "str", "updated_at": "str"}, "status": "str", "ttl_seconds": "int"},
                "storage": {"backend": "str", "tables": ["str", "str", "str", "str", "str", "str", "str", "str", "str"]},
            },
        )

    def test_guest_and_anonymous_requests_remain_rejected(self) -> None:
        credential, _claims = issue_guest_credential("phase_02_d7_mypage_guest")
        guest_response = Client(
            HTTP_X_GUEST_ID="gst_phase_02_d7_mypage_guest",
            HTTP_X_GUEST_CREDENTIAL=credential,
        ).get("/api/mypage/summary/")
        anonymous_response = Client().get("/api/mypage/summary/")

        for response in (guest_response, anonymous_response):
            self.assertEqual(response.status_code, 401, response.content)
            self.assertEqual(response.json()["error"]["code"], "auth_required")
