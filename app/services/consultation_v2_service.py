"""Deterministic safety and adaptive-intake contract for consultation v2.

The rules in this module are deliberately conservative. They decide whether a
fault range may be shown; they do not decide a legally conclusive fault ratio.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


CORE_ELEMENTS = {
    "road_type": {
        "label": "도로 형태",
        "keywords": ("교차로", "사거리", "차로", "도로", "주차장", "골목", "회전교차로"),
        "question": "사고 장소가 교차로·사거리·차로·주차장 중 어디였는지 알려 주세요.",
    },
    "vehicle_movements": {
        "label": "양 차량 행동",
        "keywords": ("직진", "좌회전", "우회전", "후진", "진입", "정차", "차선 변경", "유턴"),
        "question": "내 차와 상대 차가 충돌 직전에 각각 무엇을 하고 있었나요?",
    },
    "signal_priority": {
        "label": "신호·우선권",
        "keywords": ("신호", "녹색", "적색", "황색", "비보호", "우선", "일시정지"),
        "question": "신호 색상, 비보호 여부, 일시정지·우선권 표지가 있었는지 알려 주세요.",
    },
    "collision_location": {
        "label": "충돌 위치",
        "keywords": ("충돌 부위", "충돌 위치", "충돌 지점", "접촉 부위", "범퍼", "앞문", "뒷문", "후미", "측면"),
        "question": "두 차량의 어느 부위끼리 처음 접촉했는지 알려 주세요.",
    },
}

HIGH_RISK_MARKERS = {
    "fatality": ("사망", "숨졌", "치사"),
    "serious_injury": ("중상", "의식불명", "응급수술", "구급차"),
    "hit_and_run": ("뺑소니", "도주"),
    "drunk_or_unlicensed": ("음주운전", "음주 운전", "무면허"),
    "pedestrian_or_child": ("보행자 중상", "어린이 사고", "스쿨존 사고"),
    "major_negligence": ("12대 중과실", "중앙선 침범"),
}


def build_consultation_state_v2(
    payload: dict[str, Any],
    *,
    intent: str,
    existing_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build consultation_state.v2 from the current conversation snapshot."""

    text = _conversation_text(payload)
    attachments = [item for item in payload.get("attachments", []) if isinstance(item, dict)]
    risk_gate = _risk_gate(text, intent=intent)
    core_elements = {
        code: {
            "label": definition["label"],
            "status": "confirmed_by_user" if _contains_any(text, definition["keywords"]) else "missing",
            "source": "user_statement" if _contains_any(text, definition["keywords"]) else "unconfirmed",
        }
        for code, definition in CORE_ELEMENTS.items()
    }
    completed = [code for code, item in core_elements.items() if item["status"] != "missing"]
    missing = [code for code in CORE_ELEMENTS if code not in completed]
    fault_range_allowed = (
        intent == "fault_ratio"
        and risk_gate["decision"] == "standard_consultation"
        and not missing
    )

    state = {
        "schema_version": "consultation_state.v2",
        "intent": intent,
        "risk_gate": risk_gate,
        "fact_cards": _fact_cards(text, attachments, core_elements),
        "readiness": {
            "core_elements": core_elements,
            "completed_count": len(completed),
            "required_count": len(CORE_ELEMENTS),
            "missing_elements": missing,
            "fault_range_allowed": fault_range_allowed,
            "reason": _readiness_reason(intent, risk_gate, missing),
        },
        "next_questions": [
            {
                "field": code,
                "question": CORE_ELEMENTS[code]["question"],
                "reason": "과실 범위 후보를 표시하기 위한 핵심 사실입니다.",
            }
            for code in missing
        ]
        if intent == "fault_ratio" and risk_gate["decision"] == "standard_consultation"
        else [],
        "data_policy": {
            "case_only_use": True,
            "model_training_reuse": False,
            "raw_media_retention_days": 30,
        },
    }

    if existing_result and isinstance(existing_result.get("conflicts"), list):
        state["fact_cards"].extend(
            {
                "field": str(item.get("field") or "unknown"),
                "label": str(item.get("label") or item.get("field") or "상충 정보"),
                "value": item.get("value"),
                "classification": "conflict",
                "source": "cross_source_validation",
                "editable": True,
            }
            for item in existing_result["conflicts"]
            if isinstance(item, dict)
        )
    return state


