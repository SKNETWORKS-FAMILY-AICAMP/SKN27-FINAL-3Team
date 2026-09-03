"""Security and application contracts for the D13 IssueGuestSession boundary."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.application.auth.issue_guest_session import (
    IssueGuestSessionCommand,
    execute_issue_guest_session,
)
from app.services.auth_error_contract import build_www_authenticate_header
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
    def test_issue_guest_session_projects_only_public_collaborator_fields(self) -> None:
        history_records: list[dict[str, object]] = []

        def guest_session_creator(
            _payload: dict[str, object],
            *,
            guest_credential: str | None,
        ) -> dict[str, object]:
            return {
                "auth_state": "guest",
                "guest": {
                    "guest_id": "gst_d13_projection",
                    "status": "active",
                    "issued_at": "2026-09-03T00:00:00+00:00",
                    "expires_at": "2026-09-10T00:00:00+00:00",
                    "ttl_seconds": 604800,
                    "policy_status": "review_required",
                    "secret": "d13-nested-secret-marker",
                },
                "subject": {
                    "subject_id": "guest:gst_d13_projection",
                    "subject_type": "guest",
                    "user_id": None,
                    "guest_id": "gst_d13_projection",
                    "auth_session_id": None,
                    "is_authenticated": False,
                    "raw_payload": "d13-subject-raw-payload-marker",
                },
                "session_binding": {
                    "session_id": None,
                    "can_bind_to_chat_session": False,
                    "binding_policy": "guest binding policy",
                    "private_binding_metadata": "d13-private-binding-marker",
                },
                "guest_credential": guest_credential or "issued-d13-guest-credential",
                "rate_limit": {
                    "subject_id": "guest:gst_d13_projection",
                    "policy_status": "review_required",
                    "keys": ["guest:gst_d13_projection"],
                    "notes": ["deterministic test policy"],
                    "internal_counter": "d13-rate-limit-counter-marker",
                },
                "merge_policy": {
                    "guest_to_user_merge": "user_confirmation_required",
                    "auto_merge": False,
                    "reason": "explicit confirmation",
                    "internal_reasoning": "d13-merge-reasoning-marker",
                },
                "limitations": ["deterministic test limitation"],
                "access_token": "d13-access-token-marker",
                "raw_claims": "d13-raw-claims-marker",
                "authorization": "d13-authorization-marker",
            }

        def persistence_writer(_payload: dict[str, object]) -> dict[str, object]:
            return {
                "backend": "postgresql",
                "tables": ["guest_identities", "auth_events", "chat_sessions"],
                "guest_identity_table": "guest_identities",
                "auth_events_table": "auth_events",
                "chat_session_table": "chat_sessions",
                "guest_id": "gst_d13_projection",
                "event_id": "authevt_d13_projection",
                "session_id": None,
                "status": "saved",
                "private_persistence_marker": "d13-private-persistence-marker",
                "raw_payload": "d13-persistence-raw-payload-marker",
            }

        def history_recorder(**event: object) -> None:
            history_records.append(event)

        result = execute_issue_guest_session(
            IssueGuestSessionCommand(
                payload={},
                guest_credential="issued-d13-guest-credential",
                audit_source={"surface": "test"},
                guest_session_creator=guest_session_creator,
                persistence_writer=persistence_writer,
                history_recorder=history_recorder,
            )
        )

        payload = result.payload
        self.assertNotIn("access_token", payload)
        self.assertNotIn("raw_claims", payload)
        self.assertNotIn("authorization", payload)
        self.assertEqual(
            set(payload),
            {
                "auth_state",
                "guest",
                "subject",
                "session_binding",
                "guest_credential",
                "rate_limit",
                "merge_policy",
                "limitations",
                "persistence",
            },
        )
        self.assertEqual(payload["guest_credential"], "issued-d13-guest-credential")
        self.assertEqual(
            set(payload["guest"]),
            {"guest_id", "status", "issued_at", "expires_at", "ttl_seconds", "policy_status"},
        )
        self.assertEqual(
            set(payload["subject"]),
            {
                "subject_id",
                "subject_type",
                "user_id",
                "guest_id",
                "auth_session_id",
                "is_authenticated",
            },
        )
        self.assertEqual(
            set(payload["session_binding"]),
            {"session_id", "can_bind_to_chat_session", "binding_policy"},
        )
        self.assertEqual(
            set(payload["rate_limit"]),
            {"subject_id", "policy_status", "keys", "notes"},
        )
        self.assertEqual(
            set(payload["merge_policy"]),
            {"guest_to_user_merge", "auto_merge", "reason"},
        )
        self.assertEqual(
            set(payload["persistence"]),
            {
                "backend",
                "tables",
                "guest_identity_table",
                "auth_events_table",
                "chat_session_table",
                "guest_id",
                "event_id",
                "session_id",
                "status",
            },
        )
        self.assertEqual(len(history_records), 1)
        self.assertFalse(_contains_any_private_projection_marker(history_records[0]))

    def test_guest_session_delegates_to_issue_guest_session_application(self) -> None:
        with patch(
            "chatbot.views.execute_issue_guest_session",
            create=True,
        ) as execute_application:
            response = Client(raise_request_exception=False).post(
                "/api/auth/guest-session/",
                data={},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content)
        execute_application.assert_called_once()

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
        self.assertIn("WWW-Authenticate", response)
        self.assertEqual(
            response["WWW-Authenticate"],
            build_www_authenticate_header(response.json()),
        )
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

    def test_valid_signed_credential_remains_the_subject_despite_forged_body_identity(self) -> None:
        signed_guest_id = "gst_d13_signed_subject"
        credential, _claims = issue_guest_credential(signed_guest_id)
        forged_guest_id = "gst_d13_forged_subject"
        forged_values = (
            forged_guest_id,
            "d13-forged-user-id",
            "d13-forged-owner-id",
            "d13-forged-subject-id",
            "d13-forged-subject-type",
            "d13-forged-auth-session-id",
        )

        response = Client(
            raise_request_exception=False,
            HTTP_X_GUEST_CREDENTIAL=credential,
        ).post(
            "/api/auth/guest-session/",
            data={
                "guest_id": forged_guest_id,
                "user_id": forged_values[1],
                "owner_id": forged_values[2],
                "subject_id": forged_values[3],
                "subject_type": forged_values[4],
                "auth_session_id": forged_values[5],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["guest"]["guest_id"], signed_guest_id)
        self.assertEqual(payload["subject"]["guest_id"], signed_guest_id)
        persisted_guest = GuestIdentity.objects.get(guest_id=signed_guest_id)
        self.assertFalse(GuestIdentity.objects.filter(guest_id=forged_guest_id).exists())
        events = AuthEvent.objects.filter(event_type="guest_session_created")
        self.assertEqual(events.count(), 1)
        auth_event = events.get()
        self.assertEqual(auth_event.guest_id, persisted_guest.pk)
        self.assertEqual(auth_event.subject_id, f"guest:{signed_guest_id}")
        for forged_value in forged_values:
            self.assertFalse(_contains_value(payload, forged_value))
            self.assertFalse(_contains_value(auth_event.metadata, forged_value))
        credential_valid, claims = decode_guest_credential(payload["guest_credential"])
        self.assertTrue(credential_valid)
        self.assertEqual(claims["sub"], signed_guest_id)

    def test_guest_session_persists_one_safe_auth_event(self) -> None:
        response = Client(raise_request_exception=False).post(
            "/api/auth/guest-session/",
            data={"access_token": "d13-auth-event-secret-marker"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        events = AuthEvent.objects.filter(event_type="guest_session_created")
        self.assertEqual(events.count(), 1)
        auth_event = events.get()
        self.assertEqual(auth_event.guest.guest_id, payload["guest"]["guest_id"])
        self.assertEqual(auth_event.subject_id, payload["subject"]["subject_id"])
        self.assertEqual(auth_event.metadata["source"], "auth_guest_session")
        self.assertIsNone(auth_event.metadata["chat_session_id"])
        self.assertNotIn("raw_payload", auth_event.metadata)
        self.assertFalse(_contains_value(auth_event.metadata, "d13-auth-event-secret-marker"))

    def test_guest_session_persists_one_safe_history_event(self) -> None:
        response = Client(raise_request_exception=False).post(
            "/api/auth/guest-session/",
            data={"access_token": "d13-history-event-secret-marker"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        events = HistoryEvent.objects.filter(event_type="guest_session_created")
        self.assertEqual(events.count(), 1)
        history_event = events.get()
        self.assertEqual(history_event.actor_guest_id, payload["guest"]["guest_id"])
        self.assertEqual(history_event.actor["guest_id"], payload["guest"]["guest_id"])
        self.assertEqual(history_event.actor["auth_state"], "guest")
        self.assertEqual(history_event.subject_session_id, "")
        self.assertEqual(history_event.status, "success")
        self.assertNotIn("raw_payload", history_event.metadata)
        self.assertFalse(
            _contains_value(history_event.metadata, "d13-history-event-secret-marker")
        )

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
        self.assertIn("WWW-Authenticate", response)
        self.assertEqual(
            response["WWW-Authenticate"],
            build_www_authenticate_header(response.json()),
        )
        foreign_session.refresh_from_db()
        self.assertEqual(
            foreign_session.metadata["auth_context"]["guest_id"],
            "gst_d13_other",
        )

    def test_guest_session_persistence_failure_does_not_send_auth_challenge(self) -> None:
        with patch(
            "chatbot.views.persist_guest_session_identity",
            side_effect=DatabaseError("guest session store offline"),
        ):
            response = Client(raise_request_exception=False).post(
                "/api/auth/guest-session/",
                data={},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 503, response.content)
        self.assertNotIn("WWW-Authenticate", response)


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


def _contains_any_private_projection_marker(value: object) -> bool:
    return any(
        _contains_value(value, marker)
        for marker in (
            "d13-nested-secret-marker",
            "d13-subject-raw-payload-marker",
            "d13-private-binding-marker",
            "d13-rate-limit-counter-marker",
            "d13-merge-reasoning-marker",
            "d13-private-persistence-marker",
            "d13-persistence-raw-payload-marker",
        )
    )
