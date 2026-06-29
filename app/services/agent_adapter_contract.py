"""Shared contract for replacing mock node execution with real Agent adapters."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, TypedDict


class AgentAdapterInput(TypedDict, total=False):
    analysis_plan_id: str | None
    job_id: str | None
    session_id: str | None
    message_id: str | None
    node_code: str
    user_text: str | None
    attachments: list[dict[str, Any]]
    context: dict[str, Any]
    required_inputs: list[str]
    depends_on: list[str]
    upstream_results: dict[str, dict[str, Any]]


class AgentAdapterContext(TypedDict, total=False):
    signature_version: str
    execution_id: str
    execution_mode: str
    node: dict[str, Any]
    plan_step: dict[str, Any]


class AgentAdapterOutput(TypedDict, total=False):
    session_id: str | None
    message_id: str | None
    job_id: str | None
    node_name: str
    node_code: str
    node_type: str
    owner: str
    status: str
    summary: str
    structured_result: dict[str, Any]
    evidence: list[dict[str, Any]]
    next_actions: list[str]
    limitations: list[str]
    created_at: str


AgentAdapter = Callable[[AgentAdapterInput, AgentAdapterContext], AgentAdapterOutput]

ADAPTER_CONTRACT_VERSION = "agent_adapter.v1"
ADAPTER_CALL_STYLE = "sync_callable"
ADAPTER_EXECUTION_MODES = ("mock", "sync", "async_worker")
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
    "signature_version",
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

REQUIRED_AGENT_OUTPUT_COLLECTION_FIELDS: dict[str, type] = {
    "structured_result": dict,
    "evidence": list,
    "next_actions": list,
    "limitations": list,
}


def build_agent_adapter_contract(node: dict[str, Any]) -> dict[str, Any]:
    """Return the public callable contract for a registry node."""

    node_code = str(node.get("node_code") or "unknown_node")
    return {
        "signature_version": ADAPTER_CONTRACT_VERSION,
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
        "call_style": ADAPTER_CALL_STYLE,
        "execution_modes": list(ADAPTER_EXECUTION_MODES),
        "idempotency_scope": "job_id:node_code:analysis_plan_id",
        "timeout_seconds": 30,
        "retry_policy": {
            "max_attempts": 1,
            "retryable_statuses": ["partial"],
        },
        "side_effect_policy": "Adapters return envelopes only; persistence is owned by the orchestrator.",
        "owner": node.get("owner"),
        "node_type": node.get("node_type"),
    }


def build_agent_adapter_input(
    *,
    analysis_plan_id: str | None = None,
    job_id: str | None = None,
    session_id: str | None = None,
    message_id: str | None = None,
    node: dict[str, Any],
    user_text: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
    required_inputs: list[str] | None = None,
    depends_on: list[str] | None = None,
    upstream_results: dict[str, dict[str, Any]] | None = None,
) -> AgentAdapterInput:
    """Build the input envelope passed to a real or mock Agent adapter."""

    return {
        "analysis_plan_id": analysis_plan_id,
        "job_id": job_id,
        "session_id": session_id,
        "message_id": message_id,
        "node_code": str(node.get("node_code") or "unknown_node"),
        "user_text": user_text,
        "attachments": deepcopy(attachments or []),
        "context": deepcopy(context or {}),
        "required_inputs": deepcopy(required_inputs or node.get("required_inputs") or []),
        "depends_on": deepcopy(depends_on or []),
        "upstream_results": deepcopy(upstream_results or {}),
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
        "signature_version": ADAPTER_CONTRACT_VERSION,
        "execution_id": execution_id,
        "execution_mode": execution_mode,
        "node": deepcopy(node),
        "plan_step": deepcopy(plan_step or {}),
    }


def validate_agent_input_envelope(
    agent_input: dict[str, Any],
    *,
    expected_node_code: str | None = None,
) -> dict[str, Any]:
    """Validate the minimum input envelope every Agent adapter receives."""

    missing_fields = [
        field for field in REQUIRED_AGENT_INPUT_FIELDS if field not in agent_input
    ]
    node_code_mismatch = (
        expected_node_code is not None
        and agent_input.get("node_code") != expected_node_code
    )
    invalid_collection_fields = _invalid_collection_fields(
        agent_input,
        {
            "attachments": list,
            "context": dict,
            "required_inputs": list,
            "depends_on": list,
            "upstream_results": dict,
        },
    )

    return {
        "valid": not missing_fields and not node_code_mismatch and not invalid_collection_fields,
        "missing_fields": missing_fields,
        "node_code_mismatch": node_code_mismatch,
        "invalid_collection_fields": invalid_collection_fields,
        "required_input_fields": list(REQUIRED_AGENT_INPUT_FIELDS),
    }


def validate_adapter_context_envelope(
    context: dict[str, Any],
    *,
    expected_execution_mode: str | None = None,
) -> dict[str, Any]:
    """Validate the runtime context passed beside AgentAdapterInput."""

    missing_fields = [
        field for field in REQUIRED_ADAPTER_CONTEXT_FIELDS if field not in context
    ]
    invalid_signature_version = (
        context.get("signature_version") != ADAPTER_CONTRACT_VERSION
    )
    invalid_execution_mode = context.get("execution_mode") not in ADAPTER_EXECUTION_MODES
    execution_mode_mismatch = (
        expected_execution_mode is not None
        and context.get("execution_mode") != expected_execution_mode
    )

    return {
        "valid": (
            not missing_fields
            and not invalid_signature_version
            and not invalid_execution_mode
            and not execution_mode_mismatch
        ),
        "missing_fields": missing_fields,
        "invalid_signature_version": invalid_signature_version,
        "invalid_execution_mode": invalid_execution_mode,
        "execution_mode_mismatch": execution_mode_mismatch,
        "signature_version": ADAPTER_CONTRACT_VERSION,
        "allowed_execution_modes": list(ADAPTER_EXECUTION_MODES),
        "required_context_fields": list(REQUIRED_ADAPTER_CONTEXT_FIELDS),
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
    invalid_collection_fields = _invalid_collection_fields(
        output,
        REQUIRED_AGENT_OUTPUT_COLLECTION_FIELDS,
    )

    return {
        "valid": (
            not missing_fields
            and not invalid_status
            and not node_code_mismatch
            and not invalid_collection_fields
        ),
        "missing_fields": missing_fields,
        "invalid_status": invalid_status,
        "node_code_mismatch": node_code_mismatch,
        "invalid_collection_fields": invalid_collection_fields,
        "allowed_statuses": list(AGENT_RESULT_STATUSES),
        "required_output_fields": list(REQUIRED_AGENT_OUTPUT_FIELDS),
    }


def _invalid_collection_fields(
    envelope: dict[str, Any],
    expected_types: dict[str, type],
) -> list[str]:
    return [
        field
        for field, expected_type in expected_types.items()
        if field in envelope and not isinstance(envelope[field], expected_type)
    ]
