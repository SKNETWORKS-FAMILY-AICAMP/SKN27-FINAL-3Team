from __future__ import annotations

from copy import deepcopy
from typing import Any


CASE_MEMORY_SCHEMA_VERSION = "case_memory.v1"
_LIST_FIELDS = (
    "parties",
    "vehicles",
    "time_place",
    "incident_types",
    "confirmed_facts",
    "user_claims",
    "attachments",
    "evidence_refs",
    "search_grounds",
    "unknowns",
    "deadlines",
    "progress_steps",
)


def update_case_memory(
    current: dict[str, Any] | None,
    *,
    user_text: str,
    routing_intent: str,
    fact_state: dict[str, Any] | None,
    case_evidence: dict[str, Any] | None,
    attachments: list[dict[str, Any]] | None,
    consultation_state: dict[str, Any] | None,
) -> dict[str, Any]:
    memory = _normalized_memory(current)
    facts = _dict(fact_state).get("facts") if isinstance(_dict(fact_state).get("facts"), dict) else {}
    evidence = _dict(case_evidence)
    consultation = _dict(consultation_state)

    memory["incident_types"] = _merge_text_list(memory["incident_types"], [routing_intent])
    memory["time_place"] = _merge_text_list(
        memory["time_place"],
        [
            _text(_dict(facts.get("road_layout")).get("value")),
            _text(_dict(facts.get("collision_location")).get("value")),
        ],
    )
    memory["vehicles"] = _merge_text_list(
        memory["vehicles"],
        [_text(_dict(facts.get("vehicle_actions")).get("value"))],
    )
    memory["confirmed_facts"] = _merge_dict_list(
        memory["confirmed_facts"],
        [
            {
                "field": field,
                "value": _text(record.get("value")),
                "source_message_id": _text(record.get("source_message_id")) or None,
            }
            for field, record in facts.items()
            if isinstance(record, dict) and record.get("confirmed") is True and _text(record.get("value"))
        ],
        key_fields=("field", "value"),
    )
    memory["user_claims"] = _merge_dict_list(
        memory["user_claims"],
        [
            {
                "field": field,
                "value": _text(record.get("value")),
                "source_ref": _text(_dict(record.get("evidence_source")).get("source_ref")) or None,
            }
            for field, record in _dict(evidence.get("claims")).items()
            if isinstance(record, dict) and _text(record.get("value"))
        ],
        key_fields=("field", "value"),
    )
    memory["attachments"] = _merge_dict_list(
        memory["attachments"],
        [
            {
                "attachment_id": _text(item.get("attachment_id")),
                "purpose": _text(item.get("purpose")) or None,
            }
            for item in attachments or []
            if isinstance(item, dict) and _text(item.get("attachment_id"))
        ],
        key_fields=("attachment_id",),
    )

    search_grounds = [
        _text(_dict(record.get("evidence_source")).get("source_ref"))
        for record in list(_dict(evidence.get("facts")).values()) + list(_dict(evidence.get("claims")).values())
        if isinstance(record, dict)
    ]
    memory["search_grounds"] = _merge_text_list(memory["search_grounds"], search_grounds)
    memory["evidence_refs"] = _merge_text_list(
        memory["evidence_refs"],
        [item.get("attachment_id") for item in memory["attachments"]] + memory["search_grounds"],
    )
    memory["unknowns"] = _merge_dict_list(
        memory["unknowns"],
        [
            {"field": _text(item.get("field")), "reason": _text(item.get("reason"))}
            for item in _dict_list(evidence.get("unknowns"))
            if _text(item.get("field")) and _text(item.get("reason"))
        ],
        key_fields=("field", "reason"),
    )
    memory["deadlines"] = _merge_text_list(
        memory["deadlines"],
        [
            _text(consultation.get("computed_deadline")),
            _text(consultation.get("opinion_deadline")),
        ],
    )
    memory["progress_steps"] = _merge_text_list(
        memory["progress_steps"],
        [_text(consultation.get("next_action"))],
    )
    return compact_case_memory(memory, latest_user_text=user_text)


def compact_case_memory(
    memory: dict[str, Any] | None,
    *,
    latest_user_text: str = "",
) -> dict[str, Any]:
    compacted = _normalized_memory(memory)
    compacted["conversation_summary"] = _summary_text(
        _text(compacted.get("conversation_summary")),
        latest_user_text,
    )
    return compacted


def _normalized_memory(value: dict[str, Any] | None) -> dict[str, Any]:
    raw = deepcopy(value) if isinstance(value, dict) else {}
    normalized = {"schema_version": CASE_MEMORY_SCHEMA_VERSION}
    for field in _LIST_FIELDS:
        current = raw.get(field)
        if field in {"confirmed_facts", "user_claims", "attachments", "unknowns"}:
            normalized[field] = _dict_list(current)
        else:
            normalized[field] = _text_list(current)
    normalized["conversation_summary"] = _text(raw.get("conversation_summary"))
    return normalized


def _summary_text(existing: str, latest_user_text: str) -> str:
    parts = [item for item in [existing, _text(latest_user_text)] if item]
    merged = " ".join(_dedupe_text(parts))
    if len(merged) <= 280:
        return merged
    return merged[:277].rstrip() + "..."


def _merge_text_list(current: list[str], incoming: list[Any]) -> list[str]:
    return _dedupe_text([*current, *[_text(item) for item in incoming if _text(item)]])


def _merge_dict_list(
    current: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    key_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for item in [*current, *incoming]:
        if not isinstance(item, dict):
            continue
        key = tuple(_text(item.get(field)) for field in key_fields)
        if not any(key):
            continue
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            {
                key_name: (
                    item.get(key_name)
                    if item.get(key_name) not in ("", None)
                    and item.get(key_name) != []
                    else None
                )
                for key_name in item
            }
        )
    return merged


def _dedupe_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe_text([_text(item) for item in value if _text(item)])


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [deepcopy(item) for item in value or [] if isinstance(item, dict)]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""
