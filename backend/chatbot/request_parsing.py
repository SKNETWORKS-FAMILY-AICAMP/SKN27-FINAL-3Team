"""Request parsing helpers for mock chatbot views."""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest


def json_body(request: HttpRequest) -> dict[str, Any]:
    raw_body = request.body or b"{}"
    try:
        return json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def request_payload(request: HttpRequest) -> dict[str, Any]:
    if request.content_type and request.content_type.startswith("multipart/"):
        return {key: request.POST.get(key) for key in request.POST}
    if request.content_type and request.content_type.startswith("application/x-www-form-urlencoded"):
        return {key: request.POST.get(key) for key in request.POST}
    return json_body(request)


def first_upload_file(request: HttpRequest) -> Any | None:
    if not request.FILES:
        return None
    return request.FILES.get("file") or next(iter(request.FILES.values()))
