"""Smoke test for uploaded file scan policy and state transitions."""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from chatbot.file_scan_service import process_uploaded_file_scans
from chatbot.models import ChatSession, ChatSessionStatus, UploadedFile, UploadedFileStatus


class Command(BaseCommand):
    help = "Create a small uploaded_files row and verify the file scan pipeline."

    def add_arguments(self, parser):
        parser.add_argument("--attachment-id", default="att_file_scan_smoke")
        parser.add_argument("--session-id", default="ses_file_scan_smoke")
        parser.add_argument("--require-clean", action="store_true")
        parser.add_argument("--format", choices=["text", "json"], default="text")

    def handle(self, *args, **options):
        storage_uri = _write_smoke_upload(options["attachment_id"])
        session, _created = ChatSession.objects.get_or_create(
            session_id=options["session_id"],
            defaults={
                "status": ChatSessionStatus.ACTIVE,
                "metadata": {"created_by": "smoke_file_scan"},
            },
        )
        uploaded_file, _created = UploadedFile.objects.update_or_create(
            attachment_id=options["attachment_id"],
            defaults={
                "session": session,
                "purpose": "fine_notice",
                "file_type": "text",
                "original_filename": "file-scan-smoke.txt",
                "content_type": "text/plain",
                "size_bytes": 128,
                "storage_uri": storage_uri,
                "privacy_risk": False,
                "status": UploadedFileStatus.UPLOADED,
                "scan_status": "not_started",
                "agent_handoff": {
                    "attachment_id": options["attachment_id"],
                    "purpose": "fine_notice",
                    "type": "text",
                },
                "metadata": {"source": "smoke_file_scan"},
            },
        )

        batch = process_uploaded_file_scans(limit=1)
        uploaded_file.refresh_from_db()
        result = {
            "contract_version": "file_scan_smoke.v1",
            "status": "pass" if uploaded_file.scan_status == "clean" else "fail",
            "attachment_id": uploaded_file.attachment_id,
            "file_status": uploaded_file.status,
            "scan_status": uploaded_file.scan_status,
            "scanner": (uploaded_file.metadata.get("scan_result") or {}).get("scanner"),
            "batch": batch,
        }
        if options["require_clean"] and result["status"] != "pass":
            raise CommandError("File scan smoke did not produce a clean uploaded file.")

        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False))
            return

        self.stdout.write(f"File scan smoke: {result['status']}")
        self.stdout.write(f"- attachment: {uploaded_file.attachment_id}")
        self.stdout.write(f"- file_status: {uploaded_file.status}")
        self.stdout.write(f"- scan_status: {uploaded_file.scan_status}")
        self.stdout.write(f"- scanner: {result['scanner']}")


def _write_smoke_upload(attachment_id: str) -> str:
    filename = "file-scan-smoke.txt"
    root = Path(getattr(settings, "MOCK_UPLOAD_ROOT", "") or "backend/media/mock_uploads")
    upload_dir = root / attachment_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / filename).write_text("file scan smoke clean sample\n", encoding="utf-8")
    return f"mock://uploads/{attachment_id}/{filename}"
