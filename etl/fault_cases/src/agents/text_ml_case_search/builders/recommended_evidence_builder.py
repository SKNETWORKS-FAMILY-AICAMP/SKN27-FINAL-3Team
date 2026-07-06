from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.schemas import AgentContext


RECOMMENDATION_RULES: list[tuple[tuple[str, ...], list[dict[str, str]]]] = [
    (
        ("신호위반", "신호 준수 여부"),
        [
            {"type": "signal_evidence", "description": "각 차량의 교차로 진입 시점과 신호 색상이 확인되는 영상"},
            {"type": "signal_timing", "description": "사고 지점 신호 주기 또는 신호 운영 자료"},
        ],
    ),
    (
        ("신호 없는 교차로", "우측 차량 우선", "선진입 여부"),
        [
            {"type": "entry_sequence", "description": "양 차량의 교차로 진입 순서를 확인할 수 있는 영상"},
            {"type": "impact_position", "description": "충돌 위치와 최종 정차 위치 사진"},
        ],
    ),
    (
        ("차로 변경", "진로변경 주의의무"),
        [
            {"type": "lane_change_video", "description": "방향지시등 작동 여부와 차로 변경 시작 시점이 보이는 영상"},
            {"type": "rear_vehicle_distance", "description": "후행 차량과의 거리 및 속도 확인 자료"},
        ],
    ),
    (
        ("중앙선 침범", "진행 방향 위반"),
        [
            {"type": "road_marking_photo", "description": "중앙선 표시와 차로 구조가 보이는 현장 사진"},
            {"type": "trajectory_video", "description": "각 차량 진행 방향을 확인할 수 있는 사고 전후 영상"},
        ],
    ),
    (
        ("후미추돌", "안전거리 확보", "전방주시의무"),
        [
            {"type": "braking_evidence", "description": "급정거 여부와 제동 시점을 확인할 수 있는 영상"},
            {"type": "damage_photo", "description": "앞뒤 차량 파손 부위 사진"},
        ],
    ),
    (
        ("보행자 보호의무", "무단횡단"),
        [
            {"type": "pedestrian_path", "description": "보행자 이동 경로와 차량 접근 방향이 보이는 영상"},
            {"type": "crosswalk_photo", "description": "횡단보도, 보행 신호, 주변 시야 상태 사진"},
        ],
    ),
    (
        ("보험사 과실비율 주장",),
        [
            {"type": "insurer_claim_document", "description": "보험사의 과실비율 산정 이유가 적힌 문자, 안내문, 녹취 요약"},
        ],
    ),
]


def build_recommended_evidence(
    *,
    context: AgentContext,
    issue_tags: list[str],
    evidence: list[dict[str, Any]],
) -> list[dict[str, str]]:
    del evidence
    del context

    recommendations: list[dict[str, str]] = []
    for keywords, values in RECOMMENDATION_RULES:
        if any(keyword in issue_tags for keyword in keywords):
            recommendations.extend(values)

    if not recommendations:
        recommendations.append(
            {
                "type": "accident_video",
                "description": "사고 전후 진행 방향, 충돌 위치, 정차 위치가 확인되는 블랙박스 또는 CCTV 영상",
            }
        )

    return _dedupe_recommendations(recommendations)


