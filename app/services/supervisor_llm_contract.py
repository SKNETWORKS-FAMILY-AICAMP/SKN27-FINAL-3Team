"""Server-owned contracts for Supervisor LLM structured output."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services.agent_node_service import NODE_REGISTRY


AGENT_INPUT_SCHEMA_VERSION = "agent_input_schema.v1"
AGENT_PACKAGE_STATUSES = {"ready", "waiting_for_fields"}
SERVER_OWNED_PAYLOAD_FIELDS = {"slot_state"}


def conversation_response_format(
    fallback_state: dict[str, Any],
) -> dict[str, Any]:
    """Build the strict model-owned conversation response schema."""

    package_schemas = _package_schemas(
        fallback_state.get("agent_input_packages")
    )
    package_count = len(package_schemas)
    properties = {
        "conversation_summary": {"type": "string"},
        "collected_facts": {
            "type": "array",
            "items": _object_schema(
                {
                    "field": {"type": "string"},
                    "value": {"type": "string"},
                }
            ),
        },
        "fact_conflicts": {
            "type": "array",
            "items": _object_schema(
                {
                    "field": {
                        "type": "string",
                        "enum": [
                            "road_layout",
                            "vehicle_actions",
                            "signal_priority",
                            "collision_location",
                        ],
                    },
                    "candidates": {
                        "type": "array",
                        "minItems": 2,
                        "items": _object_schema(
                            {
                                "value": {"type": "string"},
                                "source_message_id": {"type": "string"},
                                "confidence": {
                                    "type": "number",
                                    "minimum": 0.0,
                                    "maximum": 1.0,
                                },
                            }
                        ),
                    },
                }
            ),
        },
        "missing_fields": {
            "type": "array",
            "items": _object_schema(
                {
                    "field": {"type": "string"},
                    "reason": {"type": "string"},
                }
            ),
        },
        "next_questions": {
            "type": "array",
            "items": _object_schema(
                {
                    "field": {"type": "string"},
                    "question": {"type": "string"},
                }
            ),
        },
        "agent_input_packages": {
            "type": "array",
            "items": _combined_item_schema(package_schemas),
            "minItems": package_count,
            "maxItems": package_count,
        },
    }
    return _response_format(
        "supervisor_conversation_response_v2",
        _object_schema(properties),
    )


def analysis_plan_response_format(
    fallback_plan: dict[str, Any],
) -> dict[str, Any]:
    """Build the strict model-owned analysis-plan response schema."""

    package_schemas = _package_schemas(
        fallback_plan.get("agent_input_packages")
    )
    step_codes = [
        str(step.get("node_code") or "").strip()
        for step in fallback_plan.get("steps") or []
        if isinstance(step, dict) and str(step.get("node_code") or "").strip()
    ]
    step_schema = _object_schema(
        {
            "node_code": {"type": "string", "enum": step_codes},
            "status": {
                "type": "string",
                "enum": [
                    "ready",
                    "success",
                    "partial",
                    "running",
                    "blocked",
                    "failed",
                    "skipped",
                ],
            },
            "required_inputs": {
                "type": "array",
                "items": {"type": "string"},
            },
            "depends_on": {
                "type": "array",
                "items": {"type": "string", "enum": step_codes},
            },
            "fallback": {"type": "string"},
        }
    )
    routing_intent = str(fallback_plan.get("routing_intent") or "").strip()
    properties = {
        "routing_intent": {
            "type": "string",
            "enum": [routing_intent] if routing_intent else [""],
        },
        "input_summary": _schema_from_value(
            fallback_plan.get("input_summary", {})
        ),
        "required_inputs": {
            "type": "array",
            "items": {"type": "string"},
        },
        "pending_questions": {
            "type": "array",
            "items": _object_schema(
                {
                    "field": {"type": "string"},
                    "question": {"type": "string"},
                }
            ),
        },
        "agent_input_packages": {
            "type": "array",
            "items": _combined_item_schema(package_schemas),
            "minItems": 0,
            "maxItems": len(package_schemas),
        },
        "steps": {
            "type": "array",
            "items": step_schema,
            "minItems": 1 if step_codes else 0,
            "maxItems": len(step_codes),
        },
        "blocked_reason": {"type": ["string", "null"]},
    }
    return _response_format(
        "supervisor_analysis_plan_response_v2",
        _object_schema(properties),
    )


def enrich_supervisor_state(
    fallback_state: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Inject canonical registry controls into a server fallback state."""

    state = deepcopy(fallback_state)
    packages = state.get("agent_input_packages")
    if not isinstance(packages, list):
        return None, "invalid_agent_packages"

    enriched: list[dict[str, Any]] = []
    for raw_package in packages:
        package, error = enrich_agent_package(raw_package)
        if error:
            return None, error
        if package is None:
            return None, "invalid_agent_package"
        enriched.append(package)

    state["agent_input_packages"] = enriched
    return state, None


