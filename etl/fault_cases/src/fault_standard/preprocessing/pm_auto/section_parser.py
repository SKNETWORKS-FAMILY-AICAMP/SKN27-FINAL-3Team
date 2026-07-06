# -*- coding: utf-8 -*-
"""개요, 적용범위, 용어정의, 수정요소 해설 section을 저장용 JSON으로 만듭니다."""

from typing import Any, Dict, List
import re

from .models import PageText
from .config import SECTION_ID_PREFIX


def find_first_chart_page(pages: List[PageText]) -> int:
    """첫 도표 시작 페이지를 텍스트 앵커로 찾습니다."""

    for page in pages:
        if re.search(r"도표\s*0?1\b", page.clean_text) and ("수정요소" in page.clean_text or re.search(r"A\s*\d{1,3}\s*:\s*B\s*\d{1,3}", page.clean_text)):
            return page.page_no
    for page in pages:
        if re.search(r"도표\s*0?1\b", page.clean_text) and "사고" in page.clean_text:
            return page.page_no
    return max(page.page_no for page in pages) + 1 if pages else 1


def select_before_first_chart(pages: List[PageText]) -> List[PageText]:
    """상세 도표 이전 설명 페이지들을 선택합니다."""

    first_chart_page = find_first_chart_page(pages)
    return [page for page in pages if page.page_no < first_chart_page and any(k in page.clean_text for k in ["개요", "적용범위", "용어", "수정요소"])]


def page_range(selected: List[PageText]) -> tuple[int | None, int | None]:
    if not selected:
        return None, None
    nums = [p.page_no for p in selected]
    return min(nums), max(nums)


def build_explanatory_sections(pages: List[PageText]) -> List[Dict[str, Any]]:
    """상세 도표 전 설명 section들을 생성합니다."""

    selected = select_before_first_chart(pages)
    raw_text = "\n\n".join(page.raw_text for page in selected).strip()
    clean_text = "\n\n".join(page.clean_text for page in selected).strip()
    start, end = page_range(selected)

    return [
        build_overview_section(raw_text, clean_text, start, end),
        build_scope_section(raw_text, clean_text, start, end),
        build_terms_section(raw_text, clean_text, start, end),
        build_adjustment_section(raw_text, clean_text, start, end),
    ]


def build_overview_section(raw_text: str, clean_text: str, page_start: int | None, page_end: int | None) -> Dict[str, Any]:
    """개요 section을 만듭니다."""

    return {
        "section_id": f"{SECTION_ID_PREFIX}_overview",
        "section_type": "overview",
        "section_title": "개요",
        "page_start": page_start,
        "page_end": page_end,
        "pm_growth_background": "PM 이용 증가 및 독자적 교통수단 인정",
        "standard_creation_reason": "PM 운행특성과 PM 관련 사고 증가를 고려한 기준 신설",
        "raw_text": raw_text,
        "clean_text": clean_text,
    }


def build_scope_section(raw_text: str, clean_text: str, page_start: int | None, page_end: int | None) -> Dict[str, Any]:
    """적용범위 section을 만듭니다."""

    return {
        "section_id": f"{SECTION_ID_PREFIX}_scope",
        "section_type": "scope",
        "section_title": "적용범위",
        "page_start": page_start,
        "page_end": page_end,
        "applies_to": "car_vs_pm_accident",
        "pm_must_be_riding": True,
        "pm_dismounted_excluded": True,
        "pm_legal_definition_required": True,
        "pm_speed_limit_condition": "25km/h 이상 운행 시 전동기가 작동하지 않아야 함",
        "pm_weight_condition": "30kg 미만",
        "included_pm_examples": ["전동킥보드", "전동외륜보드", "전동이륜평행차", "전동스케이트보드", "전동기 구동 자전거"],
        "excluded_cases": ["PM을 끌고 가는 경우"],
        "raw_text": raw_text,
        "clean_text": clean_text,
    }


def build_terms_section(raw_text: str, clean_text: str, page_start: int | None, page_end: int | None) -> Dict[str, Any]:
    """용어 정의 section을 만듭니다."""

    return {
        "section_id": f"{SECTION_ID_PREFIX}_terms",
        "section_type": "terms",
        "section_title": "용어 정의",
        "page_start": page_start,
        "page_end": page_end,
        "important_terms": ["도로", "차도", "자전거도로", "자전거횡단도", "보도", "횡단보도", "교차로", "신호기", "자동차", "개인형이동장치"],
        "bicycle_crossing_distance_rule": extract_sentence_with_terms(clean_text, ["자전거횡단도", "m", "이내"]),
        "left_right_road_definition": "제3자의 시점에서 우측 도로 진행 차량을 우측진입, 좌측 도로 진행 차량을 좌측진입으로 정의",
        "raw_text": raw_text,
        "clean_text": clean_text,
    }


def build_adjustment_section(raw_text: str, clean_text: str, page_start: int | None, page_end: int | None) -> Dict[str, Any]:
    """수정요소 해설 section을 만듭니다."""

    return {
        "section_id": f"{SECTION_ID_PREFIX}_adjustment_factor_explanation",
        "section_type": "adjustment_factor_explanation",
        "section_title": "수정요소의 해설",
        "page_start": page_start,
        "page_end": page_end,
        "car_heavy_fault_items": ["전방주시의무 위반", "음주운전", "속도위반", "조작 부적절", "휴대전화 사용"],
        "pm_heavy_fault_items": ["음주운전", "정원초과", "야간 등화 미점등", "한손 운전", "전방주시의무 위반", "휴대전화 사용", "사행 운전", "안전모 미착용"],
        "pm_left_side_travel_rule": "PM 좌측통행 시 PM 과실 가산",
        "near_bicycle_road_rule": "인근 자전거도로가 있으면 PM은 자전거도로를 이용해야 함",
        "clear_first_entry_rule": "선진입은 명확한 경우에만 적용",
        "raw_text": raw_text,
        "clean_text": clean_text,
    }


def extract_sentence_with_terms(text: str, terms: List[str]) -> str | None:
    """모든 term을 포함하는 원문 문장을 반환합니다."""

    normalized = " ".join(text.split())
    sentences = re.split(r"(?<=[.。])\s+|(?:\n)+", normalized)
    for sentence in sentences:
        if all(term in sentence for term in terms):
            return sentence.strip()
    return None
