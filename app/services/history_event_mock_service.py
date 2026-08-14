"""Legacy compatibility shim for Explicit Mock history sidecars."""

from app.mock_runtime.history import (
    actor_from_payload,
    build_agent_execution_events,
    build_history_event,
    list_history_events,
    record_agent_execution_events,
    record_history_event,
    sanitize_metadata,
    source_from_request,
    subject_from_payload,
)

__all__ = [
    "actor_from_payload",
    "build_agent_execution_events",
    "build_history_event",
    "list_history_events",
    "record_agent_execution_events",
    "record_history_event",
    "sanitize_metadata",
    "source_from_request",
    "subject_from_payload",
]
