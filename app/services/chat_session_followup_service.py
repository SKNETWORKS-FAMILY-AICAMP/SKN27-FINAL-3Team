"""Server-authoritative follow-up state helpers for canonical chat sessions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


CHAT_SESSION_FOLLOWUP_STATE_VERSION = "chat_session_followup_state.v1"
MAX_FOLLOWUP_HISTORY_TURNS = 16


def merge_chat_followup_payload(
    payload: dict[str, Any],
    stored_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge a safe request with the authoritative state stored for its session."""

    merged = deepcopy(payload)
    state = _valid_state(stored_state)
    if state is None:
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
    merged["conversation_history"] = _history_with_current_user_turn(state, merged)
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

    return {
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


def followup_routing_intent(stored_state: dict[str, Any] | None) -> str:
    """Return the route selected by authorized, persisted session state only."""

    state = _valid_state(stored_state)
    return _text(state.get("routing_intent")) if state else ""


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
