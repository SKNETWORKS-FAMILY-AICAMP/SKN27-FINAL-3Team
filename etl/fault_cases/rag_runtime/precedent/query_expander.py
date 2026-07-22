"""판례 RAG B-4 질의 보강기"""
from __future__ import annotations
from typing import Any

CONCEPT_PATTERNS: dict[str, tuple[str, ...]] = {
    "unsignalized": ("신호기 없는", "신호등 없는", "교통정리가 없는"),
    "equal_width": ("같은 폭",),
    "unequal_road": ("대로", "소로", "좁은", "넓은 도로"),
    "four_way_intersection": ("사거리",),
    "intersection": ("교차로", "사거리", "t자형"),
    "right_approach": ("오른쪽 도로", "우측 도로"),
    "lane_change": ("진로를 변경", "진로변경", "진로 변경", "차로를 변경", "차로변경", "차로 변경"),
    "changed_lane_rear_straight": ("변경 차로의 후행", "변경차로의 후행"),
    "side_collision": ("측면 충돌",),
    "uturn": ("유턴", "u턴"),
    "illegal_uturn": ("불법 유턴", "신호위반", "신호를 위반"),
    "overtake": ("추월",),
    "center_line": ("중앙선",),
    "oncoming": ("맞은편", "반대 방향"),
    "stop": ("정차", "정지"),
    "signal_waiting": ("신호대기", "신호 대기", "정지신호", "적색 신호에 정차"),
    "rear_end": ("추돌", "들이받"),
    "forward_attention_or_distance": ("전방주시", "안전거리"),
    "prior_accident": ("1차 사고", "사고 후", "2차 교통사고", "연쇄 충돌"),
    "expressway": ("고속도로", "자동차전용도로"),
    "icing": ("결빙",),
    "offroad_place": ("주차장", "차도가 아닌", "골목", "출입로"),
    "road_entry": ("도로로 진입", "도로에 진입", "본선으로 진입", "본선으로 합류"),
    "mainline_straight": ("본선을 직진", "본선 차로를 직진", "본선 도로를 직진"),
    "mainline_exit": ("진출",),
    "driving_lane": ("주행차로",),
    "passing_lane": ("추월차로",),
    "passing_lane_straight": ("추월차로를 직진",),
    "mainline_merge": ("본선으로 합류", "고속도로 진입로"),
    "car": ("자동차",),
    "motorcycle": ("이륜차", "오토바이", "원동기장치자전거"),
    "bicycle": ("자전거",),
    "right_turn": ("우회전",),
    "left_turn": ("좌회전",),
    "right_side": ("오른쪽", "우측"),
    "following": ("후행", "뒤따라"),
    "motorcycle_only": ("오토바이", "이륜차"),
    "turn_lane": ("좌회전 전용차로",),
}

CONCEPT_PATTERNS.update(
    {
        "flashing_red_signal": ("적색 점멸", "빨간색 점멸"),
        "flashing_yellow_signal": ("황색 점멸", "노란색 점멸"),
    }
)

def detect_concepts(query_text: str) -> tuple[set[str], list[dict[str, Any]]]:
    """질문 원문에서 대표 개념과 문맥 의존어 정규화 결과를 찾는다."""
    normalized = query_text.lower()
    concepts: set[str] = set()
    evidence: list[dict[str, Any]] = []

    for concept_id, patterns in CONCEPT_PATTERNS.items():
        matched = [pattern for pattern in patterns if pattern.lower() in normalized]
        if matched:
            concepts.add(concept_id)
            evidence.append({"concept_id": concept_id, "matched_aliases": matched})

    straight_count = normalized.count("직진")
    if straight_count >= 1:
        concepts.add("straight")
        evidence.append({"concept_id": "straight", "matched_aliases": ["직진"], "count": straight_count})
    if straight_count >= 2:
        concepts.add("two_actors_straight")

    if "진입" in normalized:
        if ("진입로" in normalized or "가속차로" in normalized) and "본선" in normalized:
            concepts.add("mainline_merge")
            evidence.append({"concept_id": "mainline_merge", "matched_aliases": ["진입"], "context": "진입로·가속차로와 본선"})
        elif any(term in normalized for term in ("주차장", "골목", "출입로", "차도가 아닌")) and "도로" in normalized:
            concepts.add("road_entry")
            evidence.append({"concept_id": "road_entry", "matched_aliases": ["진입"], "context": "도로 외 장소와 도로"})
        elif "교차로" in normalized:
            evidence.append({"concept_id": "ambiguous_entry", "matched_aliases": ["진입"], "context": "교차로 문맥"})
        else:
            evidence.append({"concept_id": "ambiguous_entry", "matched_aliases": ["진입"], "context": "문맥 부족"})

    return concepts, evidence

def evaluate_variant(concepts: set[str], variant: dict[str, list[str]]) -> dict[str, Any]:
    """필수 개념 충족과 충돌 개념 존재를 분리해 가상 발동 여부를 계산한다."""
    required = variant.get("all", [])
    forbidden = variant.get("none", [])
    missing = [concept for concept in required if concept not in concepts]
    conflicts = [concept for concept in forbidden if concept in concepts]
    return {
        "fired": not missing and not conflicts,
        "missing_concepts": missing,
        "conflict_concepts": conflicts,
    }
