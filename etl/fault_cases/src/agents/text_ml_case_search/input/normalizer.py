from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.schemas import AgentContext


ACCIDENT_TYPE_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (
        ("차로", "진로변경"),
        "차로 변경 중 후행 차량 충돌 사고",
        "차로 또는 진로변경 관련 표현이 포함되어 있습니다.",
    ),
    (
        ("중앙선", "역주행"),
        "중앙선 침범 또는 역주행 사고",
        "중앙선 침범 또는 역주행 관련 표현이 포함되어 있습니다.",
    ),
    (
        ("신호위반", "적색", "녹색"),
        "신호 있는 교차로 신호 관련 사고",
        "신호위반 또는 신호 색상 관련 표현이 포함되어 있습니다.",
    ),
    (
        ("신호 없는", "신호등 없음", "우측"),
        "신호 없는 교차로 차량 간 충돌 사고",
        "신호 없는 교차로 또는 우측 차량 진입 관련 표현이 포함되어 있습니다.",
    ),
    (
        ("후방추돌", "후미추돌", "안전거리"),
        "후미추돌 또는 후행 차량 충돌 사고",
        "후방추돌, 후미추돌, 안전거리 관련 표현이 포함되어 있습니다.",
    ),
    (
        ("횡단보도", "보행자", "무단횡단"),
        "보행자와 차량 충돌 사고",
        "횡단보도, 보행자, 무단횡단 관련 표현이 포함되어 있습니다.",
    ),
    (
        ("좌회전", "직진"),
        "교차로 좌회전 차량과 직진 차량 충돌 사고",
        "좌회전과 직진 차량 간 충돌 관련 표현이 포함되어 있습니다.",
    ),
    (
        ("오토바이", "이륜차"),
        "자동차와 이륜차 충돌 사고",
        "오토바이 또는 이륜차 관련 표현이 포함되어 있습니다.",
    ),
    (
        ("자전거",),
        "자동차와 자전거 충돌 사고",
        "자전거 관련 표현이 포함되어 있습니다.",
    ),
    (
        ("주정차", "정차", "주차"),
        "주정차 차량 관련 사고",
        "주정차, 정차, 주차 관련 표현이 포함되어 있습니다.",
    ),
]


def normalize_accident(context: AgentContext) -> dict[str, Any]:
    text = _combine_context_text(context)
    query_text = context.get("query_text") or ""

    candidates: list[dict[str, str]] = []
    for keywords, accident_type, reason in ACCIDENT_TYPE_RULES:
        if any(keyword in text for keyword in keywords):
            candidates.append({"type": accident_type, "reason": reason})

    if not candidates:
        candidates.append(
            {
                "type": "교통사고 과실 판단 사건",
                "reason": "구체 사고 유형을 단정할 키워드는 부족하지만 교통사고 과실 판단 요청입니다.",
            }
        )

    primary_type = candidates[0]["type"]
    normalized_description = f"{primary_type}로 정리됩니다."
    if query_text:
        normalized_description += f" 입력 사고 설명은 '{query_text}'입니다."

    return {
        "normalized_description": normalized_description,
        "accident_type_candidates": candidates,
    }


def _combine_context_text(context: AgentContext) -> str:
    parts: list[str] = [
        context.get("query_text") or "",
        context.get("raw_user_text") or "",
    ]

    for item in context.get("vision_evidence") or []:
        parts.append(str(item.get("description") or ""))
        observations = item.get("observations") or []
        parts.extend(str(value) for value in observations)

    ocr = context.get("ocr_evidence")
    if isinstance(ocr, dict):
        for key in ["accident_type", "accident_cause", "accident_description", "accident_location"]:
            parts.append(str(ocr.get(key) or ""))

    claim = context.get("insurer_claim")
    if isinstance(claim, dict):
        for key in ["claimed_ratio", "reason_text", "source_text"]:
            parts.append(str(claim.get(key) or ""))

    return " ".join(part for part in parts if part).strip()
