"""Traffic-confirmation OCR wrappers for the canonical masking policy."""

from __future__ import annotations

from typing import Any

from app.security.pii_masking import (
    MASK_TOKEN as MASK_TOKEN,
    mask_sensitive_fields as _mask_sensitive_fields,
    mask_text,
)


def mask_sensitive_text(text: str) -> str:
    return mask_text(text)


def mask_sensitive_fields(value: Any) -> tuple[Any, list[str]]:
    return _mask_sensitive_fields(value)
