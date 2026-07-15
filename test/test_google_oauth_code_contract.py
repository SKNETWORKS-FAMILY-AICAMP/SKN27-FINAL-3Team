from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace
from urllib import error as urllib_error

import pytest

from app.services import google_auth_service


CONFIG = {
    "GOOGLE_CLIENT_ID": "web-client.apps.googleusercontent.com",
    "GOOGLE_CLIENT_SECRET": "server-only-client-secret",
    "GOOGLE_POPUP_REDIRECT_URI": "https://app.example.test",
    "APP_JWT_SECRET": "test-app-jwt-secret-at-least-32-characters",
}


def _configure_google(monkeypatch) -> None:
    monkeypatch.setattr(
        google_auth_service,
        "_django_setting",
        lambda name, default="": CONFIG.get(name, default),
    )
    monkeypatch.setattr(
        google_auth_service,
        "_google_token_response_from_code",
        lambda _payload, _code: (
            200,
            {
                "access_token": "provider-access-token",
                "id_token": "provider-id-token",
                "expires_in": 3600,
                "scope": "openid email profile",
            },
        ),
    )
    monkeypatch.setattr(
        google_auth_service,
        "_google_profile_from_code_tokens",
        lambda _token_payload, _payload: {
            "sub": "google-subject-123",
            "email": "driver@example.test",
            "email_verified": True,
            "display_name": "Driver",
            "picture": "",
            "aud": CONFIG["GOOGLE_CLIENT_ID"],
            "verification": "google_id_token_verified",
        },
    )


def _valid_payload() -> dict:
    return {
        "provider": "google",
        "client_id": CONFIG["GOOGLE_CLIENT_ID"],
        "code": "one-time-authorization-code",
        "scope": "openid email profile",
        "redirect_uri": CONFIG["GOOGLE_POPUP_REDIRECT_URI"],
    }


def _valid_headers() -> dict:
    return {
        "X-Requested-With": "XmlHttpRequest",
        "Origin": CONFIG["GOOGLE_POPUP_REDIRECT_URI"],
    }


@pytest.mark.parametrize(
    ("missing_field", "headers", "expected_status", "expected_reason"),
    [
        ("code", _valid_headers(), 401, "authorization_code_missing"),
        ("client_id", _valid_headers(), 401, "google_client_id_missing"),
        ("redirect_uri", _valid_headers(), 401, "google_redirect_uri_missing"),
        (
            None,
            {"Origin": CONFIG["GOOGLE_POPUP_REDIRECT_URI"]},
            403,
            "invalid_google_code_request_header",
        ),
        (
            None,
            {"X-Requested-With": "XmlHttpRequest"},
            403,
            "google_origin_missing",
        ),
    ],
)
def test_google_code_boundary_rejects_invalid_requests_without_provider_exchange(
    monkeypatch,
    missing_field: str | None,
    headers: dict,
    expected_status: int,
    expected_reason: str,
) -> None:
    _configure_google(monkeypatch)
    payload = _valid_payload()
    if missing_field is not None:
        payload.pop(missing_field)
    exchange_calls = []
    monkeypatch.setattr(
        google_auth_service,
        "_google_token_response_from_code",
        lambda *_args, **_kwargs: exchange_calls.append(True),
    )

    result = google_auth_service.validate_google_code_request_boundary(payload, headers)

    assert result is not None
    status, response = result
    assert status == expected_status
    assert response["error"]["auth"]["reason"] == expected_reason
    assert exchange_calls == []


def test_google_code_boundary_accepts_valid_request_without_provider_exchange(monkeypatch) -> None:
    _configure_google(monkeypatch)
    exchange_calls = []
    monkeypatch.setattr(
        google_auth_service,
        "_google_token_response_from_code",
        lambda *_args, **_kwargs: exchange_calls.append(True),
    )

    result = google_auth_service.validate_google_code_request_boundary(
        _valid_payload(),
        _valid_headers(),
    )

    assert result is None
    assert exchange_calls == []


