"""Server-authoritative Supervisor execution input transformations.

Public requests may contain conversational context for the Supervisor planner,
but they must never choose an Agent execution path. Worker construction applies
the stricter runtime boundary after planning has produced server-owned packages.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


SERVER_EXECUTION_MODE = "sync"
SERVER_EXECUTION_CONTEXT_CONTRACT_VERSION = "server_execution_context.v1"
REQUIRES_SUPERVISOR_HANDOFF_FIELD = "requires_supervisor_handoff"
SERVER_EXECUTION_CONTEXT_FIELD = "server_execution_context"
SUPERVISOR_HANDOFF_CONTRACT_VERSIONS = frozenset(
    {
        "supervisor_conversation.v1",
        "supervisor_conversation_state.v1",
        "supervisor_conversation_state.v2",
    }
)
AGENT_INPUT_SCHEMA_VERSION = "agent_input_schema.v1"

# These controls never belong to a public conversational request. They are
# removed before the Supervisor plans, fingerprints, or queues any work.
EXECUTION_CONTROL_FIELDS = frozenset(
    {
        "adapter_mode",
        "agent_input",
        "analysis_plan",
        "analysis_plan_id",
        "depends_on",
        "execution_mode",
        "execution_status",
        "handoff_required",
        "mock_status",
        "node_code",
        "plan_step",
        "reporting_payload",
        "required_inputs",
        REQUIRES_SUPERVISOR_HANDOFF_FIELD,
        SERVER_EXECUTION_CONTEXT_FIELD,
        "slot_state",
        "supervisor_handoff",
        "supervisor_reporting_handoff",
        "upstream_results",
    }
)

# Search/retrieval hints may be useful conversational input to the Supervisor,
# but they must not become direct runtime controls after a plan is selected.
WORKER_ONLY_EXECUTION_CONTROL_FIELDS = frozenset({"search_query", "violation_text"})

CONTEXT_EXECUTION_CONTROL_FIELDS = EXECUTION_CONTROL_FIELDS | frozenset(
    {"supervisor_agent_package"}
)


def sanitize_public_supervisor_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep conversational input while removing planning/execution authority."""

    return _sanitize_payload(
        payload,
        control_fields=EXECUTION_CONTROL_FIELDS,
        context_control_fields=CONTEXT_EXECUTION_CONTROL_FIELDS,
    )


def sanitize_public_worker_execution_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Discard all public context before a Supervisor-selected Agent runs."""

    return _sanitize_payload(
        payload,
        control_fields=EXECUTION_CONTROL_FIELDS | WORKER_ONLY_EXECUTION_CONTROL_FIELDS,
        context_control_fields=CONTEXT_EXECUTION_CONTROL_FIELDS,
        discard_context=True,
    )


def serialize_server_execution_context(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Wrap server-produced runtime context for queue-only persistence."""

    context = _trusted_server_context(value)
    if not context:
        return {}
    return {
        "contract_version": SERVER_EXECUTION_CONTEXT_CONTRACT_VERSION,
        "context": context,
    }


def read_server_execution_context(value: Any) -> dict[str, Any]:
    """Read only a versioned server context envelope, never request JSON."""

    if not isinstance(value, Mapping):
        return {}
    if value.get("contract_version") != SERVER_EXECUTION_CONTEXT_CONTRACT_VERSION:
        return {}
    return _trusted_server_context(value.get("context"))


def requires_supervisor_handoff(payload: Mapping[str, Any]) -> bool:
    """Return the server-only marker that makes public Agent execution fail closed."""

    return payload.get(REQUIRES_SUPERVISOR_HANDOFF_FIELD) is True


def canonical_attachment_selectors(attachments: Any) -> list[dict[str, str]]:
    """Return package-safe attachment selectors from canonical attachment metadata."""

    selectors: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for attachment in _list_or_empty(attachments):
        if not isinstance(attachment, Mapping):
            continue
        attachment_id = _text(attachment.get("attachment_id"))
        if not attachment_id or attachment_id in seen_ids:
            continue
        seen_ids.add(attachment_id)
        selectors.append({"attachment_id": attachment_id})
    return selectors


def project_package_attachment_selectors(
    package_attachments: Any,
    approved_selectors: Any,
) -> list[dict[str, Any]] | None:
    """Validate a package selector list against server-approved selector IDs."""

    return _project_package_attachments(package_attachments, approved_selectors)


