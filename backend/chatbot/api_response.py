"""Shared response helpers for the canonical API surface."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, JsonResponse


def json_response(_request: HttpRequest, data: dict[str, Any], status: int = 200) -> JsonResponse:
    return JsonResponse(dict(data), status=status)


def is_canonical_request(request: HttpRequest) -> bool:
    return request.path.startswith("/api/")


def is_canonical_mock_request(request: HttpRequest) -> bool:
    """Compatibility alias while callers migrate to ``is_canonical_request``."""

    return is_canonical_request(request)


def canonicalize_mock_paths(value: Any) -> Any:
    """Compatibility no-op for persisted legacy payload readers."""

    return value
