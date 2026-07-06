# -*- coding: utf-8 -*-
"""PM 대 자동차 사고유형과 도로환경을 분류합니다."""

import re
from typing import Any, Dict, List

from .config import PM_CATEGORY_METADATA, RULE_GROUP_RANGES


def classify_accident(chart_no: int, title: str, text: str) -> Dict[str, Any]:
    """도표 번호와 제목으로 사고유형을 분류합니다."""

    combined = remove_adjustment_condition_terms(f"{title}\n{text}")
    title_text = remove_adjustment_condition_terms(title)

    return {
        "accident_group": infer_accident_group(chart_no, title, text),
        "accident_subgroup": infer_accident_subgroup(title, text),
        "collision_pattern": infer_collision_pattern(title, text),
        "movement_relation": infer_movement_relation(title, text),
        "violation_actor": infer_violation_actor(title, text),
        "primary_violation": infer_primary_violation(title, text),
        "priority_basis": infer_priority_basis(title, text),
        "is_signalized": infer_has_signal(title_text, combined),
        "is_unsignalized": "신호기 없음" in title_text or "신호기 없는" in title_text or "신호기 없음" in combined or "신호기 없는" in combined,
        "is_intersection_case": "교차로" in title_text or "교차로" in combined,
        "is_crossing_case": "횡단" in title_text or "횡단" in combined,
        "is_lane_change_case": "진로변경" in title_text or "진로변경" in combined,
        "is_rear_end_case": "추돌" in title_text or "추돌" in combined,
    }


def build_applicability() -> Dict[str, Any]:
    """PM 기준서의 적용범위 정보를 반환합니다."""

    return {
        "applies_to": "car_vs_pm_accident",
        "pm_must_be_riding": True,
        "pm_dismounted_excluded": True,
        "pm_legal_definition_required": True,
        "pm_speed_limit_condition": "25km/h 이상 운행 시 전동기가 작동하지 않음",
        "pm_weight_condition": "30kg 미만",
        "included_pm_examples": ["전동킥보드", "전동외륜보드", "전동이륜평행차", "전동스케이트보드"],
        "excluded_cases": ["PM을 끌고 가는 경우"],
    }


def build_road_context(title: str, text: str) -> Dict[str, Any]:
    """도로와 교통환경 context를 만듭니다."""

    base_text = remove_adjustment_condition_terms(f"{title}\n{text}")
    title_text = remove_adjustment_condition_terms(title)
    return {
        "road_area": infer_road_area(title_text, base_text),
        "intersection_type": "사거리" if "사거리" in base_text else None,
        "road_width_relation": infer_road_width_relation(base_text),
        "has_signal": infer_has_signal(title_text, base_text),
        "has_bicycle_road": infer_base_feature(title_text, base_text, "자전거도로"),
        "has_bicycle_crossing": infer_base_feature(title_text, base_text, "자전거횡단도"),
        "has_crosswalk": infer_base_feature(title_text, base_text, "횡단보도"),
        "has_sidewalk": infer_base_feature(title_text, base_text, "보도"),
        "has_centerline": infer_base_feature(title_text, base_text, "중앙선"),
        "has_one_way": infer_base_feature(title_text, base_text, "일방통행"),
    }


def build_signal_context(title: str, text: str) -> Dict[str, Any]:
    """신호 관련 context를 만듭니다."""

    combined = remove_adjustment_condition_terms(f"{title}\n{text}")
    title_text = remove_adjustment_condition_terms(title)
    is_unsignalized = infer_is_unsignalized(title_text, combined)
    is_signalized = infer_has_signal(title_text, combined) and not is_unsignalized
    return {
        "is_signalized": is_signalized,
        "is_unsignalized": is_unsignalized,
        "pm_signal_state": infer_pm_signal_state(combined),
        "car_signal_state": infer_car_signal_state(combined),
        "pedestrian_signal_state": infer_pedestrian_signal_state(combined),
        "bicycle_signal_rule_applied": "자전거횡단도" in combined,
        "signal_priority_basis": "도로교통법 제5조" if is_signalized else None,
    }


