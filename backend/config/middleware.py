"""CORS and JWT boundaries shared by local and deployed API processes."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from app.services.auth_error_contract import (
    build_auth_error,
    build_www_authenticate_header,
)
from app.services.google_auth_service import decode_access_token


PUBLIC_PATHS = (
    "/api/health/",
    "/api/health/live/",
    "/api/health/ready/",
    "/api/capabilities/",
    "/api/auth/guest-session/",
    "/api/auth/google/code/",
    "/api/auth/refresh/",
)

GUEST_ALLOWED_PATHS = (
    "/api/chat/sessions/",
    "/api/chat/messages/",
    "/api/chat/save-state/",
    "/api/files/",
    "/api/reports/",
)

PROTECTED_PREFIXES = (
    "/api/agents/",
    "/api/analysis/",
    "/api/chat/",
    "/api/files/",
    "/api/history/",
    "/api/mypage/",
    "/api/reports/",
)


class SameOriginCorsMiddleware:
    """Return CORS headers only for explicitly configured browser origins."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        origin = request.headers.get("Origin", "")
        if origin and origin in getattr(settings, "CORS_ALLOWED_ORIGINS", ()):
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Credentials"] = "true"
            response["Vary"] = "Origin"
            response["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
            response["Access-Control-Allow-Headers"] = (
                "Content-Type, Authorization, X-Guest-Id, X-Auth-Session-Id, X-Requested-With"
            )
        return response


class JwtAuthMiddleware:
    """Require an app JWT or an explicitly guest-safe identity."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not _requires_auth(request):
            return self.get_response(request)

        valid, error_body = _is_valid_api_auth(request)
        if valid:
            return self.get_response(request)

        status = error_body["error"]["status"]
        response = JsonResponse(error_body, status=status)
        response["WWW-Authenticate"] = build_www_authenticate_header(error_body)
        return response


def _requires_auth(request: HttpRequest) -> bool:
    if request.method == "OPTIONS":
        return False
    if request.path in PUBLIC_PATHS:
        return False
    return request.path.startswith(PROTECTED_PREFIXES)


def _is_valid_api_auth(request: HttpRequest) -> tuple[bool, dict | None]:
    authorization_header = request.headers.get("Authorization")
    if _is_guest_allowed_request(request, authorization_header):
        return True, None

    token = _bearer_token_from_header(authorization_header)
    if token:
        app_jwt_valid, app_jwt_claims = decode_access_token(token)
        if app_jwt_valid:
            return True, None
        reason = str(app_jwt_claims.get("reason") or "invalid_app_jwt")
        if reason == "expired_token":
            return False, build_auth_error("token_expired")
        if reason == "not_app_jwt":
            reason = "app_jwt_required"
        return False, build_auth_error("token_invalid", reason=reason)

    if authorization_header:
        return False, build_auth_error("token_invalid", reason="malformed_authorization_header")
    return False, build_auth_error("auth_required")


def _is_guest_allowed_request(request: HttpRequest, authorization_header: str | None) -> bool:
    if authorization_header:
        return False
    if not request.headers.get("X-Guest-Id"):
        return False
    if request.path in GUEST_ALLOWED_PATHS:
        return True
    return request.path.startswith("/api/reports/") and request.path.endswith("/download/")


def _bearer_token_from_header(header_value: str | None) -> str:
    if not header_value:
        return ""
    parts = header_value.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()

