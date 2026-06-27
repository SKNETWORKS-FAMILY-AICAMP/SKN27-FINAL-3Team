"""Shared contract for replacing mock node execution with real Agent adapters."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable


AgentAdapterInput = dict[str, Any]
AgentAdapterContext = dict[str, Any]
AgentAdapterOutput = dict[str, Any]
AgentAdapter = Callable[[AgentAdapterInput, AgentAdapterContext], AgentAdapterOutput]

AGENT_RESULT_STATUSES = ("success", "partial", "failed")

REQUIRED_AGENT_INPUT_FIELDS = (
    "analysis_plan_id",
    "job_id",
    "session_id",
    "message_id",
    "node_code",
    "user_text",
    "attachments",
    "context",
    "required_inputs",
    "depends_on",
    "upstream_results",
)

REQUIRED_ADAPTER_CONTEXT_FIELDS = (
    "execution_id",
    "execution_mode",
    "node",
    "plan_step",
)

REQUIRED_AGENT_OUTPUT_FIELDS = (
    "session_id",
    "message_id",
    "job_id",
    "node_name",
    "node_code",
    "node_type",
    "owner",
    "status",
    "summary",
    "structured_result",
    "evidence",
    "next_actions",
    "limitations",
    "created_at",
)


def build_agent_adapter_contract(node: dict[str, Any]) -> dict[str, Any]:
    """Return the public callable contract for a registry node."""

    node_code = str(node.get("node_code") or "unknown_node")
    return {
        "adapter_key": node_code,
        "function_name": f"run_{node_code}",
        "call_signature": (
            f"run_{node_code}("
            "agent_input: AgentAdapterInput, "
            "context: AgentAdapterContext"
            ") -> AgentAdapterOutput"
        ),
        "input_model": "AgentAdapterInput",
        "context_model": "AgentAdapterContext",
        "output_model": "AgentAdapterOutput",
        "required_input_fields": list(REQUIRED_AGENT_INPUT_FIELDS),
        "required_context_fields": list(REQUIRED_ADAPTER_CONTEXT_FIELDS),
        "required_output_fields": list(REQUIRED_AGENT_OUTPUT_FIELDS),
        "allowed_statuses": list(AGENT_RESULT_STATUSES),
        "owner": node.get("owner"),
        "node_type": node.get("node_type"),
    }


def build_adapter_context(
    *,
    execution_id: str,
    execution_mode: str,
    node: dict[str, Any],
    plan_step: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the context object passed beside AgentAdapterInput."""

    return {
        "execution_id": execution_id,
        "execution_mode": execution_mode,
        "node": deepcopy(node),
        "plan_step": deepcopy(plan_step or {}),
    }


def validate_agent_output_envelope(
    output: dict[str, Any],
    *,
    expected_node_code: str | None = None,
) -> dict[str, Any]:
    """Validate the minimum envelope fields every Agent adapter must return."""

    missing_fields = [
        field for field in REQUIRED_AGENT_OUTPUT_FIELDS if field not in output
    ]
    invalid_status = output.get("status") not in AGENT_RESULT_STATUSES
    node_code_mismatch = (
        expected_node_code is not None
        and output.get("node_code") != expected_node_code
    )

    return {
        "valid": not missing_fields and not invalid_status and not node_code_mismatch,
        "missing_fields": missing_fields,
        "invalid_status": invalid_status,
        "node_code_mismatch": node_code_mismatch,
        "allowed_statuses": list(AGENT_RESULT_STATUSES),
        "required_output_fields": list(REQUIRED_AGENT_OUTPUT_FIELDS),
    }
