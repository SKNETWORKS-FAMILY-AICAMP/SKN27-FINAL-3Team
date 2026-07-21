"""Regression tests for the quarantine-first upload and scan pipeline."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import timedelta
from io import BytesIO
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.guest_credential_service import issue_guest_credential
from app.services.google_auth_service import issue_access_token
from app.services.agent_node_service import _attachment_object_storage_bytes
from app.services.attachment_mock_service import resolve_attachment_references
from chatbot import file_scan_service
from chatbot.file_scan_service import (
    apply_attachment_scan_gate,
    process_uploaded_file_scans,
    scan_uploaded_file,
)
from chatbot.models import (
    AgentWorkItem,
    AgentWorkItemStatus,
    AnalysisJob,
    AnalysisJobStatus,
    AuthSession,
    AuthSessionStatus,
    ChatSession,
    GuestIdentity,
    GuestIdentityStatus,
    UsageEvent,
    UploadedFile,
    UploadedFileStatus,
    UserAccount,
)
from chatbot.object_storage import copy_object, read_object_bytes, write_object
from chatbot.repositories import (
    _execute_agent_work_item_plan,
    process_agent_work_item,
)


EICAR_TEST_BYTES = (
    b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)
TEST_JWT_SIGNING_KEY = "file-quarantine-test-signing-key-is-long-enough"


class FakeS3Client:
    """Small stateful S3 double that preserves object-store side effects."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.put_calls: list[dict[str, object]] = []
        self.copy_calls: list[dict[str, object]] = []
        self.head_calls: list[dict[str, object]] = []

    def put_object(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        body = bytes(kwargs["Body"])
        self.objects[(bucket, key)] = body
        self.put_calls.append(dict(kwargs))
        return {"ETag": "fake-put-etag"}

    def get_object(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        return {"Body": BytesIO(self.objects[(bucket, key)])}

    def copy_object(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        source = kwargs["CopySource"]
        assert isinstance(source, dict)
        source_bucket = str(source["Bucket"])
        source_key = str(source["Key"])
        self.objects[(bucket, key)] = self.objects[(source_bucket, source_key)]
        self.copy_calls.append(dict(kwargs))
        return {"CopyObjectResult": {"ETag": "fake-copy-etag"}}

    def head_object(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        self.head_calls.append(dict(kwargs))
        body = self.objects[(bucket, key)]
        return {"ContentLength": len(body)}

    def delete_object(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        self.objects.pop((bucket, key), None)
        return {}


class FileQuarantinePipelineTests(TestCase):
    """The clean object namespace must only contain scanner-approved bytes."""

    clean_bucket = "clean-test-bucket"
    quarantine_bucket = "quarantine-test-bucket"

    def setUp(self) -> None:
        self.object_root = tempfile.TemporaryDirectory()
        self.upload_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.object_root.cleanup)
        self.addCleanup(self.upload_root.cleanup)
        self.settings_override = override_settings(
            OBJECT_STORAGE_PROVIDER="mock_s3",
            OBJECT_STORAGE_BUCKET=self.clean_bucket,
            OBJECT_STORAGE_QUARANTINE_BUCKET=self.quarantine_bucket,
            OBJECT_STORAGE_LOCAL_ROOT=self.object_root.name,
            MOCK_UPLOAD_ROOT=self.upload_root.name,
            FILE_SCAN_PROVIDER="local_policy",
            APP_JWT_SECRET=TEST_JWT_SIGNING_KEY,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.env_override = patch.dict(
            os.environ,
            {"MOCK_UPLOAD_ROOT": self.upload_root.name},
        )
        self.env_override.start()
        self.addCleanup(self.env_override.stop)
        issued_at = timezone.now()
        expires_at = issued_at + timedelta(hours=1)
        user_id = "usr_quarantine_contract"
        auth_session_id = "auth_quarantine_contract"
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
        self.client = Client(
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def _post_file(self, *, filename: str, body: bytes) -> dict[str, object]:
        response = self.client.post(
            "/api/files/",
            data={
                "session_id": "ses_quarantine_contract",
                "purpose": "evidence",
                "file": SimpleUploadedFile(
                    filename,
                    body,
                    content_type="application/octet-stream",
                ),
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["attachment"]

    def _object_path(self, bucket: str, storage_uri: str) -> Path:
        prefix = f"s3://{self.clean_bucket}/"
        self.assertTrue(storage_uri.startswith(prefix), storage_uri)
        key = storage_uri.removeprefix(prefix)
        return (
            Path(self.object_root.name)
            / bucket
            / Path(*PurePosixPath(key).parts)
        )

    def _uploaded_file(self, attachment: dict[str, object]) -> UploadedFile:
        return UploadedFile.objects.get(
            attachment_id=attachment["attachment_id"]
        )

    def test_multipart_registration_writes_only_to_quarantine(self) -> None:
        payload = b"bytes awaiting malware scan"

        attachment = self._post_file(filename="evidence.bin", body=payload)

        storage_uri = str(attachment["storage_uri"])
        quarantine_path = self._object_path(self.quarantine_bucket, storage_uri)
        clean_path = self._object_path(self.clean_bucket, storage_uri)
        self.assertTrue(quarantine_path.exists())
        self.assertEqual(quarantine_path.read_bytes(), payload)
        self.assertFalse(clean_path.exists())
        self.assertEqual(
            [path for path in Path(self.upload_root.name).rglob("*") if path.is_file()],
            [],
        )
        self.assertNotIn(
            self.quarantine_bucket,
            json.dumps(attachment, ensure_ascii=False),
        )

    def test_metadata_only_registration_stays_pending_without_fallback_object(self) -> None:
        response = self.client.post(
            "/api/files/",
            data={
                "session_id": "ses_metadata_only_quarantine",
                "purpose": "evidence",
                "filename": "metadata-only.txt",
                "content_type": "text/plain",
                "size_bytes": 128,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        attachment = response.json()["attachment"]
        uploaded_file = UploadedFile.objects.get(
            attachment_id=attachment["attachment_id"]
        )

        self.assertFalse(
            self._object_path(
                self.quarantine_bucket,
                uploaded_file.storage_uri,
            ).exists()
        )
        self.assertFalse(
            self._object_path(self.clean_bucket, uploaded_file.storage_uri).exists()
        )
        self.assertEqual(
            [path for path in Path(self.upload_root.name).rglob("*") if path.is_file()],
            [],
        )

        batch = process_uploaded_file_scans(limit=20)

        uploaded_file.refresh_from_db()
        self.assertEqual(batch["processed"], 0)
        self.assertEqual(uploaded_file.status, UploadedFileStatus.PENDING)
        self.assertEqual(uploaded_file.scan_status, "awaiting_upload")

    def test_clean_mock_s3_scan_promotes_exact_quarantine_bytes(self) -> None:
        payload = b"scanner-approved exact payload\x00\xff"
        attachment = self._post_file(filename="safe.bin", body=payload)
        uploaded_file = UploadedFile.objects.get(
            attachment_id=attachment["attachment_id"]
        )
        clean_path = self._object_path(self.clean_bucket, uploaded_file.storage_uri)
        quarantine_path = self._object_path(
            self.quarantine_bucket,
            uploaded_file.storage_uri,
        )
        self.assertTrue(quarantine_path.exists())
        self.assertEqual(quarantine_path.read_bytes(), payload)
        self.assertFalse(clean_path.exists())

        result = scan_uploaded_file(uploaded_file)

        uploaded_file.refresh_from_db()
        self.assertEqual(result["status"], "clean")
        self.assertEqual(uploaded_file.status, UploadedFileStatus.READY)
        self.assertEqual(uploaded_file.scan_status, "clean")
        self.assertTrue(clean_path.exists())
        self.assertEqual(clean_path.read_bytes(), payload)

    def test_eicar_bytes_with_benign_filename_are_rejected_without_promotion(self) -> None:
        attachment = self._post_file(
            filename="family-photo.bin",
            body=EICAR_TEST_BYTES,
        )
        uploaded_file = UploadedFile.objects.get(
            attachment_id=attachment["attachment_id"]
        )
        clean_path = self._object_path(self.clean_bucket, uploaded_file.storage_uri)

        result = scan_uploaded_file(uploaded_file)

        uploaded_file.refresh_from_db()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(uploaded_file.status, UploadedFileStatus.REJECTED)
        self.assertEqual(uploaded_file.scan_status, "rejected")
        self.assertFalse(clean_path.exists())

    def test_missing_quarantine_source_never_becomes_ready(self) -> None:
        attachment = self._post_file(
            filename="missing-source.bin",
            body=b"source will disappear before scan",
        )
        uploaded_file = self._uploaded_file(attachment)
        quarantine_path = self._object_path(
            self.quarantine_bucket,
            uploaded_file.storage_uri,
        )
        clean_path = self._object_path(self.clean_bucket, uploaded_file.storage_uri)
        quarantine_path.unlink(missing_ok=True)
        clean_path.unlink(missing_ok=True)

        result = scan_uploaded_file(uploaded_file)

        uploaded_file.refresh_from_db()
        self.assertEqual(result["status"], "error")
        self.assertEqual(uploaded_file.status, UploadedFileStatus.UPLOADED)
        self.assertEqual(uploaded_file.scan_status, "error")
        self.assertFalse(clean_path.exists())

    @override_settings(FILE_SCAN_PROVIDER="unavailable-test-provider")
    def test_scanner_unavailable_is_retryable_error_not_rejection(self) -> None:
        attachment = self._post_file(
            filename="scanner-unavailable.bin",
            body=b"benign bytes requiring an available scanner",
        )
        uploaded_file = self._uploaded_file(attachment)
        clean_path = self._object_path(self.clean_bucket, uploaded_file.storage_uri)

        result = scan_uploaded_file(uploaded_file)

        uploaded_file.refresh_from_db()
        self.assertEqual(result["status"], "error")
        self.assertEqual(uploaded_file.status, UploadedFileStatus.UPLOADED)
        self.assertEqual(uploaded_file.scan_status, "error")
        self.assertFalse(clean_path.exists())

    def test_clean_write_failure_never_marks_file_ready(self) -> None:
        attachment = self._post_file(
            filename="copy-failure.bin",
            body=b"clean bytes that cannot be promoted",
        )
        uploaded_file = self._uploaded_file(attachment)
        clean_path = self._object_path(self.clean_bucket, uploaded_file.storage_uri)
        clean_path.unlink(missing_ok=True)

        with patch(
            "chatbot.file_scan_service.write_object",
            return_value={
                "status": "skipped",
                "reason": "write_failed",
                "exists": False,
                "writes_binary": False,
            },
        ):
            result = scan_uploaded_file(uploaded_file)

        uploaded_file.refresh_from_db()
        self.assertEqual(result["status"], "error")
        self.assertEqual(uploaded_file.status, UploadedFileStatus.UPLOADED)
        self.assertEqual(uploaded_file.scan_status, "error")
        self.assertFalse(clean_path.exists())

    def test_clean_object_verification_failure_never_marks_file_ready(self) -> None:
        attachment = self._post_file(
            filename="verification-failure.bin",
            body=b"clean bytes whose promoted object cannot be verified",
        )
        uploaded_file = self._uploaded_file(attachment)
        clean_path = self._object_path(self.clean_bucket, uploaded_file.storage_uri)

        with patch(
            "chatbot.file_scan_service.read_object_bytes",
            side_effect=[
                b"clean bytes whose promoted object cannot be verified",
                None,
            ],
        ) as read_bytes:
            result = scan_uploaded_file(uploaded_file)

        uploaded_file.refresh_from_db()
        self.assertEqual(result["status"], "error")
        self.assertEqual(uploaded_file.status, UploadedFileStatus.UPLOADED)
        self.assertEqual(uploaded_file.scan_status, "error")
        self.assertEqual(read_bytes.call_count, 2)
        self.assertFalse(clean_path.exists())

    def test_fresh_scanning_claim_is_not_processed_twice(self) -> None:
        attachment = self._post_file(
            filename="fresh-claim.bin",
            body=b"fresh scan claim",
        )
        uploaded_file = self._uploaded_file(attachment)
        uploaded_file.status = UploadedFileStatus.SCANNING
        uploaded_file.scan_status = "scanning"
        metadata = dict(uploaded_file.metadata or {})
        metadata["scan_started_at"] = timezone.now().isoformat()
        uploaded_file.metadata = metadata
        uploaded_file.save(
            update_fields=["status", "scan_status", "metadata", "updated_at"]
        )

        duplicate_result = scan_uploaded_file(uploaded_file)
        batch = process_uploaded_file_scans(limit=20)

        uploaded_file.refresh_from_db()
        self.assertEqual(duplicate_result["status"], "skipped")
        self.assertEqual(batch["processed"], 0)
        self.assertEqual(uploaded_file.status, UploadedFileStatus.SCANNING)
        self.assertEqual(uploaded_file.scan_status, "scanning")

    @override_settings(FILE_SCAN_CLAIM_STALE_AFTER_SECONDS=1)
    def test_stale_scanning_claim_is_recovered_with_a_new_fence(self) -> None:
        attachment = self._post_file(
            filename="stale-claim.bin",
            body=b"stale claim recovery bytes",
        )
        uploaded_file = self._uploaded_file(attachment)
        metadata = dict(uploaded_file.metadata or {})
        metadata["scan_claim"] = {
            "contract_version": "file_scan_claim.v1",
            "token": "stale-worker-token",
            "status": "active",
            "claimed_at": (timezone.now() - timedelta(minutes=5)).isoformat(),
        }
        UploadedFile.objects.filter(pk=uploaded_file.pk).update(
            status=UploadedFileStatus.SCANNING,
            scan_status="scanning",
            metadata=metadata,
            updated_at=timezone.now() - timedelta(minutes=5),
        )

        batch = process_uploaded_file_scans(limit=20)

        uploaded_file.refresh_from_db()
        self.assertEqual(batch["processed"], 1)
        self.assertEqual(batch["clean"], 1)
        self.assertEqual(uploaded_file.status, UploadedFileStatus.READY)
        self.assertEqual(uploaded_file.scan_status, "clean")
        self.assertNotEqual(
            uploaded_file.metadata["scan_claim"]["token"],
            "stale-worker-token",
        )

    def test_worker_that_loses_claim_cannot_promote_to_clean_storage(self) -> None:
        attachment = self._post_file(
            filename="lost-claim.bin",
            body=b"clean bytes from a stale worker",
        )
        uploaded_file = self._uploaded_file(attachment)
        clean_path = self._object_path(self.clean_bucket, uploaded_file.storage_uri)
        original_build = file_scan_service.build_file_scan_result

        def lose_claim(claimed_file: UploadedFile, **kwargs) -> dict[str, object]:
            result = original_build(claimed_file, **kwargs)
            current = UploadedFile.objects.get(pk=claimed_file.pk)
            metadata = dict(current.metadata or {})
            metadata["scan_claim"] = {
                **dict(metadata.get("scan_claim") or {}),
                "token": "successor-worker-token",
            }
            UploadedFile.objects.filter(pk=current.pk).update(metadata=metadata)
            return result

        with patch(
            "chatbot.file_scan_service.build_file_scan_result",
            side_effect=lose_claim,
        ):
            result = scan_uploaded_file(uploaded_file)

        uploaded_file.refresh_from_db()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "scan_claim_lost")
        self.assertFalse(clean_path.exists())
        self.assertEqual(uploaded_file.status, UploadedFileStatus.SCANNING)
        self.assertEqual(
            uploaded_file.metadata["scan_claim"]["token"],
            "successor-worker-token",
        )

    def test_lost_worker_never_deletes_successor_clean_object(self) -> None:
        attachment = self._post_file(
            filename="successor-wins.bin",
            body=b"stale worker snapshot",
        )
        uploaded_file = self._uploaded_file(attachment)
        clean_path = self._object_path(self.clean_bucket, uploaded_file.storage_uri)
        successor_bytes = b"successor verified bytes"

        def successor_finishes(*_args, **_kwargs) -> bool:
            clean_path.parent.mkdir(parents=True, exist_ok=True)
            clean_path.write_bytes(successor_bytes)
            current = UploadedFile.objects.get(pk=uploaded_file.pk)
            metadata = dict(current.metadata or {})
            metadata["scan_claim"] = {
                **dict(metadata.get("scan_claim") or {}),
                "token": "successor-worker-token",
                "status": "completed",
            }
            UploadedFile.objects.filter(pk=current.pk).update(
                status=UploadedFileStatus.READY,
                scan_status="clean",
                metadata=metadata,
            )
            return True

        with patch(
            "chatbot.file_scan_service._renew_file_scan_claim",
            side_effect=successor_finishes,
        ):
            result = scan_uploaded_file(uploaded_file)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "scan_claim_lost")
        self.assertEqual(clean_path.read_bytes(), successor_bytes)

    def test_promotion_writes_the_exact_bytes_that_were_scanned(self) -> None:
        original_bytes = b"benign bytes inspected by scanner"
        attachment = self._post_file(
            filename="snapshot-bound.bin",
            body=original_bytes,
        )
        uploaded_file = self._uploaded_file(attachment)
        quarantine_path = self._object_path(
            self.quarantine_bucket,
            uploaded_file.storage_uri,
        )
        clean_path = self._object_path(self.clean_bucket, uploaded_file.storage_uri)
        original_build = file_scan_service.build_file_scan_result

        def overwrite_after_scan(*args, **kwargs):
            result = original_build(*args, **kwargs)
            quarantine_path.write_bytes(EICAR_TEST_BYTES)
            return result

        with patch(
            "chatbot.file_scan_service.build_file_scan_result",
            side_effect=overwrite_after_scan,
        ):
            result = scan_uploaded_file(uploaded_file)

        uploaded_file.refresh_from_db()
        self.assertEqual(result["status"], "clean")
        self.assertEqual(uploaded_file.status, UploadedFileStatus.READY)
        self.assertEqual(clean_path.read_bytes(), original_bytes)

    def test_retention_fence_prevents_a_late_clean_write(self) -> None:
        attachment = self._post_file(
            filename="retention-wins.bin",
            body=b"bytes scanned before retention",
        )
        uploaded_file = self._uploaded_file(attachment)
        clean_path = self._object_path(self.clean_bucket, uploaded_file.storage_uri)

        def retention_finishes(*_args, **_kwargs) -> bool:
            UploadedFile.objects.filter(pk=uploaded_file.pk).update(
                status=UploadedFileStatus.DELETED,
                scan_status="purged",
                deleted_at=timezone.now(),
            )
            return True

        with (
            patch(
                "chatbot.file_scan_service._renew_file_scan_claim",
                side_effect=retention_finishes,
            ),
            patch(
                "chatbot.file_scan_service.write_object",
                wraps=write_object,
            ) as clean_write,
        ):
            result = scan_uploaded_file(uploaded_file)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "scan_claim_lost")
        clean_write.assert_not_called()
        self.assertFalse(clean_path.exists())

    def test_queued_worker_regates_attachment_after_retention_expiry(self) -> None:
        attachment = self._post_file(
            filename="queued-then-expired.bin",
            body=b"clean before queue but expired before execution",
        )
        uploaded_file = self._uploaded_file(attachment)
        scan_uploaded_file(uploaded_file)
        uploaded_file.refresh_from_db()
        job = AnalysisJob.objects.create(
            job_id="job_attachment_regate",
            session=uploaded_file.session,
            owner_id="usr_quarantine_contract",
            status=AnalysisJobStatus.QUEUED,
        )
        work_item = AgentWorkItem.objects.create(
            work_item_id="work_attachment_regate",
            job=job,
            status=AgentWorkItemStatus.QUEUED,
            next_run_at=timezone.now(),
            payload={
                "analysis_plan": {"steps": []},
                "job_payload": {},
                "execution_payload": {
                    "owner_id": "usr_quarantine_contract",
                    "session_id": "ses_quarantine_contract",
                    "attachments": [
                        {"attachment_id": uploaded_file.attachment_id}
                    ],
                },
            },
        )
        UploadedFile.objects.filter(pk=uploaded_file.pk).update(
            retention_expires_at=timezone.now() - timedelta(seconds=1)
        )

        with patch(
            "app.services.agent_node_service.execute_agent_plan"
        ) as execute_agent_plan:
            result = process_agent_work_item(work_item.work_item_id)

        execute_agent_plan.assert_not_called()
        self.assertEqual(result["status"], AgentWorkItemStatus.RETRYING)
        work_item.refresh_from_db()
        self.assertEqual(work_item.error_code, "AttachmentScanGateError")

    def test_object_read_rechecks_retention_under_the_database_fence(self) -> None:
        attachment = self._post_file(
            filename="expire-after-gate.bin",
            body=b"must not be read after the retention fence",
        )
        uploaded_file = self._uploaded_file(attachment)
        scan_uploaded_file(uploaded_file)
        gated = apply_attachment_scan_gate(
            {
                "owner_id": "usr_quarantine_contract",
                "session_id": "ses_quarantine_contract",
                "attachments": [
                    {"attachment_id": uploaded_file.attachment_id}
                ],
            }
        )
        canonical_attachment = resolve_attachment_references(gated)["attachments"][0]
        UploadedFile.objects.filter(pk=uploaded_file.pk).update(
            retention_expires_at=timezone.now() - timedelta(seconds=1)
        )

        with patch(
            "chatbot.file_scan_service.read_object_bytes"
        ) as read_object:
            result = _attachment_object_storage_bytes(
                canonical_attachment,
                canonical_attachment["storage_uri"],
            )

        self.assertIsNone(result)
        read_object.assert_not_called()

    def test_valid_queued_worker_consumes_marker_before_agent_execution(self) -> None:
        attachment = self._post_file(
            filename="worker-marker-safe.bin",
            body=b"valid clean worker attachment",
        )
        uploaded_file = self._uploaded_file(attachment)
        scan_uploaded_file(uploaded_file)
        job = AnalysisJob.objects.create(
            job_id="job_worker_marker_safe",
            session=uploaded_file.session,
            owner_id="usr_quarantine_contract",
            status=AnalysisJobStatus.QUEUED,
        )
        work_item = AgentWorkItem.objects.create(
            work_item_id="work_worker_marker_safe",
            job=job,
            payload={
                "analysis_plan": {"steps": []},
                "job_payload": {},
                "execution_payload": {
                    "owner_id": "usr_quarantine_contract",
                    "session_id": "ses_quarantine_contract",
                    "attachments": [
                        {"attachment_id": uploaded_file.attachment_id}
                    ],
                },
            },
        )

        def assert_json_safe(_plan, execution_payload):
            json.dumps(execution_payload)
            canonical = execution_payload["attachments"][0]
            self.assertNotIn("_canonical_scan_gate", canonical)
            self.assertEqual(
                canonical["metadata_source"],
                "canonical_scan_gate",
            )
            return {"status": "success"}

        with patch(
            "app.services.agent_node_service.execute_agent_plan",
            side_effect=assert_json_safe,
        ) as execute_agent_plan:
            result = _execute_agent_work_item_plan(work_item)

        execute_agent_plan.assert_called_once()
        self.assertEqual(result["status"], "success")

    def test_worker_and_direct_claim_skip_deleted_or_expired_uploads(self) -> None:
        deleted_attachment = self._post_file(
            filename="deleted-before-scan.bin",
            body=b"deleted raw bytes",
        )
        expired_attachment = self._post_file(
            filename="expired-before-scan.bin",
            body=b"expired raw bytes",
        )
        deleted_file = self._uploaded_file(deleted_attachment)
        expired_file = self._uploaded_file(expired_attachment)
        UploadedFile.objects.filter(pk=deleted_file.pk).update(
            deleted_at=timezone.now()
        )
        UploadedFile.objects.filter(pk=expired_file.pk).update(
            retention_expires_at=timezone.now() - timedelta(seconds=1)
        )

        batch = process_uploaded_file_scans(limit=20)
        deleted_result = scan_uploaded_file(deleted_file)
        expired_result = scan_uploaded_file(expired_file)

        self.assertEqual(batch["processed"], 0)
        self.assertEqual(deleted_result["status"], "skipped")
        self.assertEqual(deleted_result["reason"], "upload_deleted")
        self.assertEqual(expired_result["status"], "skipped")
        self.assertEqual(expired_result["reason"], "upload_retention_expired")
        for uploaded_file in (deleted_file, expired_file):
            self.assertFalse(
                self._object_path(
                    self.clean_bucket,
                    uploaded_file.storage_uri,
                ).exists()
            )

    def test_scan_gate_blocks_unknown_and_cross_owner_attachment_ids(self) -> None:
        attachment = self._post_file(
            filename="owned-ready.bin",
            body=b"owned clean attachment",
        )
        uploaded_file = self._uploaded_file(attachment)
        scan_uploaded_file(uploaded_file)

        unknown = apply_attachment_scan_gate(
            {
                "owner_id": "usr_quarantine_contract",
                "session_id": "ses_quarantine_contract",
                "attachments": [{"attachment_id": "att_unknown"}],
            }
        )
        foreign = apply_attachment_scan_gate(
            {
                "owner_id": "usr_attacker",
                "session_id": "ses_quarantine_contract",
                "attachments": [
                    {"attachment_id": uploaded_file.attachment_id}
                ],
            }
        )

        for gated in (unknown, foreign):
            self.assertEqual(gated["attachments"], [])
            self.assertEqual(
                gated["blocked_attachments"][0]["reason"],
                "attachment_not_found_or_forbidden",
            )

    def test_scan_gate_uses_only_canonical_storage_not_client_overrides(self) -> None:
        attachment = self._post_file(
            filename="canonical-ready.bin",
            body=b"canonical clean attachment",
        )
        uploaded_file = self._uploaded_file(attachment)
        scan_uploaded_file(uploaded_file)
        uploaded_file.refresh_from_db()

        gated = apply_attachment_scan_gate(
            {
                "owner_id": "usr_quarantine_contract",
                "session_id": "ses_quarantine_contract",
                "attachments": [
                    {
                        "attachment_id": uploaded_file.attachment_id,
                        "storage_uri": "s3://attacker/unsafe.bin",
                        "object_storage": {
                            "provider": "mock_s3",
                            "bucket": "attacker",
                            "key": "unsafe.bin",
                        },
                        "content_base64": "RVZJTCBCWVRFUw==",
                        "scan_status": "clean",
                    }
                ],
            }
        )

        canonical = gated["attachments"][0]
        json.dumps(gated)
        self.assertEqual(canonical["storage_uri"], uploaded_file.storage_uri)
        self.assertEqual(canonical["object_storage"]["bucket"], self.clean_bucket)
        self.assertNotIn("content_base64", canonical)
        self.assertEqual(canonical["scan_status"], "clean")

    def test_attachment_ids_are_merged_deduplicated_and_canonically_gated(self) -> None:
        clean_attachment = self._post_file(
            filename="alias-clean.bin",
            body=b"clean alias attachment",
        )
        clean_file = self._uploaded_file(clean_attachment)
        scan_uploaded_file(clean_file)
        pending_attachment = self._post_file(
            filename="alias-pending.bin",
            body=b"pending alias attachment",
        )

        gated = apply_attachment_scan_gate(
            {
                "owner_id": "usr_quarantine_contract",
                "session_id": "ses_quarantine_contract",
                "attachments": [
                    {
                        "attachment_id": clean_file.attachment_id,
                        "storage_uri": "s3://attacker/unsafe.bin",
                    }
                ],
                "attachment_ids": [
                    clean_file.attachment_id,
                    pending_attachment["attachment_id"],
                    "att_alias_unknown",
                ],
            }
        )

        self.assertNotIn("attachment_ids", gated)
        self.assertEqual(
            [item["attachment_id"] for item in gated["attachments"]],
            [clean_file.attachment_id],
        )
        self.assertEqual(
            gated["attachments"][0]["storage_uri"],
            clean_file.storage_uri,
        )
        self.assertEqual(
            [item["attachment_id"] for item in gated["blocked_attachments"]],
            [pending_attachment["attachment_id"], "att_alias_unknown"],
        )
        self.assertEqual(
            [item["reason"] for item in gated["blocked_attachments"]],
            ["scan_not_ready", "attachment_not_found_or_forbidden"],
        )
        self.assertEqual(gated["attachment_scan_policy"]["allowed_count"], 1)
        self.assertEqual(gated["attachment_scan_policy"]["blocked_count"], 2)

    def test_attachment_ids_use_the_same_owner_session_and_case_gate(self) -> None:
        attachment = self._post_file(
            filename="alias-owned.bin",
            body=b"owned alias attachment",
        )
        uploaded_file = self._uploaded_file(attachment)
        scan_uploaded_file(uploaded_file)

        forbidden_payloads = (
            {
                "owner_id": "usr_other",
                "session_id": "ses_quarantine_contract",
            },
            {
                "owner_id": "usr_quarantine_contract",
                "session_id": "ses_other",
            },
            {
                "owner_id": "usr_quarantine_contract",
                "session_id": "ses_quarantine_contract",
                "case_id": "case_other",
            },
        )
        for identity in forbidden_payloads:
            with self.subTest(identity=identity):
                gated = apply_attachment_scan_gate(
                    {
                        **identity,
                        "attachment_ids": [uploaded_file.attachment_id],
                    }
                )

                self.assertNotIn("attachment_ids", gated)
                self.assertEqual(gated["attachments"], [])
                self.assertEqual(len(gated["blocked_attachments"]), 1)
                self.assertEqual(
                    gated["blocked_attachments"][0]["reason"],
                    "attachment_not_found_or_forbidden",
                )

    def test_malformed_attachment_ids_fail_closed(self) -> None:
        gated = apply_attachment_scan_gate(
            {
                "owner_id": "usr_quarantine_contract",
                "session_id": "ses_quarantine_contract",
                "attachment_ids": {"attachment_id": "att_not_a_list"},
            }
        )

        self.assertNotIn("attachment_ids", gated)
        self.assertEqual(gated["attachments"], [])
        self.assertEqual(len(gated["blocked_attachments"]), 1)
        self.assertEqual(
            gated["blocked_attachments"][0]["reason"],
            "malformed_attachment_reference",
        )
        self.assertEqual(gated["attachment_scan_policy"]["allowed_count"], 0)
        self.assertEqual(gated["attachment_scan_policy"]["blocked_count"], 1)

    def test_scan_gate_rejects_excessive_attachment_count_without_queries(self) -> None:
        with self.assertNumQueries(0):
            gated = apply_attachment_scan_gate(
                {
                    "owner_id": "usr_quarantine_contract",
                    "session_id": "ses_quarantine_contract",
                    "attachment_ids": [f"att_excess_{index}" for index in range(21)],
                }
            )

        self.assertEqual(gated["attachments"], [])
        self.assertEqual(
            gated["blocked_attachments"][0]["reason"],
            "attachment_limit_exceeded",
        )
        self.assertEqual(gated["attachment_scan_policy"]["max_count"], 20)

    def test_scan_gate_batches_attachment_lookup_into_one_query(self) -> None:
        attachment = self._post_file(
            filename="batched-ready.bin",
            body=b"ready for a batched lookup",
        )
        uploaded_file = self._uploaded_file(attachment)
        scan_uploaded_file(uploaded_file)

        with self.assertNumQueries(1):
            gated = apply_attachment_scan_gate(
                {
                    "owner_id": "usr_quarantine_contract",
                    "session_id": "ses_quarantine_contract",
                    "attachment_ids": [
                        uploaded_file.attachment_id,
                        *[f"att_unknown_{index}" for index in range(9)],
                    ],
                }
            )

        self.assertEqual(len(gated["attachments"]), 1)
        self.assertEqual(len(gated["blocked_attachments"]), 9)

    def test_direct_guest_upload_binds_session_and_blocks_another_guest(self) -> None:
        GuestIdentity.objects.create(
            guest_id="gst_quarantine_owner",
            status=GuestIdentityStatus.ACTIVE,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        guest_client = Client(
            HTTP_X_GUEST_ID="gst_quarantine_owner",
            HTTP_X_GUEST_CREDENTIAL=issue_guest_credential("gst_quarantine_owner")[0],
        )

        response = guest_client.post(
            "/api/files/",
            data={
                "session_id": "ses_direct_guest_upload",
                "purpose": "evidence",
                "file": SimpleUploadedFile(
                    "guest-owned.bin",
                    b"guest owned clean bytes",
                    content_type="application/octet-stream",
                ),
            },
        )

        self.assertEqual(response.status_code, 200, response.content)
        attachment_id = response.json()["attachment"]["attachment_id"]
        uploaded_file = UploadedFile.objects.get(attachment_id=attachment_id)
        scan_uploaded_file(uploaded_file)
        session = ChatSession.objects.get(session_id="ses_direct_guest_upload")
        self.assertEqual(
            session.metadata["auth_context"]["guest_id"],
            "gst_quarantine_owner",
        )
        uploaded_file.refresh_from_db()
        remaining = uploaded_file.retention_expires_at - timezone.now()
        self.assertGreaterEqual(remaining, timedelta(days=6))

        gated = apply_attachment_scan_gate(
            {
                "session_id": session.session_id,
                "auth_context": {"guest_id": "gst_quarantine_attacker"},
                "attachments": [{"attachment_id": attachment_id}],
            }
        )

        self.assertEqual(gated["attachments"], [])
        self.assertEqual(
            gated["blocked_attachments"][0]["reason"],
            "attachment_not_found_or_forbidden",
        )

    def test_authenticated_upload_cannot_claim_an_unbound_existing_session(self) -> None:
        ChatSession.objects.create(
            session_id="ses_unbound_upload_claim",
            owner_id="",
            metadata={},
        )

        response = self.client.post(
            "/api/files/",
            data={
                "session_id": "ses_unbound_upload_claim",
                "purpose": "evidence",
                "file": SimpleUploadedFile(
                    "claim.bin",
                    b"must not be persisted",
                    content_type="application/octet-stream",
                ),
            },
        )

        self.assertEqual(response.status_code, 403, response.content)
        session = ChatSession.objects.get(session_id="ses_unbound_upload_claim")
        self.assertEqual(session.owner_id, "")
        self.assertFalse(
            UploadedFile.objects.filter(
                session__session_id="ses_unbound_upload_claim"
            ).exists()
        )

    def test_guest_body_owner_spoof_cannot_use_victim_attachment(self) -> None:
        attachment = self._post_file(
            filename="victim-ready.bin",
            body=b"victim owned clean attachment",
        )
        uploaded_file = self._uploaded_file(attachment)
        scan_uploaded_file(uploaded_file)
        GuestIdentity.objects.create(
            guest_id="gst_owner_spoof_attacker",
            status=GuestIdentityStatus.ACTIVE,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        attacker = Client(
            HTTP_X_GUEST_ID="gst_owner_spoof_attacker",
            HTTP_X_GUEST_CREDENTIAL=issue_guest_credential("gst_owner_spoof_attacker")[0],
        )

        response = attacker.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_quarantine_contract",
                "owner_id": "usr_quarantine_contract",
                "user_id": "usr_quarantine_contract",
                "user_text": "analyze the victim file",
                "attachments": [
                    {"attachment_id": uploaded_file.attachment_id}
                ],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")

    @override_settings(FILE_UPLOAD_MAX_BYTES=8)
    def test_multipart_upload_over_hard_limit_returns_413_without_persistence(self) -> None:
        response = self.client.post(
            "/api/files/",
            data={
                "session_id": "ses_upload_too_large",
                "purpose": "evidence",
                "file": SimpleUploadedFile(
                    "too-large.bin",
                    b"123456789",
                    content_type="application/octet-stream",
                ),
            },
        )

        self.assertEqual(response.status_code, 413, response.content)
        self.assertEqual(response.json()["error"]["code"], "file_too_large")
        self.assertFalse(
            UploadedFile.objects.filter(
                session__session_id="ses_upload_too_large"
            ).exists()
        )
        raw_payloads = [
            path
            for path in Path(self.upload_root.name).rglob("*")
            if path.is_file() and path.name != "metadata.json"
        ]
        self.assertEqual(raw_payloads, [])
        self.assertFalse(UsageEvent.objects.filter(scope="file_upload").exists())

    @override_settings(FILE_UPLOAD_MAX_BYTES=1024)
    def test_oversized_content_length_is_rejected_before_upload_parsing(self) -> None:
        with patch(
            "chatbot.views.register_uploaded_file",
            side_effect=AssertionError("oversized request must not reach the view"),
        ):
            response = self.client.post(
                "/api/files/",
                data={
                    "session_id": "ses_content_length_rejected",
                    "purpose": "evidence",
                    "file": SimpleUploadedFile(
                        "small-body.bin",
                        b"small",
                        content_type="application/octet-stream",
                    ),
                },
                CONTENT_LENGTH=str(1024 + 1024 * 1024 + 1),
            )

        self.assertEqual(response.status_code, 413, response.content)
        self.assertEqual(response.json()["error"]["code"], "file_too_large")
        self.assertFalse(UsageEvent.objects.filter(scope="file_upload").exists())

    def test_quarantine_write_failure_returns_503_and_refunds_upload_quota(self) -> None:
        with patch(
            "chatbot.repositories.write_object_from_source_uri",
            return_value={
                "status": "skipped",
                "reason": "provider_unavailable",
                "exists": False,
                "writes_binary": False,
            },
        ):
            response = self.client.post(
                "/api/files/",
                data={
                    "session_id": "ses_quarantine_write_failure",
                    "purpose": "evidence",
                    "file": SimpleUploadedFile(
                        "retry-me.bin",
                        b"client must retry these bytes",
                        content_type="application/octet-stream",
                    ),
                },
            )

        self.assertEqual(response.status_code, 503, response.content)
        self.assertEqual(
            response.json()["error"]["code"],
            "upload_storage_unavailable",
        )
        self.assertFalse(
            UploadedFile.objects.filter(
                session__session_id="ses_quarantine_write_failure"
            ).exists()
        )
        self.assertEqual(
            [path for path in Path(self.upload_root.name).rglob("*") if path.is_file()],
            [],
        )
        usage = UsageEvent.objects.get(scope="file_upload")
        self.assertEqual(usage.amount, 0)
        self.assertEqual(
            usage.metadata["refund_reason"],
            "file_upload_storage_failed",
        )

    def test_guest_upload_without_session_is_rejected_and_unbound_detail_is_private(self) -> None:
        GuestIdentity.objects.create(
            guest_id="gst_no_session_upload",
            status=GuestIdentityStatus.ACTIVE,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        guest_client = Client(
            HTTP_X_GUEST_ID="gst_no_session_upload",
            HTTP_X_GUEST_CREDENTIAL=issue_guest_credential("gst_no_session_upload")[0],
        )

        response = guest_client.post(
            "/api/files/",
            data={
                "purpose": "evidence",
                "file": SimpleUploadedFile(
                    "missing-session.bin",
                    b"must not become an unbound upload",
                    content_type="application/octet-stream",
                ),
            },
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["error"]["code"], "session_id_required")
        self.assertFalse(UploadedFile.objects.exists())

        UploadedFile.objects.create(
            attachment_id="att_legacy_unbound_private",
            owner_id="",
            session=None,
            purpose="evidence",
            original_filename="legacy.bin",
            storage_uri="s3://legacy/unbound.bin",
            status=UploadedFileStatus.READY,
            scan_status="clean",
        )
        detail = self.client.get("/api/files/att_legacy_unbound_private/")
        self.assertEqual(detail.status_code, 403, detail.content)
        self.assertEqual(detail.json()["error"]["code"], "object_access_denied")

    @override_settings(OBJECT_STORAGE_PROVIDER="s3")
    def test_s3_pipeline_puts_the_scanned_snapshot_into_clean_storage(self) -> None:
        fake_s3 = FakeS3Client()
        payload = b"exact bytes through fake s3"

        with patch("chatbot.object_storage._boto3_client", return_value=fake_s3):
            attachment = self._post_file(filename="fake-s3.bin", body=payload)
            uploaded_file = self._uploaded_file(attachment)
            clean_key = uploaded_file.storage_uri.removeprefix(
                f"s3://{self.clean_bucket}/"
            )
            self.assertEqual(
                fake_s3.objects[(self.quarantine_bucket, clean_key)],
                payload,
            )
            self.assertNotIn((self.clean_bucket, clean_key), fake_s3.objects)

            result = scan_uploaded_file(uploaded_file)

        uploaded_file.refresh_from_db()
        self.assertEqual(result["status"], "clean")
        self.assertEqual(uploaded_file.status, UploadedFileStatus.READY)
        self.assertIn((self.clean_bucket, clean_key), fake_s3.objects)
        self.assertEqual(fake_s3.objects[(self.clean_bucket, clean_key)], payload)
        self.assertEqual(fake_s3.copy_calls, [])
        clean_write = next(
            call
            for call in fake_s3.put_calls
            if call["Bucket"] == self.clean_bucket and call["Key"] == clean_key
        )
        self.assertEqual(
            clean_write["Metadata"]["resource_type"],
            "uploaded_file",
        )
        self.assertIn("snapshot_sha256", clean_write["Metadata"])
        self.assertNotIn("source_uri", clean_write["Metadata"])

    @override_settings(
        OBJECT_STORAGE_PROVIDER="s3",
        OBJECT_STORAGE_BUCKET="same-misconfigured-bucket",
        OBJECT_STORAGE_QUARANTINE_BUCKET="same-misconfigured-bucket",
    )
    def test_same_clean_and_quarantine_bucket_fails_before_any_s3_write(self) -> None:
        fake_s3 = FakeS3Client()

        with patch("chatbot.object_storage._boto3_client", return_value=fake_s3):
            response = self.client.post(
                "/api/files/",
                data={
                    "session_id": "ses_same_bucket_rejected",
                    "purpose": "evidence",
                    "file": SimpleUploadedFile(
                        "same-bucket.bin",
                        b"raw bytes must never enter the clean namespace",
                        content_type="application/octet-stream",
                    ),
                },
            )

        self.assertEqual(response.status_code, 503, response.content)
        self.assertEqual(fake_s3.put_calls, [])
        self.assertEqual(fake_s3.copy_calls, [])
        self.assertFalse(
            UploadedFile.objects.filter(
                session__session_id="ses_same_bucket_rejected"
            ).exists()
        )

    def test_same_bucket_report_staging_copy_remains_supported(self) -> None:
        source = {
            "provider": "mock_s3",
            "bucket": self.clean_bucket,
            "key": "staging/canonical/reports/usr/report.txt",
            "resource_type": "report",
            "resource_id": "rep_same_bucket_copy:staging",
        }
        target = {
            "provider": "mock_s3",
            "bucket": self.clean_bucket,
            "key": "canonical/reports/usr/report.txt",
            "resource_type": "report",
            "resource_id": "rep_same_bucket_copy",
        }
        write_object(source, b"staged report bytes")

        result = copy_object(source, target)

        self.assertEqual(result["status"], "copied")
        self.assertEqual(read_object_bytes(target), b"staged report bytes")
