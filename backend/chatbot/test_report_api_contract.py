from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.guest_credential_service import issue_guest_credential
from app.contracts.report import (
    ReportApiErrorResponse,
    ReportDetailResponse,
    ReportListResponse,
)
from app.services.google_auth_service import issue_access_token
from chatbot.models import (
    AuthSession,
    AuthSessionStatus,
    ChatSession,
    ChatSessionStatus,
    GuestIdentity,
    GuestIdentityStatus,
    Report,
    ReportStatus,
    ReportType,
    UserAccount,
)


TEST_JWT_SIGNING_KEY = "report-api-contract-test-signing-key-is-long-enough"


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
class ReportApiContractTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_report_api_owner"
        self.other_id = "usr_report_api_other"
        self.owner_client = authenticated_client(self.owner_id)
        self.other_client = authenticated_client(self.other_id)
        self.owner_session = ChatSession.objects.create(
            session_id="ses_report_api_owner",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        self.report = Report.objects.create(
            report_id="rep_report_api_owner",
            owner_id=self.owner_id,
            session=self.owner_session,
            report_type=ReportType.FAULT_RATIO_ANALYSIS,
            status=ReportStatus.READY,
            title="Owner report",
            storage_uri="s3://private-bucket/reports/owner.pdf",
            content_summary="Safe summary",
            content={
                "contract_version": "analysis_report.v1",
                "format": "json",
                "action": "worker_finalize",
                "reporting_payload": {
                    "report_type": "fault_ratio_analysis",
                    "screen_id": "UI-REPORT-FAULT-001",
                    "stage": "agent_execution_ready",
                    "title": "Owner report",
                    "summary": "Safe summary",
                    "sections": [
                        {
                            "title": "Facts",
                            "body": "Confirmed facts",
                            "items": ["Verified"],
                            "provenance": {"fingerprint": "must-not-leak"},
                            "storage_uri": "s3://private-bucket/section.json",
                        }
                    ],
                    "source_node_codes": ["law_ground_search"],
                },
                "source": {"request_fingerprint": "must-not-leak"},
            },
            metadata={
                "source": "analysis_worker_reporting",
                "report_quality": {
                    "contract_version": "report_quality.v2",
                    "partial_report": False,
                    "review_required": True,
                    "limitation_count": 1,
                    "limitations": ["Latest revision may not be reflected."],
                    "agent_status_counts": {"success": 1},
                    "public_quality_summary": {
                        "status": "partial",
                        "partial_result": True,
                        "review_required": True,
                        "freshness": {
                            "effective_at": "2026-07-20",
                            "retrieved_at": "2026-07-27T09:00:00+09:00",
                            "limitation": "Latest revision may not be reflected.",
                        },
                        "retrieval": {
                            "backend_label": "legal_ground_search",
                            "result_count": 1,
                            "used_fallback": False,
                        },
                        "limitation_count": 1,
                        "limitations": ["Latest revision may not be reflected."],
                        "dataset_version": "sha256:must-not-leak",
                    },
                },
                "limitations": ["Latest revision may not be reflected."],
                "object_storage": {
                    "policy_version": "object_storage.v1",
                    "backend": "s3",
                    "provider": "s3",
                    "bucket": "private-bucket",
                    "storage_uri": "s3://private-bucket/reports/owner.pdf",
                    "key": "reports/owner.pdf",
                    "resource_type": "report",
                    "resource_id": "rep_report_api_owner",
                },
            },
        )

    def test_owner_reads_strict_public_list_and_detail_contracts(self) -> None:
        list_response = self.owner_client.get(
            "/api/reports/",
            {"session_id": self.owner_session.session_id},
        )
        detail_response = self.owner_client.get(f"/api/reports/{self.report.report_id}/")

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        ReportListResponse.model_validate(list_response.json())
        ReportDetailResponse.model_validate(detail_response.json())
        self.assertEqual(list_response.json()["api_surface"], "canonical")
        self.assertEqual(detail_response.json()["api_surface"], "canonical")
        self.assertEqual(detail_response.json()["execution_mode"], "async_worker")
        detail = detail_response.json()["report"]
        public_json = json.dumps(detail, sort_keys=True)
        self.assertNotIn("owner_id", public_json)
        self.assertNotIn("storage_uri", public_json)
        self.assertNotIn("request_fingerprint", public_json)
        self.assertNotIn("source_node_codes", public_json)
        self.assertEqual(
            detail["content"]["reporting_payload"]["sections"],
            [{"title": "Facts", "body": "Confirmed facts", "items": ["Verified"]}],
        )

    def test_owner_list_spans_owned_sessions_without_cross_owner_leakage(self) -> None:
        second_owner_session = ChatSession.objects.create(
            session_id="ses_report_api_owner_second",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        second_owner_report = Report.objects.create(
            report_id="rep_report_api_owner_second",
            owner_id=self.owner_id,
            session=second_owner_session,
            report_type=ReportType.FINE_NOTICE_OBJECTION,
            status=ReportStatus.READY,
            title="Second owner report",
            content={},
            metadata={},
        )
        other_session = ChatSession.objects.create(
            session_id="ses_report_api_other",
            owner_id=self.other_id,
            status=ChatSessionStatus.ACTIVE,
        )
        Report.objects.create(
            report_id="rep_report_api_other",
            owner_id=self.other_id,
            session=other_session,
            report_type=ReportType.FINE_NOTICE_OBJECTION,
            status=ReportStatus.READY,
            title="Other user report",
            content={},
            metadata={},
        )

        response = self.owner_client.get("/api/reports/")

        self.assertEqual(response.status_code, 200)
        report_ids = {item["report_id"] for item in response.json()["reports"]}
        self.assertEqual(
            report_ids,
            {self.report.report_id, second_owner_report.report_id},
        )

    def test_report_detail_exposes_only_public_quality_summary_fields(self) -> None:
        response = self.owner_client.get(f"/api/reports/{self.report.report_id}/")
        detail = response.json()["report"]

        quality = detail["metadata"]["report_quality"]
        self.assertEqual(quality["limitation_count"], 1)
        self.assertEqual(
            quality["limitations"], ["Latest revision may not be reflected."]
        )
        self.assertEqual(
            quality["public_quality_summary"],
            {
                "status": "partial",
                "partial_result": True,
                "review_required": True,
                "freshness": {
                    "effective_at": "2026-07-20",
                    "retrieved_at": "2026-07-27T09:00:00+09:00",
                    "limitation": "Latest revision may not be reflected.",
                },
                "retrieval": {
                    "backend_label": "legal_ground_search",
                    "result_count": 1,
                    "used_fallback": False,
                },
                "limitation_count": 1,
                "limitations": ["Latest revision may not be reflected."],
            },
        )
        self.assertNotIn("agent_status_counts", quality)
        self.assertNotIn("dataset_version", json.dumps(detail))
        self.assertNotIn("storage_uri", json.dumps(detail))

    def test_report_detail_rejects_private_values_in_quality_allowlist_fields(self) -> None:
        self.report.metadata["report_quality"] = {
            "contract_version": "s3://private-bucket/report_quality.v2",
            "confidence_label": "C:\\private\\report.json",
            "limitation_count": 99,
            "limitations": ["raw query: secret user question"],
            "public_quality_summary": {
                "status": "raw query: secret user question",
                "partial_result": True,
                "review_required": True,
                "freshness": {
                    "effective_at": "s3://private-bucket/effective_at",
                    "retrieved_at": "C:\\private\\retrieved_at",
                    "limitation": "RuntimeError: embedding model text-embedding-3-large",
                },
                "retrieval": {
                    "backend_label": "text-embedding-3-large",
                    "result_count": 1,
                    "used_fallback": False,
                },
                "limitation_count": 99,
                "limitations": ["raw query: secret user question"],
            },
        }
        self.report.save(update_fields=["metadata", "updated_at"])

        response = self.owner_client.get(f"/api/reports/{self.report.report_id}/")

        self.assertEqual(response.status_code, 200)
        detail = response.json()["report"]
        quality = detail["metadata"]["report_quality"]
        self.assertEqual(quality["limitation_count"], 0)
        self.assertEqual(quality["limitations"], [])
        self.assertIsNone(quality["confidence_label"])
        self.assertEqual(
            quality["public_quality_summary"],
            {
                "status": "unavailable",
                "partial_result": True,
                "review_required": True,
                "freshness": {
                    "effective_at": None,
                    "retrieved_at": None,
                    "limitation": None,
                },
                "retrieval": {
                    "backend_label": None,
                    "result_count": 1,
                    "used_fallback": False,
                },
                "limitation_count": 0,
                "limitations": [],
            },
        )
        public_json = json.dumps(detail, sort_keys=True)
        for private_value in (
            "private-bucket",
            "private\\\\report.json",
            "secret user question",
            "text-embedding-3-large",
            "RuntimeError",
        ):
            self.assertNotIn(private_value, public_json)

    def test_other_user_is_denied_before_report_document_resolution(self) -> None:
        with patch("chatbot.views.get_report_download_metadata") as resolve_download:
            response = self.other_client.get(
                f"/api/reports/{self.report.report_id}/download/"
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")
        self.assertFalse(resolve_download.called)
        denied_json = json.dumps(response.json(), sort_keys=True)
        self.assertNotIn("owner_id", denied_json)
        self.assertNotIn("storage_backend", denied_json)

    def test_invalid_bearer_token_returns_a_safe_401_challenge(self) -> None:
        response = Client(HTTP_AUTHORIZATION="Bearer malformed-token").get(
            "/api/reports/"
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "token_invalid")
        self.assertTrue(response["WWW-Authenticate"].startswith("Bearer "))

    def test_missing_bearer_token_returns_the_documented_safe_401(self) -> None:
        response = Client().get("/api/reports/")

        self.assertEqual(response.status_code, 401)
        ReportApiErrorResponse.model_validate(response.json())
        self.assertEqual(response.json()["error"]["code"], "auth_required")

    def test_expired_bearer_token_returns_a_safe_401_challenge(self) -> None:
        expires_at = timezone.now() - timedelta(minutes=1)
        token, _claims = issue_access_token(
            user_id=self.owner_id,
            auth_session_id="auth_expired_report_client",
            issued_at=expires_at - timedelta(hours=1),
            expires_at=expires_at,
        )

        response = Client(HTTP_AUTHORIZATION=f"Bearer {token}").get("/api/reports/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "token_expired")
        self.assertTrue(response["WWW-Authenticate"].startswith("Bearer "))

    def test_expired_guest_header_returns_the_documented_safe_401(self) -> None:
        GuestIdentity.objects.create(
            guest_id="gst_expired_report_api",
            status=GuestIdentityStatus.ACTIVE,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        response = Client(
            HTTP_X_GUEST_ID="gst_expired_report_api",
            HTTP_X_GUEST_CREDENTIAL=issue_guest_credential("gst_expired_report_api")[0],
        ).get("/api/reports/")

        self.assertEqual(response.status_code, 401)
        error = response.json()["error"]
        self.assertEqual(error["code"], "guest_session_invalid")
        self.assertEqual(error["required_action"], "refresh_guest_session")
        self.assertEqual(error["reason"], "guest_expired")

    def test_owner_download_exposes_only_public_document_headers(self) -> None:
        confirmation = self.owner_client.post(
            f"/api/reports/{self.report.report_id}/document-confirmation/",
            data=json.dumps(
                {
                    "facts_confirmed": True,
                    "agency_confirmed": True,
                    "deadline_confirmed": True,
                    "attachments_confirmed": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(confirmation.status_code, 201)
        response = self.owner_client.get(
            f"/api/reports/{self.report.report_id}/download/?document_type=objection_form"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(response["X-API-Surface"], "canonical")
        self.assertEqual(response["X-Execution-Mode"], "async_worker")
        self.assertIn("X-Report-Document-Type", response)
        for header in (
            "X-Report-Persistence",
            "X-Report-Storage-Backend",
            "X-Report-Storage-URI",
            "X-Report-Object-Key",
            "X-Report-Object-Policy",
            "X-Report-Access-Decision",
        ):
            self.assertNotIn(header, response)

    def test_owner_download_does_not_return_a_mock_document_after_metadata_disappears(self) -> None:
        confirmation = self.owner_client.post(
            f"/api/reports/{self.report.report_id}/document-confirmation/",
            data=json.dumps(
                {
                    "facts_confirmed": True,
                    "agency_confirmed": True,
                    "deadline_confirmed": True,
                    "attachments_confirmed": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(confirmation.status_code, 201)
        with patch(
            "chatbot.views.get_report_download_metadata",
            return_value=None,
        ):
            response = self.owner_client.get(
                f"/api/reports/{self.report.report_id}/download/?document_type=objection_form"
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "report_not_found")
