from __future__ import annotations

import json
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from chatbot.file_retention_service import purge_expired_uploads
from chatbot.models import UploadedFile, UploadedFileStatus
from chatbot.object_storage import (
    build_quarantine_upload_storage_reference,
    build_upload_storage_reference,
    object_exists,
    write_object,
)
from app.services.attachment_mock_service import register_attachment


class FileRetentionPurgeTests(TestCase):
    def setUp(self) -> None:
        self.object_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.object_root.cleanup)
        self.settings_override = override_settings(
            OBJECT_STORAGE_PROVIDER="mock_s3",
            OBJECT_STORAGE_BUCKET="retention-clean",
            OBJECT_STORAGE_QUARANTINE_BUCKET="retention-quarantine",
            OBJECT_STORAGE_PREFIX="canonical",
            OBJECT_STORAGE_LOCAL_ROOT=self.object_root.name,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def _expired_upload(
        self,
        attachment_id: str,
        *,
        write_clean: bool = True,
        write_quarantine: bool = True,
    ) -> tuple[UploadedFile, dict, dict]:
        attachment = {
            "attachment_id": attachment_id,
            "session_id": "ses-retention",
            "filename": "private-evidence.txt",
            "content_type": "text/plain",
            "size_bytes": 16,
        }
        clean = build_upload_storage_reference(attachment, owner_id="usr-private")
        quarantine = build_quarantine_upload_storage_reference(
            attachment,
            owner_id="usr-private",
        )
        if write_clean:
            self.assertEqual(write_object(clean, b"clean-private-data")["status"], "written")
        if write_quarantine:
            self.assertEqual(
                write_object(quarantine, b"quarantine-private-data")["status"],
                "written",
            )
        uploaded_file = UploadedFile.objects.create(
            attachment_id=attachment_id,
            owner_id="usr-private",
            purpose="fine_notice",
            file_type="document",
            original_filename="private-evidence.txt",
            content_type="text/plain",
            size_bytes=16,
            storage_uri=clean["storage_uri"],
            privacy_risk=True,
            status=UploadedFileStatus.READY,
            scan_status="clean",
            agent_handoff={"storage_uri": clean["storage_uri"], "private": "value"},
            metadata={
                "private_text": "resident-number-like private value",
                "upload_storage_lifecycle": {
                    "contract_version": "upload_storage_lifecycle.v1",
                    "quarantine": quarantine,
                    "clean": clean,
                },
            },
            retention_expires_at=timezone.now() - timedelta(minutes=1),
        )
        return uploaded_file, clean, quarantine

    def test_expired_upload_deletes_both_objects_and_scrubs_tombstone(self) -> None:
        uploaded_file, clean, quarantine = self._expired_upload("att-retention-success")

        result = purge_expired_uploads(limit=10)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["selected"], 1)
        self.assertEqual(result["purged"], 1)
        self.assertEqual(result["retryable"], 0)
        self.assertFalse(object_exists(clean))
        self.assertFalse(object_exists(quarantine))

        uploaded_file.refresh_from_db()
        self.assertEqual(uploaded_file.status, UploadedFileStatus.DELETED)
        self.assertEqual(uploaded_file.scan_status, "purged")
        self.assertIsNotNone(uploaded_file.deleted_at)
        self.assertEqual(uploaded_file.owner_id, "")
        self.assertEqual(uploaded_file.original_filename, "")
        self.assertEqual(uploaded_file.content_type, "")
        self.assertIsNone(uploaded_file.size_bytes)
        self.assertEqual(uploaded_file.storage_uri, "")
        self.assertEqual(uploaded_file.agent_handoff, {})
        self.assertEqual(set(uploaded_file.metadata), {"retention_purge"})
        self.assertEqual(uploaded_file.metadata["retention_purge"]["status"], "purged")

    def test_non_expired_upload_is_untouched(self) -> None:
        uploaded_file, clean, quarantine = self._expired_upload("att-retention-future")
        UploadedFile.objects.filter(pk=uploaded_file.pk).update(
            retention_expires_at=timezone.now() + timedelta(days=1)
        )

        result = purge_expired_uploads(limit=10)

        self.assertEqual(result["selected"], 0)
        self.assertEqual(result["purged"], 0)
        uploaded_file.refresh_from_db()
        self.assertEqual(uploaded_file.status, UploadedFileStatus.READY)
        self.assertTrue(object_exists(clean))
        self.assertTrue(object_exists(quarantine))

    def test_explicitly_deleted_upload_is_purged_before_retention_deadline(self) -> None:
        uploaded_file, clean, quarantine = self._expired_upload(
            "att-retention-explicit-delete"
        )
        UploadedFile.objects.filter(pk=uploaded_file.pk).update(
            status=UploadedFileStatus.DELETED,
            deleted_at=timezone.now(),
            retention_expires_at=timezone.now() + timedelta(days=30),
        )

        result = purge_expired_uploads(limit=10)

        self.assertEqual(result["purged"], 1)
        uploaded_file.refresh_from_db()
        self.assertEqual(uploaded_file.scan_status, "purged")
        self.assertFalse(object_exists(clean))
        self.assertFalse(object_exists(quarantine))

    def test_every_nonterminal_scan_state_is_physically_purged(self) -> None:
        uploaded_files = []
        quarantine_references = []
        for suffix, status, scan_status in (
            ("pending", UploadedFileStatus.PENDING, "awaiting_upload"),
            ("scanning", UploadedFileStatus.SCANNING, "scanning"),
            ("rejected", UploadedFileStatus.REJECTED, "rejected"),
        ):
            uploaded_file, _clean, quarantine = self._expired_upload(
                f"att-retention-{suffix}",
                write_clean=False,
            )
            UploadedFile.objects.filter(pk=uploaded_file.pk).update(
                status=status,
                scan_status=scan_status,
            )
            uploaded_files.append(uploaded_file)
            quarantine_references.append(quarantine)

        result = purge_expired_uploads(limit=10)

        self.assertEqual(result["purged"], 3)
        for uploaded_file, quarantine in zip(
            uploaded_files,
            quarantine_references,
            strict=True,
        ):
            uploaded_file.refresh_from_db()
            self.assertEqual(uploaded_file.scan_status, "purged")
            self.assertFalse(object_exists(quarantine))

    def test_failed_object_delete_is_fenced_and_retried_idempotently(self) -> None:
        uploaded_file, clean, quarantine = self._expired_upload("att-retention-retry")

        with patch(
            "chatbot.file_retention_service.delete_object",
            side_effect=[
                {"status": "deleted"},
                {"status": "skipped", "reason": "storage_unavailable"},
            ],
        ):
            failed = purge_expired_uploads(limit=10)

        self.assertEqual(failed["status"], "warn")
        self.assertEqual(failed["purged"], 0)
        self.assertEqual(failed["retryable"], 1)
        uploaded_file.refresh_from_db()
        self.assertEqual(uploaded_file.status, UploadedFileStatus.DELETED)
        self.assertEqual(uploaded_file.scan_status, "retention_purge_retry")
        self.assertIsNotNone(uploaded_file.deleted_at)
        self.assertEqual(uploaded_file.agent_handoff, {})
        self.assertIn("upload_storage_lifecycle", uploaded_file.metadata)

        retried = purge_expired_uploads(limit=10)

        self.assertEqual(retried["status"], "pass")
        self.assertEqual(retried["purged"], 1)
        uploaded_file.refresh_from_db()
        self.assertEqual(uploaded_file.scan_status, "purged")
        self.assertFalse(object_exists(clean))
        self.assertFalse(object_exists(quarantine))

    def test_s3_clean_delete_requires_permanent_version_verification(self) -> None:
        uploaded_file, _clean, _quarantine = self._expired_upload(
            "att-retention-version-proof"
        )
        metadata = dict(uploaded_file.metadata)
        lifecycle = dict(metadata["upload_storage_lifecycle"])
        lifecycle["clean"] = {**lifecycle["clean"], "provider": "s3"}
        lifecycle["quarantine"] = {
            **lifecycle["quarantine"],
            "provider": "s3",
        }
        metadata["upload_storage_lifecycle"] = lifecycle
        UploadedFile.objects.filter(pk=uploaded_file.pk).update(metadata=metadata)

        with patch(
            "chatbot.file_retention_service.delete_object",
            side_effect=[
                {"status": "deleted", "provider": "s3"},
                {"status": "deleted", "provider": "s3"},
            ],
        ):
            result = purge_expired_uploads(limit=10)

        self.assertEqual(result["purged"], 0)
        self.assertEqual(result["retryable"], 1)
        uploaded_file.refresh_from_db()
        self.assertEqual(uploaded_file.scan_status, "retention_purge_retry")
        self.assertEqual(
            uploaded_file.metadata["retention_purge"]["clean"]["reason"],
            "permanent_delete_unverified",
        )

    def test_missing_objects_are_an_idempotent_success(self) -> None:
        uploaded_file, _clean, _quarantine = self._expired_upload(
            "att-retention-missing",
            write_clean=False,
            write_quarantine=False,
        )

        result = purge_expired_uploads(limit=10)

        self.assertEqual(result["purged"], 1)
        uploaded_file.refresh_from_db()
        self.assertEqual(uploaded_file.scan_status, "purged")

    def test_retention_removes_legacy_local_upload_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as upload_root:
            with (
                override_settings(MOCK_UPLOAD_ROOT=upload_root),
                patch.dict("os.environ", {"MOCK_UPLOAD_ROOT": upload_root}),
            ):
                attachment = register_attachment(
                    {
                        "session_id": "ses-retention",
                        "filename": "legacy-private.txt",
                        "content_type": "text/plain",
                        "purpose": "evidence",
                    },
                    upload_file=type(
                        "Upload",
                        (),
                        {
                            "name": "legacy-private.txt",
                            "content_type": "text/plain",
                            "chunks": lambda self: [b"legacy private bytes"],
                        },
                    )(),
                )
                uploaded_file, _clean, _quarantine = self._expired_upload(
                    attachment["attachment_id"],
                )
                metadata = dict(uploaded_file.metadata)
                metadata["source_storage_uri"] = attachment["storage_uri"]
                UploadedFile.objects.filter(pk=uploaded_file.pk).update(
                    metadata=metadata,
                )
                attachment_dir = Path(upload_root) / attachment["attachment_id"]
                self.assertTrue((attachment_dir / "metadata.json").exists())

                result = purge_expired_uploads(limit=10)

                self.assertEqual(result["purged"], 1)
                self.assertFalse(attachment_dir.exists())

    def test_local_sidecar_delete_failure_stays_retryable(self) -> None:
        uploaded_file, _clean, _quarantine = self._expired_upload(
            "att-retention-local-retry"
        )
        metadata = dict(uploaded_file.metadata)
        metadata["source_storage_uri"] = (
            "mock://uploads/att-retention-local-retry/private-evidence.txt"
        )
        UploadedFile.objects.filter(pk=uploaded_file.pk).update(metadata=metadata)

        with patch(
            "chatbot.file_retention_service.delete_source_uri",
            side_effect=OSError("local cleanup failed"),
        ):
            result = purge_expired_uploads(limit=10)

        self.assertEqual(result["purged"], 0)
        self.assertEqual(result["retryable"], 1)
        uploaded_file.refresh_from_db()
        self.assertEqual(uploaded_file.scan_status, "retention_purge_retry")
        self.assertEqual(
            uploaded_file.metadata["upload_storage_lifecycle"]["source_uri"],
            "mock://uploads/att-retention-local-retry/private-evidence.txt",
        )

    def test_legacy_storage_uri_is_preserved_and_physically_deleted(self) -> None:
        uploaded_file, clean, _quarantine = self._expired_upload(
            "att-retention-legacy-uri",
            write_quarantine=False,
        )
        UploadedFile.objects.filter(pk=uploaded_file.pk).update(
            metadata={},
            storage_uri=clean["storage_uri"],
        )

        result = purge_expired_uploads(limit=10)

        self.assertEqual(result["purged"], 1)
        self.assertFalse(object_exists(clean))
        uploaded_file.refresh_from_db()
        self.assertEqual(uploaded_file.scan_status, "purged")

    def test_dry_run_reports_without_mutation(self) -> None:
        uploaded_file, clean, quarantine = self._expired_upload("att-retention-dry-run")

        result = purge_expired_uploads(limit=10, dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["selected"], 1)
        self.assertEqual(result["purged"], 0)
        uploaded_file.refresh_from_db()
        self.assertEqual(uploaded_file.status, UploadedFileStatus.READY)
        self.assertTrue(object_exists(clean))
        self.assertTrue(object_exists(quarantine))

    def test_management_command_outputs_only_aggregate_json(self) -> None:
        self._expired_upload("att-retention-command")
        output = StringIO()

        call_command(
            "purge_expired_uploads",
            "--limit",
            "10",
            "--format",
            "json",
            stdout=output,
        )

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["contract_version"], "file_retention_purge_batch.v1")
        self.assertEqual(payload["purged"], 1)
        self.assertNotIn("att-retention-command", output.getvalue())
        self.assertNotIn("private-evidence", output.getvalue())

    def test_scan_worker_loop_also_enforces_retention(self) -> None:
        uploaded_file, clean, quarantine = self._expired_upload(
            "att-retention-scan-worker"
        )
        output = StringIO()

        call_command(
            "process_uploaded_file_scans",
            "--limit",
            "0",
            "--purge-limit",
            "10",
            "--format",
            "json",
            stdout=output,
        )

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["retention_purge"]["purged"], 1)
        uploaded_file.refresh_from_db()
        self.assertEqual(uploaded_file.scan_status, "purged")
        self.assertFalse(object_exists(clean))
        self.assertFalse(object_exists(quarantine))
