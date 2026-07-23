from __future__ import annotations

import os
from pathlib import Path
import sys

import django
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from chatbot.attachment_intake_policy import classify_attachment_intake
from chatbot import repositories


class UploadStub:
    name = "dashcam.mp4"
    content_type = "video/mp4"


def test_mp4_is_normalized_to_the_blackbox_video_route() -> None:
    decision = classify_attachment_intake(
        content_type="video/mp4",
        filename="dashcam.mp4",
        purpose="unknown",
    )

    assert decision == {
        "accepted": True,
        "error_code": "",
        "file_type": "video",
        "routing_purpose": "blackbox_video",
        "purpose_conflict": False,
    }


def test_video_with_document_purpose_is_rejected_before_storage() -> None:
    decision = classify_attachment_intake(
        content_type="video/mp4",
        filename="dashcam.mp4",
        purpose="fine_notice",
    )

    assert decision["accepted"] is False
    assert decision["error_code"] == "purpose_media_mismatch"


def test_executable_mime_is_not_an_attachment_analysis_input() -> None:
    decision = classify_attachment_intake(
        content_type="application/x-msdownload",
        filename="unsafe.exe",
        purpose="unknown",
    )

    assert decision["accepted"] is False
    assert decision["error_code"] == "unsupported_media_type"


def test_legacy_supporting_evidence_document_purpose_is_canonicalized() -> None:
    decision = classify_attachment_intake(
        content_type="application/pdf",
        filename="evidence.pdf",
        purpose="supporting_evidence",
    )

    assert decision == {
        "accepted": True,
        "error_code": "",
        "file_type": "pdf",
        "routing_purpose": "evidence",
        "purpose_conflict": False,
    }


def test_canonical_upload_persists_the_normalized_video_purpose(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def register_mock_attachment(payload, **_kwargs):
        captured["payload"] = dict(payload)
        return {
            "session_id": payload["session_id"],
            "purpose": payload["purpose"],
        }

    monkeypatch.setattr(repositories, "_get_or_create_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        repositories,
        "register_mock_attachment",
        register_mock_attachment,
    )
    monkeypatch.setattr(
        repositories,
        "persist_uploaded_file_metadata",
        lambda attachment, **_kwargs: attachment,
    )

    repositories.register_uploaded_file(
        {"session_id": "ses_upload", "purpose": "unknown"},
        upload_file=UploadStub(),
    )

    assert captured["payload"] == {
        "session_id": "ses_upload",
        "purpose": "blackbox_video",
    }


def test_canonical_upload_rejects_purpose_mismatch_before_storage(monkeypatch) -> None:
    monkeypatch.setattr(repositories, "_get_or_create_session", lambda *_args, **_kwargs: None)
    register_mock_attachment = monkeypatch.setattr(
        repositories,
        "register_mock_attachment",
        lambda *_args, **_kwargs: pytest.fail("storage must not be reached"),
    )

    with pytest.raises(repositories.UploadValidationError, match="purpose_media_mismatch"):
        repositories.register_uploaded_file(
            {"session_id": "ses_upload", "purpose": "fine_notice"},
            upload_file=UploadStub(),
        )

    assert register_mock_attachment is None
