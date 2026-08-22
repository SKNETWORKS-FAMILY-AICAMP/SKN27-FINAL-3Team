"""RED-first characterization for the FileReadQueries application boundary."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from chatbot.models import (
    AuthSession,
    AuthSessionStatus,
    ChatSession,
    ChatSessionStatus,
    UploadedFile,
    UploadedFileStatus,
    UserAccount,
)


TEST_JWT_SIGNING_KEY = "phase-02-d10-file-read-queries-signing-key-is-long-enough"


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
class FileReadQueriesApplicationSeamTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_phase_02_d10_owner"
        self.owner_client = authenticated_client(self.owner_id)
        self.owner_session = ChatSession.objects.create(
            session_id="ses_phase_02_d10_owner",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        self.owner_attachment = UploadedFile.objects.create(
            attachment_id="att_phase_02_d10_owner",
            owner_id=self.owner_id,
            session=self.owner_session,
            purpose="evidence",
            file_type="image",
            original_filename="owner-evidence.png",
            content_type="image/png",
            size_bytes=128,
            storage_uri="s3://private/owner-evidence.png",
            status=UploadedFileStatus.READY,
            scan_status="clean",
        )

    def test_file_list_delegates_to_execute_list_file_attachments(self) -> None:
        with patch(
            "chatbot.views.execute_list_file_attachments",
            create=True,
        ) as execute_application:
            response = self.owner_client.get(
                "/api/files/",
                {"session_id": self.owner_session.session_id},
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            [item["attachment_id"] for item in response.json()["attachments"]],
            [self.owner_attachment.attachment_id],
        )
        execute_application.assert_called_once()

    def test_file_detail_delegates_to_execute_get_file_attachment(self) -> None:
        with patch(
            "chatbot.views.execute_get_file_attachment",
            create=True,
        ) as execute_application:
            response = self.owner_client.get(
                f"/api/files/{self.owner_attachment.attachment_id}/",
                {"session_id": self.owner_session.session_id},
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json()["attachment"]["attachment_id"],
            self.owner_attachment.attachment_id,
        )
        execute_application.assert_called_once()
