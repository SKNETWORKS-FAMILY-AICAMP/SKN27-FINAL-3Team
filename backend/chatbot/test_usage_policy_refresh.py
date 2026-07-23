from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from chatbot.models import (
    AuthSession,
    AuthSessionStatus,
    CodeGroup,
    CodeItem,
    UserAccount,
)


TEST_JWT_SIGNING_KEY = "usage-policy-refresh-test-signing-key-is-long-enough"


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class UsagePolicyRefreshTests(TestCase):
    def setUp(self) -> None:
        user_id = "usr_usage_policy"
        issued_at = timezone.now()
        expires_at = issued_at + timedelta(hours=1)
        auth_session_id = f"auth_{user_id}"
        token, _claims = issue_access_token(
            user_id=user_id,
            auth_session_id=auth_session_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        user = UserAccount.objects.create(user_id=user_id)
        AuthSession.objects.create(
            auth_session_id=auth_session_id,
            user=user,
            subject_type="user",
            subject_id=f"user:{user_id}",
            status=AuthSessionStatus.ACTIVE,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        self.client = Client(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _create_policy(self, metadata: dict) -> CodeItem:
        group = CodeGroup.objects.create(
            group_code="usage_quota_policy",
            name="Usage quota policy",
        )
        return CodeItem.objects.create(
            group=group,
            code="free",
            label="free usage policy",
            metadata=metadata,
        )

    def _post_chat(self, session_id: str):
        return self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": session_id,
                "user_text": "quota 정책 확인",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )

    def test_seeded_policy_refreshes_stale_canonical_limits(self) -> None:
        code_item = self._create_policy(
            {
                "source": "canonical_usage_policy",
                "policy_status": "seeded_default",
                "limits": {"chat_message": 1},
            }
        )

        response = self._post_chat("ses_refreshed_free_policy")

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["usage"]["limit_count"], 100)
        code_item.refresh_from_db()
        self.assertEqual(code_item.metadata["limits"]["chat_message"], 100)

    def test_operator_policy_limits_are_not_overwritten(self) -> None:
        code_item = self._create_policy(
            {
                "source": "operator_configured",
                "policy_status": "active",
                "limits": {"chat_message": 7},
            }
        )

        response = self._post_chat("ses_operator_free_policy")

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["usage"]["limit_count"], 7)
        code_item.refresh_from_db()
        self.assertEqual(code_item.metadata["limits"]["chat_message"], 7)