def test_google_code_login_rejects_non_login_purpose_before_exchange(monkeypatch) -> None:
    _configure_google(monkeypatch)
    payload = _valid_payload()
    payload["purpose"] = "GOOGLE_DRIVE_CONNECT"
    exchange_calls = []

    def exchange(_payload, _code):
        exchange_calls.append(True)
        return 200, {
            "access_token": "provider-access-token",
            "id_token": "provider-id-token",
            "scope": "openid email profile",
        }

    monkeypatch.setattr(
        google_auth_service,
        "_google_token_response_from_code",
        exchange,
    )

    status, response = google_auth_service.create_google_code_login(
        payload,
        request_headers=_valid_headers(),
    )

    assert status == 401
    assert response["error"]["auth"]["reason"] == "google_login_purpose_invalid"
    assert exchange_calls == []


def test_google_code_login_rejects_missing_browser_origin_before_exchange(monkeypatch) -> None:
    _configure_google(monkeypatch)

    status, payload = google_auth_service.create_google_code_login(
        _valid_payload(),
        request_headers={"X-Requested-With": "XmlHttpRequest"},
    )

    assert status == 403
    assert payload["error"]["auth"]["reason"] == "google_origin_missing"


def test_google_code_login_rejects_origin_mismatch_before_exchange(monkeypatch) -> None:
    _configure_google(monkeypatch)

    status, payload = google_auth_service.create_google_code_login(
        _valid_payload(),
        request_headers={
            "X-Requested-With": "XmlHttpRequest",
            "Origin": "https://attacker.example",
        },
    )

    assert status == 403
    assert payload["error"]["auth"]["reason"] == "google_origin_mismatch"


def test_google_code_login_rejects_redirect_uri_mismatch_before_exchange(monkeypatch) -> None:
    _configure_google(monkeypatch)
    payload = _valid_payload()
    payload["redirect_uri"] = "https://other.example.test"

    status, response = google_auth_service.create_google_code_login(
        payload,
        request_headers=_valid_headers(),
    )

    assert status == 401
    assert response["error"]["auth"]["reason"] == "google_redirect_uri_mismatch"


def test_google_code_login_rejects_frontend_client_id_mismatch_before_exchange(monkeypatch) -> None:
    _configure_google(monkeypatch)
    payload = _valid_payload()
    payload["client_id"] = "other-client.apps.googleusercontent.com"

    status, response = google_auth_service.create_google_code_login(
        payload,
        request_headers=_valid_headers(),
    )

    assert status == 401
    assert response["error"]["auth"]["reason"] == "google_client_id_mismatch"


def test_google_code_login_rejects_missing_frontend_client_id_before_exchange(monkeypatch) -> None:
    _configure_google(monkeypatch)
    payload = _valid_payload()
    payload.pop("client_id")

    status, response = google_auth_service.create_google_code_login(
        payload,
        request_headers=_valid_headers(),
    )

    assert status == 401
    assert response["error"]["auth"]["reason"] == "google_client_id_missing"


def test_google_code_login_rejects_invalid_redirect_uri_before_exchange(monkeypatch) -> None:
    _configure_google(monkeypatch)
    payload = _valid_payload()
    payload["redirect_uri"] = "https://app.example.test/oauth/callback?code=unsafe"

    status, response = google_auth_service.create_google_code_login(
        payload,
        request_headers=_valid_headers(),
    )

    assert status == 401
    assert response["error"]["auth"]["reason"] == "google_redirect_uri_invalid"


def test_google_code_login_rejects_missing_redirect_uri_before_exchange(monkeypatch) -> None:
    _configure_google(monkeypatch)
    payload = _valid_payload()
    payload.pop("redirect_uri")

    status, response = google_auth_service.create_google_code_login(
        payload,
        request_headers=_valid_headers(),
    )

    assert status == 401
    assert response["error"]["auth"]["reason"] == "google_redirect_uri_missing"


