from __future__ import annotations

import tempfile
import os
import sys
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile


def test_attachment_staging_contract_uses_neutral_local_adapter_uri() -> None:
    from app.services.attachment_staging_service import register_staged_attachment

    with tempfile.TemporaryDirectory() as staging_root, patch.dict(
        "os.environ", {"ATTACHMENT_STAGING_ROOT": staging_root}
    ):
        attachment = register_staged_attachment(
            {"session_id": "ses_phase_01", "filename": "notice.txt"},
            upload_file=SimpleUploadedFile("notice.txt", b"evidence", content_type="text/plain"),
        )

        assert attachment["storage_uri"].startswith("local://attachment-staging/")
        assert attachment["staging_status"] == "staged"
        assert "mock_status" not in attachment
        assert (Path(staging_root) / attachment["attachment_id"] / "notice.txt").exists()


def test_history_event_contract_drops_mock_markers_from_canonical_metadata() -> None:
    from app.services.history_event_contract import build_history_event

    event = build_history_event(
        event_type="chat_message_created",
        status="success",
        summary="canonical event",
        metadata={
            "case_id": "case_phase_01",
            "mock_scenario": "fixture",
            "mock_status": "success",
            "canonical_mock": True,
        },
    )

    assert event["metadata"] == {"case_id": "case_phase_01"}
    assert event["source"]["execution_mode"] == "canonical"


def test_local_staging_uri_is_handed_to_the_local_object_storage_adapter() -> None:
    backend_root = Path(__file__).resolve().parents[1] / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from app.services.attachment_staging_service import register_staged_attachment
    from chatbot.object_storage import write_object_from_source_uri
    from django.test import override_settings

    with tempfile.TemporaryDirectory() as staging_root, tempfile.TemporaryDirectory() as object_root, patch.dict(
        "os.environ", {"ATTACHMENT_STAGING_ROOT": staging_root}
    ), override_settings(OBJECT_STORAGE_PROVIDER="mock_s3", OBJECT_STORAGE_LOCAL_ROOT=object_root):
        attachment = register_staged_attachment(
            {"session_id": "ses_phase_01", "filename": "notice.txt"},
            upload_file=SimpleUploadedFile("notice.txt", b"evidence", content_type="text/plain"),
        )
        result = write_object_from_source_uri(
            {
                "provider": "mock_s3",
                "bucket": "quarantine",
                "key": "uploads/att_phase_01/notice.txt",
                "resource_type": "uploaded_file",
                "resource_id": attachment["attachment_id"],
                "source_uri": attachment["storage_uri"],
            }
        )

    assert result["status"] == "written"
    assert result["exists"] is True
