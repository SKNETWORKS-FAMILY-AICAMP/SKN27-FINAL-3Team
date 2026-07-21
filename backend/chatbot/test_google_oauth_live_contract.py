from __future__ import annotations

import json
import os
from io import StringIO
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.test import Client, SimpleTestCase, TestCase, override_settings

from app.services.guest_credential_service import issue_guest_credential
from chatbot.models import (
    AuthEvent,
    AuthSession,
    ChatSession,
    OAuthConnection,
    SocialAccount,
    UsageEvent,
    UsageQuota,
    UserAccount,
    UserAccountStatus,
)
from chatbot.readiness import build_production_readiness_report
from chatbot.repositories import SessionBindingError


def fixture_value(*parts: str) -> str:
    return "".join(parts)


@override_settings(
    GOOGLE_CLIENT_ID="web-client.apps.googleusercontent.com",
    GOOGLE_CLIENT_SECRET=fixture_value("server-only-", "client-secret"),
    GOOGLE_POPUP_REDIRECT_URI="https://app.example.test",
    GOOGLE_TOKEN_ENDPOINT="https://oauth2.googleapis.com/token",
    GOOGLE_USERINFO_ENDPOINT="https://openidconnect.googleapis.com/v1/userinfo",
)
class GoogleOAuthLiveSmokeContractTests(SimpleTestCase):
    @override_settings(
        GOOGLE_CLIENT_ID="not-a-web-client-id",
        GOOGLE_POPUP_REDIRECT_URI="http://public.example.test/callback",
    )
    def test_smoke_rejects_invalid_web_client_and_popup_origin_config(self) -> None:
        output = StringIO()

        with self.assertRaises(CommandError):
            call_command(
                "smoke_google_oauth_code",
                "--format",
                "json",
                stdout=output,
            )

        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            set(result["config"]["invalid"]),
            {"GOOGLE_CLIENT_ID", "GOOGLE_POPUP_REDIRECT_URI"},
        )

    @override_settings(
        GOOGLE_TOKEN_ENDPOINT="https://attacker.example/token",
        GOOGLE_USERINFO_ENDPOINT="http://attacker.example/userinfo",
    )
    def test_smoke_rejects_unapproved_google_provider_endpoints(self) -> None:
        output = StringIO()

        with self.assertRaises(CommandError):
            call_command(
                "smoke_google_oauth_code",
                "--format",
                "json",
                stdout=output,
            )

        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            set(result["config"]["invalid"]),
            {"GOOGLE_TOKEN_ENDPOINT", "GOOGLE_USERINFO_ENDPOINT"},
        )

    def test_smoke_can_verify_that_google_rejects_reused_authorization_code(self) -> None:
        persisted_snapshots = []
        successful_login = {
            "contract_version": "google_auth_code.v1",
            "auth_mode": "authorization_code",
            "google": {
                "connected": True,
                "purpose": "LOGIN",
                "granted_scopes": ["openid", "email", "profile"],
                "connection_policy": "login_tokens_discarded_after_identity_verification",
            },
            "_private_oauth_tokens": {
                "access_token": fixture_value("must-not-reach-", "smoke-persistence"),
            },
        }
        replay_rejection = {
            "error": {
                "code": "token_invalid",
                "auth": {"reason": "google_token_exchange_failed:400"},
            }
        }
        output = StringIO()

        with (
            patch(
                "chatbot.management.commands.smoke_google_oauth_code.create_google_code_login",
                side_effect=[(200, successful_login), (401, replay_rejection)],
            ) as login,
            patch(
                "chatbot.management.commands.smoke_google_oauth_code.persist_current_auth_subject",
                side_effect=lambda payload, **_kwargs: (
                    persisted_snapshots.append(json.loads(json.dumps(payload)))
                    or {"status": "saved", "tables": ["social_accounts"]}
                ),
            ),
            patch.dict(
                os.environ,
                {"GOOGLE_OAUTH_SMOKE_CODE": "one-time-sensitive-code"},
            ),
        ):
            call_command(
                "smoke_google_oauth_code",
                "--require-exchange",
                "--verify-replay-rejection",
                "--format",
                "json",
                stdout=output,
            )

        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["exchange"]["auth_mode"], "authorization_code")
        self.assertEqual(result["replay_check"]["http_status"], 401)
        self.assertEqual(result["replay_check"]["status"], "rejected")
        self.assertNotIn("one-time-sensitive-code", output.getvalue())
        self.assertNotIn("_private_oauth_tokens", persisted_snapshots[0])
        self.assertEqual(login.call_count, 2)
        for call in login.call_args_list:
            self.assertEqual(
                call.kwargs["request_headers"]["Origin"],
                "https://app.example.test",
            )

    def test_smoke_does_not_treat_network_failure_as_replay_rejection(self) -> None:
        successful_login = {
            "contract_version": "google_auth_code.v1",
            "auth_mode": "authorization_code",
            "google": {},
        }
        network_failure = {
            "error": {
                "code": "provider_unavailable",
                "auth": {"reason": "google_token_exchange_unavailable"},
            }
        }
        output = StringIO()

        with (
            patch(
                "chatbot.management.commands.smoke_google_oauth_code.create_google_code_login",
                side_effect=[(200, successful_login), (503, network_failure)],
            ),
            patch(
                "chatbot.management.commands.smoke_google_oauth_code.persist_current_auth_subject",
                return_value={"status": "saved"},
            ),
            patch.dict(
                os.environ,
                {
                    "GOOGLE_OAUTH_SMOKE_CODE": (
                        "fresh-code-with-network-failure-on-replay"
                    )
                },
            ),
            self.assertRaises(CommandError),
        ):
            call_command(
                "smoke_google_oauth_code",
                "--require-exchange",
                "--verify-replay-rejection",
                "--format",
                "json",
                stdout=output,
            )

        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["replay_check"]["status"], "inconclusive")


