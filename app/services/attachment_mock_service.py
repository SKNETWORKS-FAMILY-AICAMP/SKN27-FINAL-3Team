"""Legacy compatibility shim for Explicit Mock attachments."""

from app.services.attachment_scan_gate_contract import CANONICAL_SCAN_GATE_MARKER
from app.mock_runtime.attachments import (
    UploadTooLargeError,
    get_attachment,
    list_attachments,
    register_attachment,
    resolve_attachment_references,
)

__all__ = [
    "CANONICAL_SCAN_GATE_MARKER",
    "UploadTooLargeError",
    "get_attachment",
    "list_attachments",
    "register_attachment",
    "resolve_attachment_references",
]
