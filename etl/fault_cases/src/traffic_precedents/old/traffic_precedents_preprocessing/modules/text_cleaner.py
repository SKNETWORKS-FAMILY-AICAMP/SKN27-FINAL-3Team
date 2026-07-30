from __future__ import annotations

import html
import re
import unicodedata
from typing import Any


JsonDict = dict[str, Any]


TEXT_FIELDS = (
    "사건명",
    "사건번호",
    "법원명",
    "사건종류명",
    "판시사항",
    "판결요지",
    "참조조문",
    "참조판례",
    "판례내용",
    "주문",
    "이유",
    "과실비율",
)

ZERO_WIDTH_PATTERN = re.compile(r"[\u200b\u200c\u200d\ufeff]")
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
SPACE_PATTERN = re.compile(r"[ \t\r\f\v]+")
NEWLINE_PATTERN = re.compile(r"\n{3,}")


def clean_html(text: str | None) -> str | None:
    """Remove HTML tags and decode HTML entities."""

    if text is None:
        return None

    decoded = html.unescape(str(text))
    without_tags = HTML_TAG_PATTERN.sub(" ", decoded)
    return without_tags


def clean_broken_chars(text: str | None) -> str | None:
    """
    Remove invisible control characters while preserving legal text.

    This does not remove symbols such as %, :, 【】, or brackets because those
    can be meaningful for ratio extraction and section extraction.
    """

    if text is None:
        return None

    normalized = unicodedata.normalize("NFKC", str(text))
    normalized = ZERO_WIDTH_PATTERN.sub("", normalized)
    normalized = "".join(
        char
        for char in normalized
        if char == "\n" or char == "\t" or not unicodedata.category(char).startswith("C")
    )
    return normalized


def normalize_whitespace(text: str | None) -> str | None:
    """Normalize repeated spaces and excessive blank lines."""

    if text is None:
        return None

    lines = [SPACE_PATTERN.sub(" ", line).strip() for line in str(text).splitlines()]
    compacted = "\n".join(line for line in lines if line)
    compacted = NEWLINE_PATTERN.sub("\n\n", compacted)
    return compacted.strip() or None


def clean_text(text: str | None) -> str | None:
    """Apply conservative text cleaning for one field."""

    cleaned = clean_html(text)
    cleaned = clean_broken_chars(cleaned)
    cleaned = normalize_whitespace(cleaned)
    return cleaned


def clean_text_fields(row: JsonDict, fields: tuple[str, ...] = TEXT_FIELDS) -> JsonDict:
    """Clean configured text fields in a row."""

    updated = dict(row)

    for field in fields:
        if field in updated:
            updated[field] = clean_text(updated.get(field))

    return updated


def clean_text_rows(rows: list[JsonDict]) -> list[JsonDict]:
    """Clean text fields for multiple rows."""

    return [clean_text_fields(row) for row in rows]
