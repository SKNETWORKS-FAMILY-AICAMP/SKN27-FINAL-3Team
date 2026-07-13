"""Versioned intake state for accident-first traffic dispute consultation."""

from __future__ import annotations

from typing import Any


CORE_FACT_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("road_layout", "사고 장소의 도로 형태를 알려주세요."),
    ("vehicle_actions", "충돌 직전 양쪽 차량의 진행 방향과 행동을 알려주세요."),
    ("signal_priority", "당시 신호나 우선권 상황을 알려주세요."),
    ("collision_location", "각 차량의 어느 부위가 충돌했는지 알려주세요."),
)

HIGH_RISK_MARKERS = (
    "의식이 없",
    "사망",
    "중상",
    "크게 다쳐",
    "구급차",
    "뺑소니",
    "음주",
    "무면허",
)


def build_consultation_state_v2(
    *,
    user_text: str,
    facts: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    conflicts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the risk, fact-card, and readiness contract before analysis."""

    normalized_facts = _dict(facts)
    normalized_sources = _dict_list(sources)
    normalized_conflicts = _dict_list(conflicts)
    high_risk = _is_high_risk(user_text)
    missing_fields = [
        field
        for field, _question in CORE_FACT_QUESTIONS
        if not _text(normalized_facts.get(field))
    ]
    ready_for_fault_range = not high_risk and not missing_fields and not normalized_conflicts

    return {
        "schema_version": "consultation_state.v2",
        "intent": "accident_initial_consultation",
        "risk_gate": {
            "level": "high_risk" if high_risk else "standard",
            "allows_fault_range": not high_risk,
            "required_actions": (
                ["contact_emergency_services", "preserve_evidence", "expert_handoff"]
                if high_risk
                else []
            ),
        },
        "fact_cards": _fact_cards(
            facts=normalized_facts,
            sources=normalized_sources,
            conflicts=normalized_conflicts,
        ),
        "readiness": {
            "required_fields": [field for field, _question in CORE_FACT_QUESTIONS],
            "missing_fields": missing_fields,
            "conflict_count": len(normalized_conflicts),
            "ready_for_fault_range": ready_for_fault_range,
        },
        "next_questions": (
            []
            if high_risk
            else [
                {"field": field, "question": question}
                for field, question in CORE_FACT_QUESTIONS
                if field in missing_fields
            ]
        ),
        "next_action": (
            "expert_handoff"
            if high_risk
            else "confirm_facts"
            if ready_for_fault_range
            else "collect_missing_facts"
        ),
        "limitations": (
            ["고위험 사건에서는 과실 범위를 산출하지 않습니다."]
            if high_risk
            else ["사용자가 사실 카드를 확정하기 전에는 과실 범위를 산출하지 않습니다."]
        ),
    }


def _fact_cards(
    *,
    facts: dict[str, Any],
    sources: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_by_field = {
        _text(source.get("field")): source
        for source in sources
        if _text(source.get("field"))
    }
    cards: list[dict[str, Any]] = []
    for field, _question in CORE_FACT_QUESTIONS:
        value = facts.get(field)
        source = source_by_field.get(field)
        if _text(value):
            source_type = _text((source or {}).get("source_type"))
            category = "user_statement" if source_type in {"", "user_statement", "user_confirmation"} else "material_confirmed"
            cards.append(
                {
                    "field": field,
                    "category": category,
                    "value": value,
                    "source": source or {"source_type": "user_statement"},
                }
            )
        else:
            cards.append({"field": field, "category": "unconfirmed", "value": None, "source": None})

    cards.extend(
        {
            "field": _text(conflict.get("field")) or "unknown",
            "category": "conflict",
            "value": conflict,
            "source": None,
        }
        for conflict in conflicts
    )
    return cards


def _is_high_risk(user_text: str) -> bool:
    normalized = _text(user_text).lower()
    return any(marker in normalized for marker in HIGH_RISK_MARKERS)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value or [] if isinstance(item, dict)]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""