def test_google_code_login_never_posts_secret_to_unapproved_token_endpoint(monkeypatch) -> None:
    monkeypatch.setitem(CONFIG, "GOOGLE_TOKEN_ENDPOINT", "https://attacker.example/token")
    monkeypatch.setattr(
        google_auth_service,
        "_django_setting",
        lambda name, default="": CONFIG.get(name, default),
    )
    urlopen_calls = []
    monkeypatch.setattr(
        google_auth_service.urllib_request,
        "urlopen",
        lambda *_args, **_kwargs: urlopen_calls.append(True),
    )

    status, response = google_auth_service.create_google_code_login(
        _valid_payload(),
        request_headers=_valid_headers(),
    )

    assert status == 401
    assert response["error"]["auth"]["reason"] == "google_token_endpoint_invalid"
    assert urlopen_calls == []


@pytest.mark.parametrize("provider_status", [429, 500, 503])
def test_google_token_exchange_maps_transient_http_errors_to_503(
    monkeypatch,
    provider_status: int,
) -> None:
    monkeypatch.setattr(
        google_auth_service,
        "_django_setting",
        lambda name, default="": CONFIG.get(name, default),
    )
    urlopen_calls = []

    def fail_exchange(request, timeout=0):
        urlopen_calls.append((request.full_url, timeout))
        raise urllib_error.HTTPError(
            request.full_url,
            provider_status,
            "provider failure",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(google_auth_service.urllib_request, "urlopen", fail_exchange)

    status, response = google_auth_service._google_token_response_from_code(
        _valid_payload(),
        _valid_payload()["code"],
    )

    assert status == 503
    assert response["error"]["code"] == "provider_unavailable"
    assert response["error"]["retryable"] is False
    assert response["error"]["required_action"] == "restart_google_login"
    assert len(urlopen_calls) == 1


def test_google_token_exchange_keeps_invalid_grant_as_401(monkeypatch) -> None:
    monkeypatch.setattr(
        google_auth_service,
        "_django_setting",
        lambda name, default="": CONFIG.get(name, default),
    )

    def reject_code(request, timeout=0):
        raise urllib_error.HTTPError(
            request.full_url,
            400,
            "invalid grant",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(google_auth_service.urllib_request, "urlopen", reject_code)

    status, response = google_auth_service._google_token_response_from_code(
        _valid_payload(),
        _valid_payload()["code"],
    )

    assert status == 401
    assert response["error"]["code"] == "token_invalid"
    assert response["error"]["auth"]["reason"] == "google_token_exchange_failed:400"


@pytest.mark.parametrize("provider_error", [urllib_error.URLError("offline"), TimeoutError()])
def test_google_token_exchange_maps_network_failure_to_503(
    monkeypatch,
    provider_error: Exception,
) -> None:
    monkeypatch.setattr(
        google_auth_service,
        "_django_setting",
        lambda name, default="": CONFIG.get(name, default),
    )
    urlopen_calls = []

    def fail_exchange(request, timeout=0):
        urlopen_calls.append((request.full_url, timeout))
        raise provider_error

    monkeypatch.setattr(google_auth_service.urllib_request, "urlopen", fail_exchange)

    status, response = google_auth_service._google_token_response_from_code(
        _valid_payload(),
        _valid_payload()["code"],
    )

    assert status == 503
    assert response["error"]["code"] == "provider_unavailable"
    assert len(urlopen_calls) == 1


def test_google_userinfo_transient_failure_maps_to_503(monkeypatch) -> None:
    monkeypatch.setattr(
        google_auth_service,
        "_django_setting",
        lambda name, default="": CONFIG.get(name, default),
    )
    monkeypatch.setattr(
        google_auth_service,
        "_google_token_response_from_code",
        lambda _payload, _code: (200, {"access_token": "provider-access-token"}),
    )
    urlopen_calls = []

    def fail_userinfo(request, timeout=0):
        urlopen_calls.append((request.full_url, timeout))
        raise urllib_error.URLError("offline")

    monkeypatch.setattr(google_auth_service.urllib_request, "urlopen", fail_userinfo)

    status, response = google_auth_service.create_google_code_login(
        _valid_payload(),
        request_headers=_valid_headers(),
    )

    assert status == 503
    assert response["error"]["code"] == "provider_unavailable"
    assert response["error"]["auth"]["reason"] == "google_userinfo_unavailable"
    assert len(urlopen_calls) == 1


def test_google_id_token_transport_failure_maps_to_provider_unavailable(monkeypatch) -> None:
    class ProviderTransportError(Exception):
        pass

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "google.auth.transport":
            return SimpleNamespace(requests=SimpleNamespace(Request=lambda: object()))
        if name == "google.oauth2":
            return SimpleNamespace(
                id_token=SimpleNamespace(
                    verify_oauth2_token=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                        ProviderTransportError("cert endpoint offline")
                    )
                )
            )
        if name == "google.auth.exceptions":
            return SimpleNamespace(TransportError=ProviderTransportError)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(
        google_auth_service,
        "_django_setting",
        lambda name, default="": CONFIG.get(name, default),
    )

    with pytest.raises(google_auth_service.GoogleProviderUnavailable) as exc_info:
        google_auth_service._verified_google_profile("provider-id-token")

    assert exc_info.value.reason == "google_id_token_verification_unavailable"


def test_google_code_identity_falls_back_to_userinfo_after_id_token_transport_failure(
    monkeypatch,
) -> None:
    def fail_id_token(_id_token):
        raise google_auth_service.GoogleProviderUnavailable(
            "google_id_token_verification_unavailable"
        )

    expected_profile = {
        "sub": "google-subject-123",
        "email": "driver@example.test",
        "email_verified": True,
        "display_name": "Driver",
        "picture": "",
        "aud": "",
        "verification": "google_userinfo_verified",
    }
    userinfo_calls = []
    monkeypatch.setattr(google_auth_service, "_verified_google_profile", fail_id_token)
    monkeypatch.setattr(
        google_auth_service,
        "_fetch_google_userinfo",
        lambda access_token: userinfo_calls.append(access_token) or expected_profile,
    )

    profile = google_auth_service._google_profile_from_code_tokens(
        {
            "id_token": "provider-id-token",
            "access_token": "provider-access-token",
        },
        {},
    )

    assert profile == expected_profile
    assert userinfo_calls == ["provider-access-token"]


def test_google_code_login_returns_503_when_id_token_and_userinfo_are_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        google_auth_service,
        "_django_setting",
        lambda name, default="": CONFIG.get(name, default),
    )
    monkeypatch.setattr(
        google_auth_service,
        "_google_token_response_from_code",
        lambda _payload, _code: (
            200,
            {
                "id_token": "provider-id-token",
                "access_token": "provider-access-token",
            },
        ),
    )

    def fail_id_token(_id_token):
        raise google_auth_service.GoogleProviderUnavailable(
            "google_id_token_verification_unavailable"
        )

    userinfo_calls = []
    monkeypatch.setattr(google_auth_service, "_verified_google_profile", fail_id_token)
    monkeypatch.setattr(
        google_auth_service,
        "_fetch_google_userinfo",
        lambda access_token: userinfo_calls.append(access_token),
    )

    status, response = google_auth_service.create_google_code_login(
        _valid_payload(),
        request_headers=_valid_headers(),
    )

    assert status == 503
    assert response["error"]["code"] == "provider_unavailable"
    assert response["error"]["auth"]["reason"] == "google_id_token_verification_unavailable"
    assert userinfo_calls == ["provider-access-token"]


