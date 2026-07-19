"""Versioned service-scope policy evaluation before Supervisor planning."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.consultation_v2_service import is_high_risk_consultation

POLICY_CONTRACT_VERSION = "service_scope_policy.v1"
DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "service_scope_policy.v1.json"
)


@lru_cache(maxsize=1)
def _service_scope_policy() -> dict[str, Any]:
    configured_path = os.environ.get("SERVICE_SCOPE_POLICY_PATH", "").strip()
    path = Path(configured_path).expanduser() if configured_path else DEFAULT_POLICY_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))
    _validate_policy(raw)
    return raw


def evaluate_service_scope(
    *,
    user_text: str,
    attachments: list[dict[str, Any]],
    routing_intent: str,
) -> dict[str, Any]:
    """Return the declared service boundary without planning any agent work."""

    del attachments
    policy = _service_scope_policy()
    normalized_text = _normalized(user_text)
    if (
        _text(routing_intent) == "accident_initial_consultation"
        and is_high_risk_consultation(user_text)
    ):
        return {
            **_scope_result(policy["supported_intents"]["accident_initial_consultation"]),
            "decision": "proceed",
        }
    for excluded_case in policy["excluded_cases"]:
        if any(_normalized(keyword) in normalized_text for keyword in excluded_case["keywords"]):
            return _scope_result(excluded_case)

    supported = policy["supported_intents"].get(_text(routing_intent))
    if isinstance(supported, dict):
        return {
            **_scope_result(supported),
            "decision": "proceed",
        }
    return _scope_result(policy["unclassified_intent"])


def _validate_policy(policy: Any) -> None:
    if not isinstance(policy, dict):
        raise ValueError("service_scope_policy_must_be_an_object")
    if policy.get("contract_version") != POLICY_CONTRACT_VERSION:
        raise ValueError("unsupported_service_scope_policy_version")
    if not isinstance(policy.get("supported_intents"), dict):
        raise ValueError("service_scope_policy_requires_supported_intents")
    excluded_cases = policy.get("excluded_cases")
    if not isinstance(excluded_cases, list):
        raise ValueError("service_scope_policy_requires_excluded_cases")
    for entry in [*policy["supported_intents"].values(), *excluded_cases, policy.get("unclassified_intent")]:
        if not isinstance(entry, dict):
            raise ValueError("service_scope_policy_contains_invalid_entry")
        if not _text(entry.get("scope_code")) or not _text(entry.get("reason")):
            raise ValueError("service_scope_policy_requires_scope_and_reason")
        if not _string_list(entry.get("limitations")) or not _string_list(entry.get("next_actions")):
            raise ValueError("service_scope_policy_requires_safe_guidance")
    for entry in excluded_cases:
        if entry.get("decision") not in {"guidance_only", "expert_handoff"}:
            raise ValueError("service_scope_policy_contains_invalid_exclusion_decision")
        if not _string_list(entry.get("keywords")):
            raise ValueError("service_scope_policy_exclusion_requires_keywords")
    unclassified = policy.get("unclassified_intent")
    if not isinstance(unclassified, dict) or unclassified.get("decision") != "proceed":
        raise ValueError("service_scope_policy_requires_unclassified_intent_flow")


def _scope_result(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": POLICY_CONTRACT_VERSION,
        "decision": _text(entry.get("decision")) or "proceed",
        "scope_code": _text(entry.get("scope_code")),
        "reason": _text(entry.get("reason")),
        "limitations": _string_list(entry.get("limitations")),
        "next_actions": _string_list(entry.get("next_actions")),
    }


def _normalized(value: Any) -> str:
    return "".join(_text(value).lower().split())


def _string_list(value: Any) -> list[str]:
    return [_text(item) for item in value or [] if _text(item)]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""
