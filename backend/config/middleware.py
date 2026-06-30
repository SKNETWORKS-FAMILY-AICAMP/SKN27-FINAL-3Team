"""Small development CORS middleware for the demo API workspace."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from app.services.auth_error_contract import (
    build_www_authenticate_header,
    is_valid_mock_bearer_header,
)


MOCK_AUTH_PUBLIC_PATHS = (
    "/api/health/",
    "/api/mock/chat/scenarios/",
)

MOCK_AUTH_PROTECTED_PREFIXES = (
    "/api/agents/",
    "/api/analysis/",
    "/api/chat/",
    "/api/files/",
    "/api/history/",
    "/api/mypage/",
    "/api/mock/",
    "/api/reports/",
)


class DemoCorsMiddleware:
    """Allow local frontend apps to call the mock API during the mid-demo build."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Guest-Id, X-Auth-Session-Id"
        return response


class MockJwtAuthMiddleware:
    """Require a Bearer header on protected mock API routes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not _requires_mock_auth(request):
            return self.get_response(request)

        valid, error_body = is_valid_mock_bearer_header(request.headers.get("Authorization"))
        if valid:
            return self.get_response(request)

        status = error_body["error"]["status"]
        response = JsonResponse(error_body, status=status)
        response["WWW-Authenticate"] = build_www_authenticate_header(error_body)
        return response


def _requires_mock_auth(request: HttpRequest) -> bool:
    if not getattr(settings, "MOCK_REQUIRE_AUTH", True):
        return False
    if request.method == "OPTIONS":
        return False
    if request.path in MOCK_AUTH_PUBLIC_PATHS:
        return False
    return request.path.startswith(MOCK_AUTH_PROTECTED_PREFIXES)

