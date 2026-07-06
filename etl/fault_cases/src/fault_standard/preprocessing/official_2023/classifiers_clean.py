# -*- coding: utf-8 -*-
"""2023 공식 인정기준 사고유형/hierarchy 분류 보정 로직입니다."""

from typing import Any, Dict


def build_hierarchy(rule_prefix: str, page_start: int, rule_title: str) -> Dict[str, Any]:
    """rule prefix와 제목으로 공식 인정기준 hierarchy를 만듭니다."""

    chapter_no, chapter_title, rule_type = get_chapter_info(rule_prefix)
    category_title = infer_category_title(rule_prefix, page_start, rule_title)

    return {
        "part_no": "4",
        "part_title": "과실비율 적용기준",
        "chapter_no": chapter_no,
        "chapter_title": chapter_title,
        "section_no": "4",
        "section_title": "세부유형별 과실비율 적용기준",
        "category_no": None,
        "category_title": category_title,
        "sub_category_no": None,
        "sub_category_title": None,
        "rule_group_ref": None,
        "section_path": [
            "과실비율 적용기준",
            f"{chapter_no} {chapter_title}",
            "4. 세부유형별 과실비율 적용기준",
            category_title,
            rule_title,
        ],
        "rule_type": rule_type,
    }


def get_chapter_info(rule_prefix: str) -> tuple[str, str, str]:
    """rule prefix로 장 제목과 rule_type을 반환합니다."""

    if rule_prefix == "보":
        return "제1장", "자동차와 보행자의 사고", "vehicle_vs_pedestrian"

    if rule_prefix == "차":
        return "제2장", "자동차와 자동차(이륜차 포함)의 사고", "vehicle_vs_vehicle"

    return "제3장", "자동차와 자전거(농기계 포함)의 사고", "vehicle_vs_bicycle"


def infer_category_title(rule_prefix: str, page_start: int, rule_title: str) -> str:
    """제목과 prefix로 사고 category를 추정합니다."""

    title = rule_title or ""

    if rule_prefix == "보":
        if "횡단보도" in title:
            return "횡단보도 사고"
        if any(word in title for word in ["차도", "보도", "도로", "횡단"]):
            return "보행자 도로횡단 및 보도 사고"
        return "자동차와 보행자 사고"

    if "회전교차로" in title:
        return "회전교차로 사고"
    if any(word in title for word in ["교차로", "직진", "좌회전", "우회전", "신호"]):
        return "교차로 사고"
    if "중앙선" in title:
        return "중앙선 침범 사고"
    if "추돌" in title:
        return "추돌 사고"
    if any(word in title for word in ["진로변경", "차로변경", "끼어들기"]):
        return "진로변경 사고"
    if any(word in title for word in ["주차장", "주차", "정차"]):
        return "주정차 및 주차장 사고"
    if "개문" in title or "문" in title:
        return "문 개방 사고"

    return "자동차와 자동차 사고" if rule_prefix == "차" else "자동차와 자전거 사고"


def classify_accident(rule_prefix: str, rule_title: str, text: str) -> Dict[str, Any]:
    """rule 제목과 prefix 중심으로 사고유형을 분류합니다."""

    combined = f"{rule_title}\n{text}"
    title = rule_title or ""
    is_highway_pedestrian = rule_prefix == "보" and any(word in title for word in ["고속도로", "자동차전용도로"])

    return {
        "accident_group": infer_accident_group(rule_prefix, title, combined),
        "accident_subgroup": infer_accident_subgroup(combined, title),
        "collision_pattern": infer_collision_pattern(combined),
        "movement_relation": infer_movement_relation(combined),
        "violation_actor": infer_violation_actor(combined),
        "primary_violation": infer_primary_violation(combined),
        "priority_basis": infer_priority_basis(combined),
        "is_signalized": "신호" in combined,
        "is_intersection_case": False if is_highway_pedestrian else "교차로" in combined or any(word in title for word in ["직진", "좌회전", "우회전"]),
        "is_crosswalk_case": False if is_highway_pedestrian else rule_prefix == "보" and "횡단보도" in combined,
        "is_lane_change_case": any(word in combined for word in ["진로변경", "차로변경", "끼어들기"]),
        "is_rear_end_case": "추돌" in combined,
    }


