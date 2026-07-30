from __future__ import annotations

import re
from typing import Any


JsonDict = dict[str, Any]


SECTION_HEADINGS = {
    "전문": ("전 문", "전문"),
    "주문": ("주 문", "주문"),
    "이유": ("이 유", "이유"),
}

ORDER_HEADINGS = SECTION_HEADINGS["주문"]
REASON_HEADINGS = SECTION_HEADINGS["이유"]


def _heading_pattern(heading: str) -> re.Pattern[str]:
    """
    Build a conservative heading pattern.

    Only bracketed headings are trusted. This avoids splitting normal sentences
    that merely contain words such as 주문 or 이유.
    """

    escaped = re.escape(heading)
    compact = re.escape(heading.replace(" ", ""))

    return re.compile(
        rf"(?:【\s*(?:{escaped}|{compact})\s*】|\[\s*(?:{escaped}|{compact})\s*\])"
    )


def find_heading_positions(text: str) -> list[tuple[str, int, int]]:
    """Find trusted bracket heading positions in source order."""

    positions: list[tuple[str, int, int]] = []

    for section_name, headings in SECTION_HEADINGS.items():
        for heading in headings:
            for match in _heading_pattern(heading).finditer(text):
                positions.append((section_name, match.start(), match.end()))

    positions.sort(key=lambda item: item[1])
    return positions


def normalize_section_text(text: str | None) -> str | None:
    """Trim extracted section text without changing legal wording."""

    if text is None:
        return None

    stripped = text.strip()
    return stripped or None


def extract_section(text: str | None, section_name: str) -> str | None:
    """
    Extract a section by trusted bracket heading.

    The section ends at the next trusted heading. If a heading is absent, the
    function returns None instead of guessing from unbracketed words.
    """

    if not text:
        return None

    positions = find_heading_positions(text)

    for index, (name, _start, end) in enumerate(positions):
        if name != section_name:
            continue

        next_start = len(text)

        if index + 1 < len(positions):
            next_start = positions[index + 1][1]

        return normalize_section_text(text[end:next_start])

    return None


def extract_order_and_reason(row: JsonDict) -> JsonDict:
    """
    Fill 주문 and 이유 from 판례내용 when bracket headings are available.

    Existing 주문/이유 values are preserved. The original 판례내용 is never
    modified here.
    """

    updated = dict(row)
    content = updated.get("판례내용")

    if not updated.get("주문"):
        updated["주문"] = extract_section(content, "주문")

    if not updated.get("이유"):
        updated["이유"] = extract_section(content, "이유")

    return updated


def extract_order_and_reason_many(rows: list[JsonDict]) -> list[JsonDict]:
    """Apply 주문/이유 extraction to multiple rows."""

    return [extract_order_and_reason(row) for row in rows]
