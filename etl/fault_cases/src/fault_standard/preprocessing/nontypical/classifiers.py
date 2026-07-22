# -*- coding: utf-8 -*-
"""사고유형, 도로환경, 우선권 관련 분류 함수입니다."""

import re
from typing import Any, Dict, List, Optional

from .extractors import extract_between
from .cleaners import normalize_spaces


def classify_accident(title: str, text: str) -> Dict[str, Any]:
    """사고 제목과 본문으로 사고유형을 분류합니다."""

    # 제목과 본문을 함께 보아 분류 정확도를 높입니다.
    combined = f"{title}\n{text}"

    # 분류 결과를 반환합니다.
    return {
        "accident_group": infer_accident_group(title, combined),
        "accident_subgroup": infer_accident_subgroup(combined),
        "collision_pattern": infer_collision_pattern(combined),
        "road_environment": infer_road_environment(combined),
        "traffic_control": infer_traffic_control(combined),
        "movement_relation": infer_movement_relation(combined),
        "violation_actor": infer_violation_actor(combined),
        "primary_violation": infer_primary_violation(combined),
        "is_intersection_case": "교차로" in combined,
        "is_private_or_narrow_road_case": "이면도로" in combined,
        "is_bus_stop_case": "버스정류장" in combined,
        "is_overtaking_case": "추월" in combined or "앞지르기" in combined,
        "is_lane_change_case": "진로변경" in combined,
        "is_u_turn_case": "유턴" in combined,
        "is_crosswalk_case": "횡단보도" in combined,
    }


def build_road_context(title: str, text: str) -> Dict[str, Any]:
    """도로 환경 context를 만듭니다."""

    # 제목과 본문을 합쳐서 판단합니다.
    combined = f"{title}\n{text}"

    road_area = infer_road_area(title, combined)

    # 도로 context를 반환합니다. 교차로 유형은 도로 영역이 실제 교차로일 때만 채웁니다.
    # 뒤쪽 법규/판례에 등장한 '교차로'가 주차장·동일차로 사고를 오염시키지 않게 합니다.
    return {
        "road_area": road_area,
        "intersection_type": infer_intersection_type(title, combined) if road_area == "교차로" else None,
        "road_width_relation": infer_road_width_relation(combined),
        "lane_relation": infer_lane_relation(title, combined),
        "main_road_party": infer_party_by_keyword(combined, "대로"),
        "side_road_party": infer_party_by_keyword(combined, "소로"),
        "right_side_party": infer_party_by_keyword(combined, "우측"),
        "left_side_party": infer_party_by_keyword(combined, "좌측"),
        "has_centerline": False if "중앙선 없는" in combined else ("중앙선" in combined),
        "has_bus_stop": "버스정류장" in combined,
        "has_parked_vehicle_visibility_issue": "주정차" in combined,
        "visibility_issue": "시야" in combined,
        "road_surface_or_width_issue": "폭" in combined or "동일폭" in combined,
    }


def build_priority_context(text: str) -> Dict[str, Any]:
    """통행우선권 관련 context를 만듭니다."""

    # 우선권 판단에 쓰이는 키워드입니다.
    priority_words = ["우선권", "양보", "우측 도로", "대로", "소로", "직진", "우회전 통행우선권"]

    # 우선권 관련 단어가 있는지 판단합니다.
    has_priority = any(word in text for word in priority_words)

    # 우선권 context를 반환합니다.
    return {
        "priority_basis": infer_priority_basis(text),
        "priority_party": None,
        "duty_heavier_party": None,
        "priority_conflict_exists": "우선권" in text and "대등" in text,
        "priority_conflict_description": extract_priority_sentence(text),
        "legal_priority_refs": extract_legal_priority_refs(text),
        "reason_for_base_fault": extract_block_summary(text, "기본과실 해설 :"),
        "priority_keywords_detected": has_priority,
    }


