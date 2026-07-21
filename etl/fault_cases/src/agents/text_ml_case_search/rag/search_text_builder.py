from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.schemas import AgentContext


def build_search_text(
    *,
    context: AgentContext,
    normalized: dict[str, Any],
    issue_tags: list[str],
) -> dict[str, Any]:
    """Build stable text variants for BM25/Nori retrieval.

    This step does not call Elasticsearch. It only prepares query text that the
    next retriever step can use without re-reading the raw agent input.
    """

    natural_query_text = _clean(context.get("query_text"))
    normalized_description = _clean(normalized.get("normalized_description"))
    accident_types = [
        _clean(item.get("type"))
        for item in normalized.get("accident_type_candidates", [])
        if isinstance(item, dict) and _clean(item.get("type"))
    ]

    sections = [
        _format_section("사고유형", accident_types),
        _format_section("쟁점", issue_tags),
        _format_section("사고설명", [natural_query_text, _clean(context.get("raw_user_text"))]),
        _format_section("Vision 단서", _vision_lines(context.get("vision_evidence") or [])),
        _format_section("OCR 단서", _ocr_lines(context.get("ocr_evidence"))),
        _format_section("보험사 주장", _insurer_claim_lines(context.get("insurer_claim"))),
    ]
    full_optional_context = "\n\n".join(section for section in sections if section)

    schema_search_text = _join_non_empty(
        [
            f"[사고유형] {', '.join(accident_types)}" if accident_types else "",
            f"[쟁점] {', '.join(issue_tags)}" if issue_tags else "",
            f"[사고설명] {natural_query_text}" if natural_query_text else "",
            f"[정규화설명] {normalized_description}" if normalized_description else "",
            f"[OCR] {' / '.join(_ocr_lines(context.get('ocr_evidence')))}",
            f"[보험사주장] {' / '.join(_insurer_claim_lines(context.get('insurer_claim')))}",
        ],
        separator=" ",
    )

    return {
        "natural_query_text": natural_query_text,
        "normalized_description": normalized_description,
        "schema_search_text": schema_search_text,
        "full_optional_context": full_optional_context,
        "input_sections": {
            "has_raw_user_text": bool(_clean(context.get("raw_user_text"))),
            "has_vision_evidence": bool(context.get("vision_evidence")),
            "has_ocr_evidence": isinstance(context.get("ocr_evidence"), dict),
            "has_insurer_claim": isinstance(context.get("insurer_claim"), dict),
            "issue_tag_count": len(issue_tags),
            "accident_type_candidate_count": len(accident_types),
        },
    }


def _format_section(title: str, lines: list[str]) -> str:
    values = [_clean(line) for line in lines if _clean(line)]
    if not values:
        return ""
    return f"[{title}]\n" + "\n".join(f"- {value}" for value in values)


def _vision_lines(vision_evidence: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in vision_evidence:
        description = _clean(item.get("description"))
        source_reference = _clean(item.get("source_reference"))
        if description:
            lines.append(_with_source(description, source_reference))
        observations = item.get("observations") or []
        if isinstance(observations, list):
            lines.extend(_clean(value) for value in observations if _clean(value))
    return lines


def _ocr_lines(ocr_evidence: Any) -> list[str]:
    if not isinstance(ocr_evidence, dict):
        return []

    fields = [
        ("사고유형", "accident_type"),
        ("사고원인", "accident_cause"),
        ("사고설명", "accident_description"),
        ("사고장소", "accident_location"),
        ("사고일시", "accident_datetime"),
    ]
    return [
        f"{label}: {_clean(ocr_evidence.get(key))}"
        for label, key in fields
        if _clean(ocr_evidence.get(key))
    ]


def _insurer_claim_lines(insurer_claim: Any) -> list[str]:
    if not isinstance(insurer_claim, dict):
        return []

    fields = [
        ("주장비율", "claimed_ratio"),
        ("주장이유", "reason_text"),
        ("원문", "source_text"),
        ("출처", "source_reference"),
    ]
    return [
        f"{label}: {_clean(insurer_claim.get(key))}"
        for label, key in fields
        if _clean(insurer_claim.get(key))
    ]


def _with_source(text: str, source_reference: str) -> str:
    if not source_reference:
        return text
    return f"{text} (source: {source_reference})"


def _join_non_empty(values: list[str], *, separator: str) -> str:
    return separator.join(_clean(value) for value in values if _clean(value)).strip()


def _clean(value: Any) -> str:
    return str(value or "").strip()
