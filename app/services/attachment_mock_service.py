"""Legacy compatibility shim for Explicit Mock attachments."""

from app.mock_runtime.attachments import (
    CANONICAL_SCAN_GATE_MARKER,
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
