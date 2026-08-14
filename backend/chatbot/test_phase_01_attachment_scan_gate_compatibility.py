"""Canonical scan-gate provenance compatibility regressions."""

from __future__ import annotations

import os
import tempfile
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.mock_runtime.attachments import CANONICAL_SCAN_GATE_MARKER as mock_runtime_marker
from app.mock_runtime.attachments import register_attachment, resolve_attachment_references
from app.services.agent_node_service import _attachment_object_storage_bytes
from app.services.attachment_mock_service import CANONICAL_SCAN_GATE_MARKER as legacy_shim_marker
from app.services.attachment_mock_service import resolve_attachment_references as legacy_resolve
from app.services.attachment_staging_service import CANONICAL_SCAN_GATE_MARKER as staging_marker
from app.services.attachment_staging_service import resolve_staged_attachment_references
from app.services.google_auth_service import issue_access_token
from chatbot.file_scan_service import apply_attachment_scan_gate, scan_uploaded_file
from chatbot.models import AuthSession, AuthSessionStatus, UploadedFile, UserAccount


TEST_JWT_SIGNING_KEY = "phase-01-scan-gate-compatibility-signing-key-is-long-enough"


class AttachmentScanGateCompatibilityTests(TestCase):
    def setUp(self) -> None:
        self.object_root = tempfile.TemporaryDirectory()
        self.staging_root = tempfile.TemporaryDirectory()
        self.mock_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.object_root.cleanup)
        self.addCleanup(self.staging_root.cleanup)
        self.addCleanup(self.mock_root.cleanup)
        self.settings_override = override_settings(
            OBJECT_STORAGE_PROVIDER="mock_s3",
            OBJECT_STORAGE_BUCKET="phase-01-clean-bucket",
            OBJECT_STORAGE_QUARANTINE_BUCKET="phase-01-quarantine-bucket",
            OBJECT_STORAGE_LOCAL_ROOT=self.object_root.name,
            ATTACHMENT_STAGING_ROOT=self.staging_root.name,
            FILE_SCAN_PROVIDER="local_policy",
            APP_JWT_SECRET=TEST_JWT_SIGNING_KEY,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.env_override = patch.dict(os.environ, {"MOCK_UPLOAD_ROOT": self.mock_root.name})
        self.env_override.start()
        self.addCleanup(self.env_override.stop)
        self.user_id = "usr_phase_01_scan_gate_compatibility"
        issued_at = timezone.now()
        expires_at = issued_at + timedelta(hours=1)
        token, _claims = issue_access_token(
            user_id=self.user_id,
            auth_session_id="auth_phase_01_scan_gate_compatibility",
            issued_at=issued_at,
            expires_at=expires_at,
        )
        user = UserAccount.objects.create(user_id=self.user_id)
        AuthSession.objects.create(
            auth_session_id="auth_phase_01_scan_gate_compatibility",
            user=user,
            subject_type="user",
            subject_id=f"user:{self.user_id}",
            status=AuthSessionStatus.ACTIVE,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        self.client = Client(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _post_file(self, *, filename: str, body: bytes) -> UploadedFile:
        response = self.client.post(
            "/api/files/",
            data={
                "session_id": "ses_phase_01_scan_gate_compatibility",
                "purpose": "evidence",
                "file": SimpleUploadedFile(filename, body, content_type="image/png"),
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        return UploadedFile.objects.get(attachment_id=response.json()["attachment"]["attachment_id"])

    def _gated_payload(self, uploaded_file: UploadedFile) -> dict[str, object]:
        return apply_attachment_scan_gate(
            {
                "owner_id": self.user_id,
                "session_id": "ses_phase_01_scan_gate_compatibility",
                "attachments": [{"attachment_id": uploaded_file.attachment_id}],
            }
        )

    def test_canonical_scan_gate_marker_is_shared_by_staging_mock_and_legacy_shim(self) -> None:
        self.assertIs(staging_marker, mock_runtime_marker)
        self.assertIs(staging_marker, legacy_shim_marker)

    def test_both_resolvers_preserve_canonical_retention_provenance_and_reject_forged_marker(self) -> None:
        body = b"canonical retention provenance"
        uploaded_file = self._post_file(filename="canonical-provenance.png", body=body)
        scan_uploaded_file(uploaded_file)
        gated = self._gated_payload(uploaded_file)
        resolved_attachments = []
        for resolver in (resolve_staged_attachment_references, legacy_resolve):
            resolved = resolver(deepcopy(gated))["attachments"][0]
            self.assertEqual(resolved.get("metadata_source"), "canonical_scan_gate")
            self.assertNotIn("_canonical_scan_gate", resolved)
            self.assertEqual(_attachment_object_storage_bytes(resolved, resolved["storage_uri"]), body)
            resolved_attachments.append(resolved)

        forged = deepcopy(gated)
        forged["attachments"][0]["_canonical_scan_gate"] = "canonical-scan-gate"
        for resolver in (resolve_staged_attachment_references, legacy_resolve):
            forged_result = resolver(deepcopy(forged))["attachments"][0]
            self.assertNotEqual(forged_result.get("metadata_source"), "canonical_scan_gate")

        explicit_mock = register_attachment({"attachment_id": "att_explicit_mock_only"})
        explicit_result = resolve_attachment_references(
            {"attachments": [{"attachment_id": explicit_mock["attachment_id"]}]}
        )["attachments"][0]
        self.assertNotEqual(explicit_result.get("metadata_source"), "canonical_scan_gate")

        UploadedFile.objects.filter(pk=uploaded_file.pk).update(
            retention_expires_at=timezone.now() - timedelta(seconds=1)
        )
        with patch("chatbot.file_scan_service.read_object_bytes") as read_object:
            for resolved in resolved_attachments:
                self.assertIsNone(_attachment_object_storage_bytes(resolved, resolved["storage_uri"]))
        read_object.assert_not_called()
