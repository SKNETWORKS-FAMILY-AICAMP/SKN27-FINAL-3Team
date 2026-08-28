"""Contract tests for the D12 GetCurrentAuthIdentity application boundary."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.contracts import api_route_specs
from app.contracts.openapi_v1 import build_openapi_document
from app.services.guest_credential_service import issue_guest_credential
from app.services.google_auth_service import issue_access_token
from chatbot.models import (
    AuthSession,
    AuthSessionStatus,
    GuestIdentity,
    GuestIdentityStatus,
    UserAccount,
)
from chatbot.repositories import SessionBindingError


TEST_JWT_SIGNING_KEY = "d12-get-current-auth-identity-test-signing-key"


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class GetCurrentAuthIdentitySecurityContractTests(TestCase):
    def _guest_client(self, guest_id: str = "gst_d12_guest") -> Client:
        credential, _claims = issue_guest_credential(guest_id)
        return Client(
            raise_request_exception=False,
            HTTP_X_GUEST_ID=guest_id,
            HTTP_X_GUEST_CREDENTIAL=credential,
        )

    def test_external_anonymous_transport_remains_auth_required(self) -> None:
        response = Client().get("/api/auth/me/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "auth_required")

    def test_openapi_requires_bearer_or_signed_guest_credential(self) -> None:
        spec = next(
            candidate
            for candidate in api_route_specs.AUTH_SESSION_API_ROUTE_SPECS
            if candidate.method == "GET" and candidate.path == "/api/auth/me/"
        )
        document = build_openapi_document()
        operation = document["paths"]["/api/auth/me/"]["get"]

        self.assertEqual(
            spec.security_requirements,
            ({"bearerAuth": ()}, {"guestCredentialAuth": ()}),
        )
        self.assertFalse(spec.auth_optional)
        self.assertNotIn("anonymous", spec.summary.lower())
        self.assertEqual(
            operation["security"],
            [{"bearerAuth": []}, {"guestCredentialAuth": []}],
        )
        self.assertIn("auth_required", operation["responses"]["401"]["x-error-codes"])

    def test_conflicting_header_and_query_guest_ids_fail_closed(self) -> None:
        client = self._guest_client("gst_d12_header")

        response = client.get("/api/auth/me/?guest_id=gst_d12_query")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "token_invalid")
        self.assertEqual(
            response.json()["error"]["auth"]["reason"],
            "guest_identity_source_mismatch",
        )

    def test_existing_expired_guest_identity_fails_closed(self) -> None:
        GuestIdentity.objects.create(
            guest_id="gst_d12_expired",
            status=GuestIdentityStatus.EXPIRED,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        response = self._guest_client("gst_d12_expired").get("/api/auth/me/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "token_invalid")
        self.assertEqual(response.json()["error"]["auth"]["reason"], "guest_expired")

    def test_signed_guest_without_persisted_row_keeps_bootstrap_contract(self) -> None:
        response = self._guest_client("gst_d12_bootstrap").get("/api/auth/me/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["subject"]["guest_id"], "gst_d12_bootstrap")
        self.assertTrue(GuestIdentity.objects.filter(guest_id="gst_d12_bootstrap").exists())

    def test_persisted_session_binding_error_maps_to_forbidden(self) -> None:
        with patch(
            "chatbot.views.persist_current_auth_subject",
            side_effect=SessionBindingError("guest_session_binding_mismatch"),
        ):
            response = self._guest_client("gst_d12_binding").get("/api/auth/me/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "forbidden")
        self.assertEqual(
            response.json()["error"]["auth"]["reason"],
            "guest_session_binding_mismatch",
        )

    def test_persistence_database_error_maps_to_retryable_provider_unavailable(self) -> None:
        with patch(
            "chatbot.views.persist_current_auth_subject",
            side_effect=DatabaseError("auth persistence unavailable"),
        ):
            response = self._guest_client("gst_d12_database").get("/api/auth/me/")

        self.assertEqual(response.status_code, 503)
        error = response.json()["error"]
        self.assertEqual(error["code"], "provider_unavailable")
        self.assertEqual(error["auth"]["reason"], "auth_me_persistence_unavailable")
        self.assertEqual(error["required_action"], "retry")

    def test_history_failure_does_not_change_a_successful_response(self) -> None:
        with patch(
            "chatbot.views.record_history_event_record",
            side_effect=DatabaseError("history persistence unavailable"),
        ):
            response = self._guest_client("gst_d12_history").get("/api/auth/me/")

        self.assertEqual(response.status_code, 200, response.content)

    def test_valid_jwt_without_persisted_active_session_is_rejected(self) -> None:
        token, _claims = issue_access_token(
            user_id="usr_d12_unpersisted",
            auth_session_id="auth_d12_unpersisted",
        )

        response = Client(HTTP_AUTHORIZATION=f"Bearer {token}").get("/api/auth/me/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["error"]["auth"]["reason"],
            "auth_session_not_persisted",
        )

    def test_active_persisted_jwt_keeps_the_public_auth_me_contract(self) -> None:
        issued_at = timezone.now()
        expires_at = issued_at + timedelta(hours=1)
        token, _claims = issue_access_token(
            user_id="usr_d12_active",
            auth_session_id="auth_d12_active",
            issued_at=issued_at,
            expires_at=expires_at,
        )
        user = UserAccount.objects.create(user_id="usr_d12_active")
        AuthSession.objects.create(
            auth_session_id="auth_d12_active",
            user=user,
            subject_type="user",
            subject_id="user:usr_d12_active",
            status=AuthSessionStatus.ACTIVE,
            issued_at=issued_at,
            expires_at=expires_at,
        )

        response = Client(HTTP_AUTHORIZATION=f"Bearer {token}").get("/api/auth/me/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["subject"]["user_id"], "usr_d12_active")

    def test_auth_me_delegates_to_execute_get_current_auth_identity(self) -> None:
        with patch(
            "chatbot.views.execute_get_current_auth_identity",
            create=True,
        ) as executor:
            response = self._guest_client("gst_d12_executor").get("/api/auth/me/")

        self.assertEqual(response.status_code, 200, response.content)
        executor.assert_called_once()

    def test_public_response_excludes_credentials_and_raw_claims(self) -> None:
        response = self._guest_client("gst_d12_private").get("/api/auth/me/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(
            _private_response_keys(response.json()).intersection(
                {
                    "access_token",
                    "refresh_token",
                    "guest_credential",
                    "authorization",
                    "jwt",
                    "claims",
                    "secret",
                    "private_key",
                }
            )
        )


def _private_response_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {
            key.lower()
            for key in value
        }.union(*( _private_response_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*( _private_response_keys(item) for item in value))
    return set()
