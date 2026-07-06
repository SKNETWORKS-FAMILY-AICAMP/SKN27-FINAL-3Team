from __future__ import annotations

import html
import re
from typing import Any


DEFAULT_SUMMARY_CHARS = 260
DEFAULT_SNIPPET_CHARS = 180
MAX_SNIPPETS = 3
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def build_display_evidence(
    *,
    evidence: list[dict[str, Any]],
    summary_chars: int = DEFAULT_SUMMARY_CHARS,
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
) -> list[dict[str, Any]]:
    return [
        build_display_evidence_item(
            item=item,
            summary_chars=summary_chars,
            snippet_chars=snippet_chars,
        )
        for item in evidence
    ]


def build_display_evidence_item(
    *,
    item: dict[str, Any],
    summary_chars: int = DEFAULT_SUMMARY_CHARS,
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
) -> dict[str, Any]:
    metadata = item.get("metadata") or {}
    chunk_text = _clean_text(item.get("chunk_text"))
    matched_snippets = _build_matched_snippets(
        highlight=metadata.get("highlight") or {},
        fallback_text=chunk_text,
        snippet_chars=snippet_chars,
    )
    display_text = " ".join([chunk_text, " ".join(matched_snippets)])

    return {
        "source_type": _clean_text(item.get("source_type")),
        "title": _clean_text(item.get("title")),
        "source_reference": _clean_text(item.get("source_reference")),
        "reference_chart_key": _clean_text(metadata.get("reference_chart_key")),
        "case_number": _clean_text(metadata.get("case_number")),
        "court_name": _clean_text(metadata.get("court_name")),
        "decision_date": _clean_text(metadata.get("decision_date")),
        "ratio_label": _build_ratio_label(metadata),
        "summary": _preview(chunk_text, summary_chars),
        "matched_snippets": matched_snippets,
        "display_warnings": _build_display_warnings(display_text),
    }


def _build_matched_snippets(
    *,
    highlight: dict[str, Any],
    fallback_text: str,
    snippet_chars: int,
) -> list[str]:
    snippets: list[str] = []

    for field_name in ("search_text", "chunk_text"):
        fragments = highlight.get(field_name) or []
        if isinstance(fragments, str):
            fragments = [fragments]
        for fragment in fragments:
            cleaned = _preview(_clean_text(fragment), snippet_chars)
            if cleaned and cleaned not in snippets:
                snippets.append(cleaned)
            if len(snippets) >= MAX_SNIPPETS:
                return snippets

    if snippets:
        return snippets[:MAX_SNIPPETS]

    if fallback_text:
        snippets.append(_preview(fallback_text, snippet_chars))

    return snippets[:MAX_SNIPPETS]


def _build_ratio_label(metadata: dict[str, Any]) -> str:
    decision_fault_ratio = _clean_text(metadata.get("decision_fault_ratio"))
    if decision_fault_ratio:
        return decision_fault_ratio

    claimant_ratio = _clean_text(metadata.get("claimant_final_ratio"))
    respondent_ratio = _clean_text(metadata.get("respondent_final_ratio"))
    if claimant_ratio and respondent_ratio:
        return f"claimant {claimant_ratio} : respondent {respondent_ratio}"

    precedent_context = metadata.get("precedent_context") or {}
    if precedent_context:
        return _clean_text(precedent_context.get("source_label"))

    return ""


def _build_display_warnings(text: str) -> list[str]:
    warnings: list[str] = []
    if _looks_like_encoding_issue(text):
        warnings.append("text_encoding_review_required")
    return warnings


def _looks_like_encoding_issue(text: str) -> bool:
    if not text:
        return False
    if "\ufffd" in text:
        return True

    mojibake_markers = (
        "\u00ec",
        "\u00eb",
        "\u00ea",
        "\uf9e1",
        "\uf9e7",
        "\uf92f",
    )
    marker_count = sum(text.count(marker) for marker in mojibake_markers)
    return marker_count >= 3


def _clean_text(value: Any) -> str:
    text = str(value or "")
    text = html.unescape(text)
    text = _TAG_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text)
    return text.strip()


def _preview(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."
