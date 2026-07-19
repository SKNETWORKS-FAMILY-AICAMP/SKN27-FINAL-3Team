"""Auth error envelope contract for the Django mock API."""

from __future__ import annotations

from typing import Any


AUTH_ERROR_CONTRACT_VERSION = "auth_error.v1"
AUTH_SCHEME = "Bearer"

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
    "provider_unavailable": {
        "status": 503,
        "message": "외부 로그인 서비스를 일시적으로 사용할 수 없습니다.",
        "required_action": "restart_google_login",
        "reason": "provider_unavailable",
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
            "contract_version": AUTH_ERROR_CONTRACT_VERSION,
            "type": "auth",
            "code": code if code in AUTH_ERROR_TEMPLATES else "token_invalid",
            "message": message or template["message"],
            "status": template["status"],
            "missing_fields": [],
            "retryable": False,
            "required_action": template["required_action"],
            "auth": {
                "scheme": AUTH_SCHEME,
                "reason": auth_reason,
            },
        }
    }


def build_www_authenticate_header(error_body: dict[str, Any]) -> str:
    """Build the HTTP auth challenge header for JWT/Bearer failures."""

    error = error_body.get("error", {})
    auth = error.get("auth", {})
    reason = auth.get("reason") or "invalid_token"
    code = error.get("code") or "token_invalid"
    return f'{AUTH_SCHEME} error="{code}", error_description="{reason}"'


def list_auth_error_contracts() -> dict[str, dict[str, Any]]:
    """Return public auth error examples for docs/tests."""

    return {
        code: build_auth_error(code)["error"]
        for code in sorted(AUTH_ERROR_TEMPLATES)
    }
