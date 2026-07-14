from __future__ import annotations

import re
from typing import Any


JsonDict = dict[str, Any]


COMPACTION_MARKER = "[손해액_산정표_생략]"
NUMERIC_DENSE_MIN_LENGTH = 120
NUMERIC_DENSE_DIGIT_RATIO = 0.35

COMPACT_FIELDS = ("판례내용", "이유")

FAULT_CONTEXT_PATTERN = re.compile(
    r"과실|과실비율|책임비율|책임분담비율|과실상계|책임제한|손해배상책임"
)
TABLE_HINT_PATTERN = re.compile(
    r"호프만|노임|월소득|일실수입|기간초일|기간말일|상실률|노동능력|"
    r"계산표|산정표|기왕치료비|향후치료비|일수|월수|원\s*[×x]"
)


def _digit_ratio(text: str) -> float:
    if not text:
        return 0.0

    return sum(char.isdigit() for char in text) / len(text)


def is_numeric_table_like_block(text: str) -> bool:
    """
    Detect dense numeric calculation blocks conservatively.

    Blocks containing fault-ratio context are not compacted, because they can
    include the exact ratio evidence we need.
    """

    if not text:
        return False

    block = text.strip()

    if len(block) < NUMERIC_DENSE_MIN_LENGTH:
        return False

    if FAULT_CONTEXT_PATTERN.search(block):
        return False

    if _digit_ratio(block) < NUMERIC_DENSE_DIGIT_RATIO:
        return False

    return bool(TABLE_HINT_PATTERN.search(block))


def split_blocks(text: str) -> list[str]:
    """Split text into paragraph-like blocks."""

    return re.split(r"\n{2,}", text)


def compact_numeric_tables(text: str | None) -> tuple[str | None, int]:
    """Replace numeric table-like blocks with a marker."""

    if text is None:
        return None, 0

    blocks = split_blocks(str(text))
    compacted_blocks: list[str] = []
    compact_count = 0

    for block in blocks:
        if is_numeric_table_like_block(block):
            compacted_blocks.append(COMPACTION_MARKER)
            compact_count += 1
        else:
            compacted_blocks.append(block)

    compacted = "\n\n".join(block.strip() for block in compacted_blocks if block.strip())
    return compacted or None, compact_count


def compact_numeric_table_fields(
    row: JsonDict,
    fields: tuple[str, ...] = COMPACT_FIELDS,
) -> tuple[JsonDict, int]:
    """Compact numeric table-like blocks in configured row fields."""

    updated = dict(row)
    total_count = 0

    for field in fields:
        if field not in updated:
            continue

        compacted, count = compact_numeric_tables(updated.get(field))
        updated[field] = compacted
        total_count += count

    if total_count:
        updated["_numeric_table_compaction_count"] = total_count

    return updated, total_count


def compact_numeric_table_rows(rows: list[JsonDict]) -> tuple[list[JsonDict], int]:
    """Compact numeric table-like blocks for multiple rows."""

    compacted_rows: list[JsonDict] = []
    total_count = 0

    for row in rows:
        compacted, count = compact_numeric_table_fields(row)
        compacted_rows.append(compacted)
        total_count += count

    return compacted_rows, total_count
