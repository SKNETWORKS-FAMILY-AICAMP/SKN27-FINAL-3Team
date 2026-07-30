from __future__ import annotations

import difflib
from collections import defaultdict
from typing import Any


JsonDict = dict[str, Any]


DUPLICATE_KEY_FIELDS = ("사건명", "사건번호", "법원명", "선고일자")
SIMILARITY_FIELDS = ("판시사항", "판결요지", "판례내용")
DEFAULT_SIMILARITY_THRESHOLD = 0.90


def normalize_key_value(value: Any) -> str:
    """Normalize duplicate-key values without changing the row itself."""

    if value is None:
        return ""

    return " ".join(str(value).split())


def build_duplicate_key(row: JsonDict) -> tuple[str, ...]:
    """Build a same-case duplicate key."""

    return tuple(normalize_key_value(row.get(field)) for field in DUPLICATE_KEY_FIELDS)


def build_similarity_text(row: JsonDict) -> str:
    """Build comparison text from legally meaningful source fields."""

    parts = [normalize_key_value(row.get(field)) for field in SIMILARITY_FIELDS]
    return "\n".join(part for part in parts if part)


def text_similarity(a: str, b: str) -> float:
    """Return SequenceMatcher similarity for two text values."""

    if not a and not b:
        return 1.0

    if not a or not b:
        return 0.0

    return difflib.SequenceMatcher(None, a, b).ratio()


def choose_representative(rows: list[JsonDict]) -> JsonDict:
    """
    Choose a representative duplicate row.

    The row with the longest comparison text is kept because it usually
    preserves the most complete 판시사항/판결요지/판례내용.
    """

    return max(rows, key=lambda row: len(build_similarity_text(row)))


def group_rows_by_duplicate_key(rows: list[JsonDict]) -> dict[tuple[str, ...], list[JsonDict]]:
    """Group rows by duplicate key."""

    groups: dict[tuple[str, ...], list[JsonDict]] = defaultdict(list)

    for row in rows:
        groups[build_duplicate_key(row)].append(row)

    return dict(groups)


def remove_duplicates(
    rows: list[JsonDict],
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> tuple[list[JsonDict], list[JsonDict], list[JsonDict]]:
    """
    Remove near-duplicate cases inside the same duplicate-key group.

    Returns:
        kept_rows, removed_rows, duplicate_group_summaries
    """

    kept_rows: list[JsonDict] = []
    removed_rows: list[JsonDict] = []
    duplicate_group_summaries: list[JsonDict] = []

    for key, group in group_rows_by_duplicate_key(rows).items():
        if len(group) == 1:
            kept_rows.append(group[0])
            continue

        representative = choose_representative(group)
        representative_text = build_similarity_text(representative)
        representative_id = representative.get("_case_id")
        group_removed: list[JsonDict] = []

        for row in group:
            if row is representative:
                continue

            similarity = text_similarity(representative_text, build_similarity_text(row))

            if similarity >= similarity_threshold:
                removed = dict(row)
                removed["_duplicate_reason"] = "same_key_high_text_similarity"
                removed["_duplicate_similarity"] = similarity
                removed["_duplicate_representative_case_id"] = representative_id
                group_removed.append(removed)
            else:
                kept_rows.append(row)

        kept_rows.append(representative)

        if group_removed:
            removed_rows.extend(group_removed)
            duplicate_group_summaries.append(
                {
                    "duplicate_key": key,
                    "representative_case_id": representative_id,
                    "group_size": len(group),
                    "removed_count": len(group_removed),
                    "similarity_threshold": similarity_threshold,
                }
            )

    return kept_rows, removed_rows, duplicate_group_summaries