def build_trusted_worker_execution_payload(
    request_payload: Mapping[str, Any],
    *,
    chat_response: Mapping[str, Any],
    server_upstream_results: Mapping[str, Any] | None = None,
    server_execution_context: Mapping[str, Any] | None = None,
    public_request: bool = False,
) -> dict[str, Any]:
    """Build worker input from server-generated response and trusted overlays.

    Public worker context is rebuilt from scratch. Internal Case and operational
    callers may supply a separate, versioned server context through the queue
    resolver. Stored request JSON never supplies an upstream result.
    """

    if public_request:
        execution_payload = sanitize_public_worker_execution_request(request_payload)
        context: dict[str, Any] = {}
    else:
        execution_payload = _sanitize_payload(
            request_payload,
            control_fields=EXECUTION_CONTROL_FIELDS | WORKER_ONLY_EXECUTION_CONTROL_FIELDS,
            context_control_fields=CONTEXT_EXECUTION_CONTROL_FIELDS,
        )
        context = _mapping_or_empty(execution_payload.get("context"))

    context.update(_trusted_server_context(server_execution_context))
    supervisor_state = _optional_mapping(chat_response.get("supervisor_state"))
    if supervisor_state:
        context["supervisor_handoff"] = supervisor_state
    else:
        context.pop("supervisor_handoff", None)

    if public_request:
        execution_payload[REQUIRES_SUPERVISOR_HANDOFF_FIELD] = True
    else:
        execution_payload.pop(REQUIRES_SUPERVISOR_HANDOFF_FIELD, None)

    execution_payload.update(
        {
            "session_id": chat_response.get("session_id"),
            "message_id": chat_response.get("message_id"),
            "attachments": deepcopy(_list_or_empty(chat_response.get("attachments"))),
            "execution_mode": SERVER_EXECUTION_MODE,
            "upstream_results": (
                {}
                if public_request or is_ready_supervisor_handoff(supervisor_state)
                else deepcopy(_mapping_or_empty(server_upstream_results))
            ),
            "context": context,
        }
    )
    return execution_payload


def is_ready_supervisor_handoff(value: Any) -> bool:
    """Return whether a handoff is a server-ready Supervisor contract."""

    if not isinstance(value, Mapping):
        return False
    return (
        str(value.get("contract_version") or "") in SUPERVISOR_HANDOFF_CONTRACT_VERSIONS
        and str(value.get("stage") or "") == "agent_execution_ready"
        and isinstance(value.get("agent_input_packages"), list)
    )


