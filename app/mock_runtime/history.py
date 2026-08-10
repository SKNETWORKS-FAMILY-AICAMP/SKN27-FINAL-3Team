"""Explicit Mock history sidecar adapters."""

from __future__ import annotations

from typing import Any


def list_history_events(**filters: Any) -> list[dict[str, Any]]:
    from app.services.history_event_mock_service import list_history_events as _list_history_events

    return _list_history_events(**filters)


def record_history_event(**kwargs: Any) -> dict[str, Any]:
    from app.services.history_event_mock_service import record_history_event as _record_history_event

    return _record_history_event(**kwargs)
