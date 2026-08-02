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

ACCIDENT_CORE_FIELDS = {
    "road_layout",
    "signal_priority",
    "collision_location",
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


def accident_fact_candidates(
    value: Mapping[str, Any],
    *,
    source_message_id: str,
) -> list[dict[str, Any]]:
    candidates = _eligible_accident_candidates(value)
    by_field_value = {
        (str(item.get("field") or ""), str(item.get("value") or "")): item
        for item in candidates
    }
    projected: list[dict[str, Any]] = []
    self_straight = by_field_value.get(("vehicle_actions.self", "straight"))
    other_left_turn = by_field_value.get(("vehicle_actions.other", "left_turn"))
    if self_straight and other_left_turn:
        projected.append(
            {
                "field": "vehicle_actions",
                "value": "본인 차량 직진, 상대 차량 좌회전",
                "source_message_id": source_message_id,
                "confidence": round(
                    min(
                        float(self_straight.get("confidence") or 0.0),
                        float(other_left_turn.get("confidence") or 0.0),
                    ),
                    4,
                ),
                "confirmed": False,
            }
        )

    for item in candidates:
        field = str(item.get("field") or "")
        if field not in ACCIDENT_CORE_FIELDS:
            continue
        projected.append(
            {
                "field": field,
                "value": str(item.get("normalized_expression") or ""),
                "source_message_id": source_message_id,
                "confidence": float(item.get("confidence") or 0.0),
                "confirmed": False,
            }
        )
    return projected


def accident_fact_sources(
    value: Mapping[str, Any],
    *,
    source_message_id: str,
) -> list[dict[str, Any]]:
    candidates = _eligible_accident_candidates(value)
    action_values = {
        (str(item.get("field") or ""), str(item.get("value") or ""))
        for item in candidates
    }
    actions_ready = {
        ("vehicle_actions.self", "straight"),
        ("vehicle_actions.other", "left_turn"),
    }.issubset(action_values)
    sources: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in candidates:
        field = str(item.get("field") or "")
        target_field = (
            "vehicle_actions"
            if actions_ready and field.startswith("vehicle_actions.")
            else field
        )
        if target_field not in {*ACCIDENT_CORE_FIELDS, "vehicle_actions"}:
            continue
        rule_id = str(item.get("rule_id") or "")
        identity = (target_field, rule_id)
        if not rule_id or identity in seen:
            continue
        seen.add(identity)
        sources.append(
            {
                "field": target_field,
                "source_type": "rule_normalization",
                "rule_id": rule_id,
                "source_message_id": source_message_id,
            }
        )
    return sources


def _eligible_accident_candidates(
    value: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    return [
        item
        for item in value.get("candidates", [])
        if isinstance(item, Mapping)
        and item.get("domain") == "accident"
        and item.get("decision") == "auto_applied"
        and item.get("negated") is not True
        and item.get("uncertain") is not True
    ]
