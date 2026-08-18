from __future__ import annotations

import ast
import importlib
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from app.contracts.consultation_case import CreateConsultationCaseResponse
from chatbot.case_repository import CaseAnalysisInProgress, CaseOwnerMismatch
from chatbot.models import (
    AgentWorkItem,
    AgentWorkItemStatus,
    AnalysisJob,
    Case,
    ChatSession,
    ChatSessionStatus,
    Report,
    UploadedFile,
)
from chatbot.test_consultation_v2 import authenticated_client


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEST_JWT_SIGNING_KEY = "phase-02-d2-case-creation-signing-key-is-long-enough"


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class CaseCreationUseCaseCharacterizationTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_phase_02_d2_owner"
        self.foreign_owner_id = "usr_phase_02_d2_foreign"
        self.owner_client = authenticated_client(self.owner_id)

    def test_http_post_delegates_to_application_with_trusted_identity_and_preserves_case_response(self) -> None:
        session = ChatSession.objects.create(
            session_id="ses_phase_02_d2_http",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
            current_intent="fault_ratio_text",
        )
        captured: dict[str, object] = {}

        def application_spy(command: object) -> object:
            captured["command"] = command
            module = importlib.import_module("app.application.cases.create_case")
            return module.execute_create_consultation_case(command)

        with patch(
            "chatbot.views.execute_create_consultation_case",
            side_effect=application_spy,
            create=True,
        ) as execute_application:
            response = self.owner_client.post(
                "/api/cases/",
                data={
                    "session_id": session.session_id,
                    "title": "D2 boundary case",
                    "case_type": "accident_fault",
                    "consultation_state": {
                        "schema_version": "consultation_state.v2",
                    },
                },
                content_type="application/json",
                HTTP_X_GUEST_ID="gst_phase_02_d2_attacker",
                HTTP_X_GUEST_CREDENTIAL="untrusted-client-credential",
            )

        self.assertEqual(response.status_code, 201, response.content)
        CreateConsultationCaseResponse.model_validate(response.json())
        execute_application.assert_called_once()
        command = captured["command"]
        self.assertEqual(command.identity_payload["auth_context"]["user_id"], self.owner_id)
        self.assertEqual(command.payload["session_id"], session.session_id)
        self.assertNotIn("owner_id", command.payload)
        self.assertNotIn("user_id", command.payload)
        self.assertNotIn("guest_id", command.payload)
        self.assertEqual(response.json()["case"]["owner_id"], self.owner_id)
        self.assertEqual(
            Case.objects.get(case_id=response.json()["case"]["case_id"]).owner_id,
            self.owner_id,
        )

    def test_application_promotes_matching_guest_session_and_relinks_related_records(self) -> None:
        module = importlib.import_module("app.application.cases.create_case")
        guest_id = "gst_phase_02_d2_matching"
        session = ChatSession.objects.create(
            session_id="ses_phase_02_d2_matching",
            owner_id="",
            status=ChatSessionStatus.ACTIVE,
            metadata={"auth_context": {"guest_id": guest_id}},
        )
        job = AnalysisJob.objects.create(
            job_id="job_phase_02_d2_matching",
            session=session,
            owner_id="",
            status="success",
        )
        report = Report.objects.create(
            report_id="rep_phase_02_d2_matching",
            session=session,
            owner_id="",
            version_no=1,
        )
        old_retention = timezone.now() - timedelta(days=1)
        attachment = UploadedFile.objects.create(
            attachment_id="att_phase_02_d2_matching",
            owner_id="",
            session=session,
            purpose="supporting_evidence",
            file_type="pdf",
            original_filename="evidence.pdf",
            content_type="application/pdf",
            storage_uri="mock://phase-02-d2/evidence.pdf",
            retention_expires_at=old_retention,
        )

        result = module.execute_create_consultation_case(
            module.CreateConsultationCaseCommand(
                identity_payload={
                    "owner_id": self.foreign_owner_id,
                    "guest_id": guest_id,
                    "auth_context": {
                        "subject_type": "user",
                        "user_id": self.owner_id,
                        "guest_id": guest_id,
                    },
                },
                payload={"session_id": session.session_id},
            )
        )

        case = Case.objects.get(case_id=result.case["case_id"])
        session.refresh_from_db()
        job.refresh_from_db()
        report.refresh_from_db()
        attachment.refresh_from_db()
        self.assertEqual(case.owner_id, self.owner_id)
        self.assertEqual((session.owner_id, session.case_id), (self.owner_id, case.id))
        self.assertEqual((job.owner_id, job.case_id), (self.owner_id, case.id))
        self.assertEqual((report.owner_id, report.case_id, report.version_no), (self.owner_id, case.id, 1))
        self.assertEqual((attachment.owner_id, attachment.case_id), (self.owner_id, case.id))
        self.assertGreater(attachment.retention_expires_at, old_retention)

    def test_application_rejects_foreign_or_active_session_before_mutation(self) -> None:
        module = importlib.import_module("app.application.cases.create_case")
        foreign_session = ChatSession.objects.create(
            session_id="ses_phase_02_d2_foreign",
            owner_id=self.foreign_owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        with self.assertRaises(CaseOwnerMismatch):
            module.execute_create_consultation_case(
                module.CreateConsultationCaseCommand(
                    identity_payload={"auth_context": {"user_id": self.owner_id}},
                    payload={"session_id": foreign_session.session_id},
                )
            )
        foreign_session.refresh_from_db()
        self.assertEqual(foreign_session.owner_id, self.foreign_owner_id)
        self.assertIsNone(foreign_session.case_id)
        self.assertFalse(Case.objects.filter(owner_id=self.owner_id).exists())

        guest_id = "gst_phase_02_d2_active"
        active_session = ChatSession.objects.create(
            session_id="ses_phase_02_d2_active",
            owner_id="",
            status=ChatSessionStatus.ACTIVE,
            metadata={"auth_context": {"guest_id": guest_id}},
        )
        active_job = AnalysisJob.objects.create(
            job_id="job_phase_02_d2_active",
            session=active_session,
            owner_id="",
            status="queued",
        )
        AgentWorkItem.objects.create(
            work_item_id="work_phase_02_d2_active",
            job=active_job,
            status=AgentWorkItemStatus.QUEUED,
        )
        with self.assertRaises(CaseAnalysisInProgress):
            module.execute_create_consultation_case(
                module.CreateConsultationCaseCommand(
                    identity_payload={
                        "auth_context": {
                            "user_id": self.owner_id,
                            "guest_id": guest_id,
                        }
                    },
                    payload={"session_id": active_session.session_id},
                )
            )
        active_session.refresh_from_db()
        active_job.refresh_from_db()
        self.assertEqual(active_session.owner_id, "")
        self.assertIsNone(active_session.case_id)
        self.assertEqual(active_job.owner_id, "")
        self.assertIsNone(active_job.case_id)
        self.assertFalse(Case.objects.filter(owner_id=self.owner_id).exists())

    def test_z_application_has_no_http_mock_or_transaction_dependencies_and_post_view_is_adapter_only(self) -> None:
        module = importlib.import_module("app.application.cases.create_case")
        application_tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        forbidden_modules = {"django.http", "app.mock_runtime", "backend.chatbot.views"}
        forbidden_names = {
            "HttpRequest",
            "HttpResponse",
            "JsonResponse",
            "csrf_exempt",
            "require_http_methods",
            "transaction",
        }
        imported_modules = {
            alias.name
            for node in ast.walk(application_tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_modules.update(
            node.module
            for node in ast.walk(application_tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        imported_names = {
            alias.name
            for node in ast.walk(application_tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        referenced_names = {
            node.id for node in ast.walk(application_tree) if isinstance(node, ast.Name)
        }
        self.assertTrue(forbidden_modules.isdisjoint(imported_modules))
        self.assertTrue(forbidden_names.isdisjoint(imported_names | referenced_names))

        views_tree = ast.parse(
            (REPOSITORY_ROOT / "backend" / "chatbot" / "views.py").read_text(
                encoding="utf-8-sig"
            )
        )
        view = next(
            node
            for node in views_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "consultation_cases"
        )
        direct_calls = {
            node.func.id
            for node in ast.walk(view)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("execute_list_consultation_cases", direct_calls)
        self.assertIn("execute_create_consultation_case", direct_calls)
        self.assertNotIn("create_case", direct_calls)