def infer_accident_group(title: str, text: str) -> str:
    """사고 대분류를 추정합니다."""

    source = f"{title}\n{text}"

    # 제목은 rule의 기본 사고상황이므로 본문보다 우선합니다.
    if "버스정류장" in title:
        return "버스정류장"

    if "적색점멸" in title or "황색점멸" in title or "교차로" in title or "신호없는 사거리" in title:
        return "교차로"

    if any(word in title for word in ["동일차로", "진로변경", "차로변경", "끼어들기", "급진입"]):
        return "진로변경"

    if "추월" in title or "앞지르기" in title:
        return "추월"

    if "주차장" in title or "주차구획" in title or "출차" in title:
        return "주차장"

    if "이면도로" in title:
        return "이면도로"

    if "횡단보도" in title:
        return "횡단보도"

    if "유턴" in title:
        return "유턴"

    if "중앙선" in title:
        return "중앙선"

    # 본문 fallback도 기본 사고상황성이 강한 키워드부터 판단합니다.
    if "버스정류장" in source:
        return "버스정류장"

    if "적색점멸" in source or "황색점멸" in source or "교차로" in source or "신호없는 사거리" in source:
        return "교차로"

    if any(word in source for word in ["동일차로", "진로변경", "차로변경", "끼어들기", "급진입"]):
        return "진로변경"

    if "추월" in source or "앞지르기" in source:
        return "추월"

    if "주차장" in source or "주차구획" in source or "출차" in source:
        return "주차장"

    if "이면도로" in source:
        return "이면도로"

    if "횡단보도" in source:
        return "횡단보도"

    if "유턴" in source:
        return "유턴"

    if "중앙선" in source:
        return "중앙선"

    return "기타"


def infer_road_area(title: str, text: str) -> str:
    """Neo4j 검색에 사용할 도로 영역을 제목 중심으로 추정합니다."""

    source = f"{title}\n{text}"

    # rule 제목은 기본 사고상황의 정본이므로, 제목의 명시 영역을 본문 fallback보다 우선합니다.
    if "버스정류장" in title:
        return "버스정류장"

    if any(word in title for word in ["주차장", "주차구획", "주차진행", "출차"]):
        return "주차장"

    if any(word in title for word in ["동일차로", "진로변경", "차로변경", "끼어들기", "급진입"]):
        return "동일차로"

    if not is_non_intersection_title(title) and (
        "교차로" in title
        or "사거리" in title
        or "삼거리" in title
        or "적색점멸" in title
        or "황색점멸" in title
    ):
        return "교차로"

    if "횡단보도" in title:
        return "횡단보도"

    if "이면도로" in title:
        return "이면도로"

    if "추월" in title or "앞지르기" in title:
        return "추월"

    if "버스정류장" in source:
        return "버스정류장"

    if "주차장" in source or "주차구획" in source or "출차" in source:
        return "주차장"

    if not is_non_intersection_title(title) and (
        "교차로" in source or "적색점멸" in source or "황색점멸" in source or "신호없는 사거리" in source
    ):
        return "교차로"

    if "동일차로" in source or "진로변경" in source or "끼어들기" in source or "급진입" in source:
        return "동일차로"

    if "이륜차" in source and ("교차로" in source or "우회전" in source or "좌회전" in source):
        return "교차로"

    if "횡단보도" in source:
        return "횡단보도"

    if "이면도로" in source:
        return "이면도로"

    if "추월" in source or "앞지르기" in source:
        return "추월"

    return infer_accident_group(title, source)


def is_non_intersection_title(title: str) -> bool:
    """제목이 교차로를 언급하되 적용 대상이 아님을 명시하는지 판단합니다."""

    normalized = normalize_spaces(title)
    return bool(re.search(r"교차로\s*(?:가\s*)?(?:아닌|아님|외)", normalized))


def infer_intersection_type(title: str, text: str) -> Optional[str]:
    """교차로 유형을 제목/사고상황 표현으로 세분화합니다."""

    source = f"{title}\n{text}"
    if is_non_intersection_title(title):
        return None
    if "적색점멸" in source or "황색점멸" in source:
        return "flashing_signal_intersection"
    if "신호없는 사거리" in source or "신호 없는 사거리" in source:
        return "unsignalized_four_way_intersection"
    if "사거리" in source:
        return "four_way_intersection"
    if "교차로" in source:
        return "intersection"
    return None


def infer_road_width_relation(text: str) -> Optional[str]:
    """도로 폭 관계를 추정합니다."""

    if "동일폭" in text or "동일 폭" in text:
        return "same_width"
    if "대로" in text and "소로" in text:
        return "main_vs_side_road"
    return None


def infer_lane_relation(title: str, text: str) -> Optional[str]:
    """동일차로/차로변경 관계를 추정합니다."""

    source = f"{title}\n{text}"
    if "동일차로" in source or "선후행" in source:
        return "same_lane"
    if "진로변경" in source or "차로변경" in source:
        return "lane_change"
    if "끼어들기" in source or "급진입" in source:
        return "cut_in"
    return None