def infer_accident_group(rule_prefix: str, title: str, text: str) -> str:
    """사고 대분류를 추정합니다."""

    if rule_prefix == "보":
        if any(word in title for word in ["고속도로", "자동차전용도로"]):
            return "자동차와 보행자"
        return "횡단보도" if "횡단보도" in title else "자동차와 보행자"

    if "회전교차로" in title or "회전교차로" in text:
        return "회전교차로"
    if "교차로" in title or "교차로" in text or any(word in title for word in ["직진", "좌회전", "우회전", "신호"]):
        return "교차로"
    if "중앙선" in title or "중앙선" in text:
        return "중앙선 침범"
    if "추돌" in title or "추돌" in text:
        return "추돌"
    if any(word in title or word in text for word in ["진로변경", "차로변경", "끼어들기"]):
        return "진로변경"
    if any(word in title for word in ["주차장", "주차", "정차"]):
        return "주정차 및 주차장"

    return "자동차와 자동차" if rule_prefix == "차" else "자동차와 자전거"


def infer_accident_subgroup(text: str, title: str = "") -> str:
    """사고 중분류를 추정합니다."""

    if any(word in title for word in ["고속도로", "자동차전용도로"]):
        return "고속도로"
    if "횡단보도" in title:
        return "횡단보도"
    if "회전교차로" in title:
        return "회전교차로"

    for keyword in ["신호위반", "신호등 없음", "중앙선 침범", "안전거리", "주정차", "진로변경", "차로변경", "문 개방", "회전교차로"]:
        if keyword in text:
            return keyword

    return "기타"


def infer_collision_pattern(text: str) -> str:
    """충돌 패턴을 추정합니다."""

    if "직진" in text and "좌회전" in text:
        return "straight_vs_left_turn"
    if "직진" in text and "우회전" in text:
        return "straight_vs_right_turn"
    if "추돌" in text:
        return "rear_end"
    if "횡단" in text:
        return "crossing"
    if any(word in text for word in ["진로변경", "차로변경", "끼어들기"]):
        return "lane_change"

    return "other"


def infer_movement_relation(text: str) -> str:
    """이동 관계를 추정합니다."""

    if any(word in text for word in ["맞은편", "대향"]):
        return "opposite_direction"
    if any(word in text for word in ["측면", "교차"]):
        return "perpendicular"
    if any(word in text for word in ["같은 방향", "선행", "후행"]):
        return "same_direction"
    if "횡단" in text:
        return "crossing"

    return "unknown"


def infer_violation_actor(text: str) -> str:
    """위반 주체를 추정합니다."""

    if "A 현저한 과실" in text and "B 현저한 과실" in text:
        return "both_possible"
    if "보행자" in text and "적색" in text:
        return "pedestrian"
    if any(word in text for word in ["중앙선 침범", "신호위반", "진로변경"]):
        return "vehicle"

    return "unknown"


def infer_primary_violation(text: str) -> str:
    """핵심 위반을 추정합니다."""

    if "신호" in text:
        return "signal"
    if "중앙선" in text:
        return "centerline"
    if any(word in text for word in ["진로변경", "차로변경", "끼어들기"]):
        return "lane_change"
    if "안전거리" in text:
        return "safe_distance"

    return "none"


def infer_priority_basis(text: str) -> str:
    """통행우선 판단 기준을 추정합니다."""

    if "신호" in text:
        return "signal"
    if "대로" in text or "소로" in text:
        return "main_road"
    if "우측" in text or "오른쪽" in text:
        return "right_side_priority"
    if "직진" in text and ("좌회전" in text or "우회전" in text):
        return "straight_priority"

    return "general"