def _dedupe_recommendations(items: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (item.get("type", ""), item.get("description", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


# Schema-aligned recommendation rules.
# The legacy definitions above are kept for patch safety; Python uses the last
# definitions below at runtime.
Recommendation = dict[str, Any]


RECOMMENDATION_RULES = [
    (
        ("신호위반", "신호 준수 여부", "신호 있는 교차로"),
        [
            {
                "type": "signal_evidence",
                "title": "교차로 진입 시점과 신호 상태 영상",
                "description": "각 차량이 교차로에 진입한 시점과 당시 신호 색상을 확인할 수 있는 블랙박스, CCTV, 주변 영상이 필요합니다.",
                "related_issue": "신호 준수 여부",
                "priority": "high",
                "based_on": ["issue_tags", "vision_evidence"],
            },
            {
                "type": "signal_timing",
                "title": "사고 지점 신호 운영 자료",
                "description": "사고 시각 전후의 신호 주기 또는 신호 운영 자료가 있으면 신호위반 여부를 더 구체적으로 비교할 수 있습니다.",
                "related_issue": "신호 준수 여부",
                "priority": "medium",
                "based_on": ["issue_tags"],
            },
        ],
    ),
    (
        ("신호 없는 교차로", "우측 차량 우선", "선진입 여부"),
        [
            {
                "type": "entry_sequence",
                "title": "양 차량의 교차로 진입 순서 영상",
                "description": "신호 없는 교차로에서는 어느 차량이 먼저 진입했는지와 우측 차량 여부가 중요하므로, 교차로 진입 전후 영상이 필요합니다.",
                "related_issue": "선진입 여부",
                "priority": "high",
                "based_on": ["issue_tags", "vision_evidence"],
            },
            {
                "type": "impact_position",
                "title": "충돌 위치와 최종 정차 위치 사진",
                "description": "충돌 부위와 정차 위치는 진입 방향, 선진입 여부, 회피 가능성을 판단하는 보조 근거가 됩니다.",
                "related_issue": "충돌 위치",
                "priority": "high",
                "based_on": ["issue_tags", "ocr_evidence"],
            },
        ],
    ),
    (
        ("차로 변경", "진로변경 주의의무"),
        [
            {
                "type": "lane_change_video",
                "title": "차로 변경 시작 시점 영상",
                "description": "방향지시등 작동 여부, 차로 변경 시작 시점, 후행 차량과의 거리가 함께 보이는 영상이 필요합니다.",
                "related_issue": "진로변경 주의의무",
                "priority": "high",
                "based_on": ["issue_tags", "vision_evidence"],
            },
            {
                "type": "rear_vehicle_distance",
                "title": "후행 차량 접근 거리와 속도 확인 자료",
                "description": "후행 차량이 충분히 인지하고 감속할 수 있었는지 판단하려면 차간거리와 접근 속도를 확인해야 합니다.",
                "related_issue": "후행 차량 전방주시",
                "priority": "medium",
                "based_on": ["issue_tags", "vision_evidence"],
            },
        ],
    ),
    (
        ("중앙선 침범", "진행 방향 위반"),
        [
            {
                "type": "road_marking_photo",
                "title": "중앙선 표시와 차로 구조 사진",
                "description": "중앙선 표시, 차로 폭, 도로 구조가 보이는 현장 사진은 중앙선 침범 여부를 판단하는 기본 자료입니다.",
                "related_issue": "중앙선 침범",
                "priority": "high",
                "based_on": ["issue_tags", "ocr_evidence"],
            },
            {
                "type": "trajectory_video",
                "title": "사고 전후 차량 진행 방향 영상",
                "description": "어느 차량이 반대 차로 방향으로 진행했는지 확인할 수 있는 사고 전후 영상이 필요합니다.",
                "related_issue": "진행 방향 위반",
                "priority": "high",
                "based_on": ["issue_tags", "vision_evidence"],
            },
        ],
    ),
    (
        ("후방추돌", "안전거리 확보", "전방주시의무"),
        [
            {
                "type": "braking_evidence",
                "title": "급정거 여부와 제동 시점 자료",
                "description": "선행 차량의 급정거 여부, 제동등 작동 시점, 후행 차량의 반응 시간을 확인할 수 있는 영상이 필요합니다.",
                "related_issue": "안전거리 확보",
                "priority": "high",
                "based_on": ["issue_tags", "vision_evidence"],
            },
            {
                "type": "damage_photo",
                "title": "앞뒤 차량 파손 부위 사진",
                "description": "파손 부위와 충격 방향은 단순 후방추돌인지, 끼어들기나 급정거 쟁점이 있는지 확인하는 보조 근거입니다.",
                "related_issue": "충돌 형태",
                "priority": "medium",
                "based_on": ["issue_tags", "ocr_evidence"],
            },
        ],
    ),
    (
        ("보행자 보호의무", "무단횡단", "횡단보도"),
        [
            {
                "type": "pedestrian_path",
                "title": "보행자 이동 경로와 차량 접근 영상",
                "description": "보행자의 진입 위치, 이동 방향, 운전자의 발견 가능성을 확인할 수 있는 영상이 필요합니다.",
                "related_issue": "보행자 보호의무",
                "priority": "high",
                "based_on": ["issue_tags", "vision_evidence"],
            },
            {
                "type": "crosswalk_photo",
                "title": "횡단보도와 주변 시야 상태 사진",
                "description": "횡단보도 위치, 보행자 신호, 가로등, 불법 주정차 등 시야 방해 요소를 확인할 수 있는 현장 사진이 필요합니다.",
                "related_issue": "보행자 발견 가능성",
                "priority": "medium",
                "based_on": ["issue_tags", "ocr_evidence"],
            },
        ],
    ),
    (
        ("보험사 과실비율 주장", "과실비율 산정 근거"),
        [
            {
                "type": "insurer_claim_document",
                "title": "보험사 과실비율 산정 근거 자료",
                "description": "보험사가 제시한 과실비율, 산정 이유, 적용 기준이 적힌 문자, 안내문, 녹취 요약이 필요합니다.",
                "related_issue": "보험사 과실비율 주장",
                "priority": "high",
                "based_on": ["insurer_claim", "issue_tags"],
            },
        ],
    ),
]


def build_recommended_evidence(
    *,
    context: AgentContext,
    issue_tags: list[str],
    evidence: list[dict[str, Any]],
) -> list[Recommendation]:
    del evidence
    del context

    recommendations: list[Recommendation] = []
    for keywords, values in RECOMMENDATION_RULES:
        if any(keyword in issue_tags for keyword in keywords):
            recommendations.extend(values)

    if not recommendations:
        recommendations.append(
            {
                "type": "accident_video",
                "title": "사고 전후 전체 진행 영상",
                "description": "사고 전후 진행 방향, 충돌 위치, 정차 위치가 확인되는 블랙박스 또는 CCTV 영상이 필요합니다.",
                "related_issue": "기본 사고 경위 확인",
                "priority": "high",
                "based_on": ["query_text", "raw_user_text"],
            }
        )

    return _dedupe_recommendations(recommendations)


def _dedupe_recommendations(items: list[Recommendation]) -> list[Recommendation]:
    deduped: list[Recommendation] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (str(item.get("type", "")), str(item.get("title", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
