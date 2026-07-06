from __future__ import annotations

from etl.fault_cases.src.agents.text_ml_case_search.schemas import AgentContext


ISSUE_RULES: list[tuple[tuple[str, ...], list[str]]] = [
    (("차로", "진로변경"), ["차로 변경", "진로변경 주의의무", "후행 차량 전방주시"]),
    (("중앙선", "역주행"), ["중앙선 침범", "진행 방향 위반", "상대방 예견 가능성"]),
    (("신호위반", "적색", "녹색"), ["신호위반", "신호 준수 여부", "교차로 통행방법"]),
    (("신호 없는", "신호등 없음", "우측"), ["신호 없는 교차로", "우측 차량 우선", "선진입 여부"]),
    (("후방추돌", "후미추돌", "안전거리"), ["후미추돌", "안전거리 확보", "전방주시의무"]),
    (("횡단보도", "보행자"), ["보행자 보호의무", "전방주시의무", "보행자 위치"]),
    (("무단횡단",), ["무단횡단", "보행자 주의의무", "운전자 발견 가능성"]),
    (("좌회전", "직진"), ["좌회전 차량 주의의무", "직진 차량 우선", "교차로 진입 시점"]),
    (("오토바이", "이륜차"), ["이륜차 사고", "차량 대 이륜차 주의의무", "충돌 위치"]),
    (("자전거",), ["자전거 사고", "자전거 주행 위치", "운전자 주의의무"]),
    (("주정차", "정차", "주차"), ["주정차 차량", "정차 위치", "전방주시의무"]),
    (("보험사", "과실", "비율"), ["보험사 과실비율 주장", "과실비율 산정 근거"]),
]


def extract_issue_tags(context: AgentContext, normalized: dict) -> list[str]:
    text = _combine_issue_text(context, normalized)

    tags: list[str] = []
    for keywords, values in ISSUE_RULES:
        if any(keyword in text for keyword in keywords):
            tags.extend(values)

    if not tags:
        tags.extend(["사고 경위", "주의의무", "과실 판단"])

    return list(dict.fromkeys(tags))


def _combine_issue_text(context: AgentContext, normalized: dict) -> str:
    parts = [
        context.get("query_text") or "",
        context.get("raw_user_text") or "",
        normalized.get("normalized_description") or "",
    ]

    ocr = context.get("ocr_evidence")
    if isinstance(ocr, dict):
        parts.extend(str(ocr.get(key) or "") for key in ["accident_type", "accident_cause", "accident_description"])

    claim = context.get("insurer_claim")
    if isinstance(claim, dict):
        parts.extend(str(claim.get(key) or "") for key in ["claimed_ratio", "reason_text", "source_text"])

    return " ".join(part for part in parts if part)
