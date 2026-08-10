"""Explicit Mock attachment fixture and sidecar adapters.

This compatibility adapter is reachable only from the Explicit Mock runtime.
Canonical callers use ``attachment_staging_service`` instead.
"""

from __future__ import annotations

from typing import Any


def register_attachment(payload: dict[str, Any], upload_file: Any | None = None) -> dict[str, Any]:
    from app.services.attachment_mock_service import register_attachment as _register_attachment

    return _register_attachment(payload, upload_file=upload_file)


def list_attachments(session_id: str | None = None) -> list[dict[str, Any]]:
    from app.services.attachment_mock_service import list_attachments as _list_attachments

    return _list_attachments(session_id=session_id)


def get_attachment(attachment_id: str) -> dict[str, Any] | None:
    from app.services.attachment_mock_service import get_attachment as _get_attachment

    return _get_attachment(attachment_id)
