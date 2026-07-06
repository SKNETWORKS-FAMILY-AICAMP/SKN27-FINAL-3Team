# -*- coding: utf-8 -*-
"""머리말과 올바른 통행방법 section을 저장용 JSON으로 만듭니다."""

from typing import Any, Dict, List

from .models import PageText


def normalize_marker(text: str) -> str:
    return text.replace(" ", "")


def select_pages_between_markers(pages: List[PageText], start_keywords: List[str], end_keywords: List[str]) -> List[PageText]:
    """문서 제목 marker를 기준으로 section 페이지를 선택합니다."""

    start_idx = None
    end_idx = None
    for idx, page in enumerate(pages):
        text = normalize_marker(page.clean_text)
        if start_idx is None and any(normalize_marker(k) in text for k in start_keywords):
            start_idx = idx
            continue
        if start_idx is not None and any(normalize_marker(k) in text for k in end_keywords):
            end_idx = idx
            break

    if start_idx is None:
        return []
    if end_idx is None:
        end_idx = len(pages)
    return pages[start_idx:end_idx]


def select_pages_containing(pages: List[PageText], keywords: List[str]) -> List[PageText]:
    """특정 marker를 포함하는 페이지를 선택합니다."""

    result = []
    for page in pages:
        text = normalize_marker(page.clean_text)
        if any(normalize_marker(k) in text for k in keywords):
            result.append(page)
    return result


def join_page_text(selected: List[PageText]) -> tuple[str, str, int | None, int | None]:
    raw_text = "\n\n".join(page.raw_text for page in selected).strip()
    clean_text = "\n\n".join(page.clean_text for page in selected).strip()
    if not selected:
        return raw_text, clean_text, None, None
    nums = [page.page_no for page in selected]
    return raw_text, clean_text, min(nums), max(nums)


def build_preface_section(pages: List[PageText]) -> Dict[str, Any]:
    """머리말 section JSON을 만듭니다."""

    selected = select_pages_between_markers(pages, ["머리말", "머 리 말"], ["회전교차로 올바른 통행방법", "올바른 통행방법"])
    raw_text, clean_text, page_start, page_end = join_page_text(selected)
    return {
        "section_id": "roundabout_2025_preface",
        "section_type": "preface",
        "section_title": "머리말",
        "page_start": page_start,
        "page_end": page_end,
        "background_reason": "차로변경억제형 2차로형 회전교차로 확대 설치와 기존 차54-1~차54-5 적용 한계",
        "design_change_basis": "국토교통부 회전교차로설계지침 개편(2022.8)",
        "roundabout_design_type": "차로변경억제형 2차로형 회전교차로",
        "existing_standard_limit": "기존 과실비율 인정기준 차54-1~차54-5 적용 한계",
        "related_existing_standard_codes": ["차54-1", "차54-2", "차54-3", "차54-4", "차54-5"],
        "operation_status": "비정형 기준으로 우선 운영",
        "future_plan": "정합성 검증 후 정형 인정기준으로 편입 예정",
        "accident_group_1": "진입차량 간 사고, 회전-1~회전-8",
        "accident_group_2": "진입차량과 회전차량 간 사고, 회전-9~회전-15",
        "raw_text": raw_text,
        "clean_text": clean_text,
    }


def build_driving_method_section(pages: List[PageText]) -> Dict[str, Any]:
    """회전교차로 올바른 통행방법 section JSON을 만듭니다."""

    selected = select_pages_containing(pages, ["회전교차로 올바른 통행방법", "올바른 통행방법"])
    raw_text, clean_text, page_start, page_end = join_page_text(selected)
    return {
        "section_id": "roundabout_2025_correct_driving_method",
        "section_type": "correct_roundabout_driving_method",
        "section_title": "회전교차로 올바른 통행방법",
        "page_start": page_start,
        "page_end": page_end,
        "must_yield_to_pedestrian": True,
        "entry_speed_rule": "접근 시 서행",
        "circulating_vehicle_priority": True,
        "right_side_keep_rule": "나올 때 우측 깜빡이",
        "left_side_signal_rule": "돌아갈 때 좌측 깜빡이",
        "allowed_lane_guidance": [
            "좌회전은 안쪽차로",
            "우회전은 바깥쪽차로",
            "회전차량 우선",
            "회전차량 멈추지 말고 서행",
        ],
        "campaign_or_public_guidance": "회전교차로 올바른 통행방법",
        "raw_text": raw_text,
        "clean_text": clean_text,
    }
