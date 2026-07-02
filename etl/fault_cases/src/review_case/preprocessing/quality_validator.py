from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable

from ..config import PipelineConfig
from ..models import ReviewCaseChunk, ReviewCaseDocument, ReviewCaseQualityRow


WARNING_FIELDS = {
    "header_road_context": "header_road_context_missing",
    "road_feature": "road_situation_missing",
    "reference_standard_text": "reference_standard_text_missing",
    "final_ratio_text": "final_ratio_text_missing",
    "toc_item_id": "toc_link_uncertain",
}

TEXT_SECTION_FIELDS = [
    "claimant_argument",
    "respondent_argument",
    "decision_reason",
    "accident_content",
    "evidence_text",
    "main_issue",
    "decision_basis",
]


def _missing(value: object) -> bool:
    return value is None or value == "" or value == []


def validate_document(doc: ReviewCaseDocument, chunks: list[ReviewCaseChunk], config: PipelineConfig) -> ReviewCaseQualityRow:
    fatal_flags: list[str] = []
    missing_fields: list[str] = []
    for field_name in config.required_document_fields:
        if _missing(getattr(doc, field_name, None)):
            missing_fields.append(field_name)
            fatal_flags.append(f"{field_name}_missing")

    if doc.a_role is None or doc.b_role is None:
        fatal_flags.append("ab_role_mapping_failed")
    if doc.claimant_final_ratio is None or doc.respondent_final_ratio is None:
        fatal_flags.append("final_ratio_mapping_failed")
    if doc.claimant_argument and doc.respondent_argument and doc.claimant_argument == doc.respondent_argument:
        fatal_flags.append("arguments_identical")
    if not chunks:
        fatal_flags.append("chunk_generation_failed")
    if doc.standard_a_behavior and doc.road_feature and doc.standard_a_behavior == doc.road_feature:
        fatal_flags.append("standard_behavior_shift_error")
    if doc.standard_a_behavior and re.fullmatch(r"\([가-하]\)", doc.standard_a_behavior):
        fatal_flags.append("standard_behavior_marker_only")
    if doc.standard_scenario_keywords and len(doc.standard_scenario_keywords) >= 4 and not doc.standard_b_behavior:
        fatal_flags.append("standard_b_behavior_missing")
    if doc.final_ratio_text and len(doc.final_ratio_text) > 120:
        fatal_flags.append("final_ratio_text_too_long")
    if doc.reference_chart_sub_no and doc.reference_chart_sub_no not in set("가나다라마바사아자차카타파하0123456789"):
        fatal_flags.append("reference_chart_sub_no_invalid")
    if any(
        value and re.search(r"목차보기|\d+\.\s*자동차와|\d+\.\s*고속도로", value)
        for value in (getattr(doc, field_name, None) for field_name in TEXT_SECTION_FIELDS)
    ):
        fatal_flags.append("navigation_text_leaked")

    warning_flags = [
        flag for field_name, flag in WARNING_FIELDS.items() if _missing(getattr(doc, field_name, None))
    ]
    if doc.reference_standard_text and len(doc.reference_standard_text) < 20:
        warning_flags.append("reference_standard_text_short")

    doc.quality_flags = fatal_flags + warning_flags
    doc.parse_status = "valid" if not fatal_flags else "review_required"
    for chunk in chunks:
        chunk.parse_status = doc.parse_status
        chunk.quality_flags = list(doc.quality_flags)

    return ReviewCaseQualityRow(
        review_case_id=doc.review_case_id,
        source_ref=doc.source_ref,
        review_no=doc.review_no,
        parse_status=doc.parse_status,
        chunk_count=len(chunks),
        fatal_flags=fatal_flags,
        warning_flags=warning_flags,
        missing_fields=missing_fields,
        validated_at=datetime.now(timezone.utc).isoformat(),
    )


def build_summary(
    documents: list[ReviewCaseDocument],
    source_chunks: Iterable[object],
    chunks: list[ReviewCaseChunk],
    quality_rows: list[ReviewCaseQualityRow],
    toc_count: int,
    toc_link_count: int,
) -> dict[str, object]:
    fatal_counter = Counter(flag for row in quality_rows for flag in row.fatal_flags)
    warning_counter = Counter(flag for row in quality_rows for flag in row.warning_flags)
    valid_count = sum(1 for doc in documents if doc.parse_status == "valid")
    return {
        "document_count": len(documents),
        "source_chunk_count": len(list(source_chunks)),
        "chunk_count": len(chunks),
        "quality_report_count": len(quality_rows),
        "toc_item_count": toc_count,
        "toc_case_link_count": toc_link_count,
        "valid_document_count": valid_count,
        "review_required_document_count": len(documents) - valid_count,
        "fatal_flag_counts": dict(sorted(fatal_counter.items())),
        "warning_flag_counts": dict(sorted(warning_counter.items())),
    }