def enrich_agent_package(
    raw_package: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """Rebuild one package with Registry-owned identity and readiness fields."""

    if not isinstance(raw_package, dict):
        return None, "invalid_agent_package"

    node_code = str(raw_package.get("node_code") or "").strip()
    registry_node = NODE_REGISTRY.get(node_code)
    if not registry_node or not str(registry_node.get("owner") or "").strip():
        return None, "registry_node_missing"
    if not isinstance(raw_package.get("payload"), dict):
        return None, "invalid_agent_payload"

    package = deepcopy(raw_package)
    package["schema_version"] = AGENT_INPUT_SCHEMA_VERSION
    package["node_code"] = node_code
    package["owner"] = str(registry_node["owner"]).strip()
    package["required_inputs"] = [
        str(item).strip()
        for item in registry_node.get("required_inputs") or []
        if str(item).strip()
    ]
    package["missing_fields"] = _string_list(package.get("missing_fields"))
    package["status"] = (
        "waiting_for_fields" if package["missing_fields"] else "ready"
    )
    if "attachments" in package:
        package["attachments"] = _attachment_selectors(package["attachments"])
    return package, None


def normalize_candidate_packages(
    candidate_packages: Any,
    fallback_packages: Any,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Merge model payload values into the exact server-selected package set."""

    if not isinstance(candidate_packages, list) or not isinstance(
        fallback_packages, list
    ):
        return None, "invalid_agent_packages"
    if not all(isinstance(item, dict) for item in candidate_packages):
        return None, "invalid_agent_package"

    fallback_by_node: dict[str, dict[str, Any]] = {}
    for raw_fallback in fallback_packages:
        enriched, error = enrich_agent_package(raw_fallback)
        if error:
            return None, error
        if enriched is None:
            return None, "invalid_agent_package"
        node_code = enriched["node_code"]
        if node_code in fallback_by_node:
            return None, "duplicate_agent_node"
        fallback_by_node[node_code] = enriched

    candidate_by_node: dict[str, dict[str, Any]] = {}
    for candidate in candidate_packages:
        node_code = str(candidate.get("node_code") or "").strip()
        if not node_code or node_code in candidate_by_node:
            return None, "duplicate_agent_node"
        candidate_by_node[node_code] = candidate

    if set(candidate_by_node) != set(fallback_by_node):
        return None, "unexpected_node_set"

    normalized: list[dict[str, Any]] = []
    for node_code, fallback in fallback_by_node.items():
        candidate = candidate_by_node[node_code]
        candidate_payload = candidate.get("payload")
        if not isinstance(candidate_payload, dict):
            return None, "invalid_agent_payload"
        package = deepcopy(fallback)
        package["payload"] = _bounded_payload(
            candidate_payload,
            fallback.get("payload"),
        )
        enriched, error = enrich_agent_package(package)
        if error:
            return None, error
        if enriched is None:
            return None, "invalid_agent_package"
        normalized.append(enriched)
    return normalized, None


def _bounded_payload(candidate: Any, fallback: Any) -> dict[str, Any]:
    fallback_payload = fallback if isinstance(fallback, dict) else {}
    candidate_payload = candidate if isinstance(candidate, dict) else {}
    bounded: dict[str, Any] = {}
    for key, fallback_value in fallback_payload.items():
        if key in SERVER_OWNED_PAYLOAD_FIELDS:
            bounded[key] = deepcopy(fallback_value)
            continue
        candidate_value = candidate_payload.get(key, fallback_value)
        if key == "attachments":
            bounded[key] = _approved_attachment_selectors(
                candidate_value,
                fallback_value,
            )
        else:
            bounded[key] = _bounded_value(candidate_value, fallback_value)
    return bounded


def _response_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": schema,
        },
    }


def _object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _package_schemas(value: Any) -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = []
    for package in value if isinstance(value, list) else []:
        if not isinstance(package, dict):
            continue
        node_code = str(package.get("node_code") or "").strip()
        if not node_code:
            continue
        schemas.append(
            _object_schema(
                {
                    "node_code": {
                        "type": "string",
                        "enum": [node_code],
                    },
                    "payload": _schema_from_value(
                        {
                            key: value
                            for key, value in (
                                package.get("payload", {})
                                if isinstance(package.get("payload"), dict)
                                else {}
                            ).items()
                            if key not in SERVER_OWNED_PAYLOAD_FIELDS
                        }
                    ),
                }
            )
        )
    return schemas


def _combined_item_schema(schemas: list[dict[str, Any]]) -> dict[str, Any]:
    if not schemas:
        return _object_schema({})
    if len(schemas) == 1:
        return schemas[0]
    return {"anyOf": schemas}


def _schema_from_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return _object_schema(
            {
                str(key): _schema_from_value(item)
                for key, item in value.items()
                if isinstance(key, str)
            }
        )
    if isinstance(value, list):
        if not value:
            return {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 0,
            }
        return {
            "type": "array",
            "items": _schema_from_value(value[0]),
        }
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if value is None:
        return {
            "anyOf": [
                {"type": "string"},
                {"type": "number"},
                {"type": "boolean"},
                {"type": "null"},
            ]
        }
    return {"type": "string"}


def _bounded_value(candidate: Any, fallback: Any) -> Any:
    if isinstance(fallback, dict):
        return _bounded_payload(candidate, fallback)
    if isinstance(fallback, list):
        if not isinstance(candidate, list) or not fallback:
            return deepcopy(fallback)
        template = fallback[0]
        return [_bounded_value(item, template) for item in candidate]
    if fallback is None:
        if isinstance(candidate, (str, int, float, bool)) or candidate is None:
            return deepcopy(candidate)
        return None
    if isinstance(candidate, type(fallback)):
        return deepcopy(candidate)
    return deepcopy(fallback)


def _approved_attachment_selectors(candidate: Any, fallback: Any) -> list[dict[str, str]]:
    approved = _attachment_selectors(fallback)
    approved_ids = {item["attachment_id"] for item in approved}
    selected = [
        item
        for item in _attachment_selectors(candidate)
        if item["attachment_id"] in approved_ids
    ]
    return selected or approved


def _attachment_selectors(value: Any) -> list[dict[str, str]]:
    selectors: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        attachment_id = str(item.get("attachment_id") or "").strip()
        if not attachment_id or attachment_id in seen:
            continue
        seen.add(attachment_id)
        selectors.append({"attachment_id": attachment_id})
    return selectors


def _string_list(value: Any) -> list[str]:
    return [
        str(item).strip()
        for item in value if str(item).strip()
    ] if isinstance(value, list) else []