def test_legacy_google_login_returns_503_for_id_token_transport_failure(monkeypatch) -> None:
    def fail_profile(_payload):
        raise google_auth_service.GoogleProviderUnavailable(
            "google_id_token_verification_unavailable"
        )

    monkeypatch.setattr(google_auth_service, "_google_profile_from_payload", fail_profile)

    status, response = google_auth_service.create_google_login(
        {"provider": "google", "id_token": "provider-id-token"}
    )

    assert status == 503
    assert response["error"]["code"] == "provider_unavailable"
    assert response["error"]["auth"]["reason"] == "google_id_token_verification_unavailable"


def test_google_code_login_does_not_treat_requested_scopes_as_granted(monkeypatch) -> None:
    _configure_google(monkeypatch)
    monkeypatch.setattr(
        google_auth_service,
        "_google_token_response_from_code",
        lambda _payload, _code: (
            200,
            {
                "access_token": "provider-access-token",
                "id_token": "provider-id-token",
                "expires_in": 3600,
            },
        ),
    )
    payload = _valid_payload()
    payload["scope"] = "openid email profile https://www.googleapis.com/auth/drive"

    status, response = google_auth_service.create_google_code_login(
        payload,
        request_headers=_valid_headers(),
    )

    assert status == 200
    assert response["google"]["granted_scopes"] == []
    assert response["google"]["oauth_connection"]["granted_scopes"] == []


