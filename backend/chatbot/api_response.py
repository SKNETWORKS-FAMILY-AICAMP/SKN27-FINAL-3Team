"""Shared response helpers for the canonical API surface."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, JsonResponse


def json_response(_request: HttpRequest, data: dict[str, Any], status: int = 200) -> JsonResponse:
    return JsonResponse(dict(data), status=status)


def is_canonical_request(request: HttpRequest) -> bool:
    return request.path.startswith("/api/")
