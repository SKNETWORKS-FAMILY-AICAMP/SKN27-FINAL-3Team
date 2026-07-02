"""
심의사례 수집/전처리 데이터 모델.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PdfLinkInfo:
    attachment_url: str
    link_text: str
    source_page_url: str


@dataclass
class CollectionManifestRow:
    collection_id: str
    seed_url: str
    source_page_url: str
    attachment_url: str
    original_filename: str
    saved_filename: str
    saved_path: str
    file_size: int
    sha256: str
    matched_keywords: list[str]
    status: str
    collection_method: str
    source_type: str
    source_reliability_score: int
    collected_at: str


@dataclass
class CollectionQualityRow:
    collection_id: str
    saved_path: str
    file_exists: bool
    file_size: int
    is_pdf_extension: bool
    sha256: str | None
    pdf_open_ok: bool
    page_count: int | None
    sample_text_ok: bool
    validation_status: str
    quality_flags: list[str]
    validated_at: str


@dataclass
class PageText:
    page_no: int
    raw_text: str
    clean_text: str
    extractor: str
    error: str | None = None
    book_page_no: int | None = None
    page_label: str | None = None
    raw_words: list[dict[str, Any]] = field(default_factory=list)
    layout_claimant_argument: str | None = None
    layout_respondent_argument: str | None = None


@dataclass
class ReviewCaseSourceChunk:
    source_chunk_id: str
    source_ref: str
    review_no: str | None
    sequence_no: int
    chunk_text: str
    page_start: int
    page_end: int
    pdf_page_start: int | None
    pdf_page_end: int | None
    book_page_start: int | None
    book_page_end: int | None
    source_type: str
    source_reliability_score: int
    created_at: str = ""


@dataclass
class ReviewCaseTocItem:
    toc_item_id: str
    chapter_title: str | None
    large_category: str | None
    middle_category: str | None
    chart_no: str | None
    chart_sub_no: str | None
    chart_key: str | None
    case_title: str
    case_condition: str | None
    fault_type: str | None
    book_page_no: int | None
    toc_pdf_page_no: int
    source_type: str
    parse_status: str
    quality_flags: list[str] = field(default_factory=list)


@dataclass
class ReviewCaseText:
    review_no: str
    page_start: int
    page_end: int
    raw_text: str
    clean_text: str
    extractor: str
    pdf_page_start: int | None = None
    pdf_page_end: int | None = None
    book_page_start: int | None = None
    book_page_end: int | None = None
    layout_claimant_argument: str | None = None
    layout_respondent_argument: str | None = None


@dataclass
class ReviewCaseDocument:
    review_case_id: str
    review_no: str
    source_ref: str
    party_type: str | None
    header_title_raw: str | None
    header_accident_group: str | None
    header_road_context: str | None
    header_parse_method: str | None
    case_title: str | None
    case_condition: str | None
    fault_type: str | None
    reference_chart_key: str | None
    reference_chart_no: str | None
    reference_chart_sub_no: str | None
    standard_scenario_raw: str | None
    standard_scenario_keywords: list[str]
    signal_condition: str | None
    road_feature: str | None
    standard_a_behavior: str | None
    standard_b_behavior: str | None
    decision_fault_ratio: str | None
    a_role: str | None
    b_role: str | None
    a_ratio: int | None
    b_ratio: int | None
    claimant_final_ratio: int | None
    respondent_final_ratio: int | None
    claimant_standard_behavior: str | None
    respondent_standard_behavior: str | None
    accident_content: str | None
    reference_standard_no: str | None
    reference_standard_text: str | None
    base_fault_ratio_text: str | None
    claimant_argument: str | None
    respondent_argument: str | None
    evidence_text: str | None
    main_issue: str | None
    decision_basis: str | None
    decision_reason: str | None
    final_ratio_text: str | None
    toc_item_id: str | None
    toc_chart_key: str | None
    toc_case_title: str | None
    toc_case_condition: str | None
    toc_chapter_title: str | None
    toc_large_category: str | None
    toc_middle_category: str | None
    toc_fault_type: str | None
    metadata_source: str | None
    pdf_page_start: int | None
    pdf_page_end: int | None
    book_page_start: int | None
    book_page_end: int | None
    raw_text: str
    clean_text: str
    source_type: str
    source_reliability_score: int
    parse_status: str
    quality_flags: list[str] = field(default_factory=list)
    metadata_enrichment_flags: list[str] = field(default_factory=list)
    created_at: str = ""


@dataclass
class ReviewCaseChunk:
    chunk_id: str
    review_case_id: str
    source_ref: str
    review_no: str
    chunk_type: str
    sequence_no: int
    chunk_text: str
    decision_fault_ratio: str | None
    reference_chart_key: str | None
    source_type: str
    source_reliability_score: int
    parse_status: str
    quality_flags: list[str] = field(default_factory=list)
    created_at: str = ""


@dataclass
class ReviewCaseTocCaseLink:
    link_id: str
    toc_item_id: str | None
    review_case_id: str
    review_no: str
    chart_key: str | None
    document_reference_chart_key: str | None
    toc_chart_key: str | None
    toc_case_title: str | None
    toc_case_condition: str | None
    chart_key_relation: str | None
    toc_book_page_no: int | None
    case_book_page_start: int | None
    match_status: str
    match_reason: str
    quality_flags: list[str] = field(default_factory=list)


@dataclass
class ReviewCaseQualityRow:
    review_case_id: str
    source_ref: str
    review_no: str
    parse_status: str
    chunk_count: int
    fatal_flags: list[str]
    warning_flags: list[str]
    missing_fields: list[str]
    validated_at: str


@dataclass
class LoaderReport:
    extractor: str
    expected_page_count: int
    read_page_count: int
    fallback_errors: dict[str, str]
    metadata: dict[str, Any] = field(default_factory=dict)
