"""Security and application contracts for the D13 IssueGuestSession boundary."""

from __future__ import annotations

from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.guest_credential_service import decode_guest_credential, issue_guest_credential
from chatbot.models import AuthEvent, ChatSession, GuestIdentity, GuestIdentityStatus, HistoryEvent


TEST_JWT_SIGNING_KEY = "d13-issue-guest-session-test-signing-key"
SENSITIVE_MARKERS = {
    "access_token": "d13-access-token-marker",
    "guest_credential": "d13-guest-credential-marker",
    "refresh_token": "d13-refresh-token-marker",
    "authorization": "d13-authorization-marker",
    "secret": "d13-nested-secret-marker",
}


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class IssueGuestSessionSecurityContractTests(TestCase):
    def test_guest_session_does_not_persist_request_secret_markers(self) -> None:
        response = Client(raise_request_exception=False).post(
            "/api/auth/guest-session/",
            data={
                "access_token": SENSITIVE_MARKERS["access_token"],
                "guest_credential": SENSITIVE_MARKERS["guest_credential"],
                "refresh_token": SENSITIVE_MARKERS["refresh_token"],
                "authorization": SENSITIVE_MARKERS["authorization"],
                "nested": {"secret": SENSITIVE_MARKERS["secret"]},
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["guest_credential"])
        auth_event = AuthEvent.objects.get(event_type="guest_session_created")
        history_event = HistoryEvent.objects.get(event_type="guest_session_created")
        self.assertNotIn("raw_payload", auth_event.metadata)
        self.assertFalse(_contains_any_marker(auth_event.metadata))
        self.assertFalse(_contains_any_marker(history_event.metadata))

    def test_expired_persisted_guest_is_not_reactivated(self) -> None:
        guest_id = "gst_d13_expired"
        credential, _claims = issue_guest_credential(guest_id)
        guest = GuestIdentity.objects.create(
            guest_id=guest_id,
            status=GuestIdentityStatus.EXPIRED,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        response = Client(
            raise_request_exception=False,
            HTTP_X_GUEST_CREDENTIAL=credential,
        ).post("/api/auth/guest-session/", data={}, content_type="application/json")

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["code"], "token_invalid")
        self.assertEqual(response.json()["error"]["auth"]["reason"], "guest_expired")
        guest.refresh_from_db()
        self.assertEqual(guest.status, GuestIdentityStatus.EXPIRED)
        self.assertLessEqual(guest.expires_at, timezone.now())
        self.assertFalse(AuthEvent.objects.filter(guest=guest).exists())
        self.assertFalse(HistoryEvent.objects.filter(event_type="guest_session_created").exists())

    def test_merged_persisted_guest_is_not_reactivated(self) -> None:
        guest_id = "gst_d13_merged"
        credential, _claims = issue_guest_credential(guest_id)
        guest = GuestIdentity.objects.create(
            guest_id=guest_id,
            status=GuestIdentityStatus.MERGED,
            expires_at=timezone.now() + timedelta(days=1),
        )

        response = Client(
            raise_request_exception=False,
            HTTP_X_GUEST_CREDENTIAL=credential,
        ).post("/api/auth/guest-session/", data={}, content_type="application/json")

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["code"], "token_invalid")
        self.assertEqual(response.json()["error"]["auth"]["reason"], "guest_inactive")
        guest.refresh_from_db()
        self.assertEqual(guest.status, GuestIdentityStatus.MERGED)
        self.assertFalse(AuthEvent.objects.filter(guest=guest).exists())
        self.assertFalse(HistoryEvent.objects.filter(event_type="guest_session_created").exists())

    def test_truthy_non_object_json_normalizes_to_a_new_unbound_guest(self) -> None:
        response = Client(raise_request_exception=False).post(
            "/api/auth/guest-session/",
            data='["unexpected"]',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        credential_valid, claims = decode_guest_credential(payload["guest_credential"])
        self.assertTrue(credential_valid)
        self.assertEqual(claims["sub"], payload["guest"]["guest_id"])
        self.assertIsNone(payload["session_binding"]["session_id"])

    def test_invalid_credential_issues_a_new_unbound_guest_without_adopting_body_identity(self) -> None:
        foreign_session = ChatSession.objects.create(
            session_id="ses_d13_invalid_credential_foreign",
            metadata={"auth_context": {"guest_id": "gst_d13_other", "subject_type": "guest"}},
        )

        response = Client(raise_request_exception=False, HTTP_X_GUEST_CREDENTIAL="tampered").post(
            "/api/auth/guest-session/",
            data={
                "guest_id": "gst_d13_forged",
                "session_id": foreign_session.session_id,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertNotEqual(payload["guest"]["guest_id"], "gst_d13_forged")
        self.assertIsNone(payload["session_binding"]["session_id"])
        credential_valid, claims = decode_guest_credential(payload["guest_credential"])
        self.assertTrue(credential_valid)
        self.assertEqual(claims["sub"], payload["guest"]["guest_id"])
        foreign_session.refresh_from_db()
        self.assertEqual(
            foreign_session.metadata["auth_context"]["guest_id"],
            "gst_d13_other",
        )
        auth_event = AuthEvent.objects.get(event_type="guest_session_created")
        self.assertFalse(_contains_value(auth_event.metadata, "tampered"))

    def test_foreign_guest_session_binding_remains_forbidden(self) -> None:
        credential, _claims = issue_guest_credential("gst_d13_requester")
        foreign_session = ChatSession.objects.create(
            session_id="ses_d13_foreign_guest",
            metadata={"auth_context": {"guest_id": "gst_d13_other", "subject_type": "guest"}},
        )

        response = Client(
            raise_request_exception=False,
            HTTP_X_GUEST_CREDENTIAL=credential,
        ).post(
            "/api/auth/guest-session/",
            data={"session_id": foreign_session.session_id},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "forbidden")
        self.assertEqual(
            response.json()["error"]["auth"]["reason"],
            "guest_session_binding_mismatch",
        )
        foreign_session.refresh_from_db()
        self.assertEqual(
            foreign_session.metadata["auth_context"]["guest_id"],
            "gst_d13_other",
        )


def _contains_any_marker(value: object) -> bool:
    return any(_contains_value(value, marker) for marker in SENSITIVE_MARKERS.values())


def _contains_value(value: object, expected: str) -> bool:
    if isinstance(value, dict):
        return any(
            _contains_value(key, expected) or _contains_value(item, expected)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_value(item, expected) for item in value)
    return value == expected
