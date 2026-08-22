"""RED-first characterization for the FileReadQueries application boundary."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.guest_credential_service import issue_guest_credential
from app.services.google_auth_service import issue_access_token
from chatbot.models import (
    AuthSession,
    AuthSessionStatus,
    ChatSession,
    ChatSessionStatus,
    GuestIdentity,
    GuestIdentityStatus,
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
            execute_application.return_value = SimpleNamespace(
                payload={
                    "attachments": [
                        {"attachment_id": self.owner_attachment.attachment_id}
                    ]
                }
            )
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
            execute_application.return_value = SimpleNamespace(
                payload={"attachment": {"attachment_id": self.owner_attachment.attachment_id}}
            )
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


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class FileReadSecurityBoundaryTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_phase_02_d10_security_owner"
        self.foreign_owner_id = "usr_phase_02_d10_security_foreign"
        self.owner_client = authenticated_client(self.owner_id)
        self.foreign_client = authenticated_client(self.foreign_owner_id)
        self.owner_session = ChatSession.objects.create(
            session_id="ses_phase_02_d10_security_owner",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        self.owner_other_session = ChatSession.objects.create(
            session_id="ses_phase_02_d10_security_owner_other",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        self.foreign_session = ChatSession.objects.create(
            session_id="ses_phase_02_d10_security_foreign",
            owner_id=self.foreign_owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        self.guest_id = "gst_phase_02_d10_security"
        GuestIdentity.objects.create(
            guest_id=self.guest_id,
            status=GuestIdentityStatus.ACTIVE,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        self.guest_session = ChatSession.objects.create(
            session_id="ses_phase_02_d10_security_guest",
            owner_id="",
            status=ChatSessionStatus.ACTIVE,
            metadata={"auth_context": {"guest_id": self.guest_id}},
        )
        self.owner_attachment = self._attachment(
            attachment_id="att_phase_02_d10_security_owner",
            owner_id=self.owner_id,
            session=self.owner_session,
            filename="owner-private-evidence.png",
        )
        self.foreign_attachment = self._attachment(
            attachment_id="att_phase_02_d10_security_foreign",
            owner_id=self.foreign_owner_id,
            session=self.foreign_session,
            filename="foreign-private-evidence.png",
        )
        self.guest_attachment = self._attachment(
            attachment_id="att_phase_02_d10_security_guest",
            owner_id="",
            session=self.guest_session,
            filename="guest-private-evidence.png",
        )
        guest_credential, _claims = issue_guest_credential(self.guest_id)
        self.guest_client = Client(
            HTTP_X_GUEST_ID=self.guest_id,
            HTTP_X_GUEST_CREDENTIAL=guest_credential,
        )

    def _attachment(
        self,
        *,
        attachment_id: str,
        owner_id: str,
        session: ChatSession,
        filename: str,
    ) -> UploadedFile:
        return UploadedFile.objects.create(
            attachment_id=attachment_id,
            owner_id=owner_id,
            session=session,
            purpose="evidence",
            file_type="image",
            original_filename=filename,
            content_type="image/png",
            size_bytes=128,
            storage_uri=f"s3://private/{filename}",
            status=UploadedFileStatus.READY,
            scan_status="clean",
            metadata={
                "filename": filename,
                "checks": {"internal_repository": "uploaded_files"},
                "scan_result": {"provider_payload": "private"},
            },
            agent_handoff={"worker_payload": "private"},
        )

    def test_valid_guest_without_session_cannot_enumerate_cross_owner_attachments(self) -> None:
        response = self.guest_client.get("/api/files/")

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")
        self.assertNotIn(self.foreign_attachment.attachment_id, response.content.decode())

    def test_anonymous_request_cannot_enumerate_global_attachment_metadata(self) -> None:
        response = Client().get("/api/files/")

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["code"], "auth_required")
        self.assertNotIn(self.foreign_attachment.attachment_id, response.content.decode())

    def test_authenticated_owner_without_session_is_owner_scoped(self) -> None:
        response = self.owner_client.get("/api/files/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            [item["attachment_id"] for item in response.json()["attachments"]],
            [self.owner_attachment.attachment_id],
        )

    def test_foreign_existing_session_preserves_object_access_denied_contract(self) -> None:
        response = self.owner_client.get(
            "/api/files/",
            {"session_id": self.foreign_session.session_id},
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")

    def test_unknown_session_preserves_empty_owner_scoped_list_contract(self) -> None:
        response = self.owner_client.get(
            "/api/files/",
            {"session_id": "ses_phase_02_d10_security_unknown"},
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["attachments"], [])

    def test_expired_guest_detail_uses_canonical_guest_identity_policy(self) -> None:
        GuestIdentity.objects.filter(guest_id=self.guest_id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        response = self.guest_client.get(
            f"/api/files/{self.guest_attachment.attachment_id}/",
            {"session_id": self.guest_session.session_id},
        )

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["code"], "guest_session_invalid")

    def test_invalid_or_forged_guest_detail_uses_identity_error_contract(self) -> None:
        forged_credential, _claims = issue_guest_credential("gst_phase_02_d10_other")
        invalid_clients = {
            "malformed": Client(
                HTTP_X_GUEST_ID=self.guest_id,
                HTTP_X_GUEST_CREDENTIAL="malformed-guest-credential",
            ),
            "forged_pair": Client(
                HTTP_X_GUEST_ID=self.guest_id,
                HTTP_X_GUEST_CREDENTIAL=forged_credential,
            ),
        }

        for scenario, client in invalid_clients.items():
            with self.subTest(scenario=scenario):
                response = client.get(
                    f"/api/files/{self.guest_attachment.attachment_id}/",
                    {"session_id": self.guest_session.session_id},
                )

                self.assertEqual(response.status_code, 401, response.content)
                self.assertEqual(response.json()["error"]["code"], "token_invalid")

    def test_detail_rejects_supplied_authorized_but_unrelated_session_scope(self) -> None:
        response = self.owner_client.get(
            f"/api/files/{self.owner_attachment.attachment_id}/",
            {"session_id": self.owner_other_session.session_id},
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")

    def test_foreign_owner_detail_preserves_object_access_denied_contract(self) -> None:
        response = self.owner_client.get(
            f"/api/files/{self.foreign_attachment.attachment_id}/",
            {"session_id": self.foreign_session.session_id},
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")

    def test_list_and_detail_exclude_private_attachment_metadata(self) -> None:
        private_fields = {
            "agent_handoff",
            "checks",
            "deleted_at",
            "object_storage",
            "persistence",
            "scan_result",
            "storage_uri",
        }
        list_response = self.owner_client.get("/api/files/")
        detail_response = self.owner_client.get(
            f"/api/files/{self.owner_attachment.attachment_id}/",
            {"session_id": self.owner_session.session_id},
        )

        self.assertEqual(list_response.status_code, 200, list_response.content)
        self.assertEqual(detail_response.status_code, 200, detail_response.content)
        list_attachment = list_response.json()["attachments"][0]
        detail_attachment = detail_response.json()["attachment"]
        self.assertFalse(private_fields.intersection(list_attachment), list_attachment)
        self.assertFalse(private_fields.intersection(detail_attachment), detail_attachment)
    def test_foreign_owner_detail_without_optional_session_is_denied(self) -> None:
        response = self.owner_client.get(
            f"/api/files/{self.foreign_attachment.attachment_id}/",
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")