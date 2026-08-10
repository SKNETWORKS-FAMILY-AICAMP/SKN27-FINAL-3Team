"""Explicit Mock agent dispatch isolated from the production agent module."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from app.services.agent_adapter_contract import build_adapter_context
from app.services.attachment_mock_service import resolve_attachment_references
from app.services.agent_node_service import (
    _agent_input,
    _normalize_result_status,
    _now_iso,
    _payload_node_code,
    _plan_execution_mode,
    _status_counts,
    _with_execution_provenance,
    build_agent_output,
    get_agent_node,
)
from app.services import agent_node_service as canonical_agent_runtime


DL_MOCK_NODE_CODES: set[str] = set()


def execute_mock_node(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute an Explicit Mock node without adding a production dispatch path."""

    payload = resolve_attachment_references(payload)
    node_code = _payload_node_code(payload)
    if node_code not in DL_MOCK_NODE_CODES:
        return canonical_agent_runtime.execute_agent_node(payload)
    execution_status = str(payload.get("execution_status") or payload.get("mock_status") or "success")
    node = get_agent_node(node_code)
    execution_id = f"exec_{uuid4().hex[:12]}"
    return _with_execution_provenance({
        "execution_id": execution_id,
        "execution_mode": "explicit_mock",
        "job_id": payload.get("job_id"),
        "node_code": node_code,
        "node": node,
        "adapter_context": build_adapter_context(execution_id=execution_id, execution_mode="mock", node=node, plan_step=payload.get("plan_step")),
        "agent_input": _agent_input(payload, node),
        "agent_output": build_agent_output(node_code=node_code, payload=payload, result_status=_normalize_result_status(execution_status), execution_status=execution_status),
        "created_at": _now_iso(),
    })


def execute_mock_plan(analysis_plan: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Execute a test/demo plan through the isolated Explicit Mock dispatcher."""

    payload = resolve_attachment_references(payload)
    executions: list[dict[str, Any]] = []
    upstream_results = deepcopy(payload.get("upstream_results", {}))
    for step in analysis_plan.get("steps", []):
        step_payload = deepcopy(payload)
        step_payload.update({
            "analysis_plan_id": analysis_plan.get("plan_id"),
            "session_id": analysis_plan.get("session_id") or payload.get("session_id"),
            "message_id": analysis_plan.get("message_id") or payload.get("message_id"),
            "node_code": step.get("node_code"),
            "execution_status": step.get("status", "success"),
            "execution_mode": step.get("execution_mode") or payload.get("execution_mode"),
            "adapter_mode": step.get("adapter_mode") or payload.get("adapter_mode"),
            "required_inputs": step.get("required_inputs", []),
            "depends_on": step.get("depends_on", []),
            "plan_step": step,
            "upstream_results": deepcopy(upstream_results),
        })
        if isinstance(step.get("context"), dict):
            context = deepcopy(payload.get("context") if isinstance(payload.get("context"), dict) else {})
            context.update(deepcopy(step["context"]))
            step_payload["context"] = context
        execution = execute_mock_node(step_payload)
        execution["plan_step"] = deepcopy(step)
        executions.append(execution)
        upstream_results[execution["node_code"]] = deepcopy(execution["agent_output"])
    return {
        "execution_mode": _plan_execution_mode(executions),
        "job_id": payload.get("job_id"),
        "plan_id": analysis_plan.get("plan_id"),
        "session_id": analysis_plan.get("session_id") or payload.get("session_id"),
        "message_id": analysis_plan.get("message_id") or payload.get("message_id"),
        "executions": executions,
        "status_counts": _status_counts(executions),
        "completed_node_codes": [item["node_code"] for item in executions if item["agent_output"]["status"] == "success"],
        "limitations": ["Explicit Mock execution does not represent production provider output."],
        "created_at": _now_iso(),
    }
