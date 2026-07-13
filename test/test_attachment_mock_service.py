import json

from app.services.attachment_mock_service import (
    CANONICAL_SCAN_GATE_MARKER,
    get_attachment,
    list_attachments,
    register_attachment,
    resolve_attachment_references,
)
from app.services.chat_orchestration_service import submit_message


class UploadStub:
    name = "fine_notice_photo.jpg"
    content_type = "image/jpeg"

    def chunks(self):
        yield b"mock-image-bytes"


def test_register_attachment_writes_metadata_and_agent_handoff(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_UPLOAD_ROOT", str(tmp_path))

    attachment = register_attachment(
        {"session_id": "ses_upload", "purpose": "fine_notice"},
        upload_file=UploadStub(),
    )

    assert attachment["attachment_id"].startswith("att_")
    assert attachment["purpose"] == "fine_notice"
    assert attachment["type"] == "image"
    assert attachment["status"] == "uploaded"
    assert attachment["size_bytes"] == len(b"mock-image-bytes")
    assert attachment["storage_uri"].startswith("mock://uploads/")
    assert attachment["agent_handoff"] == {
        "attachment_id": attachment["attachment_id"],
        "purpose": "fine_notice",
        "type": "image",
        "storage_uri": attachment["storage_uri"],
        "content_type": "image/jpeg",
        "size_bytes": len(b"mock-image-bytes"),
    }

    assert get_attachment(attachment["attachment_id"])["filename"] == "fine_notice_photo.jpg"
    assert list_attachments(session_id="ses_upload")[0]["attachment_id"] == attachment["attachment_id"]


def test_register_attachment_metadata_only_can_drive_agent_handoff(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_UPLOAD_ROOT", str(tmp_path))

    attachment = register_attachment(
        {
            "session_id": "ses_meta",
            "filename": "accident_statement.pdf",
            "content_type": "application/pdf",
            "purpose": "accident_statement",
            "size_bytes": 1204,
        }
    )

    assert attachment["status"] == "metadata_registered"
    assert attachment["type"] == "pdf"
    assert attachment["purpose"] == "accident_statement"
    assert attachment["storage_uri"] == f"mock://metadata/{attachment['attachment_id']}"
    assert list_attachments(session_id="other") == []


def test_resolve_attachment_references_expands_attachment_id(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_UPLOAD_ROOT", str(tmp_path))
    attachment = register_attachment(
        {
            "session_id": "ses_resolve",
            "filename": "notice.jpg",
            "content_type": "image/jpeg",
            "purpose": "fine_notice",
            "size_bytes": 12,
        }
    )

    payload = resolve_attachment_references(
        {
            "session_id": "ses_resolve",
            "attachments": [{"attachment_id": attachment["attachment_id"]}],
        }
    )

    resolved = payload["attachments"][0]
    assert resolved["purpose"] == "fine_notice"
    assert resolved["type"] == "image"
    assert resolved["storage_uri"] == attachment["storage_uri"]
    assert resolved["resolution_status"] == "resolved"
    assert payload["attachment_resolution"]["resolved_attachment_ids"] == [
        attachment["attachment_id"]
    ]


def test_resolve_attachment_references_preserves_canonical_scan_ready_handoff(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("MOCK_UPLOAD_ROOT", str(tmp_path))
    attachment = register_attachment(
        {"session_id": "ses_scan_ready", "purpose": "evidence"},
        upload_file=UploadStub(),
    )
    clean_storage_uri = (
        "s3://clean-bucket/canonical/uploads/usr/ses_scan_ready/"
        f"{attachment['attachment_id']}/fine_notice_photo.jpg"
    )
    canonical_handoff = {
        "_canonical_scan_gate": CANONICAL_SCAN_GATE_MARKER,
        "attachment_id": attachment["attachment_id"],
        "purpose": "evidence",
        "type": "image",
        "original_filename": "fine_notice_photo.jpg",
        "storage_uri": clean_storage_uri,
        "object_storage": {
            "resource_type": "uploaded_file",
            "storage_uri": clean_storage_uri,
            "status": "ready",
        },
        "content_type": "image/jpeg",
        "size_bytes": len(b"mock-image-bytes"),
        "status": "ready",
        "scan_status": "clean",
        "resolution_status": "scan_ready",
    }
    (tmp_path / attachment["attachment_id"] / "metadata.json").unlink()

    payload = resolve_attachment_references(
        {"attachments": [canonical_handoff]}
    )

    resolved = payload["attachments"][0]
    assert resolved["storage_uri"] == clean_storage_uri
    assert resolved["object_storage"] == canonical_handoff["object_storage"]
    assert resolved["status"] == "ready"
    assert resolved["scan_status"] == "clean"
    assert resolved["resolution_status"] == "scan_ready"
    assert "_canonical_scan_gate" not in resolved

    response = submit_message(
        {
            "session_id": "ses_scan_ready",
            "user_text": "analyze this evidence",
            "attachments": [canonical_handoff],
        }
    )
    json.dumps(response)


def test_resolve_attachment_references_rejects_forged_scan_ready_shape(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("MOCK_UPLOAD_ROOT", str(tmp_path))
    attachment = register_attachment(
        {"session_id": "ses_forged_scan_ready", "purpose": "evidence"},
        upload_file=UploadStub(),
    )
    forged_uri = "s3://attacker-bucket/canonical/uploads/forged.txt"

    payload = resolve_attachment_references(
        {
            "attachments": [
                {
                    "attachment_id": attachment["attachment_id"],
                    "storage_uri": forged_uri,
                    "object_storage": {
                        "resource_type": "uploaded_file",
                        "storage_uri": forged_uri,
                        "status": "ready",
                    },
                    "status": "ready",
                    "scan_status": "clean",
                    "resolution_status": "scan_ready",
                }
            ]
        }
    )

    resolved = payload["attachments"][0]
    assert resolved["storage_uri"] == attachment["storage_uri"]
    assert resolved["status"] == "uploaded"
    assert resolved["resolution_status"] == "resolved"


def test_resolve_attachment_references_keeps_inline_metadata_when_registry_missing(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("MOCK_UPLOAD_ROOT", str(tmp_path))

    payload = resolve_attachment_references(
        {
            "attachments": [
                {
                    "attachment_id": "att_inline",
                    "type": "image",
                    "purpose": "fine_notice",
                    "mime_type": "image/jpeg",
                },
                {"attachment_id": "att_missing"},
            ]
        }
    )

    assert payload["attachments"][0]["resolution_status"] == "inline_metadata"
    assert payload["attachments"][0]["content_type"] == "image/jpeg"
    assert payload["attachments"][1]["resolution_status"] == "unresolved"
    assert payload["attachment_resolution"]["metadata_missing_attachment_ids"] == ["att_inline"]
    assert payload["attachment_resolution"]["unresolved_attachment_ids"] == ["att_missing"]
