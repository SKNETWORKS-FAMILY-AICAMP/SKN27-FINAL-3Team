"""Smoke test for uploaded file scan policy and state transitions."""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from chatbot.file_scan_service import process_uploaded_file_scans, scan_uploaded_file
from chatbot.models import ChatSession, ChatSessionStatus, UploadedFile
from chatbot.repositories import persist_uploaded_file_metadata


class Command(BaseCommand):
    help = "Create a small uploaded_files row and verify the file scan pipeline."

    def add_arguments(self, parser):
        parser.add_argument("--attachment-id", default="att_file_scan_smoke")
        parser.add_argument("--session-id", default="ses_file_scan_smoke")
        parser.add_argument(
            "--phase",
            choices=["end-to-end", "upload", "scan"],
            default="end-to-end",
        )
        parser.add_argument("--require-clean", action="store_true")
        parser.add_argument("--format", choices=["text", "json"], default="text")

    def handle(self, *args, **options):
        phase = options["phase"]
        if phase in {"end-to-end", "upload"}:
            _persist_smoke_upload(
                attachment_id=options["attachment_id"],
                session_id=options["session_id"],
            )
        uploaded_file = UploadedFile.objects.filter(
            attachment_id=options["attachment_id"]
        ).first()
        if uploaded_file is None:
            raise CommandError("File scan smoke attachment does not exist.")

        if phase == "end-to-end":
            batch = process_uploaded_file_scans(limit=1)
        elif phase == "scan":
            scan_result = scan_uploaded_file(uploaded_file)
            batch = {
                "contract_version": "file_scan_batch.v1",
                "processed": 0 if scan_result.get("status") == "skipped" else 1,
                "results": [scan_result],
            }
        else:
            batch = {"contract_version": "file_scan_batch.v1", "processed": 0, "results": []}
        uploaded_file.refresh_from_db()
        passed = (
            uploaded_file.status == "uploaded"
            and uploaded_file.scan_status == "not_started"
            if phase == "upload"
            else uploaded_file.scan_status == "clean"
        )
        result = {
            "contract_version": "file_scan_smoke.v1",
            "status": "pass" if passed else "fail",
            "phase": phase,
            "attachment_id": uploaded_file.attachment_id,
            "file_status": uploaded_file.status,
            "scan_status": uploaded_file.scan_status,
            "scanner": (uploaded_file.metadata.get("scan_result") or {}).get("scanner"),
            "batch": batch,
        }
        if options["require_clean"] and uploaded_file.scan_status != "clean":
            raise CommandError("File scan smoke did not produce a clean uploaded file.")

        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False))
            return

        self.stdout.write(f"File scan smoke: {result['status']}")
        self.stdout.write(f"- phase: {phase}")
        self.stdout.write(f"- attachment: {uploaded_file.attachment_id}")
        self.stdout.write(f"- file_status: {uploaded_file.status}")
        self.stdout.write(f"- scan_status: {uploaded_file.scan_status}")
        self.stdout.write(f"- scanner: {result['scanner']}")


def _persist_smoke_upload(*, attachment_id: str, session_id: str) -> None:
    storage_uri = _write_smoke_upload(attachment_id)
    session, _created = ChatSession.objects.get_or_create(
        session_id=session_id,
        defaults={
            "status": ChatSessionStatus.ACTIVE,
            "metadata": {"created_by": "smoke_file_scan"},
        },
    )
    persist_uploaded_file_metadata(
        {
            "attachment_id": attachment_id,
            "session_id": session.session_id,
            "purpose": "fine_notice",
            "type": "text",
            "original_filename": "file-scan-smoke.txt",
            "filename": "file-scan-smoke.txt",
            "content_type": "text/plain",
            "size_bytes": len("file scan smoke clean sample\n".encode("utf-8")),
            "storage_uri": storage_uri,
            "status": "uploaded",
            "agent_handoff": {
                "attachment_id": attachment_id,
                "purpose": "fine_notice",
                "type": "text",
            },
            "checks": {},
            "limitations": [],
        },
        raw_payload={"source": "smoke_file_scan"},
        binary_upload=True,
    )


def _write_smoke_upload(attachment_id: str) -> str:
    filename = "file-scan-smoke.txt"
    root = Path(getattr(settings, "MOCK_UPLOAD_ROOT", "") or "backend/media/mock_uploads")
    upload_dir = root / attachment_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / filename).write_text("file scan smoke clean sample\n", encoding="utf-8")
    return f"mock://uploads/{attachment_id}/{filename}"
