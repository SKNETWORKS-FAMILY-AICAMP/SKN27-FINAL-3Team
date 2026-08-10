"""Explicit Mock HTTP entrypoints.

These views are intentionally absent from canonical URL configuration. Runtime
handlers are connected after the Explicit Mock services move to
``app.mock_runtime``.
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse


def _runtime_not_ready(_: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {"error": {"code": "explicit_mock_runtime_not_ready"}},
        status=503,
    )


attachments = _runtime_not_ready
analysis_jobs = _runtime_not_ready
history = _runtime_not_ready
agent_plan = _runtime_not_ready
