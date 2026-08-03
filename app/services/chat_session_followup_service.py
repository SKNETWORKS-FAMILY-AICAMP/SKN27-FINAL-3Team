"""Server-authoritative follow-up state helpers for canonical chat sessions."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


CHAT_SESSION_FOLLOWUP_STATE_VERSION = "chat_session_followup_state.v1"
MAX_FOLLOWUP_HISTORY_TURNS = 16
_TOPIC_SCOPED_FIELDS = frozenset(
    {
        "facts",
        "fact_sources",
        "fact_conflicts",
        "pending_questions",
        "case_memory",
        "fine_notice_intake",
        "stored_fine_notice_intake_slots",
        "consultation_state",
        "conversation_history",
        "ocr_confirmation",
    }
)
_OCR_CONFIRMATION_FIELDS = frozenset(
    {
        "fine_type",
        "notice_stage",
        "law_code",
        "violation_text",
        "opinion_deadline",
        "issuing_authority",
    }
)
_OCR_CONFIRMATION_REQUIRED_FIELDS = frozenset({"fine_type", "notice_stage"})
_REPORT_USER_FACT_MARKERS = (
    "당시",
    "표지판",
    "식별",
    "안전",
    "잠시",
    "불가피",
    "응급",
    "병원",
    "고장",
    "비상",
    "피하기 위해",
    "때문",
    "사유로",
    "상황은",
    "실제로",
)
_MAX_REPORT_USER_FACTS_LENGTH = 2000


def merge_chat_followup_payload(
    payload: dict[str, Any],
    stored_state: dict[str, Any] | None,
    *,
    current_routing_intent: str = "",
) -> dict[str, Any]:
    """Merge a safe request with the authoritative state stored for its session."""

    merged = deepcopy(payload)
    state = _valid_state(stored_state)
    if state is None:
        return merged
    if _is_topic_switch(
        current_routing_intent=current_routing_intent,
        stored_routing_intent=_text(state.get("routing_intent")),
    ):
        for field in _TOPIC_SCOPED_FIELDS:
            merged.pop(field, None)
        return merged

    server_facts = _dict(state.get("facts"))
    client_facts = _dict(merged.get("facts"))
    merged["facts"] = {
        **{
            field: deepcopy(value)
            for field, value in client_facts.items()
            if field not in server_facts
        },
        **deepcopy(server_facts),
    }
    merged["fact_sources"] = _merge_fact_sources(
        stored_sources=state.get("fact_sources"),
        client_sources=merged.get("fact_sources"),
        server_fact_fields=set(server_facts),
    )
    merged["fact_conflicts"] = _merge_conflicts(
        stored_conflicts=state.get("fact_conflicts"),
        client_conflicts=merged.get("fact_conflicts"),
        server_fact_fields=set(server_facts),
    )
    if isinstance(state.get("case_memory"), dict) and not isinstance(merged.get("case_memory"), dict):
        merged["case_memory"] = deepcopy(state["case_memory"])
    stored_fine_notice_slots = _dict(
        _dict(state.get("fine_notice_intake")).get("slots")
    )
    if stored_fine_notice_slots:
        merged["stored_fine_notice_intake_slots"] = deepcopy(
            stored_fine_notice_slots
        )
    merged["pending_questions"] = _dict_list(state.get("pending_questions"))
    merged["conversation_history"] = _history_with_current_user_turn(state, merged)
    if "ocr_confirmation" not in merged:
        restored_confirmation = _restored_ocr_confirmation(state, merged)
        if restored_confirmation:
            merged["ocr_confirmation"] = restored_confirmation
    return merged


def build_chat_followup_snapshot(
    payload: dict[str, Any],
    chat_response: dict[str, Any],
) -> dict[str, Any]:
    """Return the small, user-safe state needed for the next follow-up request."""

    consultation_state = _dict(chat_response.get("consultation_state"))
    fact_state = _dict(consultation_state.get("fact_state"))
    case_memory = _dict(
        consultation_state.get("case_memory")
        or _dict(_dict(consultation_state.get("v2")).get("case_memory"))
    )
    fine_notice_intake = _dict(chat_response.get("fine_notice_intake"))
    history = _history(payload.get("conversation_history"))
    history = _append_user_turn(history, payload)
    history = _append_assistant_turn(history, chat_response)

    snapshot = {
        "contract_version": CHAT_SESSION_FOLLOWUP_STATE_VERSION,
        "routing_intent": _text(chat_response.get("routing_intent")),
        "facts": deepcopy(fact_state.get("facts") or _dict(payload.get("facts"))),
        "fact_sources": _dict_list(payload.get("fact_sources")),
        "fact_conflicts": deepcopy(fact_state.get("conflicts") or _dict_list(payload.get("fact_conflicts"))),
        "pending_questions": _dict_list(chat_response.get("pending_questions")),
        "case_memory": deepcopy(case_memory),
        "fine_notice_intake": {
            "contract_version": _text(fine_notice_intake.get("contract_version")),
            "slots": deepcopy(_dict(fine_notice_intake.get("slots"))),
        },
        "consultation_state": _safe_consultation_state(consultation_state),
        "conversation_history": history[-MAX_FOLLOWUP_HISTORY_TURNS:],
    }
    ocr_confirmation = _stored_ocr_confirmation(payload)
    if ocr_confirmation:
        snapshot["ocr_confirmation"] = ocr_confirmation
    return snapshot


def merge_confirmed_ocr_followup_state(
    stored_state: dict[str, Any] | None,
    payload: dict[str, Any],
    *,
    routing_intent: str = "",
) -> dict[str, Any] | None:
    """Persist a narrow OCR confirmation for the same attachment set only."""

    confirmation = _stored_ocr_confirmation(payload)
    if not confirmation:
        return None
    state = deepcopy(_valid_state(stored_state) or {})
    state["contract_version"] = CHAT_SESSION_FOLLOWUP_STATE_VERSION
    if _text(routing_intent):
        state["routing_intent"] = _text(routing_intent)
    state["ocr_confirmation"] = confirmation
    return state


def followup_routing_intent(stored_state: dict[str, Any] | None) -> str:
    """Return the route selected by authorized, persisted session state only."""

    state = _valid_state(stored_state)
    return _text(state.get("routing_intent")) if state else ""


def resolve_confirmed_report_user_facts(
    stored_state: dict[str, Any] | None,
    payload: dict[str, Any],
    *,
    current_routing_intent: str = "",
) -> str:
    """Return a server-curated report fact statement from the current turn.

    A public request cannot inject worker context directly.  The current text
    becomes trusted report input only when it answers a server-persisted
    ``user_facts`` question or contains an explicit circumstance statement.
    """

    user_text = _text(payload.get("user_text"))
    if not user_text:
        return ""
    state = _valid_state(stored_state)
    if state is not None and _is_topic_switch(
        current_routing_intent=current_routing_intent,
        stored_routing_intent=_text(state.get("routing_intent")),
    ):
        return ""
    if state is not None and any(
        _text(item.get("field")) == "user_facts"
        for item in _dict_list(state.get("pending_questions"))
    ):
        return user_text[:_MAX_REPORT_USER_FACTS_LENGTH]

    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?。])\s+|[\r\n]+", user_text)
        if part.strip()
    ]
    explicit_facts = [
        sentence
        for sentence in sentences
        if any(marker in sentence for marker in _REPORT_USER_FACT_MARKERS)
    ]
    return " ".join(explicit_facts)[:_MAX_REPORT_USER_FACTS_LENGTH]


def _is_topic_switch(
    *,
    current_routing_intent: str,
    stored_routing_intent: str,
) -> bool:
    current = _text(current_routing_intent)
    stored = _text(stored_routing_intent)
    return bool(
        current
        and current != "general_consultation"
        and stored
        and current != stored
    )


def _valid_state(stored_state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(stored_state, dict):
        return None
    if stored_state.get("contract_version") != CHAT_SESSION_FOLLOWUP_STATE_VERSION:
        return None
    return stored_state


def _history_with_current_user_turn(
    state: dict[str, Any],
    payload: dict[str, Any],
) -> list[dict[str, str]]:
    history = _history(state.get("conversation_history"))
    if not history:
        history = _pending_question_history(state.get("pending_questions"))
    return _append_user_turn(history, payload)[-MAX_FOLLOWUP_HISTORY_TURNS:]


def _pending_question_history(value: Any) -> list[dict[str, str]]:
    for item in _dict_list(value):
        question = _text(item.get("question"))
        if question:
            return [{"role": "assistant", "content": question}]
    return []


def _append_user_turn(history: list[dict[str, str]], payload: dict[str, Any]) -> list[dict[str, str]]:
    user_text = _text(payload.get("user_text"))
    if not user_text:
        return history
    if history and history[-1] == {"role": "user", "content": user_text}:
        return history
    return [*history, {"role": "user", "content": user_text}]


def _append_assistant_turn(
    history: list[dict[str, str]],
    chat_response: dict[str, Any],
) -> list[dict[str, str]]:
    if chat_response.get("status") != "needs_input":
        return history
    assistant_message = _dict(chat_response.get("assistant_message"))
    answer = _text(assistant_message.get("answer"))
    if not answer:
        return history
    return [*history, {"role": "assistant", "content": answer}]


def _merge_fact_sources(
    *,
    stored_sources: Any,
    client_sources: Any,
    server_fact_fields: set[str],
) -> list[dict[str, Any]]:
    return [
        *_dict_list(stored_sources),
        *[
            item
            for item in _dict_list(client_sources)
            if _text(item.get("field")) not in server_fact_fields
        ],
    ]


def _merge_conflicts(
    *,
    stored_conflicts: Any,
    client_conflicts: Any,
    server_fact_fields: set[str],
) -> list[dict[str, Any]]:
    return [
        *_dict_list(stored_conflicts),
        *[
            item
            for item in _dict_list(client_conflicts)
            if _text(item.get("field")) not in server_fact_fields
        ],
    ]


def _safe_consultation_state(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value[key])
        for key in ("v2", "promotion_gate", "case_memory")
        if key in value
    }


def _stored_ocr_confirmation(payload: dict[str, Any]) -> dict[str, Any]:
    raw = _dict(payload.get("ocr_confirmation"))
    raw_fields = _dict(raw.get("fields"))
    fields = {
        field: value
        for field in _OCR_CONFIRMATION_FIELDS
        if (value := _text(raw_fields.get(field)))
    }
    attachment_ids = _attachment_ids(payload.get("attachments"))
    if (
        raw.get("confirmed") is not True
        or not _OCR_CONFIRMATION_REQUIRED_FIELDS.issubset(fields)
        or not attachment_ids
    ):
        return {}
    return {
        "confirmed": True,
        "fields": fields,
        "attachment_ids": attachment_ids,
    }


def _restored_ocr_confirmation(
    state: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    stored = _dict(state.get("ocr_confirmation"))
    stored_fields = _dict(stored.get("fields"))
    fields = {
        field: value
        for field in _OCR_CONFIRMATION_FIELDS
        if (value := _text(stored_fields.get(field)))
    }
    if (
        stored.get("confirmed") is not True
        or not _OCR_CONFIRMATION_REQUIRED_FIELDS.issubset(fields)
        or _attachment_ids(payload.get("attachments"))
        != sorted(
            {
                attachment_id
                for value in stored.get("attachment_ids") or []
                if (attachment_id := _text(value))
            }
        )
    ):
        return {}
    return {"confirmed": True, "fields": fields}


def _attachment_ids(value: Any) -> list[str]:
    return sorted(
        {
            attachment_id
            for item in value or []
            if isinstance(item, dict)
            if (attachment_id := _text(item.get("attachment_id")))
        }
    )


def _history(value: Any) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for item in _dict_list(value):
        role = _text(item.get("role")).lower()
        content = _text(item.get("content"))
        if role in {"assistant", "user"} and content:
            history.append({"role": role, "content": content})
    return history[-MAX_FOLLOWUP_HISTORY_TURNS:]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [deepcopy(item) for item in value or [] if isinstance(item, dict)]


def _text(value: Any) -> str:
    return str(value or "").strip()
