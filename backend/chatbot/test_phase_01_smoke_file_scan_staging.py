from __future__ import annotations

import json
import os
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from app.services.attachment_staging_service import _staging_root
from chatbot.models import UploadedFile
from chatbot.object_storage import _local_staging_root


class NeutralFileScanSmokeTests(TestCase):
    def test_default_staging_root_is_shared_local_object_storage_scope(self) -> None:
        expected_root = (
            Path.cwd() / "backend" / "media" / "mock_object_storage" / "attachment_staging"
        ).resolve()
        with patch.dict(os.environ, {"ATTACHMENT_STAGING_ROOT": ""}):
            with override_settings(ATTACHMENT_STAGING_ROOT=""):
                self.assertEqual(_staging_root(), expected_root)
                self.assertEqual(_local_staging_root(), expected_root)

    def test_staging_and_object_storage_share_settings_environment_default_order(self) -> None:
        with tempfile.TemporaryDirectory() as configured_root, tempfile.TemporaryDirectory() as environment_root:
            with patch.dict(os.environ, {"ATTACHMENT_STAGING_ROOT": environment_root}):
                with override_settings(ATTACHMENT_STAGING_ROOT=configured_root):
                    self.assertEqual(_staging_root(), _local_staging_root())
                    self.assertEqual(_staging_root(), Path(configured_root).resolve())

    def test_upload_phase_uses_neutral_staging_and_never_persists_mock_uri(self) -> None:
        with tempfile.TemporaryDirectory() as staging_root, tempfile.TemporaryDirectory() as object_root:
            with override_settings(
                ATTACHMENT_STAGING_ROOT=staging_root,
                OBJECT_STORAGE_PROVIDER="mock_s3",
                OBJECT_STORAGE_LOCAL_ROOT=object_root,
            ):
                output = StringIO()
                call_command(
                    "smoke_file_scan",
                    "--phase",
                    "upload",
                    "--attachment-id",
                    "att_phase_01_smoke",
                    "--session-id",
                    "ses_phase_01_smoke",
                    "--format",
                    "json",
                    stdout=output,
                )

        result = json.loads(output.getvalue())
        uploaded_file = UploadedFile.objects.get(attachment_id="att_phase_01_smoke")
        source_uri = str(uploaded_file.metadata.get("source_storage_uri") or "")

        self.assertEqual(result["status"], "pass")
        self.assertTrue(source_uri.startswith("local://attachment-staging/"), source_uri)
        self.assertNotIn("mock://", source_uri)
        self.assertNotIn("mock://", repr(uploaded_file.metadata))
