# -*- coding: utf-8 -*-
"""공식 인정기준 rule의 사고유형과 hierarchy를 분류합니다."""

from typing import Any, Dict


def build_hierarchy(rule_prefix: str, page_start: int, rule_title: str) -> Dict[str, Any]:
    """rule prefix와 페이지로 목차 hierarchy를 만듭니다."""

    # 기본 hierarchy입니다.
    chapter_no, chapter_title, rule_type = get_chapter_info(rule_prefix)

    # 사고 카테고리를 추정합니다.
    category_title = infer_category_title(rule_prefix, page_start, rule_title)

    # hierarchy를 반환합니다.
    return {
        "part_no": "제3편",
        "part_title": "과실비율 적용기준(사고유형별)",
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
            "제3편 과실비율 적용기준(사고유형별)",
            f"{chapter_no} {chapter_title}",
            "4. 세부유형별 과실비율 적용기준",
            category_title,
            rule_title,
        ],
        "rule_type": rule_type,
    }


def get_chapter_info(rule_prefix: str) -> tuple[str, str, str]:
    """rule prefix로 장 제목과 rule_type을 반환합니다."""

    # 보 기준입니다.
    if rule_prefix == "보":
        return "제1장", "자동차와 보행자의 사고", "vehicle_vs_pedestrian"

    # 차 기준입니다.
    if rule_prefix == "차":
        return "제2장", "자동차와 자동차(이륜차 포함)의 사고", "vehicle_vs_vehicle"

    # 거 기준입니다.
    return "제3장", "자동차와 자전거(농기계 포함)의 사고", "vehicle_vs_bicycle"


def infer_category_title(rule_prefix: str, page_start: int, rule_title: str) -> str:
    """페이지와 제목으로 사고 카테고리를 추정합니다."""

    # 제목에서 먼저 판단합니다.
    if "횡단보도" in rule_title:
        return "횡단보도 사고"

    if "교차로" in rule_title or "직진" in rule_title or "좌회전" in rule_title or "우회전" in rule_title:
        return "교차로 사고"

    if "중앙선" in rule_title:
        return "중앙선 침범 사고"

    if "추돌" in rule_title:
        return "추돌 사고"

    if "진로변경" in rule_title:
        return "진로변경 사고"

    if "주차장" in rule_title:
        return "주차장 사고"

    if "문" in rule_title:
        return "문 열림 사고"

    if "회전교차로" in rule_title:
        return "회전교차로 사고"

    # prefix별 기본값입니다.
    if rule_prefix == "보":
        return "자동차와 보행자 사고"

    if rule_prefix == "차":
        return "자동차와 자동차 사고"

    return "자동차와 자전거 사고"


def classify_accident(rule_prefix: str, rule_title: str, text: str) -> Dict[str, Any]:
    """rule 제목과 본문으로 사고유형을 분류합니다."""

    # 통합 텍스트입니다.
    combined = f"{rule_title}\n{text}"

    # 분류 결과를 반환합니다.
    return {
        "accident_group": infer_accident_group(rule_prefix, combined),
        "accident_subgroup": infer_accident_subgroup(combined),
        "collision_pattern": infer_collision_pattern(combined),
        "movement_relation": infer_movement_relation(combined),
        "violation_actor": infer_violation_actor(combined),
        "primary_violation": infer_primary_violation(combined),
        "priority_basis": infer_priority_basis(combined),
        "is_signalized": "신호" in combined,
        "is_intersection_case": "교차로" in combined,
        "is_crosswalk_case": "횡단보도" in combined,
        "is_lane_change_case": "진로변경" in combined or "차로변경" in combined,
        "is_rear_end_case": "추돌" in combined,
    }


def infer_accident_group(rule_prefix: str, text: str) -> str:
    """사고 대분류를 추정합니다."""

    if "횡단보도" in text:
        return "횡단보도"

    if "교차로" in text:
        return "교차로"

    if "중앙선" in text:
        return "중앙선 침범"

    if "추돌" in text:
        return "추돌"

    if "진로변경" in text or "차로변경" in text:
        return "진로변경"

    if "회전교차로" in text:
        return "회전교차로"

    if rule_prefix == "보":
        return "자동차와 보행자"

    if rule_prefix == "차":
        return "자동차와 자동차"

    return "자동차와 자전거"