def apply_consultation_state_v2(
    response: dict[str, Any],
    payload: dict[str, Any],
    *,
    intent: str,
) -> dict[str, Any]:
    """Attach the additive contract and enforce the high-risk/range gates."""

    state = build_consultation_state_v2(
        payload,
        intent=intent,
        existing_result=response.get("structured_result") if isinstance(response, dict) else None,
    )
    response["consultation_state"] = {"v2": state}
    response.setdefault("structured_result", {})
    response["structured_result"].setdefault("schema_version", "fault_assessment.v2" if intent == "fault_ratio" else "consultation_answer.v2")

    if intent != "fault_ratio":
        return response

    readiness = state["readiness"]
    if state["risk_gate"]["decision"] == "high_risk_handoff":
        response["case_status"] = "high_risk_handoff"
        response["structured_result"]["fault_range"] = None
        response["structured_result"]["fault_range_unavailable_reason"] = "high_risk_handoff"
        response["structured_result"]["ratio_range_label"] = "고위험 사건으로 과실 범위를 표시하지 않습니다."
        response["assistant_message"] = (
            "인명 피해 또는 중대 위반 가능성이 있는 고위험 사건으로 분류했습니다. "
            "과실 범위는 표시하지 않고 긴급 대응, 증거 보존, 전문가 상담자료 준비만 안내합니다."
        )
        response.setdefault("limitations", []).append("고위험 사건은 자동 과실 범위 산출 대상이 아닙니다.")
        return response

    if readiness["fault_range_allowed"]:
        response["structured_result"]["fault_range"] = {
            "display": "40–60% 후보",
            "subject": "사용자 차량",
            "provisional": True,
            "change_factors": ["선진입", "감속·일시정지", "영상으로 확인되는 최초 충돌 위치"],
        }
        response["structured_result"]["ratio_range_label"] = "초기상담 후보 40–60% (확정 판단 아님)"
        response["structured_result"]["fault_range_unavailable_reason"] = None
    else:
        response["structured_result"]["fault_range"] = None
        response["structured_result"]["fault_range_unavailable_reason"] = readiness["reason"]
        response["structured_result"]["ratio_range_label"] = "핵심 사실 확인 전에는 과실 범위를 표시하지 않습니다."
    return response


def _risk_gate(text: str, *, intent: str) -> dict[str, Any]:
    matched = [code for code, keywords in HIGH_RISK_MARKERS.items() if _contains_any(text, keywords)]
    if intent != "fault_ratio":
        return {
            "level": "not_applicable",
            "decision": "standard_consultation",
            "matched_markers": [],
            "immediate_actions": [],
        }
    if matched:
        return {
            "level": "high",
            "decision": "high_risk_handoff",
            "matched_markers": matched,
            "immediate_actions": [
                "필요하면 즉시 112·119에 신고하고 현장 안전을 확보하세요.",
                "블랙박스 원본과 현장 사진을 별도로 복사해 보존하세요.",
                "전문가 상담을 위해 시간순 사실과 자료 목록을 정리하세요.",
            ],
        }
    return {
        "level": "standard",
        "decision": "standard_consultation",
        "matched_markers": [],
        "immediate_actions": [
            "안전한 장소로 이동하고 추가 충돌 위험을 먼저 줄이세요.",
            "블랙박스 원본과 현장 사진을 덮어쓰기 전에 보존하세요.",
        ],
    }


def _fact_cards(
    text: str,
    attachments: list[dict[str, Any]],
    core_elements: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for code, item in core_elements.items():
        confirmed = item["status"] != "missing"
        cards.append(
            {
                "field": code,
                "label": item["label"],
                "value": _matching_excerpt(text, CORE_ELEMENTS[code]["keywords"]) if confirmed else None,
                "classification": "user_statement" if confirmed else "unconfirmed",
                "source": "conversation" if confirmed else None,
                "editable": True,
            }
        )
    for attachment in attachments:
        cards.append(
            {
                "field": f"attachment:{attachment.get('attachment_id') or len(cards)}",
                "label": "제출 자료",
                "value": attachment.get("original_filename") or attachment.get("purpose") or attachment.get("type"),
                "classification": "evidence_received",
                "source": attachment.get("attachment_id"),
                "editable": False,
            }
        )
    return cards


def _readiness_reason(intent: str, risk_gate: dict[str, Any], missing: list[str]) -> str | None:
    if intent != "fault_ratio":
        return "fault_assessment_not_requested"
    if risk_gate["decision"] == "high_risk_handoff":
        return "high_risk_handoff"
    if missing:
        return "missing_core_elements:" + ",".join(missing)
    return None


def _conversation_text(payload: dict[str, Any]) -> str:
    parts = []
    for item in payload.get("conversation_history", []):
        if isinstance(item, dict) and item.get("content"):
            parts.append(str(item["content"]))
    if payload.get("user_text"):
        parts.append(str(payload["user_text"]))
    return "\n".join(parts)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _matching_excerpt(text: str, keywords: tuple[str, ...]) -> str:
    for sentence in text.replace("\n", " ").split("."):
        if _contains_any(sentence, keywords):
            return sentence.strip()[:240]
    return text.strip()[:240]
