"""Small development CORS middleware for the demo API workspace."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from app.services.auth_error_contract import is_valid_mock_bearer_header


MOCK_AUTH_PUBLIC_PATHS = (
    "/api/health/",
    "/api/mock/chat/scenarios/",
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
        response["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
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
        return JsonResponse(error_body, status=status)


def _requires_mock_auth(request: HttpRequest) -> bool:
    if not getattr(settings, "MOCK_REQUIRE_AUTH", True):
        return False
    if request.method == "OPTIONS":
        return False
    if request.path in MOCK_AUTH_PUBLIC_PATHS:
        return False
    return request.path.startswith("/api/mock/")

