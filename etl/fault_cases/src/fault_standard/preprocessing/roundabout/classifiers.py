# -*- coding: utf-8 -*-
"""회전교차로 사고유형과 구조 context를 분류합니다."""

from typing import Any, Dict

from .config import get_round_group as get_round_group_config


def classify_accident(round_no: int, title: str, text: str) -> Dict[str, Any]:
    """회전 번호와 제목으로 사고유형을 분류합니다."""

    group_info = get_round_group_config(round_no)
    group = group_info["major_group_title"]

    # 차량 관계 코드입니다.
    relation = group_info["major_group"]

    # 사고유형 분류를 반환합니다.
    return {
        "accident_group": group,
        "accident_subgroup": infer_accident_subgroup(title, text),
        "collision_zone": infer_collision_zone(title, text),
        "collision_stage": infer_collision_stage(title, text),
        "vehicle_relation": relation,
        "movement_relation": infer_movement_relation(title, text),
        "has_first_entry_issue": "선진입" in text,
        "has_late_entry_issue": "후진입" in text,
        "has_lane_change_issue": "차로변경" in text or "진로변경" in text,
        "has_exit_issue": "진출" in text,
        "has_road_marking_violation_issue": "노면표시" in text,
        "has_yield_duty_issue": "양보" in text or "회전차량 우선" in text,
    }


def build_roundabout_scope() -> Dict[str, Any]:
    """기준서 전체에 적용되는 회전교차로 전제를 반환합니다."""

    return {
        "roundabout_type": "lane_change_suppressed_two_lane_roundabout",
        "lane_count": 2,
        "entry_lane_count": 2,
        "has_road_marking": True,
        "road_marking_type": "direction_arrow_marking",
        "road_marking_basis": "진입로 진행방향 노면표시",
        "design_guideline_basis": "회전교차로설계지침 개편",
        "driving_rule_summary": "회전차량 우선, 진입 시 서행, 진출 시 우측 깜빡이",
        "is_lane_change_suppressed": True,
    }


def build_roundabout_context() -> Dict[str, Any]:
    """회전교차로 구조와 통행 원칙 context를 반환합니다."""

    return {
        "roundabout_design": "차로변경억제형 2차로형 회전교차로",
        "circulation_direction": "반시계방향",
        "central_island_exists": True,
        "yield_line_exists": True,
        "direction_arrow_marking_exists": True,
        "lane_change_suppressed": True,
        "circulating_vehicle_priority": True,
        "entry_vehicle_yield_duty": True,
        "entry_vehicle_slow_or_stop_duty": True,
        "turn_signal_duty": True,
        # 정상 차로 매핑은 rule별 원문/도표/노면표시 태그에서 확인해야 합니다.
        # 코드에서 방향별 차로를 고정하지 않습니다.
        "normal_right_turn_lane": None,
        "normal_straight_lane": None,
        "normal_left_turn_lane": None,
        "lane_policy_source": "not_hardcoded_extract_from_document_text",
    }


def get_major_group(round_no: int) -> Dict[str, str]:
    """회전 번호의 대분류를 반환합니다."""

    group_info = get_round_group_config(round_no)
    return {
        "major_group_no": group_info["major_group_no"],
        "major_group": group_info["major_group"],
        "major_group_title": group_info["major_group_title"],
    }

def infer_accident_subgroup(title: str, text: str) -> str:
    """사고 중분류를 추정합니다."""

    if "진입부" in title:
        return "진입부 사고"

    if "회전 중" in title:
        return "회전 중 사고"

    if "진출부" in title or "진출" in title:
        return "진출부 사고"

    if "차로변경" in title or "차로변경" in text:
        return "차로변경 사고"

    return "기타"


def infer_collision_zone(title: str, text: str) -> str:
    """충돌 위치를 추정합니다."""

    if "진입부" in title:
        return "entry_zone"

    if "진출부" in title or "진출" in title:
        return "exit_zone"

    if "회전 중" in title or "회전 중" in text:
        return "circulation_zone"

    return "unknown"


def infer_collision_stage(title: str, text: str) -> str:
    """사고 발생 단계를 추정합니다."""

    if "진입" in title and "진입부" in title:
        return "entering"

    if "차로변경" in title or "차로변경" in text:
        return "lane_changing"

    if "진출" in title or "진출" in text:
        return "exiting"

    if "회전" in title or "회전" in text:
        return "circulating"

    return "unknown"


def infer_movement_relation(title: str, text: str) -> str:
    """차량 이동 관계를 추정합니다."""

    if "선진입" in title or "후진입" in title:
        return "first_entry_vs_late_entry"

    if "진입 2개 차로" in title:
        return "same_entry"

    if "차로변경" in title or "차로변경" in text:
        return "lane_change_relation"

    return "unknown"