def bind_supervisor_plan_step_payload(
    payload: Mapping[str, Any],
    *,
    step: Mapping[str, Any],
    upstream_results: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind a server plan step to its matching ready Supervisor package.

    Package attachments are selectors only. The actual attachment objects are
    projected from the worker's already scan-gated canonical attachment list.
    """

    bound = deepcopy(dict(payload))
    bound.pop("agent_input", None)
    bound["node_code"] = str(step.get("node_code") or "").strip()
    bound["upstream_results"] = deepcopy(_mapping_or_empty(upstream_results))

    context = _mapping_or_empty(bound.get("context"))
    supervisor_handoff = _mapping_or_empty(context.get("supervisor_handoff"))
    approved_attachments = _list_or_empty(bound.get("attachments"))
    package = _matching_ready_agent_package(
        supervisor_handoff,
        bound["node_code"],
        approved_attachments=approved_attachments,
    )
    if package:
        package_payload = _mapping_or_empty(package.get("payload"))
        selected_attachments = _project_package_attachments(
            package_payload.get("attachments"),
            approved_attachments,
        )
        if selected_attachments is None:  # Defensive: matching validation already rejects this.
            package = {}
        else:
            for field in ("user_text", "attachments", "slot_state"):
                bound.pop(field, None)
            bound["user_text"] = deepcopy(
                package_payload.get("user_text", package_payload.get("raw_user_text"))
            )
            bound["attachments"] = selected_attachments
            bound["slot_state"] = deepcopy(dict(package_payload["slot_state"]))
            context["supervisor_agent_package"] = _execution_safe_agent_package(package)
    if not package:
        context.pop("supervisor_agent_package", None)
        if _has_declared_ready_agent_package(supervisor_handoff, bound["node_code"]):
            for field in ("user_text", "attachments", "slot_state"):
                bound.pop(field, None)
    if supervisor_handoff:
        context["supervisor_handoff"] = _execution_safe_supervisor_handoff(supervisor_handoff)
    else:
        context.pop("supervisor_handoff", None)
    bound["context"] = context
    return bound


def _sanitize_payload(
    payload: Mapping[str, Any],
    *,
    control_fields: frozenset[str],
    context_control_fields: frozenset[str],
    discard_context: bool = False,
) -> dict[str, Any]:
    sanitized = deepcopy(dict(payload))
    for field in control_fields:
        sanitized.pop(field, None)

    if discard_context:
        sanitized.pop("context", None)
        return sanitized

    context = _mapping_or_empty(sanitized.get("context"))
    if context:
        for field in context_control_fields:
            context.pop(field, None)
        sanitized["context"] = context
    else:
        sanitized.pop("context", None)
    return sanitized


def _trusted_server_context(value: Any) -> dict[str, Any]:
    context = _mapping_or_empty(value)
    for field in CONTEXT_EXECUTION_CONTROL_FIELDS:
        context.pop(field, None)
    return context


def _matching_ready_agent_package(
    supervisor_handoff: Mapping[str, Any],
    node_code: str,
    *,
    approved_attachments: list[Any],
) -> dict[str, Any]:
    if not is_ready_supervisor_handoff(supervisor_handoff):
        return {}
    for package in _list_or_empty(supervisor_handoff.get("agent_input_packages")):
        if _is_ready_agent_package(
            package,
            node_code=node_code,
            approved_attachments=approved_attachments,
        ):
            return deepcopy(dict(package))
    return {}


def _has_declared_ready_agent_package(
    supervisor_handoff: Mapping[str, Any],
    node_code: str,
) -> bool:
    if not is_ready_supervisor_handoff(supervisor_handoff):
        return False
    return any(
        isinstance(package, Mapping)
        and str(package.get("node_code") or "").strip() == node_code
        and str(package.get("status") or "").strip().lower() == "ready"
        for package in _list_or_empty(supervisor_handoff.get("agent_input_packages"))
    )


def _is_ready_agent_package(
    package: Any,
    *,
    node_code: str,
    approved_attachments: list[Any],
) -> bool:
    if not isinstance(package, Mapping):
        return False
    if package.get("schema_version") != AGENT_INPUT_SCHEMA_VERSION:
        return False
    if str(package.get("node_code") or "").strip() != node_code:
        return False
    if str(package.get("status") or "").strip().lower() != "ready":
        return False
    package_payload = package.get("payload")
    if not isinstance(package_payload, Mapping):
        return False
    user_text = package_payload.get("user_text", package_payload.get("raw_user_text"))
    return (
        isinstance(user_text, str)
        and isinstance(package_payload.get("attachments"), list)
        and isinstance(package_payload.get("slot_state"), Mapping)
        and _project_package_attachments(
            package_payload.get("attachments"),
            approved_attachments,
        )
        is not None
    )


def _project_package_attachments(
    package_attachments: Any,
    approved_attachments: Any,
) -> list[dict[str, Any]] | None:
    if not isinstance(package_attachments, list) or not isinstance(approved_attachments, list):
        return None

    approved_by_id: dict[str, dict[str, Any]] = {}
    for attachment in approved_attachments:
        if not isinstance(attachment, Mapping):
            continue
        attachment_id = _text(attachment.get("attachment_id"))
        if not attachment_id or attachment_id in approved_by_id:
            continue
        approved_by_id[attachment_id] = deepcopy(dict(attachment))

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for selector in package_attachments:
        if not isinstance(selector, Mapping) or set(selector) != {"attachment_id"}:
            return None
        attachment_id = _text(selector.get("attachment_id"))
        if (
            not attachment_id
            or attachment_id in selected_ids
            or attachment_id not in approved_by_id
        ):
            return None
        selected_ids.add(attachment_id)
        selected.append(deepcopy(approved_by_id[attachment_id]))
    return selected


def _execution_safe_supervisor_handoff(handoff: Mapping[str, Any]) -> dict[str, Any]:
    """Return the adapter-facing handoff without raw package attachment metadata.

    Validation above intentionally uses the original Supervisor state. This
    projection is only for the execution context after validation, so malformed
    package attachment data cannot become valid execution authority.
    """

    sanitized = deepcopy(dict(handoff))
    sanitized.pop("attachments", None)
    packages = handoff.get("agent_input_packages")
    if isinstance(packages, list):
        sanitized["agent_input_packages"] = [
            _execution_safe_agent_package(package)
            if isinstance(package, Mapping)
            else deepcopy(package)
            for package in packages
        ]
    return sanitized


def _execution_safe_agent_package(package: Mapping[str, Any]) -> dict[str, Any]:
    """Keep package attachment references as selectors in adapter context only."""

    sanitized = deepcopy(dict(package))
    sanitized.pop("attachments", None)
    package_payload = sanitized.get("payload")
    if isinstance(package_payload, Mapping):
        safe_payload = deepcopy(dict(package_payload))
        if "attachments" in safe_payload:
            safe_payload["attachments"] = canonical_attachment_selectors(
                safe_payload.get("attachments")
            )
        sanitized["payload"] = safe_payload
    return sanitized


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _optional_mapping(value: Any) -> dict[str, Any] | None:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else None


def _list_or_empty(value: Any) -> list[Any]:
    return deepcopy(list(value)) if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) else ""
