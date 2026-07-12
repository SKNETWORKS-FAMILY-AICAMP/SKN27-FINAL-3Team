"""Guarded AWS staging operations boundary."""

from __future__ import annotations

import hmac
from typing import Any, Callable


CONTRACT_VERSION = "aws_ops_mcp.v1"
READ_COMMANDS = {"ecs_status", "cloudwatch_errors", "sqs_dlq_depth"}
MUTATION_COMMANDS = {"restart_worker", "replay_failed_work_item"}
SUPPORTED_COMMANDS = READ_COMMANDS | MUTATION_COMMANDS
OpsAdapter = Callable[[str], dict[str, Any]]


def run_aws_ops_command(
    command: str,
    *,
    environment: str = "staging",
    approval_token: str = "",
    expected_approval_token: str = "",
    adapter: OpsAdapter | None = None,
) -> dict[str, Any]:
    """Run an allowlisted read or guarded staging mutation."""

    normalized_command = str(command or "").strip()
    normalized_environment = str(environment or "").strip().lower()
    if normalized_command not in SUPPORTED_COMMANDS:
        return _result(
            normalized_command,
            normalized_environment,
            status="failed",
            reason="unsupported_command",
        )

    if normalized_command in MUTATION_COMMANDS:
        if normalized_environment != "staging":
            return _result(
                normalized_command,
                normalized_environment,
                status="blocked",
                reason="production changes are not allowed",
            )
        if not _valid_approval(approval_token, expected_approval_token):
            return _result(
                normalized_command,
                normalized_environment,
                status="blocked",
                reason="approval_token_required",
            )

    if adapter is None:
        return _result(
            normalized_command,
            normalized_environment,
            status="dependency_unavailable",
            reason="ops_adapter_unavailable",
        )
    try:
        data = adapter(normalized_command)
    except Exception as exc:
        return _result(
            normalized_command,
            normalized_environment,
            status="failed",
            reason=exc.__class__.__name__,
        )
    return _result(
        normalized_command,
        normalized_environment,
        status="success",
        reason="ok",
        data=data if isinstance(data, dict) else {},
    )


def _valid_approval(provided: str, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(str(provided), str(expected))


def _result(
    command: str,
    environment: str,
    *,
    status: str,
    reason: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "command": command,
        "environment": environment,
        "status": status,
        "reason": reason,
        "data": data or {},
    }
