from unittest.mock import patch

from django.db import DatabaseError
from django.test import SimpleTestCase


class GuestSessionRuntimeContractTests(SimpleTestCase):
    def test_guest_session_returns_structured_403_when_stale_session_binds_to_another_guest(self):
        from chatbot.views import SessionBindingError

        with patch(
            "chatbot.views.persist_guest_session_identity",
            side_effect=SessionBindingError("guest_session_binding_mismatch"),
        ):
            response = self.client.post(
                "/api/auth/guest-session/",
                data={"guest_id": "gst_replacement", "session_id": "ses_stale"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 403)
        error = response.json()["error"]
        self.assertEqual(error["code"], "forbidden")
        self.assertEqual(error["auth"]["reason"], "guest_session_binding_mismatch")

    def test_guest_session_returns_structured_503_when_persistence_store_is_unavailable(self):
        with patch(
            "chatbot.views.persist_guest_session_identity",
            side_effect=DatabaseError("guest session store offline"),
        ):
            response = self.client.post(
                "/api/auth/guest-session/",
                data={"guest_id": "gst_runtime_contract", "session_id": "ses_runtime_contract"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 503)
        error = response.json()["error"]
        self.assertEqual(error["contract_version"], "auth_error.v1")
        self.assertEqual(error["code"], "provider_unavailable")
        self.assertEqual(error["auth"]["reason"], "guest_session_store_unavailable")
        self.assertEqual(error["required_action"], "retry")
        self.assertFalse(error["retryable"])
