"""Runtime regression tests for the promoted MyPage summary API contract."""

from __future__ import annotations

from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from chatbot.models import AuthSession, AuthSessionStatus, ChatSession, UserAccount


TEST_JWT_SIGNING_KEY = "mypage-api-contract-test-signing-key-is-long-enough"


def authenticated_client(user_id: str) -> Client:
    issued_at = timezone.now()
    expires_at = issued_at + timedelta(hours=1)
    auth_session_id = f"auth_{user_id}"
    token, _claims = issue_access_token(
        user_id=user_id,
        auth_session_id=auth_session_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    user, _created = UserAccount.objects.get_or_create(user_id=user_id)
    AuthSession.objects.update_or_create(
        auth_session_id=auth_session_id,
        defaults={
            "user": user,
            "subject_type": "user",
            "subject_id": f"user:{user_id}",
            "status": AuthSessionStatus.ACTIVE,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "revoked_at": None,
        },
    )
    return Client(HTTP_AUTHORIZATION=f"Bearer {token}")


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class MyPageApiContractTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_mypage_contract"
        self.client = authenticated_client(self.owner_id)
        self.other_client = authenticated_client("usr_mypage_other")
        ChatSession.objects.create(
            session_id="ses_mypage_contract_owner",
            owner_id=self.owner_id,
        )
        ChatSession.objects.create(
            session_id="ses_mypage_contract_other",
            owner_id="usr_mypage_other",
        )

    def test_owner_and_legacy_user_queries_keep_current_precedence(self) -> None:
        response = self.client.get(
            "/api/mypage/summary/?owner_id=usr_mypage_contract&user_id=usr_mypage_other"
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("cases", response.json())

    def test_own_session_is_allowed_but_other_session_is_denied(self) -> None:
        own_response = self.client.get(
            "/api/mypage/summary/?session_id=ses_mypage_contract_owner"
        )
        other_response = self.client.get(
            "/api/mypage/summary/?session_id=ses_mypage_contract_other"
        )

        self.assertEqual(own_response.status_code, 200, own_response.content)
        self.assertEqual(other_response.status_code, 403, other_response.content)
        self.assertEqual(other_response.json()["error"]["code"], "object_access_denied")

    def test_other_owner_is_denied_and_invalid_limit_keeps_default_fallback(self) -> None:
        denied = self.other_client.get("/api/mypage/summary/?owner_id=usr_mypage_contract")
        fallback = self.client.get("/api/mypage/summary/?limit=not-a-number")

        self.assertEqual(denied.status_code, 403, denied.content)
        self.assertEqual(denied.json()["error"]["code"], "object_access_denied")
        self.assertEqual(fallback.status_code, 200, fallback.content)
        self.assertEqual(fallback.json()["recent_analysis_count"], 0)

    def test_raw_guest_id_without_credential_is_rejected(self) -> None:
        response = Client(HTTP_X_GUEST_ID="gst_mypage_contract").get(
            "/api/mypage/summary/?session_id=ses_mypage_contract_owner"
        )

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["error"]["code"], "auth_required")
        self.assertEqual(response.json()["error"]["auth"]["reason"], "missing_token")
