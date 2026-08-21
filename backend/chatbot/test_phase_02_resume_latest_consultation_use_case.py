"""Characterization tests for the ResumeLatestConsultation Application seam."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from app.services.guest_credential_service import issue_guest_credential
from chatbot import views
from chatbot.models import AuthSession, AuthSessionStatus, ChatSession, ChatSessionStatus, UserAccount


TEST_JWT_SIGNING_KEY = "resume-latest-consultation-test-signing-key-is-long-enough"


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
class ResumeLatestConsultationUseCaseTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_phase_02_d8_resume_owner"
        self.owner_client = _authenticated_client(self.owner_id)

    def test_http_get_requires_the_new_application_seam(self) -> None:
        """Catches a future View bypass of the D8 Application boundary."""

        with patch(
            "chatbot.views.execute_resume_latest_consultation",
            create=True,
            return_value=SimpleNamespace(payload={}),
        ) as execute_resume_latest_consultation:
            response = self.owner_client.get("/api/auth/resume/")

        self.assertEqual(response.status_code, 200, response.content)
        execute_resume_latest_consultation.assert_called_once()

    def test_external_guest_transport_stops_before_the_resume_view(self) -> None:
        credential, _claims = issue_guest_credential("gst_phase_02_d8_resume")
        with patch(
            "chatbot.views._request_access_payload",
            wraps=views._request_access_payload,
        ) as request_access_payload:
            response = Client(
                HTTP_X_GUEST_ID="gst_phase_02_d8_resume",
                HTTP_X_GUEST_CREDENTIAL=credential,
            ).get("/api/auth/resume/")

        self.assertEqual(response.status_code, 401, response.content)
        error = response.json()["error"]
        self.assertEqual(error["code"], "auth_required")
        self.assertEqual(error["auth"]["reason"], "missing_token")
        request_access_payload.assert_not_called()

    def test_direct_view_guest_keeps_login_required_contract(self) -> None:
        credential, _claims = issue_guest_credential("gst_phase_02_d8_resume")
        request = RequestFactory().get(
            "/api/auth/resume/",
            HTTP_X_GUEST_ID="gst_phase_02_d8_resume",
            HTTP_X_GUEST_CREDENTIAL=credential,
        )

        response = views.auth_resume(request)

        self.assertEqual(response.status_code, 403, response.content)
        body = response.content.decode()
        self.assertIn('"contract_version": "login_required.v1"', body)
        self.assertIn('"code": "login_required"', body)
        self.assertIn('"reason": "resume_manifest_requires_authenticated_user"', body)

    def test_user_without_a_session_receives_empty_resume_manifest(self) -> None:
        response = self.owner_client.get("/api/auth/resume/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json(),
            {
                "contract_version": "resume_manifest.v1",
                "has_resume": False,
                "session": None,
                "conversation_messages": [],
                "pending_questions": [],
                "facts": {},
                "fine_notice_intake": None,
                "attachments": [],
                "latest_analysis": None,
                "reports": [],
            },
        )

    def test_selects_latest_owned_session_not_newer_foreign_session(self) -> None:
        now = timezone.now()
        ChatSession.objects.create(
            session_id="ses_phase_02_d8_resume_owner_old",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        newest_owned = ChatSession.objects.create(
            session_id="ses_phase_02_d8_resume_owner_latest",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        newer_foreign = ChatSession.objects.create(
            session_id="ses_phase_02_d8_resume_foreign_newer",
            owner_id="usr_phase_02_d8_resume_foreign",
            status=ChatSessionStatus.ACTIVE,
        )
        ChatSession.objects.filter(session_id="ses_phase_02_d8_resume_owner_old").update(
            updated_at=now - timedelta(hours=2)
        )
        ChatSession.objects.filter(pk=newest_owned.pk).update(updated_at=now - timedelta(hours=1))
        ChatSession.objects.filter(pk=newer_foreign.pk).update(updated_at=now)

        response = self.owner_client.get("/api/auth/resume/")

        self.assertEqual(response.status_code, 200, response.content)
        manifest = response.json()
        self.assertEqual(manifest["session"]["session_id"], newest_owned.session_id)
        self.assertNotIn(newer_foreign.session_id, repr(manifest))

    def test_selects_latest_job_for_the_selected_owned_session(self) -> None:
        from chatbot.models import AnalysisJob, AnalysisJobStatus, ChatMessage

        now = timezone.now()
        session = ChatSession.objects.create(
            session_id="ses_phase_02_d8_resume_job_selection",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        message = ChatMessage.objects.create(
            message_id="msg_phase_02_d8_resume_job_selection",
            session=session,
            role="user",
            content="최신 분석 결과를 재개합니다.",
        )
        older_job = AnalysisJob.objects.create(
            job_id="job_phase_02_d8_resume_older",
            session=session,
            message=message,
            owner_id=self.owner_id,
            status=AnalysisJobStatus.PARTIAL,
        )
        latest_job = AnalysisJob.objects.create(
            job_id="job_phase_02_d8_resume_latest",
            session=session,
            message=message,
            owner_id=self.owner_id,
            status=AnalysisJobStatus.SUCCESS,
        )
        AnalysisJob.objects.filter(pk=older_job.pk).update(updated_at=now - timedelta(hours=1))
        AnalysisJob.objects.filter(pk=latest_job.pk).update(updated_at=now)

        response = self.owner_client.get("/api/auth/resume/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["latest_analysis"]["job_id"], latest_job.job_id)

    def test_excludes_foreign_derived_resources_from_the_owned_session(self) -> None:
        from chatbot.models import Report, ReportStatus, UploadedFile, UploadedFileStatus

        session = ChatSession.objects.create(
            session_id="ses_phase_02_d8_resume_derived_owner",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        UploadedFile.objects.create(
            attachment_id="att_phase_02_d8_resume_owner",
            owner_id=self.owner_id,
            session=session,
            purpose="fine_notice",
            original_filename="owner.pdf",
            storage_uri="s3://private/owner.pdf",
            status=UploadedFileStatus.READY,
            scan_status="clean",
        )
        UploadedFile.objects.create(
            attachment_id="att_phase_02_d8_resume_foreign",
            owner_id="usr_phase_02_d8_resume_foreign",
            session=session,
            purpose="fine_notice",
            original_filename="foreign.pdf",
            storage_uri="s3://private/foreign.pdf",
            status=UploadedFileStatus.READY,
            scan_status="clean",
        )
        Report.objects.create(
            report_id="rep_phase_02_d8_resume_owner",
            owner_id=self.owner_id,
            session=session,
            status=ReportStatus.READY,
            title="owner report",
        )
        Report.objects.create(
            report_id="rep_phase_02_d8_resume_foreign",
            owner_id="usr_phase_02_d8_resume_foreign",
            session=session,
            status=ReportStatus.READY,
            title="foreign report",
        )

        response = self.owner_client.get("/api/auth/resume/")

        self.assertEqual(response.status_code, 200, response.content)
        manifest = response.json()
        self.assertEqual(
            [item["attachment_id"] for item in manifest["attachments"]],
            ["att_phase_02_d8_resume_owner"],
        )
        self.assertEqual(
            [item["report_id"] for item in manifest["reports"]],
            ["rep_phase_02_d8_resume_owner"],
        )
        self.assertNotIn("foreign", repr(manifest))

    def test_projects_only_safe_resume_fields(self) -> None:
        from chatbot.models import UploadedFile, UploadedFileStatus

        session = ChatSession.objects.create(
            session_id="ses_phase_02_d8_resume_privacy",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
            metadata={
                "chat_followup_state": {
                    "contract_version": "chat_session_followup_state.v1",
                    "facts": {
                        "issuing_authority": "서울시",
                        "raw_ocr_text": "private OCR must not leak",
                        "access_token": "private token must not leak",
                    },
                }
            },
        )
        UploadedFile.objects.create(
            attachment_id="att_phase_02_d8_resume_safe_projection",
            owner_id=self.owner_id,
            session=session,
            purpose="fine_notice",
            original_filename="safe.pdf",
            storage_uri="s3://private/safe.pdf",
            status=UploadedFileStatus.READY,
            scan_status="clean",
            metadata={"raw_ocr_text": "private OCR must not leak"},
        )

        response = self.owner_client.get("/api/auth/resume/")

        self.assertEqual(response.status_code, 200, response.content)
        manifest = response.json()
        self.assertEqual(manifest["facts"], {"issuing_authority": "서울시"})
        self.assertEqual(
            manifest["attachments"],
            [
                {
                    "attachment_id": "att_phase_02_d8_resume_safe_projection",
                    "purpose": "fine_notice",
                    "filename": "safe.pdf",
                    "status": "ready",
                    "scan_status": "clean",
                }
            ],
        )
        serialized = repr(manifest)
        self.assertNotIn("private OCR", serialized)
        self.assertNotIn("private token", serialized)
        self.assertNotIn("s3://private", serialized)

    def test_external_guest_transport_does_not_call_the_application_executor(self) -> None:
        credential, _claims = issue_guest_credential("gst_phase_02_d8_resume_executor")
        with patch(
            "chatbot.views.execute_resume_latest_consultation",
            create=True,
        ) as execute_resume_latest_consultation:
            response = Client(
                HTTP_X_GUEST_ID="gst_phase_02_d8_resume_executor",
                HTTP_X_GUEST_CREDENTIAL=credential,
            ).get("/api/auth/resume/")

        self.assertEqual(response.status_code, 401, response.content)
        execute_resume_latest_consultation.assert_not_called()
