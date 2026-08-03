"""Public allowlist projection for verified law-ground results."""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.security.pii_masking import detect_text_categories


MAX_PUBLIC_LAW_SUMMARY_LENGTH = 240
_PATH_OR_URI_RE = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://|[a-zA-Z]:[\\/])",
    re.IGNORECASE,
)


def project_public_law_items(
    structured_result: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Return verified law labels without raw text or internal references."""

    raw_items = structured_result.get("matched_laws")
    if not isinstance(raw_items, list) or not raw_items:
        raw_items = structured_result.get("law_provisions")
    provision_text_by_reference = {
        str(item.get("source_reference") or "").strip(): str(
            item.get("provision_text") or ""
        ).strip()
        for item in structured_result.get("law_provisions") or []
        if isinstance(item, Mapping)
        and str(item.get("source_reference") or "").strip()
    }

    public: list[dict[str, str]] = []
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, Mapping):
            continue
        source_reference = str(raw.get("source_reference") or "").strip()
        if not source_reference:
            continue
        law_name = _first_text(raw, "law_name", "source_name", "title")
        article = _first_text(raw, "article", "article_no", "section_ref")
        if not law_name or not article:
            continue
        item = {"law_name": law_name, "article": article}
        summary = str(raw.get("summary") or "").strip()
        provision_text = (
            str(raw.get("provision_text") or "").strip()
            or provision_text_by_reference.get(source_reference, "")
        )
        if (
            summary
            and summary != provision_text
            and len(summary) <= MAX_PUBLIC_LAW_SUMMARY_LENGTH
            and not _PATH_OR_URI_RE.search(summary)
            and not detect_text_categories(summary)
            and not _contains_pipe_table_fragment(summary)
        ):
            item["summary"] = summary
        if item not in public:
            public.append(item)
    return public[:3]


def _contains_pipe_table_fragment(value: str) -> bool:
    for line in value.splitlines() or [value]:
        stripped = line.strip()
        if line.count("|") < 2:
            continue
        if stripped.startswith("|") or stripped.endswith("|"):
            return True
        if re.search(r"\|\s*\|", line):
            return True
    return False


def _first_text(value: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        text = str(value.get(key) or "").strip()
        if text:
            return text
    return ""