@override_settings(
    GOOGLE_CLIENT_SECRET=fixture_value("server-only-", "client-secret"),
    APP_JWT_SECRET=fixture_value("test-app-jwt-", "secret-with-at-least-32-characters"),
    OAUTH_TOKEN_SECRET=fixture_value("test-oauth-", "secret-with-at-least-32-characters"),
)
class GoogleOAuthReadinessContractTests(SimpleTestCase):
    @staticmethod
    def _google_check() -> dict:
        report = build_production_readiness_report(include_database=False)
        return {check["name"]: check for check in report["checks"]}["google_oauth"]

    @override_settings(
        GOOGLE_CLIENT_ID="not-a-google-web-client-id",
        GOOGLE_POPUP_REDIRECT_URI="https://app.example.test",
    )
    def test_readiness_rejects_non_web_google_client_id(self) -> None:
        check = self._google_check()

        self.assertEqual(check["status"], "fail")
        self.assertTrue(
            any("Web client ID" in detail["message"] for detail in check["details"])
        )

    @override_settings(
        GOOGLE_CLIENT_ID="web-client.apps.googleusercontent.com",
        GOOGLE_POPUP_REDIRECT_URI="http://public.example.test/callback?unsafe=1",
    )
    def test_readiness_rejects_redirect_that_is_not_a_secure_origin(self) -> None:
        check = self._google_check()

        self.assertEqual(check["status"], "fail")
        self.assertTrue(
            any("secure web origin" in detail["message"] for detail in check["details"])
        )

    @override_settings(
        DEBUG=False,
        GOOGLE_CLIENT_ID="web-client.apps.googleusercontent.com",
        GOOGLE_POPUP_REDIRECT_URI="http://127.0.0.1:5173",
    )
    def test_production_readiness_rejects_loopback_http_redirect(self) -> None:
        check = self._google_check()

        self.assertEqual(check["status"], "fail")
        self.assertTrue(
            any("HTTPS" in detail["message"] for detail in check["details"])
        )

    @override_settings(
        GOOGLE_CLIENT_ID="web-client.apps.googleusercontent.com",
        GOOGLE_POPUP_REDIRECT_URI="https://app.example.test",
        GOOGLE_TOKEN_ENDPOINT="https://attacker.example/token",
        GOOGLE_USERINFO_ENDPOINT="http://attacker.example/userinfo",
    )
    def test_readiness_rejects_unapproved_google_provider_endpoints(self) -> None:
        check = self._google_check()

        self.assertEqual(check["status"], "fail")
        self.assertTrue(
            any("official Google HTTPS endpoints" in detail["message"] for detail in check["details"])
        )

    @override_settings(GOOGLE_OAUTH_TRUSTED_PROXY_CIDRS=["not-a-cidr"])
    def test_readiness_rejects_invalid_google_oauth_trusted_proxy_cidr(self) -> None:
        check = self._google_check()

        self.assertEqual(check["status"], "fail")
        self.assertTrue(
            any("trusted proxy CIDR" in detail["message"] for detail in check["details"])
        )


