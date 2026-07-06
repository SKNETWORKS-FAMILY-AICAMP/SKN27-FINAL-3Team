from __future__ import annotations

from ..models import ReviewCaseChunk, ReviewCaseDocument, ReviewCaseSourceChunk, ReviewCaseText


def _clip(value: str | None) -> str:
    return (value or "").strip()


def _split_text(text: str, size: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return [chunk for chunk in chunks if chunk]


def build_source_chunks(cases: list[ReviewCaseText], source_type: str, reliability: int, size: int, overlap: int) -> list[ReviewCaseSourceChunk]:
    rows: list[ReviewCaseSourceChunk] = []
    for case in cases:
        for index, chunk_text in enumerate(_split_text(case.clean_text, size, overlap), start=1):
            rows.append(
                ReviewCaseSourceChunk(
                    source_chunk_id=f"source_chunk_{case.review_no.replace('-', '_')}_{index:03d}",
                    source_ref=f"review_case:{case.review_no}",
                    review_no=case.review_no,
                    sequence_no=index,
                    chunk_text=chunk_text,
                    page_start=case.page_start,
                    page_end=case.page_end,
                    pdf_page_start=case.pdf_page_start,
                    pdf_page_end=case.pdf_page_end,
                    book_page_start=case.book_page_start,
                    book_page_end=case.book_page_end,
                    source_type=source_type,
                    source_reliability_score=reliability,
                )
            )
    return rows


def build_review_case_chunks(doc: ReviewCaseDocument) -> list[ReviewCaseChunk]:
    keyword_text = ", ".join(doc.standard_scenario_keywords)
    chunks = [
        (
            "case_overview",
            "\n".join(
                [
                    f"심의번호: {doc.review_no}",
                    f"상단 사고분류: {_clip(doc.header_title_raw)}",
                    f"사례명: {_clip(doc.case_title)}",
                    f"참고기준 키워드: {keyword_text}",
                    f"신호조건: {_clip(doc.signal_condition)}",
                    f"도로특징: {_clip(doc.road_feature)}",
                    f"A 표준행동: {_clip(doc.standard_a_behavior)}",
                    f"B 표준행동: {_clip(doc.standard_b_behavior)}",
                    f"결정비율: {_clip(doc.decision_fault_ratio)}",
                    f"사고내용: {_clip(doc.accident_content)}",
                ]
            ),
        ),
        ("arguments", f"청구인 주장: {_clip(doc.claimant_argument)}\n피청구인 주장: {_clip(doc.respondent_argument)}"),
        ("evidence_issue", f"입증자료: {_clip(doc.evidence_text)}\n주요쟁점: {_clip(doc.main_issue)}"),
        ("decision", f"결정근거: {_clip(doc.decision_basis)}\n결정이유: {_clip(doc.decision_reason)}\n최종비율: {_clip(doc.final_ratio_text)}"),
    ]
    return [
        ReviewCaseChunk(
            chunk_id=f"{doc.review_case_id}_{chunk_type}",
            review_case_id=doc.review_case_id,
            source_ref=doc.source_ref,
            review_no=doc.review_no,
            chunk_type=chunk_type,
            sequence_no=index,
            chunk_text=text.strip(),
            decision_fault_ratio=doc.decision_fault_ratio,
            reference_chart_key=doc.reference_chart_key,
            source_type=doc.source_type,
            source_reliability_score=doc.source_reliability_score,
            parse_status=doc.parse_status,
            quality_flags=list(doc.quality_flags),
        )
        for index, (chunk_type, text) in enumerate(chunks, start=1)
    ]
