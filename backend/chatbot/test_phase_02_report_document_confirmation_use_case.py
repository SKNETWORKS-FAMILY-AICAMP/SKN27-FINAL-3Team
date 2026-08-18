from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import importlib
from pathlib import Path
import re
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.contracts.report import ConfirmReportDocumentResponse
from app.services.google_auth_service import issue_access_token
from app.services.guest_credential_service import issue_guest_credential
from chatbot.models import (
    AuthSession,
    AuthSessionStatus,
    Report,
    ReportStatus,
    ReportType,
    UserAccount,
)
from chatbot.repositories import get_report_record_detail


TEST_JWT_SIGNING_KEY = "phase-02-d3-report-confirmation-signing-key-is-long-enough"
REPORT_CONFIRMATION_PAYLOAD = {
    "facts_confirmed": True,
    "agency_confirmed": True,
    "deadline_confirmed": True,
    "attachments_confirmed": True,
}


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
    return Client(HTTP_AUTHORIZATION=f"Bearer {token}")


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class ReportDocumentConfirmationUseCaseCharacterizationTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_phase_02_d3_owner"
        self.foreign_owner_id = "usr_phase_02_d3_foreign"
        self.owner_client = authenticated_client(self.owner_id)
        self.foreign_client = authenticated_client(self.foreign_owner_id)
        self.report = self._create_report("rep_phase_02_d3_owner")

    def _create_report(
        self,
        report_id: str,
        *,
        document_variant: str = "fine_notice",
        report_type: str = ReportType.FINE_NOTICE_OBJECTION,
    ) -> Report:
        return Report.objects.create(
            report_id=report_id,
            owner_id=self.owner_id,
            report_type=report_type,
            status=ReportStatus.READY,
            title="Phase 2 D3 official objection form",
            content={
                "reporting_payload": {
                    "document_variant": document_variant,
                    "form_data": {
                        "recipient": "Traffic agency",
                        "applicant_name": "Applicant",
                    },
                    "sections": [{"title": "Facts", "body": "Confirmed facts"}],
                    "petition_purpose": "Review the disposition",
                    "petition_reason": "The facts require review.",
                    "appeal_gate": {"blocked": False, "reason": ""},
                }
            },
            metadata={"source": "analysis_worker_reporting"},
        )

    def _confirm(self, client: Client, report: Report, payload: dict[str, object] | None = None):
        return client.post(
            f"/api/reports/{report.report_id}/document-confirmation/",
            data=payload or REPORT_CONFIRMATION_PAYLOAD,
            content_type="application/json",
        )

    def test_http_post_delegates_to_application_with_trusted_identity_and_preserves_confirmation_response(self) -> None:
        captured: dict[str, object] = {}

        def application_spy(command: object) -> object:
            captured["command"] = command
            module = importlib.import_module("app.application.reports.confirm_document")
            return module.execute_confirm_report_document(command)

        with patch(
            "chatbot.views.execute_confirm_report_document",
            side_effect=application_spy,
            create=True,
        ) as execute_application:
            response = self._confirm(self.owner_client, self.report)

        self.assertEqual(response.status_code, 201, response.content)
        ConfirmReportDocumentResponse.model_validate(response.json())
        execute_application.assert_called_once()
        command = captured["command"]
        self.assertEqual(command.report_id, self.report.report_id)
        self.assertEqual(command.identity_payload["auth_context"]["user_id"], self.owner_id)
        self.assertEqual(command.raw_payload, REPORT_CONFIRMATION_PAYLOAD)
        self.report.refresh_from_db()
        self.assertEqual(
            self.report.metadata["document_confirmation"]["confirmed_by_user_id"],
            self.owner_id,
        )

    def test_foreign_owner_invalid_payload_is_denied_before_validation_without_mutation(self) -> None:
        response = self._confirm(
            self.foreign_client,
            self.report,
            {"facts_confirmed": False},
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")
        self.report.refresh_from_db()
        self.assertNotIn("document_confirmation", self.report.metadata)

    def test_guest_is_rejected_by_existing_login_policy_without_mutation(self) -> None:
        credential, _claims = issue_guest_credential("phase_02_d3_guest")
        guest_client = Client(
            HTTP_X_GUEST_ID="gst_phase_02_d3_guest",
            HTTP_X_GUEST_CREDENTIAL=credential,
        )

        response = self._confirm(guest_client, self.report)

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "login_required")
        self.report.refresh_from_db()
        self.assertNotIn("document_confirmation", self.report.metadata)

    def test_owner_invalid_confirmation_preserves_validation_error_without_mutation(self) -> None:
        response = self._confirm(
            self.owner_client,
            self.report,
            {**REPORT_CONFIRMATION_PAYLOAD, "agency_confirmed": False},
        )

        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(response.json()["error"]["code"], "validation_error")
        self.report.refresh_from_db()
        self.assertNotIn("document_confirmation", self.report.metadata)

    def test_unknown_report_preserves_not_found_response(self) -> None:
        missing_report = Report(report_id="rep_phase_02_d3_missing")

        response = self._confirm(self.owner_client, missing_report)

        self.assertEqual(response.status_code, 404, response.content)
        self.assertEqual(response.json()["error"]["code"], "report_not_found")
    def test_appeal_gate_blocks_confirmation_without_mutation(self) -> None:
        payload = deepcopy(self.report.content["reporting_payload"])
        payload["appeal_gate"] = {"blocked": True, "reason": "Appeal deadline passed."}
        self.report.content = {"reporting_payload": payload}
        self.report.save(update_fields=["content", "updated_at"])

        response = self._confirm(self.owner_client, self.report)

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "appeal_gate_blocked")
        self.report.refresh_from_db()
        self.assertNotIn("document_confirmation", self.report.metadata)

    def test_non_official_document_preserves_document_unavailable_response(self) -> None:
        report = self._create_report(
            "rep_phase_02_d3_non_official",
            document_variant="general",
            report_type=ReportType.GENERAL,
        )

        response = self._confirm(self.owner_client, report)

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "document_download_not_available")
        report.refresh_from_db()
        self.assertNotIn("document_confirmation", report.metadata)

    def test_confirmation_preserves_current_and_stale_fingerprint_projection(self) -> None:
        response = self._confirm(self.owner_client, self.report)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.json()["document_confirmation"]["confirmed"])
        self.report.refresh_from_db()
        changed_payload = deepcopy(self.report.content["reporting_payload"])
        changed_payload["petition_reason"] = "Changed after confirmation."
        self.report.content = {"reporting_payload": changed_payload}
        self.report.save(update_fields=["content", "updated_at"])

        detail = get_report_record_detail(self.report.report_id)

        self.assertEqual(
            detail["content"]["reporting_payload"]["document_confirmation"],
            {"required": True, "confirmed": False, "stale": True, "confirmed_at": None},
        )
    def test_application_boundary_is_http_orm_transaction_free_and_view_has_no_direct_confirmation_call(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        application_source = (
            repository_root / "app/application/reports/confirm_document.py"
        ).read_text(encoding="utf-8")
        view_source = (repository_root / "backend/chatbot/views.py").read_text(encoding="utf-8")
        view_start = view_source.index("def report_document_confirmation")
        view_end = view_source.index("\n\n@require_http_methods", view_start)
        confirmation_view = view_source[view_start:view_end]

        for prohibited in (
            "from django",
            "HttpRequest",
            "HttpResponse",
            "transaction.atomic",
            "chatbot.models",
            "Report.objects",
            "unittest.mock",
        ):
            self.assertNotIn(prohibited, application_source)
        self.assertIsNone(
            re.search(
                r"(?m)^\s*confirmation\s*=\s*confirm_report_document\(",
                confirmation_view,
            )
        )
