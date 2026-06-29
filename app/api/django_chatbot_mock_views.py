"""Optional Django view adapter for the chatbot mock service."""

from __future__ import annotations

import json
from typing import Any, Callable

from app.services.chatbot_mock_service import create_session, perform_report_action, submit_message

try:
    from django.http import HttpRequest, JsonResponse
    from django.views.decorators.http import require_http_methods
except ImportError:  # pragma: no cover - lets the module be imported before Django is installed.
    HttpRequest = Any  # type: ignore

    class JsonResponse(dict):  # type: ignore
        def __init__(self, data: dict[str, Any], status: int = 200) -> None:
            super().__init__(data)
            self.status_code = status

    def require_http_methods(_methods: list[str]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return lambda view: view


@require_http_methods(["POST"])
def create_chat_session(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    return JsonResponse(create_session(user_id=body.get("user_id")))


@require_http_methods(["POST"])
def submit_chat_message(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    return JsonResponse(submit_message(body))


@require_http_methods(["POST"])
def report_action(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    return JsonResponse(perform_report_action(body))


def _json_body(request: HttpRequest) -> dict[str, Any]:
    raw_body = getattr(request, "body", b"") or b"{}"
    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")
    try:
        return json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        return {}

