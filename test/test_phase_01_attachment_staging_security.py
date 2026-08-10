from __future__ import annotations

import shutil

import pytest

from app.services.attachment_staging_service import register_staged_attachment


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
