"""Authenticated resume-manifest API regression coverage."""

from __future__ import annotations

from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from chatbot.models import (
    AnalysisDisplayResult,
    AnalysisJob,
    AnalysisJobStatus,
    AuthSession,
    AuthSessionStatus,
    ChatMessage,
    ChatSession,
    ChatSessionStatus,
    Report,
    ReportStatus,
    UploadedFile,
    UploadedFileStatus,
    UserAccount,
)


TEST_JWT_SIGNING_KEY = "resume-manifest-test-signing-key-is-long-enough"


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
class ResumeManifestApiTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_resume_owner"
        self.client = _authenticated_client(self.owner_id)
        self.session = ChatSession.objects.create(
            session_id="ses_resume_latest",
            owner_id=self.owner_id,
            title="과태료 상담",
            status=ChatSessionStatus.ACTIVE,
            current_intent="fine_notice_analysis",
            metadata={
                "chat_followup_state": {
                    "contract_version": "chat_session_followup_state.v1",
                    "facts": {"issuing_authority": "서울시"},
                    "pending_questions": [
                        {
                            "field": "response_deadline",
                            "question": "의견제출 기한을 알려주세요.",
                        }
                    ],
                    "fine_notice_intake": {
                        "contract_version": "fine_notice_intake.v1",
                        "slots": {
                            "issuing_authority": {
                                "value": "서울시",
                                "source_type": "user_confirmation",
                                "source_message_id": "msg_resume_user",
                                "confidence": 1.0,
                                "confirmed": True,
                            }
                        },
                    },
                    "raw_ocr_text": "private OCR must not leak",
                }
            },
        )
        user_message = ChatMessage.objects.create(
            message_id="msg_resume_user",
            session=self.session,
            role="user",
            content="서울시에서 받은 사전통지서입니다.",
            routing_intent="fine_notice_analysis",
        )
        ChatMessage.objects.create(
            message_id="msg_resume_assistant",
            session=self.session,
            role="assistant",
            content="의견제출 기한을 알려주세요.",
            routing_intent="fine_notice_analysis",
        )
        UploadedFile.objects.create(
            attachment_id="att_resume_notice",
            owner_id=self.owner_id,
            session=self.session,
            purpose="fine_notice",
            file_type="pdf",
            original_filename="notice.pdf",
            content_type="application/pdf",
            storage_uri="s3://private-bucket/notice.pdf",
            status=UploadedFileStatus.READY,
            scan_status="clean",
            metadata={"raw_ocr_text": "private OCR must not leak"},
        )
        job = AnalysisJob.objects.create(
            job_id="job_resume_latest",
            session=self.session,
            message=user_message,
            owner_id=self.owner_id,
            routing_intent="fine_notice_analysis",
            status=AnalysisJobStatus.PARTIAL,
            active_node="fine_notice_analysis",
            progress_message="기한 확인이 필요합니다.",
            metadata={
                "supervisor_state": {
                    "contract_version": "supervisor_conversation_state.v2",
                    "stage": "need_more_input",
                    "collected_facts": {"issuing_authority": "서울시"},
                    "next_questions": [
                        {
                            "field": "response_deadline",
                            "question": "의견제출 기한을 알려주세요.",
                        }
                    ],
                    "prompt": "private prompt must not leak",
                },
                "attachments": [
                    {
                        "attachment_id": "att_resume_notice",
                        "purpose": "fine_notice",
                        "filename": "notice.pdf",
                        "status": "ready",
                        "scan_status": "clean",
                        "storage_uri": "s3://private-bucket/notice.pdf",
                    }
                ],
            },
        )
        display = AnalysisDisplayResult.objects.create(
            display_result_id="display_resume_latest",
            job=job,
            assistant_message={
                "answer": "의견제출 기한을 알려주세요.",
                "summary": "기한 확인이 필요합니다.",
            },
            pending_questions=[
                {
                    "field": "response_deadline",
                    "question": "의견제출 기한을 알려주세요.",
                }
            ],
            attachments=[
                {
                    "attachment_id": "att_resume_notice",
                    "purpose": "fine_notice",
                    "filename": "notice.pdf",
                    "status": "ready",
                    "scan_status": "clean",
                    "storage_uri": "s3://private-bucket/notice.pdf",
                }
            ],
        )
        Report.objects.create(
            report_id="rep_resume_latest",
            owner_id=self.owner_id,
            session=self.session,
            job=job,
            display_result=display,
            status=ReportStatus.READY,
            title="과태료 이의신청 검토",
            storage_uri="s3://private-bucket/report.docx",
            content_summary="검토 가능한 초안입니다.",
            content={"raw_ocr_text": "private OCR must not leak"},
        )

        foreign_user = UserAccount.objects.create(user_id="usr_resume_foreign")
        ChatSession.objects.create(
            session_id="ses_resume_foreign_newer",
            owner_id=foreign_user.user_id,
            status=ChatSessionStatus.ACTIVE,
        )

    def test_returns_latest_owned_session_and_only_safe_resume_fields(self) -> None:
        response = self.client.get("/api/auth/resume/")

        self.assertEqual(response.status_code, 200, response.content)
        manifest = response.json()
        self.assertEqual(manifest["contract_version"], "resume_manifest.v1")
        self.assertTrue(manifest["has_resume"])
        self.assertEqual(manifest["session"]["session_id"], "ses_resume_latest")
        self.assertEqual(
            [item["role"] for item in manifest["conversation_messages"]],
            ["user", "assistant"],
        )
        self.assertEqual(
            manifest["pending_questions"][0]["field"],
            "response_deadline",
        )
        self.assertEqual(manifest["facts"], {"issuing_authority": "서울시"})
        self.assertEqual(
            manifest["attachments"],
            [
                {
                    "attachment_id": "att_resume_notice",
                    "purpose": "fine_notice",
                    "filename": "notice.pdf",
                    "status": "ready",
                    "scan_status": "clean",
                }
            ],
        )
        self.assertEqual(
            manifest["latest_analysis"]["job_id"],
            "job_resume_latest",
        )
        self.assertEqual(manifest["reports"][0]["report_id"], "rep_resume_latest")
        serialized = repr(manifest)
        for private_value in (
            "s3://",
            "private OCR",
            "private prompt",
            "ses_resume_foreign_newer",
            "raw_ocr_text",
            "storage_uri",
        ):
            self.assertNotIn(private_value, serialized)

    def test_requires_an_authenticated_user(self) -> None:
        response = Client().get("/api/auth/resume/")

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["code"], "auth_required")