def infer_accident_subgroup(text: str) -> Optional[str]:
    """사고 중분류를 추정합니다."""

    if "우회전" in text and "좌회전" in text:
        return "우회전 대 좌회전"

    if "적색점멸" in text and "황색점멸" in text:
        return "점멸신호 교차로"

    if "정차후 출발" in text and "추월" in text:
        return "정차후 출발 대 추월"

    return None


def infer_collision_pattern(text: str) -> Optional[str]:
    """충돌 패턴을 추정합니다."""

    if "우회전" in text and "좌회전" in text:
        return "right_turn_vs_left_turn"

    if "정차후 출발" in text and "추월" in text:
        return "stopped_vehicle_departure_vs_overtaking"

    if "진로변경" in text:
        return "lane_change"

    if "추돌" in text:
        return "rear_end"

    return None


def infer_road_environment(text: str) -> Optional[str]:
    """도로 환경을 추정합니다."""

    for value in ["점멸신호 교차로", "이면도로", "동일폭 교차로", "버스정류장", "직선도로", "주차장", "횡단보도", "동일차로"]:
        if value in text:
            return value

    if "적색점멸" in text or "황색점멸" in text:
        return "점멸신호 교차로"

    if "진로변경" in text or "끼어들기" in text or "급진입" in text:
        return "동일차로"

    return None


def infer_traffic_control(text: str) -> str:
    """교통정리 상태를 추정합니다."""

    if "적색점멸" in text or "황색점멸" in text:
        return "flash_signal"

    if "신호기" in text or "녹색" in text or "적색" in text:
        return "signalized"

    if "신호없는" in text or "신호기가 없는" in text:
        return "unsignalized"

    return "none"


def infer_movement_relation(text: str) -> Optional[str]:
    """차량 진행 관계를 추정합니다."""

    if "맞은편" in text:
        return "opposite_direction"

    if "동일차로" in text or "선후행" in text:
        return "same_direction"

    if "우측" in text or "좌측" in text:
        return "right_or_left_side_entry"

    return None


def infer_violation_actor(text: str) -> Optional[str]:
    """주요 위반 주체를 추정합니다."""

    if "A " in text and "위반" in text:
        return "A"

    if "B " in text and "위반" in text:
        return "B"

    return None


def infer_primary_violation(text: str) -> Optional[str]:
    """핵심 위반을 추정합니다."""

    candidates = ["우회전방법 위반", "좌회전방법 위반", "서행불이행", "진로변경 신호불이행", "신호위반", "중앙선 침범"]

    for candidate in candidates:
        if candidate in text:
            return candidate

    return None


def infer_party_by_keyword(text: str, keyword: str) -> Optional[str]:
    """특정 키워드 주변의 A/B 당사자를 추정합니다."""

    if f"A차량의 {keyword}" in text or f"자동차 A : {keyword}" in text:
        return "A"

    if f"B차량의 {keyword}" in text or f"자동차 B : {keyword}" in text:
        return "B"

    return None


def infer_priority_basis(text: str) -> Optional[str]:
    """우선권 근거를 추정합니다."""

    if "우측 도로" in text or "우측도로" in text:
        return "우측도로 우선"

    if "우회전 통행우선권" in text:
        return "우회전 통행우선권"

    if "대로" in text and "소로" in text:
        return "대로 우선"

    if "직진" in text and "좌회전" in text:
        return "직진 우선"

    return None


def extract_priority_sentence(text: str) -> Optional[str]:
    """우선권 관련 문장을 간단히 추출합니다."""

    for sentence in re.split(r"(?<=[.!?。])\s+|\n", text):
        if "우선권" in sentence or "양보" in sentence:
            return sentence.strip()

    return None


def extract_legal_priority_refs(text: str) -> List[str]:
    """우선권 관련 법조문을 추출합니다."""

    refs = re.findall(r"도로교통법\s*제\s*\d+조(?:\s*제\s*\d+항)?", text)

    return sorted(set(refs))


def extract_block_summary(text: str, marker: str) -> Optional[str]:
    """특정 block의 앞부분을 요약용으로 잘라냅니다."""

    block = extract_between(text, marker, "수정요소 해설 :")

    if not block:
        return None

    return normalize_spaces(block[:500])
