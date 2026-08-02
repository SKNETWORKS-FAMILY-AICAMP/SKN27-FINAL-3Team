"""Safe projections from normalized input into Supervisor routing contracts."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping


DOMAIN_INTENT_ORDER = {
    "objection": "fine_notice_procedure",
    "fine_notice": "fine_notice_procedure",
    "accident": "accident_initial_consultation",
}

QUESTION_BY_NORMALIZED_FIELD = {
    "road_layout": "사고 장소의 도로 형태를 다시 확인해 주세요.",
    "vehicle_actions.self": "본인 차량이 어떻게 움직였는지 확인해 주세요.",
    "vehicle_actions.other": "상대 차량이 어떻게 움직였는지 확인해 주세요.",
    "signal_priority": "당시 신호 또는 우선권을 확인해 주세요.",
    "collision_location": "두 차량의 충돌 부위를 확인해 주세요.",
    "fine_type": "받은 문서가 과태료인지 범칙금인지 확인해 주세요.",
    "notice_stage": "문서가 사전통지서인지 납부고지서인지 확인해 주세요.",
    "requested_action": "의견제출, 이의신청, 납부 안내 중 원하는 절차를 확인해 주세요.",
}


def normalization_routing_hints(value: Mapping[str, Any]) -> list[str]:
    hints: list[str] = []
    for item in value.get("candidates", []):
        if not isinstance(item, Mapping) or item.get("decision") != "auto_applied":
            continue
        intent = DOMAIN_INTENT_ORDER.get(str(item.get("domain") or ""))
        if intent and intent not in hints:
            hints.append(intent)
    return hints


def normalization_pending_questions(
    value: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidates = [
        item for item in value.get("candidates", []) if isinstance(item, Mapping)
    ]
    fields: list[str] = [
        str(item.get("field") or "")
        for item in candidates
        if item.get("decision")
        in {"confirmation_required", "clarification_required"}
    ]
    fields.extend(
        str(item.get("field") or "")
        for item in value.get("clarifications", [])
        if isinstance(item, Mapping)
    )

    values_by_field: dict[str, set[str]] = defaultdict(set)
    for item in candidates:
        field = str(item.get("field") or "")
        candidate_value = str(item.get("value") or "")
        if field and candidate_value:
            values_by_field[field].add(candidate_value)
    fields.extend(
        field for field, values in values_by_field.items() if len(values) > 1
    )

    return [
        {"field": field, "question": QUESTION_BY_NORMALIZED_FIELD[field]}
        for field in dict.fromkeys(fields)
        if field in QUESTION_BY_NORMALIZED_FIELD
    ]