def infer_accident_subgroup(text: str) -> str:
    """사고 중분류를 추정합니다."""

    for keyword in ["신호등 있음", "신호등 없음", "중앙선 침범", "안전거리미확보", "주정차", "진로변경", "문 열림", "회전교차로"]:
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

    if "진로변경" in text or "차로변경" in text:
        return "lane_change"

    return "other"


def infer_movement_relation(text: str) -> str:
    """이동 관계를 추정합니다."""

    if "맞은편" in text:
        return "opposite_direction"

    if "측면" in text:
        return "perpendicular"

    if "같은 방향" in text:
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

    if "중앙선 침범" in text:
        return "vehicle"

    return "unknown"


def infer_primary_violation(text: str) -> str:
    """핵심 위반을 추정합니다."""

    if "신호" in text:
        return "signal"

    if "중앙선" in text:
        return "centerline"

    if "진로변경" in text or "차로변경" in text:
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


########## 현재 fault_cases 전처리 보정용 정상 분류 함수 ##########

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
        if "차도" in title or "보도" in title or "도로" in title:
            return "보행자 도로횡단 및 보도 사고"
        return "자동차와 보행자 사고"

    if "회전교차로" in title:
        return "회전교차로 사고"
    if "교차로" in title or "직진" in title or "좌회전" in title or "우회전" in title or "신호" in title:
        return "교차로 사고"
    if "중앙선" in title:
        return "중앙선 침범 사고"
    if "추돌" in title:
        return "추돌 사고"
    if "진로변경" in title or "차로변경" in title or "끼어들기" in title:
        return "진로변경 사고"
    if "주차장" in title or "주차" in title:
        return "주차장 사고"
    if "문" in title or "개문" in title:
        return "문 개방 사고"

    if rule_prefix == "차":
        return "자동차와 자동차 사고"

    return "자동차와 자전거 사고"


def classify_accident(rule_prefix: str, rule_title: str, text: str) -> Dict[str, Any]:
    """rule 제목과 prefix 중심으로 사고유형을 분류합니다."""

    combined = f"{rule_title}\n{text}"
    title = rule_title or ""

    return {
        "accident_group": infer_accident_group(rule_prefix, title, combined),
        "accident_subgroup": infer_accident_subgroup(combined),
        "collision_pattern": infer_collision_pattern(combined),
        "movement_relation": infer_movement_relation(combined),
        "violation_actor": infer_violation_actor(combined),
        "primary_violation": infer_primary_violation(combined),
        "priority_basis": infer_priority_basis(combined),
        "is_signalized": "신호" in combined,
        "is_intersection_case": "교차로" in combined or any(word in title for word in ["직진", "좌회전", "우회전"]),
        "is_crosswalk_case": rule_prefix == "보" and "횡단보도" in combined,
        "is_lane_change_case": "진로변경" in combined or "차로변경" in combined or "끼어들기" in combined,
        "is_rear_end_case": "추돌" in combined,
    }


def infer_accident_group(rule_prefix: str, title: str, text: str) -> str:
    """사고 대분류를 추정합니다."""

    if rule_prefix == "보":
        if "횡단보도" in title or "횡단보도" in text:
            return "횡단보도"
        return "자동차와 보행자"

    if "회전교차로" in title or "회전교차로" in text:
        return "회전교차로"
    if "교차로" in title or "교차로" in text or any(word in title for word in ["직진", "좌회전", "우회전", "신호"]):
        return "교차로"
    if "중앙선" in title or "중앙선" in text:
        return "중앙선 침범"
    if "추돌" in title or "추돌" in text:
        return "추돌"
    if "진로변경" in title or "차로변경" in title or "끼어들기" in title or "진로변경" in text:
        return "진로변경"
    if "주차장" in title or "주차" in title:
        return "주차장"

    if rule_prefix == "차":
        return "자동차와 자동차"

    return "자동차와 자전거"
