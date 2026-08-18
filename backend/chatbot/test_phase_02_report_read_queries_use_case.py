"""Characterization coverage for the Phase 2-D5 Report read boundary."""

from __future__ import annotations

import importlib
import json
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.contracts.report import ReportDetailResponse, ReportListResponse
from app.services.google_auth_service import issue_access_token
from chatbot.models import (
    AuthSession,
    AuthSessionStatus,
    ChatSession,
    ChatSessionStatus,
    Report,
    ReportStatus,
    ReportType,
    UserAccount,
)


TEST_JWT_SIGNING_KEY = "phase-02-d5-report-read-queries-signing-key-is-long-enough"


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
class ReportReadQueriesUseCaseCharacterizationTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_phase_02_d5_owner"
        self.foreign_owner_id = "usr_phase_02_d5_foreign"
        self.owner_client = authenticated_client(self.owner_id)
        self.foreign_client = authenticated_client(self.foreign_owner_id)
        self.owner_session = ChatSession.objects.create(
            session_id="ses_phase_02_d5_owner",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        self.owner_report = self._create_report(
            report_id="rep_phase_02_d5_owner",
            owner_id=self.owner_id,
            session=self.owner_session,
            title="Owner report",
        )
        self.foreign_session = ChatSession.objects.create(
            session_id="ses_phase_02_d5_foreign",
            owner_id=self.foreign_owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        self.foreign_report = self._create_report(
            report_id="rep_phase_02_d5_foreign",
            owner_id=self.foreign_owner_id,
            session=self.foreign_session,
            title="Foreign report",
        )

    def _create_report(
        self,
        *,
        report_id: str,
        owner_id: str,
        session: ChatSession,
        title: str,
    ) -> Report:
        return Report.objects.create(
            report_id=report_id,
            owner_id=owner_id,
            session=session,
            report_type=ReportType.FAULT_RATIO_ANALYSIS,
            status=ReportStatus.READY,
            title=title,
            storage_uri=f"s3://private-bucket/reports/{report_id}.pdf",
            content_summary=f"{title} safe summary",
            content={
                "contract_version": "analysis_report.v1",
                "format": "json",
                "action": "worker_finalize",
                "reporting_payload": {
                    "report_type": "fault_ratio_analysis",
                    "title": title,
                    "summary": f"{title} safe summary",
                    "sections": [
                        {
                            "title": "Facts",
                            "body": "Confirmed facts",
                            "items": ["Verified"],
                            "storage_uri": "s3://private-bucket/private-section.json",
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
                    "limitations": ["Check facts before submission."],
                    "agent_status_counts": {"success": 1},
                },
                "object_storage": {
                    "storage_uri": f"s3://private-bucket/reports/{report_id}.pdf",
                    "key": f"reports/{report_id}.pdf",
                },
            },
        )

    def test_list_http_get_delegates_to_application_with_trusted_owner_identity(self) -> None:
        captured: dict[str, object] = {}

        def application_spy(query: object) -> object:
            captured["query"] = query
            module = importlib.import_module("app.application.reports.read_queries")
            return module.execute_list_reports(query)

        with patch(
            "chatbot.views.execute_list_reports",
            side_effect=application_spy,
            create=True,
        ) as execute_application:
            response = self.owner_client.get(
                "/api/reports/",
                {
                    "session_id": self.owner_session.session_id,
                    "owner_id": self.foreign_owner_id,
                    "user_id": self.foreign_owner_id,
                },
            )

        self.assertEqual(response.status_code, 200, response.content)
        ReportListResponse.model_validate(response.json())
        execute_application.assert_called_once()
        query = captured["query"]
        self.assertEqual(query.session_id, self.owner_session.session_id)
        self.assertEqual(query.identity_payload["auth_context"]["user_id"], self.owner_id)

    def test_list_excludes_foreign_reports_and_preserves_session_filter(self) -> None:
        second_owner_session = ChatSession.objects.create(
            session_id="ses_phase_02_d5_owner_second",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        second_owner_report = self._create_report(
            report_id="rep_phase_02_d5_owner_second",
            owner_id=self.owner_id,
            session=second_owner_session,
            title="Second owner report",
        )

        all_owned = self.owner_client.get("/api/reports/")
        session_scoped = self.owner_client.get(
            "/api/reports/",
            {"session_id": self.owner_session.session_id},
        )

        self.assertEqual(all_owned.status_code, 200, all_owned.content)
        self.assertEqual(session_scoped.status_code, 200, session_scoped.content)
        self.assertEqual(
            {item["report_id"] for item in all_owned.json()["reports"]},
            {self.owner_report.report_id, second_owner_report.report_id},
        )
        self.assertEqual(
            [item["report_id"] for item in session_scoped.json()["reports"]],
            [self.owner_report.report_id],
        )
        self.assertNotIn(
            self.foreign_report.report_id,
            {item["report_id"] for item in all_owned.json()["reports"]},
        )

    def test_list_summary_does_not_expose_private_storage_or_source_fields(self) -> None:
        response = self.owner_client.get("/api/reports/")

        self.assertEqual(response.status_code, 200, response.content)
        public_json = json.dumps(response.json(), sort_keys=True)
        for private_value in (
            "owner_id",
            "private-bucket",
            "request_fingerprint",
            "law_ground_search",
        ):
            self.assertNotIn(private_value, public_json)

    def test_detail_http_get_delegates_to_application_with_trusted_owner_identity(self) -> None:
        captured: dict[str, object] = {}

        def application_spy(query: object) -> object:
            captured["query"] = query
            module = importlib.import_module("app.application.reports.read_queries")
            return module.execute_get_report_detail(query)

        with patch(
            "chatbot.views.execute_get_report_detail",
            side_effect=application_spy,
            create=True,
        ) as execute_application:
            response = self.owner_client.get(
                f"/api/reports/{self.owner_report.report_id}/",
                {
                    "session_id": self.owner_session.session_id,
                    "owner_id": self.foreign_owner_id,
                    "user_id": self.foreign_owner_id,
                },
            )

        self.assertEqual(response.status_code, 200, response.content)
        ReportDetailResponse.model_validate(response.json())
        execute_application.assert_called_once()
        query = captured["query"]
        self.assertEqual(query.report_id, self.owner_report.report_id)
        self.assertEqual(query.identity_payload["auth_context"]["user_id"], self.owner_id)

    def test_detail_denies_foreign_owner_without_private_report_projection(self) -> None:
        response = self.foreign_client.get(
            f"/api/reports/{self.owner_report.report_id}/"
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")
        denied_json = json.dumps(response.json(), sort_keys=True)
        for private_value in (
            self.owner_id,
            "private-bucket",
            "request_fingerprint",
            "law_ground_search",
        ):
            self.assertNotIn(private_value, denied_json)

    def test_detail_returns_not_found_for_missing_report(self) -> None:
        response = self.owner_client.get("/api/reports/rep_phase_02_d5_missing/")

        self.assertEqual(response.status_code, 404, response.content)
        self.assertEqual(response.json()["error"]["code"], "report_not_found")

    def test_detail_preserves_public_projection_and_worker_execution_mode(self) -> None:
        response = self.owner_client.get(f"/api/reports/{self.owner_report.report_id}/")

        self.assertEqual(response.status_code, 200, response.content)
        detail = response.json()
        self.assertEqual(detail["api_surface"], "canonical")
        self.assertEqual(detail["execution_mode"], "async_worker")
        self.assertEqual(
            detail["report"]["content"]["reporting_payload"]["sections"],
            [{"title": "Facts", "body": "Confirmed facts", "items": ["Verified"]}],
        )
        public_json = json.dumps(detail, sort_keys=True)
        for private_value in (
            "owner_id",
            "private-bucket",
            "request_fingerprint",
            "law_ground_search",
            "agent_status_counts",
        ):
            self.assertNotIn(private_value, public_json)