@override_settings(
    GOOGLE_CLIENT_ID="web-client.apps.googleusercontent.com",
    GOOGLE_POPUP_REDIRECT_URI="https://app.example.test",
)
class GoogleOAuthBoundarySanitizationTests(SimpleTestCase):
    def test_private_provider_tokens_are_removed_before_persistence(self) -> None:
        persisted_snapshots = []
        login_payload = {
            "contract_version": "google_auth_code.v1",
            "provider": "google",
            "auth_mode": "authorization_code",
            "subject": {},
            "google": {},
            "_private_oauth_tokens": {
                "access_token": fixture_value("must-never-reach-", "persistence"),
                "refresh_token": fixture_value("must-never-reach-", "persistence-either"),
            },
        }

        with (
            patch(
                "chatbot.views._create_google_code_login",
                return_value=(200, login_payload),
            ),
            patch(
                "chatbot.views.persist_current_auth_subject",
                side_effect=lambda payload, **_kwargs: (
                    persisted_snapshots.append(json.loads(json.dumps(payload)))
                    or {"status": "saved"}
                ),
            ) as persist,
            patch(
                "chatbot.views.record_usage_event",
                return_value={
                    "allowed": True,
                    "subject_type": "guest",
                },
            ),
            patch("chatbot.views._record_history_safely"),
        ):
            response = Client().post(
                "/api/auth/google/code/",
                data={
                    "provider": "google",
                    "client_id": "web-client.apps.googleusercontent.com",
                    "code": "boundary-sanitization-code",
                    "redirect_uri": "https://app.example.test",
                },
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(persist.call_count, 1)
        self.assertNotIn("_private_oauth_tokens", persisted_snapshots[0])
        self.assertNotIn("must-never-reach-persistence", json.dumps(response.json()))


@override_settings(
    APP_JWT_SECRET=fixture_value("test-app-jwt-", "secret-with-at-least-32-characters"),
    GOOGLE_CLIENT_ID="web-client.apps.googleusercontent.com",
    GOOGLE_POPUP_REDIRECT_URI="https://app.example.test",
    GOOGLE_OAUTH_TRUSTED_PROXY_CIDRS=[],
)
class GoogleOAuthRateLimitBoundaryTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def tearDown(self) -> None:
        cache.clear()

    @staticmethod
    def _provider_rejection() -> tuple[int, dict]:
        return 401, {
            "error": {
                "code": "token_invalid",
                "auth": {"reason": "authorization_code_missing"},
            }
        }

    def _post(self, *, guest_id: str, remote_addr: str, forwarded_for: str = ""):
        headers = {
            "REMOTE_ADDR": remote_addr,
            "HTTP_X_REQUESTED_WITH": "XmlHttpRequest",
            "HTTP_ORIGIN": "https://app.example.test",
            "HTTP_X_GUEST_CREDENTIAL": issue_guest_credential(guest_id)[0],
        }
        if forwarded_for:
            headers["HTTP_X_FORWARDED_FOR"] = forwarded_for
        return Client().post(
            "/api/auth/google/code/",
            data={
                "provider": "google",
                "client_id": "web-client.apps.googleusercontent.com",
                "code": "rate-boundary-code",
                "redirect_uri": "https://app.example.test",
                "guest_id": guest_id,
            },
            content_type="application/json",
            **headers,
        )

    def test_rate_limit_rejection_happens_before_google_provider_call(self) -> None:
        blocked = {
            "allowed": False,
            "subject_type": "guest",
            "scope": "google_oauth_code_exchange",
            "limit_count": 20,
            "used_count": 20,
        }
        with (
            patch("chatbot.views.record_usage_event", return_value=blocked),
            patch(
                "chatbot.views._create_google_code_login",
                return_value=self._provider_rejection(),
            ) as provider,
            patch("chatbot.views._record_history_safely"),
        ):
            response = self._post(
                guest_id="attacker-controlled",
                remote_addr="198.51.100.20",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["code"], "rate_limit_exceeded")
        provider.assert_not_called()

    def test_quota_store_failure_is_503_and_skips_google_provider(self) -> None:
        with (
            patch(
                "chatbot.views.record_usage_event",
                side_effect=DatabaseError("quota store unavailable"),
            ),
            patch(
                "chatbot.views._create_google_code_login",
                return_value=self._provider_rejection(),
            ) as provider,
            patch("chatbot.views._record_history_safely"),
        ):
            response = self._post(
                guest_id="attacker-controlled",
                remote_addr="198.51.100.21",
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "provider_unavailable")
        provider.assert_not_called()

    def test_untrusted_forwarded_header_and_body_guest_do_not_change_rate_key(self) -> None:
        subjects = []

        def allow(subject, *, scope, record_blocked_event):
            subjects.append((subject, scope))
            self.assertFalse(record_blocked_event)
            return {"allowed": True, "subject_type": "guest"}

        with (
            patch("chatbot.views.record_usage_event", side_effect=allow),
            patch(
                "chatbot.views._create_google_code_login",
                return_value=self._provider_rejection(),
            ),
            patch("chatbot.views._record_history_safely"),
        ):
            self._post(
                guest_id="first-attacker-value",
                remote_addr="198.51.100.22",
                forwarded_for="203.0.113.1",
            )
            self._post(
                guest_id="second-attacker-value",
                remote_addr="198.51.100.22",
                forwarded_for="203.0.113.2",
            )

        self.assertEqual(subjects[0], subjects[1])
        rate_subject, scope = subjects[0]
        self.assertEqual(scope, "google_oauth_code_exchange")
        self.assertTrue(rate_subject["guest_id"].startswith("oauth_"))
        self.assertNotIn("198.51.100.22", rate_subject["guest_id"])
        self.assertNotIn("attacker", rate_subject["guest_id"])

    @override_settings(GOOGLE_OAUTH_TRUSTED_PROXY_CIDRS=["10.0.0.0/8"])
    def test_trusted_proxy_chain_resolves_same_client_as_direct_request(self) -> None:
        subjects = []

        def allow(subject, *, scope, record_blocked_event):
            subjects.append((subject, scope))
            self.assertFalse(record_blocked_event)
            return {"allowed": True, "subject_type": "guest"}

        with (
            patch("chatbot.views.record_usage_event", side_effect=allow),
            patch(
                "chatbot.views._create_google_code_login",
                return_value=self._provider_rejection(),
            ),
            patch("chatbot.views._record_history_safely"),
        ):
            self._post(
                guest_id="proxy-request",
                remote_addr="10.0.0.5",
                forwarded_for="198.51.100.23, 10.0.0.4",
            )
            self._post(
                guest_id="direct-request",
                remote_addr="198.51.100.23",
            )

        self.assertEqual(subjects[0], subjects[1])


class _GoogleResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self._body


@override_settings(
    GOOGLE_CLIENT_ID="web-client.apps.googleusercontent.com",
    GOOGLE_CLIENT_SECRET=fixture_value("server-only-", "client-secret"),
    GOOGLE_POPUP_REDIRECT_URI="https://app.example.test",
    GOOGLE_TOKEN_ENDPOINT="https://oauth2.googleapis.com/token",
    GOOGLE_USERINFO_ENDPOINT="https://openidconnect.googleapis.com/v1/userinfo",
    APP_JWT_SECRET=fixture_value("test-app-jwt-", "secret-with-at-least-32-characters"),
)
class GoogleOAuthCodeEndpointIntegrationTests(TestCase):
    code = "one-time-sensitive-authorization-code"
    provider_access_token = fixture_value("provider-access-", "token-sensitive")

    def setUp(self) -> None:
        cache.clear()

    def tearDown(self) -> None:
        cache.clear()

    def _request_payload(self) -> dict:
        return {
            "provider": "google",
            "client_id": "web-client.apps.googleusercontent.com",
            "code": self.code,
            "purpose": "LOGIN",
            "scope": "openid email profile",
            "guest_id": "gst_google_live_contract",
            "session_id": "ses_google_live_contract",
            "redirect_uri": "https://app.example.test",
        }

    @staticmethod
    def _guest_credential_header(payload: dict) -> dict[str, str]:
        guest_id = str(payload.get("guest_id") or "").strip()
        if not guest_id:
            return {}
        return {"HTTP_X_GUEST_CREDENTIAL": issue_guest_credential(guest_id)[0]}

    def _successful_google_exchange(self, request, timeout=0):
        self.assertEqual(timeout, 10)
        if request.full_url == "https://oauth2.googleapis.com/token":
            form = urllib_parse.parse_qs(request.data.decode("utf-8"))
            self.assertEqual(form["code"], [self.code])
            self.assertEqual(form["client_id"], ["web-client.apps.googleusercontent.com"])
            self.assertEqual(form["client_secret"], ["server-only-client-secret"])
            self.assertEqual(form["redirect_uri"], ["https://app.example.test"])
            self.assertEqual(form["grant_type"], ["authorization_code"])
            return _GoogleResponse(
                {
                    "access_token": self.provider_access_token,
                    "expires_in": 3600,
                    "scope": "openid email profile",
                    "token_type": "Bearer",
                }
            )
        if request.full_url == "https://openidconnect.googleapis.com/v1/userinfo":
            self.assertEqual(
                request.headers["Authorization"],
                f"Bearer {self.provider_access_token}",
            )
            return _GoogleResponse(
                {
                    "sub": "google-provider-subject-192",
                    "email": "real.user@example.test",
                    "email_verified": True,
                    "name": "Real Google User",
                }
            )
        self.fail(f"Unexpected Google URL: {request.full_url}")

    @override_settings(GOOGLE_OAUTH_CODE_EXCHANGE_DAILY_LIMIT=2)
    def test_configured_daily_exchange_limit_blocks_before_third_provider_call(self) -> None:
        provider_rejection = {
            "error": {
                "code": "token_invalid",
                "auth": {"reason": "authorization_code_missing"},
            }
        }
        with patch(
            "chatbot.views._create_google_code_login",
            return_value=(401, provider_rejection),
        ) as provider:
            responses = [
                Client().post(
                    "/api/auth/google/code/",
                    data=self._request_payload(),
                    content_type="application/json",
                    REMOTE_ADDR="198.51.100.50",
                    HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                    HTTP_ORIGIN="https://app.example.test",
                    HTTP_X_GUEST_CREDENTIAL=issue_guest_credential("gst_google_live_contract")[0],
                )
                for _index in range(4)
            ]

        self.assertEqual(
            [response.status_code for response in responses],
            [401, 401, 429, 429],
        )
        self.assertEqual(provider.call_count, 2)
        quota = UsageQuota.objects.get(scope="google_oauth_code_exchange")
        self.assertEqual(quota.limit_count, 2)
        self.assertEqual(quota.used_count, 2)
        self.assertEqual(
            UsageEvent.objects.filter(scope="google_oauth_code_exchange").count(),
            2,
        )

    def test_invalid_boundary_request_does_not_consume_database_quota(self) -> None:
        response = Client().post(
            "/api/auth/google/code/",
            data={},
            content_type="application/json",
            REMOTE_ADDR="198.51.100.51",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(UsageQuota.objects.count(), 0)
        self.assertEqual(UsageEvent.objects.count(), 0)

    def test_session_binding_database_failure_is_503_before_provider_exchange(self) -> None:
        with (
            patch(
                "chatbot.views.get_chat_session_access_metadata",
                side_effect=DatabaseError("session store unavailable"),
            ),
            patch("chatbot.views._create_google_code_login") as provider,
        ):
            response = Client(raise_request_exception=False).post(
                "/api/auth/google/code/",
                data=self._request_payload(),
                content_type="application/json",
                REMOTE_ADDR="198.51.100.54",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
                **self._guest_credential_header(self._request_payload()),
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "provider_unavailable")
        self.assertEqual(
            response.json()["error"]["auth"]["reason"],
            "google_login_session_store_unavailable",
        )
        self.assertNotIn("session store unavailable", response.content.decode("utf-8"))
        provider.assert_not_called()

    def test_session_claim_race_returns_403_after_provider_exchange(self) -> None:
        successful_login = {
            "contract_version": "google_auth_code.v1",
            "provider": "google",
            "auth_mode": "authorization_code",
            "subject": {"subject_type": "user"},
            "google": {},
        }
        with (
            patch(
                "chatbot.views._create_google_code_login",
                return_value=(200, successful_login),
            ),
            patch(
                "chatbot.views.persist_current_auth_subject",
                side_effect=SessionBindingError("guest_session_binding_mismatch"),
            ),
        ):
            response = Client().post(
                "/api/auth/google/code/",
                data=self._request_payload(),
                content_type="application/json",
                REMOTE_ADDR="198.51.100.52",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
                **self._guest_credential_header(self._request_payload()),
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "forbidden")
        self.assertEqual(
            response.json()["error"]["auth"]["reason"],
            "guest_session_binding_mismatch",
        )

    def test_persistence_database_failure_returns_restartable_503(self) -> None:
        successful_login = {
            "contract_version": "google_auth_code.v1",
            "provider": "google",
            "auth_mode": "authorization_code",
            "subject": {"subject_type": "user"},
            "google": {},
        }
        with (
            patch(
                "chatbot.views._create_google_code_login",
                return_value=(200, successful_login),
            ),
            patch(
                "chatbot.views.persist_current_auth_subject",
                side_effect=DatabaseError("persistence unavailable"),
            ),
        ):
            response = Client().post(
                "/api/auth/google/code/",
                data=self._request_payload(),
                content_type="application/json",
                REMOTE_ADDR="198.51.100.53",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
                **self._guest_credential_header(self._request_payload()),
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "provider_unavailable")
        self.assertEqual(
            response.json()["error"]["required_action"],
            "restart_google_login",
        )

    def test_real_code_endpoint_exchanges_identity_and_persists_only_safe_login_state(self) -> None:
        with patch(
            "app.services.google_auth_service.urllib_request.urlopen",
            side_effect=self._successful_google_exchange,
        ) as urlopen:
            response = Client().post(
                "/api/auth/google/code/",
                data=self._request_payload(),
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
                **self._guest_credential_header(self._request_payload()),
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        serialized_body = json.dumps(body)
        self.assertEqual(body["contract_version"], "google_auth_code.v1")
        self.assertEqual(body["auth_mode"], "authorization_code")
        self.assertEqual(body["user"]["email"], "real.user@example.test")
        self.assertEqual(body["google"]["oauth_connection"]["token_storage"], "discarded_after_login")
        self.assertEqual(urlopen.call_count, 2)
        for secret in (self.code, self.provider_access_token, "server-only-client-secret"):
            self.assertNotIn(secret, serialized_body)

        social_account = SocialAccount.objects.get(
            provider="google",
            provider_user_id="google-provider-subject-192",
        )
        auth_session = AuthSession.objects.get(
            auth_session_id=body["subject"]["auth_session_id"],
        )
        auth_event = AuthEvent.objects.get(
            event_type="auth_google_code_completed",
            auth_session=auth_session,
        )
        self.assertTrue(social_account.email_verified)
        self.assertEqual(auth_session.metadata["google"]["token_storage"], "discarded_after_login")
        self.assertEqual(OAuthConnection.objects.count(), 0)
        oauth_quota = UsageQuota.objects.get(scope="google_oauth_code_exchange")
        oauth_usage = UsageEvent.objects.get(scope="google_oauth_code_exchange")
        self.assertTrue(oauth_quota.subject_id.startswith("guest:gst_oauth_"))
        self.assertNotIn("127.0.0.1", oauth_quota.subject_id)
        self.assertEqual(oauth_quota.used_count, 1)
        self.assertEqual(oauth_usage.metadata["status"], "allowed")
        persisted_metadata = json.dumps(
            {
                "social_account": social_account.metadata,
                "auth_session": auth_session.metadata,
                "auth_event": auth_event.metadata,
            }
        )
        for secret in (self.code, self.provider_access_token, "server-only-client-secret"):
            self.assertNotIn(secret, persisted_metadata)

    def test_reused_code_is_rejected_without_creating_a_second_session(self) -> None:
        exchange_count = 0
        login_payload = self._request_payload()
        login_payload.pop("guest_id")
        login_payload.pop("session_id")

        def google_exchange_then_reject_replay(request, timeout=0):
            nonlocal exchange_count
            if request.full_url == "https://oauth2.googleapis.com/token":
                exchange_count += 1
                if exchange_count == 2:
                    raise urllib_error.HTTPError(
                        request.full_url,
                        400,
                        "invalid_grant",
                        hdrs=None,
                        fp=None,
                    )
            return self._successful_google_exchange(request, timeout=timeout)

        client = Client()
        with patch(
            "app.services.google_auth_service.urllib_request.urlopen",
            side_effect=google_exchange_then_reject_replay,
        ):
            first = client.post(
                "/api/auth/google/code/",
                data=login_payload,
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
            )
            replay = client.post(
                "/api/auth/google/code/",
                data=login_payload,
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 401)
        self.assertEqual(
            replay.json()["error"]["auth"]["reason"],
            "google_token_exchange_failed:400",
        )
        self.assertNotIn(self.code, replay.content.decode("utf-8"))
        self.assertEqual(AuthSession.objects.count(), 1)
        self.assertEqual(SocialAccount.objects.count(), 1)
        self.assertEqual(OAuthConnection.objects.count(), 0)

    def test_transient_google_exchange_failure_is_503_without_login_persistence(self) -> None:
        def unavailable(request, timeout=0):
            raise urllib_error.HTTPError(
                request.full_url,
                503,
                "provider unavailable",
                hdrs=None,
                fp=None,
            )

        with patch(
            "app.services.google_auth_service.urllib_request.urlopen",
            side_effect=unavailable,
        ) as urlopen:
            response = Client().post(
                "/api/auth/google/code/",
                data=self._request_payload(),
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
                **self._guest_credential_header(self._request_payload()),
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "provider_unavailable")
        self.assertEqual(
            response.json()["error"]["required_action"],
            "restart_google_login",
        )
        self.assertNotIn("access_token", response.json())
        self.assertNotIn(self.code, response.content.decode("utf-8"))
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(AuthSession.objects.count(), 0)
        self.assertEqual(SocialAccount.objects.count(), 0)
        self.assertEqual(OAuthConnection.objects.count(), 0)

    def _assert_inactive_google_user_cannot_create_a_new_login_session(
        self,
        account_status: str,
    ) -> None:
        client = Client()
        login_payload = self._request_payload()
        login_payload.pop("guest_id")
        login_payload.pop("session_id")
        with patch(
            "app.services.google_auth_service.urllib_request.urlopen",
            side_effect=self._successful_google_exchange,
        ) as urlopen:
            first = client.post(
                "/api/auth/google/code/",
                data=login_payload,
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
            )
            self.assertEqual(first.status_code, 200)
            user_id = first.json()["subject"]["user_id"]
            UserAccount.objects.filter(user_id=user_id).update(
                status=account_status
            )

            relogin = client.post(
                "/api/auth/google/code/",
                data=login_payload,
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
            )

        self.assertEqual(relogin.status_code, 401)
        self.assertEqual(
            relogin.json()["error"]["auth"]["reason"],
            "user_account_inactive",
        )
        self.assertNotIn("access_token", relogin.json())
        self.assertEqual(urlopen.call_count, 4)
        self.assertEqual(AuthSession.objects.count(), 1)
        self.assertEqual(SocialAccount.objects.count(), 1)
        self.assertEqual(OAuthConnection.objects.count(), 0)

    def test_suspended_google_user_cannot_create_a_new_login_session(self) -> None:
        self._assert_inactive_google_user_cannot_create_a_new_login_session(
            UserAccountStatus.SUSPENDED
        )

    def test_soft_deleted_google_user_cannot_create_a_new_login_session(self) -> None:
        self._assert_inactive_google_user_cannot_create_a_new_login_session(
            UserAccountStatus.DELETED
        )

    def test_mismatched_guest_session_is_rejected_before_google_exchange(self) -> None:
        guest_response = Client().post(
            "/api/auth/guest-session/",
            data={
                "guest_id": "gst_original_browser",
                "session_id": "ses_google_binding_guard",
            },
            content_type="application/json",
            HTTP_X_GUEST_CREDENTIAL=issue_guest_credential("gst_original_browser")[0],
        )
        self.assertEqual(guest_response.status_code, 200)
        payload = self._request_payload()
        payload.update(
            {
                "guest_id": "gst_other_browser",
                "session_id": "ses_google_binding_guard",
            }
        )

        with patch(
            "app.services.google_auth_service.urllib_request.urlopen",
            side_effect=self._successful_google_exchange,
        ) as urlopen:
            response = Client(raise_request_exception=False).post(
                "/api/auth/google/code/",
                data=payload,
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
                **self._guest_credential_header(payload),
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["error"]["auth"]["reason"],
            "google_guest_session_mismatch",
        )
        self.assertEqual(urlopen.call_count, 0)
        self.assertEqual(AuthSession.objects.count(), 0)

    def test_owned_session_is_rejected_before_google_exchange(self) -> None:
        ChatSession.objects.create(
            session_id="ses_google_owned_guard",
            owner_id="usr_existing_owner",
            metadata={
                "auth_context": {
                    "guest_id": "gst_original_browser",
                    "subject_type": "user",
                }
            },
        )
        payload = self._request_payload()
        payload.update(
            {
                "guest_id": "gst_original_browser",
                "session_id": "ses_google_owned_guard",
            }
        )

        with patch(
            "app.services.google_auth_service.urllib_request.urlopen",
            side_effect=self._successful_google_exchange,
        ) as urlopen:
            response = Client(raise_request_exception=False).post(
                "/api/auth/google/code/",
                data=payload,
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
                **self._guest_credential_header(payload),
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["error"]["auth"]["reason"],
            "google_session_already_owned",
        )
        self.assertEqual(urlopen.call_count, 0)
        self.assertEqual(AuthSession.objects.count(), 0)