def get_category_info(chart_no: int) -> Dict[str, str]:
    """도표 번호별 사고유형 묶음 정보를 반환합니다."""

    for start_no, end_no, dir_key in RULE_GROUP_RANGES:
        if start_no <= chart_no <= end_no:
            return PM_CATEGORY_METADATA[dir_key]

    return {"category_no": "unknown", "category_title": "기타 사고", "chart_group": "other"}


def infer_accident_group(chart_no: int, title: str, text: str) -> str:
    """사고 대분류를 추정합니다."""

    return get_category_info(chart_no)["category_title"]


def infer_accident_subgroup(title: str, text: str) -> str:
    """사고 중분류를 추정합니다."""

    if "신호위반" in title:
        return "신호위반"

    if "일방통행" in title:
        return "일방통행 위반"

    if "중앙선" in title:
        return "중앙선 침범"

    if "진로변경" in title:
        return "진로변경"

    if "추돌" in title:
        return "추돌"

    if "개문" in title:
        return "개문"

    if "횡단" in title:
        return "횡단"

    return "기타"


def infer_collision_pattern(title: str, text: str) -> str:
    """충돌 패턴을 추정합니다."""

    if "직진" in title and "좌회전" in title:
        return "straight_vs_left_turn"

    if "직진" in title and "우회전" in title:
        return "straight_vs_right_turn"

    if "진로변경" in title:
        return "lane_change"

    if "추돌" in title:
        return "rear_end"

    if "개문" in title:
        return "door_opening"

    if "횡단" in title:
        return "crossing"

    return "other"


def infer_movement_relation(title: str, text: str) -> str:
    """이동 관계를 추정합니다."""

    if "선행" in title or "후행" in title:
        return "same_direction"

    if "대" in title and ("좌회전" in title or "우회전" in title):
        return "turning_conflict"

    if "횡단" in title:
        return "crossing"

    return "unknown"


def infer_violation_actor(title: str, text: str) -> str:
    """위반 주체를 추정합니다."""

    if "PM" in title and ("위반" in title or "침범" in title or "보도 통행" in title):
        return "pm"

    if "자동차" in title and ("위반" in title or "진로변경" in title or "개문" in title):
        return "car"

    if "양 차량" in title:
        return "both"

    return "none"


def infer_primary_violation(title: str, text: str) -> str:
    """핵심 위반을 추정합니다."""

    if "신호위반" in title:
        return "signal_violation"

    if "중앙선" in title:
        return "centerline_violation"

    if "보도 통행" in title:
        return "sidewalk_driving"

    if "일방통행" in title:
        return "one_way_violation"

    if "진로변경" in title:
        return "lane_change"

    if "개문" in title:
        return "door_opening"

    return "none"


def infer_priority_basis(title: str, text: str) -> str:
    """통행우선 판단 기준을 추정합니다."""

    if "신호" in title or "신호" in text:
        return "signal"

    if "오른쪽 도로" in title or "우측" in title:
        return "right_side_priority"

    if "대로" in title or "소로" in title:
        return "main_road"

    if "직진" in title and ("좌회전" in title or "우회전" in title):
        return "straight_priority"

    if "추돌" in title:
        return "safe_distance"

    return "general"


def remove_adjustment_condition_terms(text: str) -> str:
    """수정요소 조건으로 등장하는 도로/환경 표현을 기본 road context에서 제외합니다."""

    adjustment_phrases = [
        "인근에 자전거도로가 있는 경우",
        "인근에 자전거 도로가 있는 경우",
        "인근에 자전거도로",
        "인근에 자전거 도로",
        "좌측통행",
        "보도통행",
        "보도 통행",
        "야간",
        "기타 시야장애",
        "시야장애",
        "횡단금지 표지",
        "주택·상점가·학교",
        "주택",
        "상점가",
        "학교",
        "제동등 고장",
    ]

    cleaned = text
    for phrase in adjustment_phrases:
        cleaned = cleaned.replace(phrase, " ")
    cleaned = re.sub(r"대략\s*\d+\s*m\s*이내", " ", cleaned)

    return cleaned


