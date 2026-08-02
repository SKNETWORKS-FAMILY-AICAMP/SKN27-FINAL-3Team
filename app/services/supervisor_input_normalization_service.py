"""Versioned deterministic input-normalization policy for the Supervisor."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


POLICY_CONTRACT_VERSION = "supervisor_input_normalization_policy.v1"
DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "supervisor_input_normalization_policy.v1.json"
)
EXPECTED_DOMAINS = frozenset({"accident", "fine_notice", "objection"})
ALLOWED_TOKEN_CLASSES = frozenset(
    {"entity", "action", "state", "modifier", "negation", "uncertainty", "particle"}
)


@lru_cache(maxsize=1)
def normalization_policy() -> dict[str, Any]:
    """Load and validate the server-owned normalization policy."""

    configured = os.environ.get("SUPERVISOR_INPUT_NORMALIZATION_POLICY_PATH", "").strip()
    path = Path(configured).expanduser() if configured else DEFAULT_POLICY_PATH
    policy = json.loads(path.read_text(encoding="utf-8"))
    _validate_policy(policy)
    return {**policy, "_source": str(path)}


def clear_normalization_policy_cache() -> None:
    normalization_policy.cache_clear()


def normalization_policy_metadata() -> dict[str, str]:
    policy = normalization_policy()
    return {
        "contract_version": str(policy["contract_version"]),
        "source": str(policy["_source"]),
    }


def _validate_policy(policy: Any) -> None:
    if not isinstance(policy, dict):
        raise ValueError("normalization_policy_must_be_an_object")
    if policy.get("contract_version") != POLICY_CONTRACT_VERSION:
        raise ValueError("unsupported_normalization_policy_version")

    domains = policy.get("domains")
    if not isinstance(domains, dict) or set(domains) != EXPECTED_DOMAINS:
        raise ValueError("normalization_policy_requires_supported_domains")
    allowed_fields: dict[tuple[str, str], set[str]] = {}
    for domain, domain_policy in domains.items():
        schemas = domain_policy.get("schemas") if isinstance(domain_policy, dict) else None
        if not isinstance(schemas, dict) or not schemas:
            raise ValueError("normalization_policy_requires_domain_schemas")
        for schema, fields in schemas.items():
            normalized_fields = _string_set(fields)
            if not str(schema).strip() or not normalized_fields:
                raise ValueError("normalization_policy_requires_schema_fields")
            allowed_fields[(domain, str(schema).strip())] = normalized_fields

    decisions = _string_set(policy.get("decisions"))
    if decisions != {
        "auto_applied",
        "confirmation_required",
        "clarification_required",
    }:
        raise ValueError("normalization_policy_requires_supported_decisions")

    token_classes = policy.get("token_classes")
    if not isinstance(token_classes, dict):
        raise ValueError("normalization_policy_requires_token_classes")
    for field in ("negation", "uncertainty", "particles"):
        if not _string_set(token_classes.get(field)):
            raise ValueError("normalization_policy_requires_token_classes")

    threshold = policy.get("fuzzy_confirmation_threshold")
    if not isinstance(threshold, (int, float)) or not 0 < float(threshold) <= 1:
        raise ValueError("normalization_policy_requires_fuzzy_threshold")

    rules = policy.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("normalization_policy_requires_rules")
    seen_rule_ids: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("normalization_policy_contains_invalid_rule")
        rule_id = str(rule.get("rule_id") or "").strip()
        if not rule_id:
            raise ValueError("normalization_policy_requires_rule_id")
        if rule_id in seen_rule_ids:
            raise ValueError("duplicate_normalization_rule_id")
        seen_rule_ids.add(rule_id)

        domain = str(rule.get("domain") or "").strip()
        schema = str(rule.get("schema") or "").strip()
        if (domain, schema) not in allowed_fields:
            raise ValueError("normalization_policy_contains_unknown_schema")
        if str(rule.get("field") or "").strip() not in allowed_fields[(domain, schema)]:
            raise ValueError("normalization_policy_contains_unknown_field")
        if str(rule.get("decision") or "").strip() not in decisions:
            raise ValueError("normalization_policy_contains_invalid_decision")
        if str(rule.get("token_class") or "").strip() not in ALLOWED_TOKEN_CLASSES:
            raise ValueError("normalization_policy_contains_invalid_token_class")
        if not str(rule.get("value") or "").strip():
            raise ValueError("normalization_policy_requires_rule_value")
        if not str(rule.get("canonical_expression") or "").strip():
            raise ValueError("normalization_policy_requires_canonical_expression")
        variants = [
            *_string_set(rule.get("expressions")),
            *_string_set(rule.get("aliases")),
            *_string_set(rule.get("approved_typos")),
        ]
        if not variants:
            raise ValueError("normalization_policy_requires_rule_expressions")


def _string_set(value: Any) -> set[str]:
    return {
        str(item).strip()
        for item in value or []
        if str(item).strip()
    }
