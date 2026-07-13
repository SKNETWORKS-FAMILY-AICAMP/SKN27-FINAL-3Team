"""Fine-notice compatibility wrappers for the canonical masking policy."""

from __future__ import annotations

from typing import Optional

from app.security.pii_masking import MASK_TOKEN, mask_text


def mask_personal_info(text: str) -> str:
    """Mask PII and secrets in OCR text using the shared sentinel."""

    return mask_text(text)


def mask_field(value: Optional[str]) -> Optional[str]:
    """Mask a field already classified as sensitive by the OCR schema."""

    if value in (None, ""):
        return value
    return MASK_TOKEN
