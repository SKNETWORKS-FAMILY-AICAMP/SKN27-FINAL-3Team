from __future__ import annotations

from typing import Any

from .search_text_config import (
    CHUNK_TYPE_LABELS,
    COMMON_EXTRA_LABELS,
    COMMON_SEARCH_FIELDS,
    TYPE_SPECIFIC_SEARCH_FIELDS,
)


def _value(row: dict[str, Any], document: dict[str, Any], key: str) -> Any:
    value = row.get(key)
    if value is None or value == "":
        value = document.get(key)
    return value


def _append_line(lines: list[str], label: str, value: Any) -> None:
    if value is None or value == "":
        return
    if isinstance(value, list):
        if not value:
            return
        value = ", ".join(str(item) for item in value if item is not None and str(item).strip())
    elif isinstance(value, dict):
        if not value:
            return
        value = ", ".join(f"{key}={item}" for key, item in value.items())
    value = str(value).strip()
    if value:
        lines.append(f"{label}: {value}")


def _append_common(lines: list[str], row: dict[str, Any], document: dict[str, Any]) -> None:
    chunk_type = row.get("chunk_type")
    _append_line(lines, COMMON_EXTRA_LABELS["chunk_type"], CHUNK_TYPE_LABELS.get(chunk_type, chunk_type))
    for label, key in COMMON_SEARCH_FIELDS:
        _append_line(lines, label, _value(row, document, key))
    _append_line(
        lines,
        COMMON_EXTRA_LABELS["standard_scenario_keywords"],
        _value(row, document, "standard_scenario_keywords"),
    )
    _append_line(lines, COMMON_EXTRA_LABELS["claimant_final_ratio"], _value(row, document, "claimant_final_ratio"))
    _append_line(lines, COMMON_EXTRA_LABELS["respondent_final_ratio"], _value(row, document, "respondent_final_ratio"))


def _append_type_specific(lines: list[str], row: dict[str, Any], document: dict[str, Any]) -> None:
    chunk_type = row.get("chunk_type")
    for label, key in TYPE_SPECIFIC_SEARCH_FIELDS.get(chunk_type, []):
        _append_line(lines, label, document.get(key))


def build_search_text(row: dict[str, Any], document: dict[str, Any]) -> str:
    """Build BM25/Nori-oriented text while preserving chunk_text as the answer context."""

    lines: list[str] = []
    _append_common(lines, row, document)
    _append_type_specific(lines, row, document)
    _append_line(lines, COMMON_EXTRA_LABELS["body"], row.get("chunk_text"))
    return "\n".join(dict.fromkeys(line for line in lines if line.strip()))
