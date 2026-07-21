"""Django integration tests for the server-verified guest credential boundary."""

from __future__ import annotations

from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from app.services.guest_credential_service import issue_guest_credential


@override_settings(
    APP_JWT_SECRET="[MASKED]",
    GOOGLE_CLIENT_ID="guest-credential-boundary.apps.googleusercontent.com",
    GOOGLE_CLIENT_SECRET="[MASKED]",
    GOOGLE_POPUP_REDIRECT_URI="https://app.example.test",
)
class GuestCredentialBoundaryTests(TestCase):
    def test_auth_me_accepts_only_header_proved_guest_identity(self) -> None:
        credential, _claims = issue_guest_credential("owner")

        response = Client(
            HTTP_X_GUEST_ID="gst_owner",
            HTTP_X_GUEST_CREDENTIAL=credential,
        ).get("/api/auth/me/?session_id=ses_credential_owner")

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["subject"]["subject_type"], "guest")
        self.assertEqual(body["subject"]["guest_id"], "gst_owner")

    def test_guest_credential_can_prove_identity_without_a_guest_id_header(self) -> None:
        credential, _claims = issue_guest_credential("owner")

        response = Client(HTTP_X_GUEST_CREDENTIAL=credential).get("/api/auth/me/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["subject"]["guest_id"], "gst_owner")

    def test_guest_session_reuses_only_the_header_proved_guest_and_session(self) -> None:
        credential, _claims = issue_guest_credential("owner")

        response = Client(HTTP_X_GUEST_CREDENTIAL=credential).post(
            "/api/auth/guest-session/",
            data={"guest_id": "gst_owner", "session_id": "ses_credential_owner"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["guest"]["guest_id"], "gst_owner")
        self.assertEqual(body["session_binding"]["session_id"], "ses_credential_owner")
        self.assertNotEqual(body["guest_credential"], credential)

    def test_raw_guest_id_cannot_enqueue_chat_work(self) -> None:
        client = Client(raise_request_exception=False, HTTP_X_GUEST_ID="gst_owner")

        with patch("chatbot.views.submit_message") as submit_message:
            response = client.post(
                "/api/chat/messages/",
                data={"session_id": "ses_credential_owner", "user_text": "start consultation"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["auth"]["reason"], "missing_guest_credential")
        submit_message.assert_not_called()

    def test_raw_guest_id_cannot_read_history(self) -> None:
        response = Client(HTTP_X_GUEST_ID="gst_owner").get(
            "/api/history/?guest_id=gst_owner&session_id=ses_credential_owner"
        )

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["auth"]["reason"], "missing_guest_credential")

    def test_raw_guest_id_cannot_list_analysis_jobs(self) -> None:
        response = Client(HTTP_X_GUEST_ID="gst_owner").get(
            "/api/analysis/jobs/?session_id=ses_credential_owner"
        )

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["auth"]["reason"], "missing_guest_credential")

    def test_raw_guest_id_cannot_create_or_read_analysis_resources(self) -> None:
        client = Client(raise_request_exception=False, HTTP_X_GUEST_ID="gst_owner")
        with patch("chatbot.views.submit_message") as submit_message:
            create_response = client.post(
                "/api/analysis/jobs/",
                data={"session_id": "ses_credential_owner", "user_text": "start"},
                content_type="application/json",
            )

        responses = (
            create_response,
            client.get("/api/analysis/jobs/job_credential_boundary/"),
            client.get("/api/analysis/results/job_credential_boundary/"),
        )
        for response in responses:
            self.assertEqual(response.status_code, 401, response.content)
            self.assertEqual(response.json()["error"]["code"], "token_invalid")
            self.assertEqual(
                response.json()["error"]["auth"]["reason"],
                "missing_guest_credential",
            )
        submit_message.assert_not_called()

    def test_raw_guest_id_cannot_read_mypage_summary(self) -> None:
        response = Client(HTTP_X_GUEST_ID="gst_owner").get(
            "/api/mypage/summary/?session_id=ses_credential_owner"
        )

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["code"], "auth_required")
        self.assertEqual(response.json()["error"]["auth"]["reason"], "missing_token")

    def test_header_proved_guest_still_cannot_read_mypage_summary(self) -> None:
        credential, _claims = issue_guest_credential("owner")

        response = Client(
            HTTP_X_GUEST_ID="gst_owner",
            HTTP_X_GUEST_CREDENTIAL=credential,
        ).get("/api/mypage/summary/?session_id=ses_credential_owner")

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["code"], "auth_required")
        self.assertEqual(response.json()["error"]["auth"]["reason"], "missing_token")

    def test_header_proved_guest_can_read_history_and_analysis_jobs(self) -> None:
        credential, _claims = issue_guest_credential("owner")
        client = Client(
            HTTP_X_GUEST_ID="gst_owner",
            HTTP_X_GUEST_CREDENTIAL=credential,
        )

        history_response = client.get("/api/history/?guest_id=gst_owner")
        jobs_response = client.get("/api/analysis/jobs/")

        self.assertEqual(history_response.status_code, 200, history_response.content)
        self.assertEqual(jobs_response.status_code, 200, jobs_response.content)

    def test_header_proved_guest_cannot_select_a_chat_session_user(self) -> None:
        credential, _claims = issue_guest_credential("owner")

        response = Client(
            HTTP_X_GUEST_ID="gst_owner",
            HTTP_X_GUEST_CREDENTIAL=credential,
        ).post(
            "/api/chat/sessions/",
            data={"user_id": "usr_someone_else"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["user_id"])

    def test_invalid_credential_blocks_google_provider_before_exchange(self) -> None:
        client = Client(
            raise_request_exception=False,
            HTTP_X_GUEST_CREDENTIAL="tampered",
            HTTP_X_REQUESTED_WITH="XmlHttpRequest",
            HTTP_ORIGIN="https://app.example.test",
        )

        with patch("chatbot.views._create_google_code_login") as google_exchange:
            response = client.post(
                "/api/auth/google/code/",
                data={
                    "auth_flow": "google_authorization_code_popup",
                    "client_id": "guest-credential-boundary.apps.googleusercontent.com",
                    "code": "one-time-code",
                    "purpose": "LOGIN",
                    "scope": "openid email profile",
                    "redirect_uri": "https://app.example.test",
                    "guest_id": "gst_owner",
                    "session_id": "ses_credential_owner",
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["auth"]["reason"], "invalid_guest_credential")
        google_exchange.assert_not_called()
