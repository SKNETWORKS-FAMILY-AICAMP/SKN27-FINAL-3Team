# -*- coding: utf-8 -*-
"""발간사, 개정경과, 총설 section을 저장용 JSON으로 만듭니다."""

from typing import Any, Dict, List

from .models import PageText


def build_explanatory_sections(pages: List[PageText]) -> List[Dict[str, Any]]:
    """상세 rule 전 설명 section들을 생성합니다."""

    return [
        build_preface_section(pages),
        build_revision_history_section(pages),
        build_general_theory_section(pages),
    ]


def select_pages_between_markers(
    pages: List[PageText],
    start_keywords: List[str],
    end_keywords: List[str],
) -> List[PageText]:
    """문서 안의 제목 marker를 기준으로 section 페이지를 선택합니다."""

    start_idx = None
    end_idx = None
    for idx, page in enumerate(pages):
        text = page.clean_text.replace(" ", "")
        if start_idx is None and any(keyword.replace(" ", "") in text for keyword in start_keywords):
            start_idx = idx
            continue
        if start_idx is not None and any(keyword.replace(" ", "") in text for keyword in end_keywords):
            end_idx = idx
            break

    if start_idx is None:
        return []
    if end_idx is None:
        end_idx = len(pages)
    return pages[start_idx:end_idx]


def join_page_text(selected: List[PageText]) -> tuple[str, str, int | None, int | None]:
    raw_text = "\n\n".join(page.raw_text for page in selected).strip()
    clean_text = "\n\n".join(page.clean_text for page in selected).strip()
    if not selected:
        return raw_text, clean_text, None, None
    nums = [page.page_no for page in selected]
    return raw_text, clean_text, min(nums), max(nums)


def build_preface_section(pages: List[PageText]) -> Dict[str, Any]:
    """발간사 section을 만듭니다."""

    selected = select_pages_between_markers(pages, ["발간사"], ["개정경과"])
    raw_text, clean_text, page_start, page_end = join_page_text(selected)
    return {
        "section_id": "official_2023_preface",
        "section_type": "preface",
        "section_title": "발간사",
        "page_start": page_start,
        "page_end": page_end,
        "raw_text": raw_text,
        "clean_text": clean_text,
    }


def build_revision_history_section(pages: List[PageText]) -> Dict[str, Any]:
    """개정경과 section을 만듭니다."""

    selected = select_pages_between_markers(pages, ["개정경과"], ["총설", "총 설"])
    raw_text, clean_text, page_start, page_end = join_page_text(selected)
    return {
        "section_id": "official_2023_revision_history",
        "section_type": "revision_history",
        "section_title": "제1편 개정경과",
        "page_start": page_start,
        "page_end": page_end,
        "revision_round": "10차 개정",
        "published_year": 2023,
        "published_month": 6,
        "raw_text": raw_text,
        "clean_text": clean_text,
    }


def build_general_theory_section(pages: List[PageText]) -> Dict[str, Any]:
    """총설 section을 만듭니다."""

    selected = select_pages_between_markers(pages, ["총설", "총 설"], ["과실비율 적용기준", "제3편"])
    raw_text, clean_text, page_start, page_end = join_page_text(selected)
    return {
        "section_id": "official_2023_general_theory",
        "section_type": "general_theory",
        "section_title": "제2편 총설",
        "page_start": page_start,
        "page_end": page_end,
        "main_topics": [
            "과실비율 인정기준의 필요성",
            "과실과 과실상계",
            "신뢰의 원칙",
            "인과관계",
            "수정요소 적용",
            "인적 손해 별도적용기준",
        ],
        "raw_text": raw_text,
        "clean_text": clean_text,
    }
