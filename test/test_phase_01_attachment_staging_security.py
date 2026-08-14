from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.attachment_staging_service import get_staged_attachment, register_staged_attachment


class _OversizedUpload:
    name = "outside-victim.txt"
    content_type = "text/plain"

    def chunks(self):
        yield b"oversized"


def _create_directory_link(link_path: Path, target_path: Path) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        return
    link_path.symlink_to(target_path, target_is_directory=True)


def _assert_unsafe_staging_error(error: ValueError | None) -> None:
    assert error is not None
    assert "unsafe attachment staging path" in str(error)


@pytest.mark.parametrize(
    "attachment_id",
    ["../escape", "..\\escape", "/tmp/escape", "C:\\escape", "att/child"],
)
def test_staging_rejects_untrusted_attachment_id_before_creating_a_directory(tmp_path, monkeypatch, attachment_id: str) -> None:
    staging_root = tmp_path / "staging"
    outside = tmp_path / "escape"
    monkeypatch.setenv("ATTACHMENT_STAGING_ROOT", str(staging_root))
    try:
        with pytest.raises(ValueError, match="attachment_id"):
            register_staged_attachment(
                {
                    "attachment_id": attachment_id,
                    "filename": "harmless.txt",
                    "content_type": "text/plain",
                }
            )
    finally:
        shutil.rmtree(outside, ignore_errors=True)

    assert not outside.exists()
    assert not staging_root.exists()


@pytest.mark.parametrize("operation", ["read", "metadata_write", "upload_cleanup_delete"])
def test_staging_rejects_linked_attachment_directory_before_read_write_or_cleanup_delete(
    tmp_path, monkeypatch, operation: str
) -> None:
    staging_root = tmp_path / "staging"
    outside = tmp_path / "outside"
    attachment_id = "att_linked"
    outside.mkdir()
    outside_metadata = outside / "metadata.json"
    outside_metadata.write_text('{"origin": "outside"}', encoding="utf-8")
    outside_file = outside / "outside-victim.txt"
    outside_file.write_text("must remain outside staging", encoding="utf-8")
    _create_directory_link(staging_root / attachment_id, outside)
    monkeypatch.setenv("ATTACHMENT_STAGING_ROOT", str(staging_root))

    error: ValueError | None = None
    result = None
    try:
        if operation == "read":
            result = get_staged_attachment(attachment_id)
        elif operation == "metadata_write":
            result = register_staged_attachment(
                {"attachment_id": attachment_id, "filename": "harmless.txt", "content_type": "text/plain"}
            )
        else:
            result = register_staged_attachment(
                {"attachment_id": attachment_id, "filename": "outside-victim.txt", "content_type": "text/plain"},
                _OversizedUpload(),
                max_upload_bytes=1,
            )
    except ValueError as caught:
        error = caught

    assert outside_metadata.read_text(encoding="utf-8") == '{"origin": "outside"}'
    assert outside_file.exists(), "linked staging cleanup deleted an outside file"
    assert outside_file.read_text(encoding="utf-8") == "must remain outside staging"
    assert result is None
    _assert_unsafe_staging_error(error)


def test_staging_rejects_a_linked_root_before_writing_metadata(tmp_path, monkeypatch) -> None:
    configured_root = tmp_path / "staging-link"
    outside = tmp_path / "outside"
    attachment_id = "att_root_linked"
    outside_attachment_dir = outside / attachment_id
    outside_attachment_dir.mkdir(parents=True)
    outside_metadata = outside_attachment_dir / "metadata.json"
    outside_metadata.write_text('{"origin": "outside-root"}', encoding="utf-8")
    _create_directory_link(configured_root, outside)
    monkeypatch.setenv("ATTACHMENT_STAGING_ROOT", str(configured_root))

    error: ValueError | None = None
    result = None
    try:
        result = register_staged_attachment(
            {"attachment_id": attachment_id, "filename": "harmless.txt", "content_type": "text/plain"}
        )
    except ValueError as caught:
        error = caught

    assert outside_metadata.read_text(encoding="utf-8") == '{"origin": "outside-root"}'
    assert result is None
    _assert_unsafe_staging_error(error)


def test_staging_allows_a_normal_directory_inside_the_configured_root(tmp_path, monkeypatch) -> None:
    staging_root = tmp_path / "staging"
    monkeypatch.setenv("ATTACHMENT_STAGING_ROOT", str(staging_root))

    attachment = register_staged_attachment(
        {"attachment_id": "att_normal", "filename": "harmless.txt", "content_type": "text/plain"}
    )

    assert attachment["attachment_id"] == "att_normal"
    assert (staging_root / "att_normal" / "metadata.json").exists()


def test_object_storage_rejects_linked_local_staging_uri_before_read_or_delete(tmp_path, monkeypatch) -> None:
    import sys

    backend_root = Path(__file__).resolve().parents[1] / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from app.services.attachment_staging_path_contract import UnsafeAttachmentStagingPathError
    from chatbot.object_storage import delete_source_uri, write_object_from_source_uri
    from django.test import override_settings

    staging_root = tmp_path / "staging"
    outside = tmp_path / "outside"
    attachment_id = "att_linked"
    outside.mkdir()
    outside_file = outside / "outside-victim.txt"
    outside_file.write_text("must remain outside staging", encoding="utf-8")
    (outside / "metadata.json").write_text('{"origin": "outside"}', encoding="utf-8")
    _create_directory_link(staging_root / attachment_id, outside)
    source_uri = f"local://attachment-staging/{attachment_id}/outside-victim.txt"

    with override_settings(ATTACHMENT_STAGING_ROOT=str(staging_root)):
        with pytest.raises(UnsafeAttachmentStagingPathError):
            write_object_from_source_uri(
                {
                    "provider": "mock_s3",
                    "bucket": "quarantine",
                    "key": "uploads/att_linked/outside-victim.txt",
                    "resource_type": "uploaded_file",
                    "resource_id": attachment_id,
                    "source_uri": source_uri,
                }
            )
        with pytest.raises(UnsafeAttachmentStagingPathError):
            delete_source_uri(source_uri, attachment_id=attachment_id)

    assert outside_file.read_text(encoding="utf-8") == "must remain outside staging"
    assert (outside / "metadata.json").read_text(encoding="utf-8") == '{"origin": "outside"}'
