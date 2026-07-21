"""CORS and JWT boundaries shared by local and deployed API processes."""

from __future__ import annotations

from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.http import HttpRequest, HttpResponse, JsonResponse

from app.services.auth_error_contract import (
    build_auth_error,
    build_www_authenticate_header,
)
from app.services.guest_credential_service import decode_guest_credential
from app.services.google_auth_service import decode_access_token
from chatbot.auth_session_policy import validate_persisted_auth_session


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
    "/api/auth/me/",
    "/api/history/",
    "/api/analysis/jobs/",
)

PROTECTED_PREFIXES = (
    "/api/auth/",
    "/api/agents/",
    "/api/analysis/",
    "/api/cases/",
    "/api/chat/",
    "/api/files/",
    "/api/history/",
    "/api/mypage/",
    "/api/reports/",
)

FILE_UPLOAD_REQUEST_OVERHEAD_BYTES = 1024 * 1024


class BoundedFileUploadHandler(FileUploadHandler):
    """Stop multipart streaming before temporary storage exceeds the file cap."""

    chunk_size = 64 * 1024

    def __init__(self, request: HttpRequest, *, max_bytes: int) -> None:
        super().__init__(request)
        self.max_bytes = max_bytes
        self.total_file_bytes = 0

    def new_file(self, *args, **kwargs) -> None:
        super().new_file(*args, **kwargs)
        content_length = kwargs.get("content_length")
        if content_length is None and len(args) >= 4:
            content_length = args[3]
        if content_length is not None and int(content_length) > self.max_bytes:
            self._stop_upload(int(content_length))

    def receive_data_chunk(self, raw_data: bytes, start: int) -> bytes:
        del start
        self.total_file_bytes += len(raw_data)
        if self.total_file_bytes > self.max_bytes:
            self._stop_upload(self.total_file_bytes)
        return raw_data

    def file_complete(self, file_size: int):
        del file_size
        return None

    def _stop_upload(self, size_bytes: int) -> None:
        self.request.file_upload_limit_violation = {
            "size_bytes": size_bytes,
            "limit_bytes": self.max_bytes,
        }
        raise StopUpload(connection_reset=True)


class FileUploadLimitMiddleware:
    """Apply an early Content-Length guard and a bounded streaming handler."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not _is_canonical_multipart_upload(request):
            return self.get_response(request)

        max_bytes = int(getattr(settings, "FILE_UPLOAD_MAX_BYTES", 20 * 1024 * 1024))
        content_length = _positive_content_length(request)
        if (
            content_length is not None
            and content_length > max_bytes + FILE_UPLOAD_REQUEST_OVERHEAD_BYTES
        ):
            return _file_upload_limit_response(
                size_bytes=content_length,
                limit_bytes=max_bytes,
            )

        request.upload_handlers.insert(
            0,
            BoundedFileUploadHandler(request, max_bytes=max_bytes),
        )
        return self.get_response(request)


def _is_canonical_multipart_upload(request: HttpRequest) -> bool:
    return (
        request.method == "POST"
        and request.path == "/api/files/"
        and str(request.content_type or "").startswith("multipart/")
    )


def _positive_content_length(request: HttpRequest) -> int | None:
    try:
        value = int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _file_upload_limit_response(*, size_bytes: int, limit_bytes: int) -> JsonResponse:
    return JsonResponse(
        {
            "error": {
                "contract_version": "file_upload_error.v1",
                "type": "validation",
                "code": "file_too_large",
                "status": 413,
                "message": "The uploaded file exceeds the configured size limit.",
                "size_bytes": size_bytes,
                "limit_bytes": limit_bytes,
                "required_action": "select_smaller_file",
            }
        },
        status=413,
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
                "Content-Type, Authorization, X-Guest-Id, X-Guest-Credential, "
                "X-Auth-Session-Id, X-Requested-With"
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
    guest_allowed, guest_error = _is_guest_allowed_request(request, authorization_header)
    if guest_allowed:
        return True, None
    if guest_error is not None:
        return False, guest_error

    token = _bearer_token_from_header(authorization_header)
    if token:
        app_jwt_valid, app_jwt_claims = decode_access_token(token)
        if app_jwt_valid:
            session_valid, reason = validate_persisted_auth_session(app_jwt_claims)
            if session_valid:
                return True, None
            return False, build_auth_error("token_invalid", reason=reason)
        reason = str(app_jwt_claims.get("reason") or "invalid_app_jwt")
        if reason == "expired_token":
            return False, build_auth_error("token_expired")
        if reason == "not_app_jwt":
            reason = "app_jwt_required"
        return False, build_auth_error("token_invalid", reason=reason)

    if authorization_header:
        return False, build_auth_error("token_invalid", reason="malformed_authorization_header")
    return False, build_auth_error("auth_required")


def _is_guest_allowed_request(
    request: HttpRequest,
    authorization_header: str | None,
) -> tuple[bool, dict | None]:
    if authorization_header:
        return False, None
    if not _is_guest_credential_path(request.path):
        return False, None

    requested_guest_id = _normalize_guest_id(request.headers.get("X-Guest-Id"))
    guest_credential = request.headers.get("X-Guest-Credential")
    if not requested_guest_id and not guest_credential:
        return False, None

    credential_valid, credential_claims = decode_guest_credential(guest_credential)
    if not credential_valid:
        reason = str(credential_claims.get("reason") or "invalid_guest_credential")
        code = "token_expired" if reason == "expired_guest_credential" else "token_invalid"
        return False, build_auth_error(code, reason=reason)

    credential_guest_id = _normalize_guest_id(credential_claims.get("sub"))
    if requested_guest_id and credential_guest_id != requested_guest_id:
        return False, build_auth_error(
            "token_invalid",
            reason="guest_credential_guest_mismatch",
        )
    return True, None


def _is_guest_credential_path(path: str) -> bool:
    if path in GUEST_ALLOWED_PATHS:
        return True
    if path.startswith("/api/files/"):
        return True
    if path.startswith("/api/analysis/jobs/") or path.startswith("/api/analysis/results/"):
        return True
    return path.startswith("/api/reports/")


def _normalize_guest_id(value: object) -> str:
    guest_id = str(value or "").strip()
    if not guest_id:
        return ""
    return guest_id if guest_id.startswith("gst_") else f"gst_{guest_id}"


def _bearer_token_from_header(header_value: str | None) -> str:
    if not header_value:
        return ""
    parts = header_value.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()

