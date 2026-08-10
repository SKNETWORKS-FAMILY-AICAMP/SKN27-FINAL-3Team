"""Fail-closed Explicit Mock Agent execution without Canonical Agent dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.mock_runtime.attachments import resolve_attachment_references


class UnsupportedExplicitMockNodeError(ValueError):
    """Raised when an Explicit Mock plan asks for an unregistered node."""

    def __init__(self, node_code: str) -> None:
        super().__init__(f"unsupported_explicit_mock_node:{node_code or 'missing'}")
        self.node_code = node_code


class InvalidExplicitMockPlanError(ValueError):
    """Raised when an Explicit Mock plan cannot be validated as a complete plan."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"invalid_explicit_mock_plan:{reason}")
        self.reason = reason


EXPLICIT_MOCK_NODE_METADATA: Mapping[str, Mapping[str, str]] = {
    "input_context_validation": {"node_name": "Explicit Mock input validation"},
    "fine_notice_analysis": {"node_name": "Explicit Mock fine notice analysis"},
    "law_ground_search": {"node_name": "Explicit Mock law ground search"},
    "text_ml_case_search": {"node_name": "Explicit Mock similar case search"},
    "vision_media_analysis": {"node_name": "Explicit Mock vision analysis"},
    "objection_report_generation": {"node_name": "Explicit Mock report generation"},
    "agent_result_validation": {"node_name": "Explicit Mock result validation"},
}
SUPPORTED_EXPLICIT_MOCK_NODE_CODES = frozenset(EXPLICIT_MOCK_NODE_METADATA)
_MOCK_EXECUTION_STATUSES = frozenset({"success", "partial", "failed", "running", "blocked", "skipped"})


def execute_mock_node(payload: dict[str, Any]) -> dict[str, Any]:
    """Run only a registered deterministic Explicit Mock node."""

    resolved_payload = resolve_attachment_references(payload)
    node_code = _node_code(resolved_payload)
    _require_supported_node(node_code)
    execution_status = _execution_status(resolved_payload)
    execution_id = f"exec_{uuid4().hex[:12]}"
    node = {
        "node_code": node_code,
        "node_name": EXPLICIT_MOCK_NODE_METADATA[node_code]["node_name"],
        "node_type": "explicit_mock",
    }
    return {
        "execution_id": execution_id,
        "execution_mode": "explicit_mock",
        "job_id": resolved_payload.get("job_id"),
        "node_code": node_code,
        "node": node,
        "adapter_context": {
            "contract_version": "explicit_mock_adapter.v1",
            "execution_id": execution_id,
            "execution_mode": "explicit_mock",
            "node_code": node_code,
        },
        "agent_input": {
            "contract_version": "explicit_mock_agent_input.v1",
            "job_id": resolved_payload.get("job_id"),
            "session_id": resolved_payload.get("session_id"),
            "message_id": resolved_payload.get("message_id"),
            "node_code": node_code,
        },
        "agent_output": _mock_agent_output(
            node_code=node_code,
            payload=resolved_payload,
            execution_status=execution_status,
        ),
        "created_at": _now_iso(),
    }


def execute_mock_plan(analysis_plan: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Run an Explicit Mock plan only when every step is registered."""

    resolved_payload = resolve_attachment_references(payload)
    steps = _validated_plan_steps(analysis_plan)
    for step in steps:
        node_code = _node_code(step)
        if not node_code:
            raise InvalidExplicitMockPlanError("missing_node_code")
        _require_supported_node(node_code)

    executions: list[dict[str, Any]] = []
    upstream_results = deepcopy(resolved_payload.get("upstream_results", {}))
    for step in steps:
        step_payload = deepcopy(resolved_payload)
        step_payload.update(
            {
                "analysis_plan_id": analysis_plan.get("plan_id"),
                "session_id": analysis_plan.get("session_id") or resolved_payload.get("session_id"),
                "message_id": analysis_plan.get("message_id") or resolved_payload.get("message_id"),
                "node_code": step.get("node_code"),
                "execution_status": step.get("status", "success"),
                "required_inputs": step.get("required_inputs", []),
                "depends_on": step.get("depends_on", []),
                "plan_step": step,
                "upstream_results": deepcopy(upstream_results),
            }
        )
        if isinstance(step.get("context"), dict):
            context = deepcopy(resolved_payload.get("context") if isinstance(resolved_payload.get("context"), dict) else {})
            context.update(deepcopy(step["context"]))
            step_payload["context"] = context
        execution = execute_mock_node(step_payload)
        execution["plan_step"] = deepcopy(step)
        executions.append(execution)
        upstream_results[execution["node_code"]] = deepcopy(execution["agent_output"])

    return {
        "execution_mode": "explicit_mock",
        "job_id": resolved_payload.get("job_id"),
        "plan_id": analysis_plan.get("plan_id"),
        "session_id": analysis_plan.get("session_id") or resolved_payload.get("session_id"),
        "message_id": analysis_plan.get("message_id") or resolved_payload.get("message_id"),
        "executions": executions,
        "status_counts": _status_counts(executions),
        "completed_node_codes": [item["node_code"] for item in executions if item["agent_output"]["status"] == "success"],
        "limitations": ["Explicit Mock execution does not invoke Canonical Agent or external providers."],
        "created_at": _now_iso(),
    }


def _mock_agent_output(*, node_code: str, payload: dict[str, Any], execution_status: str) -> dict[str, Any]:
    result_status = "success" if execution_status == "running" else execution_status
    return {
        "node_code": node_code,
        "node_name": EXPLICIT_MOCK_NODE_METADATA[node_code]["node_name"],
        "job_id": payload.get("job_id"),
        "status": result_status,
        "summary": f"Explicit Mock result for {node_code}.",
        "structured_result": {
            "contract_version": "explicit_mock_agent_result.v1",
            "node_code": node_code,
            "status": result_status,
        },
        "evidence": [
            {
                "evidence_id": f"mock_{node_code}",
                "source_reference": f"explicit_mock:{node_code}",
                "summary": "Deterministic Explicit Mock evidence.",
            }
        ],
        "next_actions": [],
        "limitations": ["Explicit Mock output is test/demo-only and is not provider output."],
    }


def _require_supported_node(node_code: str) -> None:
    if node_code not in SUPPORTED_EXPLICIT_MOCK_NODE_CODES:
        raise UnsupportedExplicitMockNodeError(node_code)


def _validated_plan_steps(analysis_plan: Any) -> list[dict[str, Any]]:
    if not isinstance(analysis_plan, dict):
        raise InvalidExplicitMockPlanError("analysis_plan_not_object")
    if "steps" not in analysis_plan:
        raise InvalidExplicitMockPlanError("missing_steps")
    raw_steps = analysis_plan.get("steps")
    if not isinstance(raw_steps, list):
        raise InvalidExplicitMockPlanError("steps_not_list")
    if any(not isinstance(step, dict) for step in raw_steps):
        raise InvalidExplicitMockPlanError("step_not_object")
    return raw_steps


def _node_code(payload: Mapping[str, Any]) -> str:
    return str(payload.get("node_code") or "").strip()


def _execution_status(payload: Mapping[str, Any]) -> str:
    value = str(payload.get("execution_status") or payload.get("mock_status") or "success").strip().lower()
    return value if value in _MOCK_EXECUTION_STATUSES else "failed"


def _status_counts(executions: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for execution in executions:
        status = str((execution.get("agent_output") or {}).get("status") or "failed")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
