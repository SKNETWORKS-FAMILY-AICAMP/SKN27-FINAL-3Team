"""Shared response helpers for canonical and explicit mock API surfaces."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, JsonResponse


MOCK_TO_CANONICAL_PATH_PREFIXES = (
    ("/api/mock/analysis/results/", "/api/analysis/results/"),
    ("/api/mock/analysis/jobs/", "/api/analysis/jobs/"),
    ("/api/mock/agents/nodes/run/", "/api/agents/nodes/run/"),
    ("/api/mock/agents/plans/run/", "/api/agents/plans/run/"),
    ("/api/mock/attachments/", "/api/files/"),
    ("/api/mock/reports/", "/api/reports/"),
    ("/api/mock/chat/sessions/", "/api/chat/sessions/"),
    ("/api/mock/chat/messages/", "/api/chat/messages/"),
    ("/api/mock/analysis/results", "/api/analysis/results"),
    ("/api/mock/analysis/jobs", "/api/analysis/jobs"),
    ("/api/mock/agents/nodes/run", "/api/agents/nodes/run"),
    ("/api/mock/agents/plans/run", "/api/agents/plans/run"),
    ("/api/mock/attachments", "/api/files"),
    ("/api/mock/reports", "/api/reports"),
    ("/api/mock/chat/sessions", "/api/chat/sessions"),
    ("/api/mock/chat/messages", "/api/chat/messages"),
)


def json_response(request: HttpRequest, data: dict[str, Any], status: int = 200) -> JsonResponse:
    response_data = dict(data)
    if is_canonical_mock_request(request):
        response_data = canonicalize_mock_paths(response_data)
        response_data.setdefault("api_surface", "canonical_mock")
        response_data.setdefault("execution_mode", "mock")
    return JsonResponse(response_data, status=status)


def is_canonical_mock_request(request: HttpRequest) -> bool:
    return request.path.startswith("/api/") and not request.path.startswith("/api/mock/")


def canonicalize_mock_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: canonicalize_mock_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [canonicalize_mock_paths(item) for item in value]
    if isinstance(value, str):
        for mock_prefix, canonical_prefix in MOCK_TO_CANONICAL_PATH_PREFIXES:
            if value.startswith(mock_prefix):
                return value.replace(mock_prefix, canonical_prefix, 1)
    return value
