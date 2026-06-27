"""Auth error envelope contract for the Django mock API."""

from __future__ import annotations

from typing import Any


AUTH_ERROR_TEMPLATES: dict[str, dict[str, Any]] = {
    "auth_required": {
        "status": 401,
        "message": "로그인이 필요합니다.",
        "required_action": "login",
        "reason": "missing_token",
    },
    "token_invalid": {
        "status": 401,
        "message": "인증 토큰을 확인할 수 없습니다.",
        "required_action": "login",
        "reason": "invalid_token",
    },
    "token_expired": {
        "status": 401,
        "message": "로그인이 만료되었습니다. 다시 로그인해 주세요.",
        "required_action": "login",
        "reason": "expired_token",
    },
    "forbidden": {
        "status": 403,
        "message": "요청한 리소스에 접근할 권한이 없습니다.",
        "required_action": "none",
        "reason": "permission_denied",
    },
}


def build_auth_error(
    code: str,
    *,
    reason: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """Build the shared JWT/auth failure envelope."""

    template = AUTH_ERROR_TEMPLATES.get(code, AUTH_ERROR_TEMPLATES["token_invalid"])
    auth_reason = reason or template["reason"]
    return {
        "error": {
            "code": code if code in AUTH_ERROR_TEMPLATES else "token_invalid",
            "message": message or template["message"],
            "status": template["status"],
            "missing_fields": [],
            "retryable": False,
            "required_action": template["required_action"],
            "auth": {
                "scheme": "Bearer",
                "reason": auth_reason,
            },
        }
    }


def list_auth_error_contracts() -> dict[str, dict[str, Any]]:
    """Return public auth error examples for docs/tests."""

    return {
        code: build_auth_error(code)["error"]
        for code in sorted(AUTH_ERROR_TEMPLATES)
    }


def is_valid_mock_bearer_header(header_value: str | None) -> tuple[bool, dict[str, Any] | None]:
    """Validate only the mock Bearer header shape, not JWT signatures."""

    if not header_value:
        return False, build_auth_error("auth_required")

    parts = header_value.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False, build_auth_error("token_invalid", reason="malformed_authorization_header")

    token = parts[1].strip()
    if not token:
        return False, build_auth_error("token_invalid", reason="empty_token")
    if token == "expired":
        return False, build_auth_error("token_expired")
    if token == "invalid":
        return False, build_auth_error("token_invalid")

    return True, None
