"""Safe projections from normalized input into Supervisor routing contracts."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from app.services.supervisor_input_normalization_service import (
    AMOUNT_PATTERN,
    AUTHORITY_PATTERN,
    DATE_PATTERN,
    normalization_policy,
)


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
FINE_NOTICE_INTAKE_FIELD_MAP = {
    "notice_stage": "document_disposition_type",
    "issuing_authority": "issuing_authority",
    "due_date": "response_deadline",
    "attachment_available": "attachment_available",
}
NORMALIZED_AGENT_SLOT_FIELDS = {
    "fine_type",
    "notice_stage",
    "issuing_authority",
    "notice_date",
    "due_date",
    "amount",
    "alleged_violation",
    "requested_action",
    "disputed_facts",
    "objection_reason",
    "evidence_references",
    "deadline_clarification_required",
    "legal_issue_terms",
}
TARGETED_SCENARIO_FIELDS = {
    "accident_initial_consultation": {
        "road_layout",
        "vehicle_actions",
        "signal_priority",
        "collision_location",
    },
    "fine_notice_procedure": {
        "fine_type",
        "notice_stage",
        "issuing_authority",
        "notice_date",
        "due_date",
        "amount",
        "alleged_violation",
        "requested_action",
        "disputed_facts",
        "objection_reason",
        "evidence_references",
        "deadline_clarification_required",
        "legal_issue_terms",
    },
    "fine_notice_analysis": {
        "fine_type",
        "notice_stage",
        "issuing_authority",
        "notice_date",
        "due_date",
        "amount",
        "alleged_violation",
        "requested_action",
        "disputed_facts",
        "objection_reason",
        "evidence_references",
        "deadline_clarification_required",
        "legal_issue_terms",
    },
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


def policy_allowed_llm_facts(
    items: Any,
    *,
    scenario: str,
) -> list[dict[str, Any]]:
    allowed = TARGETED_SCENARIO_FIELDS.get(scenario)
    facts = [dict(item) for item in items or [] if isinstance(item, Mapping)]
    if allowed is None:
        return facts
    projected: list[dict[str, Any]] = []
    for item in facts:
        field = str(item.get("field") or "").strip()
        if field not in allowed:
            continue
        value = canonical_policy_value(field=field, value=item.get("value"))
        if value is not None:
            projected.append({**item, "field": field, "value": value})
    return projected


def canonical_policy_value(*, field: str, value: Any) -> str | None:
    normalized_value = str(value or "").strip()
    if not normalized_value:
        return None
    if field == "vehicle_actions":
        return (
            normalized_value
            if normalized_value in _registered_vehicle_action_pairs()
            else None
        )
    if field == "issuing_authority":
        return (
            normalized_value
            if AUTHORITY_PATTERN.fullmatch(normalized_value)
            else None
        )
    if field in {"notice_date", "due_date"}:
        return normalized_value if DATE_PATTERN.fullmatch(normalized_value) else None
    if field == "amount":
        return normalized_value if AMOUNT_PATTERN.fullmatch(normalized_value) else None

    for rule in normalization_policy()["rules"]:
        if str(rule.get("field") or "") != field:
            continue
        accepted = {
            str(rule.get("value") or "").strip(),
            str(rule.get("canonical_expression") or "").strip(),
            *{
                str(item).strip()
                for key in ("expressions", "aliases", "approved_typos")
                for item in rule.get(key) or []
                if str(item).strip()
            },
        }
        if normalized_value not in accepted:
            continue
        if rule.get("domain") == "accident":
            return str(rule["canonical_expression"])
        return str(rule["value"])
    return None


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
    projected: list[dict[str, Any]] = []
    self_actions = [
        item for item in candidates if item.get("field") == "vehicle_actions.self"
    ]
    other_actions = [
        item for item in candidates if item.get("field") == "vehicle_actions.other"
    ]
    if len(self_actions) == 1 and len(other_actions) == 1:
        self_action = self_actions[0]
        other_action = other_actions[0]
        self_expression = _canonical_vehicle_action_expression(self_action)
        other_expression = _canonical_vehicle_action_expression(other_action)
        projected.append(
            {
                "field": "vehicle_actions",
                "value": f"{self_expression}, {other_expression}",
                "source_message_id": source_message_id,
                "confidence": round(
                    min(
                        float(self_action.get("confidence") or 0.0),
                        float(other_action.get("confidence") or 0.0),
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


def _canonical_vehicle_action_expression(candidate: Mapping[str, Any]) -> str:
    field = str(candidate.get("field") or "")
    value = str(candidate.get("value") or "")
    for rule in normalization_policy()["rules"]:
        if str(rule.get("field") or "") != field:
            continue
        if str(rule.get("value") or "") == value:
            return _canonical_vehicle_rule_expression(rule)
    return str(candidate.get("normalized_expression") or "").strip()


def _canonical_vehicle_rule_expression(rule: Mapping[str, Any]) -> str:
    field = str(rule.get("field") or "")
    expression = str(rule.get("canonical_expression") or "").strip()
    if field == "vehicle_actions.self" and not expression.startswith("본인"):
        return f"본인 차량 {expression}"
    if field == "vehicle_actions.other" and not expression.startswith("상대"):
        return f"상대 차량 {expression}"
    return expression


def _registered_vehicle_action_pairs() -> set[str]:
    self_actions: set[str] = set()
    other_actions: set[str] = set()
    for rule in normalization_policy()["rules"]:
        field = str(rule.get("field") or "")
        expression = _canonical_vehicle_rule_expression(rule)
        if field == "vehicle_actions.self" and expression:
            self_actions.add(expression)
        elif field == "vehicle_actions.other" and expression:
            other_actions.add(expression)
    return {
        f"{self_action}, {other_action}"
        for self_action in self_actions
        for other_action in other_actions
    }


def fine_notice_intake_slots(
    value: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    slots: dict[str, dict[str, Any]] = {}
    for candidate in _eligible_legal_slot_candidates(value):
        target = FINE_NOTICE_INTAKE_FIELD_MAP.get(
            str(candidate.get("field") or "")
        )
        if not target:
            continue
        slots[target] = {
            "value": candidate["value"],
            "source_type": "rule_normalization",
            "source_message_id": candidate["source_message_id"],
            "confidence": candidate["confidence"],
            "confirmed": False,
        }
    return slots


def normalized_slot_state(value: Mapping[str, Any]) -> dict[str, Any]:
    slots: dict[str, dict[str, Any]] = {}
    for candidate in _eligible_legal_slot_candidates(value):
        field = str(candidate.get("field") or "")
        if field not in NORMALIZED_AGENT_SLOT_FIELDS:
            continue
        slots[field] = {
            "value": candidate["value"],
            "source": {
                "type": "rule_normalization",
                "reference": candidate["source_message_id"],
            },
            "confidence": candidate["confidence"],
            "editable": True,
            "confirmed": False,
            "rule_id": candidate["rule_id"],
        }
    return {
        "contract_version": "slot_filling_state.v1",
        "slots": slots,
    }


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


def _eligible_legal_slot_candidates(
    value: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = []
    for item in value.get("candidates", []):
        if (
            not isinstance(item, Mapping)
            or item.get("domain") not in {"fine_notice", "objection"}
            or item.get("decision") != "auto_applied"
            or item.get("negated") is True
            or item.get("uncertain") is True
        ):
            continue
        field = str(item.get("field") or "")
        candidate_value = str(item.get("value") or "").strip()
        if not _valid_structured_legal_value(field, candidate_value):
            continue
        candidates.append(item)
    return candidates


def _valid_structured_legal_value(field: str, value: str) -> bool:
    if not value:
        return False
    if field == "amount":
        return AMOUNT_PATTERN.fullmatch(value) is not None
    if field == "issuing_authority":
        return AUTHORITY_PATTERN.fullmatch(value) is not None
    if field in {"notice_date", "due_date"}:
        return DATE_PATTERN.fullmatch(value) is not None
    return True
