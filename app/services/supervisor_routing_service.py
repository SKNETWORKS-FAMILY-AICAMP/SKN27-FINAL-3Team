"""Versioned routing and plan policy loader for the canonical Supervisor."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.supervisor_input_projection_service import (
    normalization_routing_hints,
)


POLICY_CONTRACT_VERSION = "supervisor_routing_policy.v1"
DOCUMENT_CLASSIFICATION_TYPES = frozenset({"image", "pdf"})
SPECIALIZED_DOCUMENT_PURPOSES = frozenset({"traffic_accident_confirmation"})
DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "supervisor_routing_policy.v1.json"
)


@lru_cache(maxsize=1)
def _routing_policy() -> dict[str, Any]:
    configured_path = os.environ.get("SUPERVISOR_ROUTING_POLICY_PATH", "").strip()
    path = Path(configured_path).expanduser() if configured_path else DEFAULT_POLICY_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))
    _validate_policy(raw)
    return {**raw, "_source": str(path.resolve())}


def _validate_policy(policy: Any) -> None:
    if not isinstance(policy, dict):
        raise ValueError("supervisor_routing_policy_must_be_an_object")
    if policy.get("contract_version") != POLICY_CONTRACT_VERSION:
        raise ValueError("unsupported_supervisor_routing_policy_version")
    rules = policy.get("intent_rules")
    plans = policy.get("plans")
    report_policy = policy.get("report_policy")
    validation_policy = policy.get("agent_result_validation_policy")
    if not isinstance(rules, list) or not rules:
        raise ValueError("supervisor_routing_policy_requires_intent_rules")
    if not isinstance(plans, dict) or not plans:
        raise ValueError("supervisor_routing_policy_requires_plans")
    if not isinstance(report_policy, dict):
        raise ValueError("supervisor_routing_policy_requires_report_policy")
    if not isinstance(validation_policy, dict):
        raise ValueError("supervisor_routing_policy_requires_agent_result_validation_policy")
    if not _string_list(validation_policy.get("evidence_required_node_codes")):
        raise ValueError("supervisor_routing_policy_requires_evidence_rules")
    if not _string_list(validation_policy.get("partial_result_intents")):
        raise ValueError("supervisor_routing_policy_requires_partial_result_intents")
    if not isinstance(validation_policy.get("report_required_nodes"), dict):
        raise ValueError("supervisor_routing_policy_requires_report_readiness_rules")
    if not _text(policy.get("default_intent")):
        raise ValueError("supervisor_routing_policy_requires_default_intent")
    for intent, node_codes in plans.items():
        if not _text(intent) or not _string_list(node_codes):
            raise ValueError("supervisor_routing_policy_contains_invalid_plan")
        if node_codes[0] != "input_context_validation" or node_codes[-1] != "final_response_merge":
            raise ValueError("supervisor_routing_plan_requires_boundary_nodes")
        if "agent_result_validation" not in node_codes:
            raise ValueError("supervisor_routing_plan_requires_result_validation")


def _plans_from_policy() -> dict[str, tuple[str, ...]]:
    return {
        _text(intent): tuple(_string_list(node_codes))
        for intent, node_codes in _routing_policy()["plans"].items()
    }


def route_supervisor_input(
    user_text: str,
    attachments: list[dict[str, Any]],
    *,
    normalized_input: dict[str, Any] | None = None,
) -> str:
    """Classify input with attachment rules taking precedence over text rules."""

    policy = _routing_policy()
    if requires_attachment_document_classification(attachments):
        return "attachment_document_classification"
    attachment_purposes = {
        _text(item.get("purpose")).lower()
        for item in attachments
        if isinstance(item, dict) and _text(item.get("purpose"))
    }
    normalized_text = _text(user_text).lower()
    for raw_rule in policy["intent_rules"]:
        if not isinstance(raw_rule, dict):
            continue
        intent = _text(raw_rule.get("intent"))
        purposes = {item.lower() for item in _string_list(raw_rule.get("attachment_purposes"))}
        keywords = [item.lower() for item in _string_list(raw_rule.get("keywords"))]
        if purposes and attachment_purposes.intersection(purposes):
            return intent
        if keywords and any(keyword in normalized_text for keyword in keywords):
            return _promote_fine_notice_report_intent(intent, user_text)
    normalized_hints = normalization_routing_hints(normalized_input or {})
    if normalized_hints:
        return normalized_hints[0]
    return _text(policy["default_intent"])


def requires_attachment_document_classification(attachments: list[dict[str, Any]]) -> bool:
    """Require a server-proven clean image/PDF before document classification."""

    return any(
        isinstance(item, dict)
        and _text(item.get("metadata_source")) == "canonical_scan_gate"
        and _text(item.get("resolution_status")) == "scan_ready"
        and _text(item.get("status")) == "ready"
        and _text(item.get("scan_status")) == "clean"
        and _text(item.get("type")).lower() in DOCUMENT_CLASSIFICATION_TYPES
        and _text(item.get("purpose")).lower() not in SPECIALIZED_DOCUMENT_PURPOSES
        for item in attachments
    )


def report_generation_requested(user_text: str) -> bool:
    normalized = _text(user_text).lower()
    report_policy = _routing_policy()["report_policy"]
    document_terms = [item.lower() for item in _string_list(report_policy.get("document_terms"))]
    action_terms = [item.lower() for item in _string_list(report_policy.get("action_terms"))]
    return (
        any(term in normalized for term in document_terms)
        and any(term in normalized for term in action_terms)
    )


def _promote_fine_notice_report_intent(intent: str, user_text: str) -> str:
    """Send a text-only draft request through verified fine-notice intake first.

    The promotion does not authorize report generation by itself.  The
    orchestration layer still requires confirmed OCR fields before it can add
    the law, appeal, and report nodes to the executable plan.
    """

    report_policy = _routing_policy()["report_policy"]
    if (
        intent == "fine_notice_procedure"
        and report_generation_requested(user_text)
    ):
        return _text(report_policy.get("supported_intent")) or intent
    return intent


def plan_node_codes(routing_intent: str, *, report_requested: bool) -> tuple[str, ...]:
    policy = _routing_policy()
    default_intent = _text(policy["default_intent"])
    base = BASE_NODE_PLANS.get(routing_intent, BASE_NODE_PLANS[default_intent])
    report_policy = policy["report_policy"]
    if (
        routing_intent != _text(report_policy.get("supported_intent"))
        or not report_requested
    ):
        return base
    report_node = _text(report_policy.get("node_code"))
    # The canonical Worker persists every analysis result before dispatching
    # Reporting as its own paid phase.  Keep that step last so the queue plan
    # can be partitioned without dropping a trailing executable node.
    return (*base, report_node)


def routing_policy_metadata() -> dict[str, str]:
    policy = _routing_policy()
    return {
        "contract_version": _text(policy.get("contract_version")),
        "source": _text(policy.get("_source")),
    }


def agent_result_validation_policy() -> dict[str, Any]:
    policy = _routing_policy()["agent_result_validation_policy"]
    return {
        "evidence_required_node_codes": set(
            _string_list(policy.get("evidence_required_node_codes"))
        ),
        "report_required_nodes": {
            _text(intent): set(_string_list(node_codes))
            for intent, node_codes in policy["report_required_nodes"].items()
        },
        "partial_result_intents": set(
            _string_list(policy.get("partial_result_intents"))
        ),
    }


def _string_list(value: Any) -> list[str]:
    return [_text(item) for item in value or [] if _text(item)]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


BASE_NODE_PLANS = _plans_from_policy()
PUBLIC_AGENT_NODE_CODES = set(
    _string_list(_routing_policy().get("public_agent_node_codes"))
)