def infer_road_area(title: str, text: str) -> str:
    """도로 영역을 추정합니다."""

    title_first_values = ["자전거횡단도", "횡단보도", "자전거도로", "보도", "차도가 아닌 장소", "교차로", "차도"]

    for value in title_first_values:
        if value in title:
            return value

    if any(word in title for word in ["직진", "좌회전", "우회전", "신호위반", "신호기 없음", "사거리"]):
        return "교차로"

    if any(word in title for word in ["추돌", "진로변경", "개문"]):
        return "차도"

    for value in title_first_values:
        if value in text:
            return value

    if any(word in text for word in ["직진", "좌회전", "우회전", "신호위반", "신호기 없음", "사거리"]):
        return "교차로"

    return "기타"


def infer_has_signal(title: str, text: str) -> bool:
    """신호기 유무를 제목/기본 사고상황 기준으로 판단합니다."""

    if "신호기 없음" in title or "신호기 없는" in title:
        return False

    if "신호기 없음" in text or "신호기 없는" in text:
        return False

    return "신호" in title or "신호" in text


def infer_base_feature(title: str, text: str, keyword: str) -> bool:
    """수정요소 제거 후 기본 사고상황에 남은 도로 특성만 반환합니다."""

    if keyword in title:
        return True
    if appears_only_as_adjustment_condition(text, keyword):
        return False
    return title_or_party_action_contains(title, text, keyword)


def infer_is_unsignalized(title: str, text: str) -> bool:
    """신호기 없음 표현을 우선 판단합니다."""

    return any(value in f"{title}\n{text}" for value in ["신호기 없음", "신호기 없는", "신호 없는"])


def title_or_party_action_contains(title: str, text: str, keyword: str) -> bool:
    """제목 또는 PM/자동차 action에 keyword가 직접 등장하는지 확인합니다."""

    if keyword in title:
        return True
    action_lines = re.findall(r"(?m)^(?:PM|자동차)\s*[AB]\s*:\s*.+$", text)
    return any(keyword in line for line in action_lines)


def appears_only_as_adjustment_condition(text: str, keyword: str) -> bool:
    """keyword가 수정요소 조건 문맥으로만 보이는지 판단합니다."""

    if keyword not in text:
        return False
    adjustment_patterns = [
        rf"인근에\s*{re.escape(keyword)}",
        rf"{re.escape(keyword)}가?\s*있는\s*경우",
        rf"{re.escape(keyword)}\s*이용",
        rf"{re.escape(keyword)}\s*통행\s*시",
        rf"{re.escape(keyword)}\s*부근",
    ]
    return any(re.search(pattern, text) for pattern in adjustment_patterns)


def infer_road_width_relation(text: str) -> str:
    """대로/소로 관계를 추정합니다."""

    if "대로" in text and "소로" in text:
        return "main_vs_side_road"

    if "동일폭" in text:
        return "same_width"

    return "unknown"


def infer_pm_signal_state(text: str) -> str | None:
    """PM 신호 상태를 추정합니다."""

    for value in ["PM A : 녹색", "PM A: 녹색", "PM B : 녹색", "PM B: 녹색"]:
        if value in text:
            return "녹색"

    for value in ["PM A : 적색", "PM A: 적색", "PM B : 적색", "PM B: 적색"]:
        if value in text:
            return "적색"

    for value in ["PM A : 황색", "PM A: 황색", "PM B : 황색", "PM B: 황색"]:
        if value in text:
            return "황색"

    return None


def infer_car_signal_state(text: str) -> str | None:
    """자동차 신호 상태를 추정합니다."""

    for value in ["자동차 A : 녹색", "자동차 A: 녹색", "자동차 B : 녹색", "자동차 B: 녹색"]:
        if value in text:
            return "녹색"

    for value in ["자동차 A : 적색", "자동차 A: 적색", "자동차 B : 적색", "자동차 B: 적색"]:
        if value in text:
            return "적색"

    for value in ["자동차 A : 황색", "자동차 A: 황색", "자동차 B : 황색", "자동차 B: 황색"]:
        if value in text:
            return "황색"

    return None


def infer_pedestrian_signal_state(text: str) -> str | None:
    """보행자신호 상태를 추정합니다."""

    if "보행자신호 적색" in text or "보행자 적색" in text:
        return "적색"

    if "보행자신호 녹색" in text or "보행자 녹색" in text:
        return "녹색"

    return None
