from __future__ import annotations

from datetime import datetime, timezone

from ..config import PipelineConfig
from ..models import ReviewCaseDocument, ReviewCaseText, ReviewCaseTocItem
from .ratio_parser import parse_decision_ratio
from .section_parser import parse_header, parse_sections
from .standard_scenario_parser import behavior_for_role, parse_standard_scenario


def _review_case_id(review_no: str) -> str:
    return f"review_case_{review_no.replace('-', '_')}"


def _find_toc_item(doc: ReviewCaseDocument, toc_items: list[ReviewCaseTocItem]) -> ReviewCaseTocItem | None:
    if doc.reference_chart_key:
        for item in toc_items:
            if item.chart_key == doc.reference_chart_key:
                return item
    if doc.book_page_start is not None:
        for item in toc_items:
            if item.book_page_no == doc.book_page_start:
                return item
    return None


def _apply_toc(doc: ReviewCaseDocument, toc_items: list[ReviewCaseTocItem]) -> ReviewCaseDocument:
    item = _find_toc_item(doc, toc_items)
    if not item:
        return doc
    doc.toc_item_id = item.toc_item_id
    doc.toc_chart_key = item.chart_key
    doc.toc_case_title = item.case_title
    doc.toc_case_condition = item.case_condition
    doc.toc_chapter_title = item.chapter_title
    doc.toc_large_category = item.large_category
    doc.toc_middle_category = item.middle_category
    doc.toc_fault_type = item.fault_type
    doc.metadata_source = "top_box+toc"
    return doc


def build_document(case: ReviewCaseText, config: PipelineConfig, toc_items: list[ReviewCaseTocItem]) -> ReviewCaseDocument:
    header = parse_header(case.clean_text)
    scenario = parse_standard_scenario(case.clean_text)
    ratio = parse_decision_ratio(case.clean_text)
    sections = parse_sections(case)
    claimant_behavior, respondent_behavior = behavior_for_role(
        ratio.a_role,
        ratio.b_role,
        scenario.standard_a_behavior,
        scenario.standard_b_behavior,
    )
    now = datetime.now(timezone.utc).isoformat()
    doc = ReviewCaseDocument(
        review_case_id=_review_case_id(case.review_no),
        review_no=case.review_no,
        source_ref=f"review_case:{case.review_no}",
        party_type=header.party_type,
        header_title_raw=header.header_title_raw,
        header_accident_group=header.header_accident_group,
        header_road_context=header.header_road_context,
        header_parse_method=header.header_parse_method,
        case_title=scenario.case_title,
        case_condition=scenario.case_condition,
        fault_type=scenario.fault_type,
        reference_chart_key=scenario.reference_chart_key,
        reference_chart_no=scenario.reference_chart_no,
        reference_chart_sub_no=scenario.reference_chart_sub_no,
        standard_scenario_raw=scenario.standard_scenario_raw,
        standard_scenario_keywords=scenario.standard_scenario_keywords,
        signal_condition=scenario.signal_condition,
        road_feature=scenario.road_feature,
        standard_a_behavior=scenario.standard_a_behavior,
        standard_b_behavior=scenario.standard_b_behavior,
        decision_fault_ratio=ratio.decision_fault_ratio,
        a_role=ratio.a_role,
        b_role=ratio.b_role,
        a_ratio=ratio.a_ratio,
        b_ratio=ratio.b_ratio,
        claimant_final_ratio=ratio.claimant_final_ratio,
        respondent_final_ratio=ratio.respondent_final_ratio,
        claimant_standard_behavior=claimant_behavior,
        respondent_standard_behavior=respondent_behavior,
        accident_content=sections.accident_content,
        reference_standard_no=sections.reference_standard_no or scenario.reference_chart_no,
        reference_standard_text=sections.reference_standard_text,
        base_fault_ratio_text=sections.base_fault_ratio_text,
        claimant_argument=sections.claimant_argument,
        respondent_argument=sections.respondent_argument,
        evidence_text=sections.evidence_text,
        main_issue=sections.main_issue,
        decision_basis=sections.decision_basis,
        decision_reason=sections.decision_reason,
        final_ratio_text=sections.final_ratio_text,
        toc_item_id=None,
        toc_chart_key=None,
        toc_case_title=None,
        toc_case_condition=None,
        toc_chapter_title=None,
        toc_large_category=None,
        toc_middle_category=None,
        toc_fault_type=None,
        metadata_source="top_box",
        pdf_page_start=case.pdf_page_start,
        pdf_page_end=case.pdf_page_end,
        book_page_start=case.book_page_start,
        book_page_end=case.book_page_end,
        raw_text=case.raw_text,
        clean_text=case.clean_text,
        source_type=config.source_type,
        source_reliability_score=config.source_reliability_score,
        parse_status="pending",
        quality_flags=[],
        metadata_enrichment_flags=[],
        created_at=now,
    )
    return _apply_toc(doc, toc_items)


def build_documents(cases: list[ReviewCaseText], config: PipelineConfig, toc_items: list[ReviewCaseTocItem]) -> list[ReviewCaseDocument]:
    return [build_document(case, config, toc_items) for case in cases]