def test_google_code_identity_preserves_provider_email_verification(monkeypatch) -> None:
    monkeypatch.setattr(
        google_auth_service,
        "_verified_google_profile",
        lambda _id_token: {
            "sub": "google-subject-123",
            "email": "unverified@example.test",
            "email_verified": False,
            "display_name": "Unverified",
            "picture": "",
            "aud": CONFIG["GOOGLE_CLIENT_ID"],
            "verification": "google_id_token_verified",
        },
    )

    profile = google_auth_service._google_profile_from_code_tokens(
        {"id_token": "provider-id-token"},
        {},
    )

    assert profile is not None
    assert profile["email_verified"] is False


def test_smoke_text_output_has_no_removed_mock_setting_dependency() -> None:
    content = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "chatbot"
        / "management"
        / "commands"
        / "smoke_google_oauth_code.py"
    ).read_text(encoding="utf-8")

    assert "config['mock_allowed']" not in content
    assert 'parser.add_argument("--code",' not in content
    assert "GOOGLE_OAUTH_SMOKE_CODE" in content
    assert "getpass(" in content


def test_local_env_example_requires_real_google_code_flow() -> None:
    content = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")

    assert "GOOGLE_CLIENT_ID=" in content
    assert "GOOGLE_CLIENT_SECRET=" in content
    assert "GOOGLE_POPUP_REDIRECT_URI=" in content
    assert "APP_JWT_SECRET=" in content
    assert "OAUTH_TOKEN_SECRET=" in content
    assert "GOOGLE_OAUTH_CODE_EXCHANGE_DAILY_LIMIT=" in content
    assert "GOOGLE_OAUTH_TRUSTED_PROXY_CIDRS=" in content
    assert "GOOGLE_AUTH_ALLOW_MOCK" not in content
    assert "APP_AUTH_ALLOW_MOCK_BEARER" not in content
    assert "VITE_GOOGLE_LOCAL_AUTH_MODE" not in content


def test_frontend_sends_public_client_id_with_authorization_code() -> None:
    content = (Path(__file__).resolve().parents[1] / "app" / "web" / "authSession.js").read_text(
        encoding="utf-8"
    )

    assert "client_id: String(googleClientId || \"\").trim()" in content
    assert "select_account: true" in content
    assert 'prompt: "consent"' not in content


def test_docker_runtime_has_no_removed_google_mock_switches() -> None:
    content = (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )

    assert "GOOGLE_AUTH_ALLOW_MOCK" not in content
    assert "APP_AUTH_ALLOW_MOCK_BEARER" not in content
    assert "VITE_DEV_AUTH_TOKEN" not in content


def test_runtime_auth_boundary_has_no_legacy_mock_service_or_bearer_validator() -> None:
    root = Path(__file__).resolve().parents[1]
    auth_error_source = (root / "app" / "services" / "auth_error_contract.py").read_text(
        encoding="utf-8"
    )
    views_source = (root / "backend" / "chatbot" / "views.py").read_text(
        encoding="utf-8"
    )

    assert not (root / "app" / "services" / "auth_session_mock_service.py").exists()
    assert "is_valid_mock_bearer_header" not in auth_error_source
    assert "auth_session_mock_service" not in views_source
