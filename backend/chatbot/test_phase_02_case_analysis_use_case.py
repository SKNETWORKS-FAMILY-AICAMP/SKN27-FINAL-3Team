from __future__ import annotations

import ast
import importlib
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from chatbot.models import (
    AgentWorkItem,
    AnalysisJob,
    AuthSession,
    AuthSessionStatus,
    Case,
    ChatSession,
    ChatSessionStatus,
    UploadedFile,
    UserAccount,
)


TEST_JWT_SIGNING_KEY = "phase-02-b3-case-analysis-signing-key-is-long-enough"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_EVIDENCE_URI = "local://attachment-staging/phase-02-b3/police-record.pdf"
EXPECTED_NODE_CODES = [
    "text_ml_case_search",
    "law_ground_search",
    "objection_report_generation",
]


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
class CaseAnalysisUseCaseCharacterizationTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_phase_02_b3_owner"
        self.owner_client = authenticated_client(self.owner_id)
        self.session = ChatSession.objects.create(
            session_id="ses_phase_02_b3_analysis",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
            current_intent="fault_ratio_text",
        )
        create_response = self.owner_client.post(
            "/api/cases/",
            data={
                "session_id": self.session.session_id,
                "title": "Phase 2 B3 case analysis characterization",
                "case_type": "accident_fault",
                "consultation_state": {"schema_version": "consultation_state.v2"},
            },
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 201, create_response.content)
        self.case_id = create_response.json()["case"]["case_id"]
        self.analysis_url = f"/api/cases/{self.case_id}/analysis/jobs/"
        self.confirm_url = f"/api/cases/{self.case_id}/facts/confirm/"
        self.attachment_id = "att_phase_02_b3_police_record"
        UploadedFile.objects.create(
            attachment_id=self.attachment_id,
            owner_id=self.owner_id,
            session=self.session,
            case=self._case(),
            purpose="supporting_evidence",
            file_type="pdf",
            original_filename="police-record.pdf",
            content_type="application/pdf",
            storage_uri=CANONICAL_EVIDENCE_URI,
            status="ready",
            scan_status="passed",
        )
        self.confirmed_payload = {
            "facts": {
                "road_layout": "four_way_intersection",
                "vehicle_actions": "ego_straight_other_left_turn",
                "signal_priority": "ego_green",
                "collision_location": "front_left",
            },
            "sources": [
                {"source_type": "official_document", "source_ref": self.attachment_id}
            ],
            "conflicts": [],
            "user_edit_history": [],
        }

    def _case(self) -> Case:
        return Case.objects.get(case_id=self.case_id)

    def _confirm(self, payload: dict[str, object] | None = None) -> dict[str, object]:
        response = self.owner_client.post(
            self.confirm_url,
            data=self.confirmed_payload if payload is None else payload,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["fact_version"]

    def _start(
        self,
        payload: dict[str, object] | None = None,
        *,
        client: Client | None = None,
    ):
        return (client or self.owner_client).post(
            self.analysis_url,
            data={} if payload is None else payload,
            content_type="application/json",
        )

    def test_owner_success_preserves_job_work_item_plan_and_case_projection(self) -> None:
        fact_version = self._confirm()
        response = self._start({"fact_version_id": fact_version["fact_version_id"]})

        self.assertEqual(response.status_code, 202, response.content)
        payload = response.json()
        self.assertEqual(payload["contract_version"], "case_analysis_job.v2")
        self.assertEqual(payload["job"]["status"], "queued")
        self.assertEqual(payload["work_item"]["status"], "queued")
        self.assertEqual(payload["analysis_plan"]["node_codes"], EXPECTED_NODE_CODES)
        job = AnalysisJob.objects.get(job_id=payload["job"]["job_id"])
        work_item = AgentWorkItem.objects.get(work_item_id=payload["work_item"]["work_item_id"])
        self.assertEqual(AnalysisJob.objects.filter(case=self._case()).count(), 1)
        self.assertEqual(AgentWorkItem.objects.filter(job=job).count(), 1)
        self.assertEqual(job.case_id, self._case().id)
        self.assertEqual(job.owner_id, self.owner_id)
        self.assertEqual(job.session_id, self.session.id)
        self.assertEqual(work_item.job_id, job.id)
        case = self._case()
        self.assertEqual(case.status, "queued")
        self.assertEqual(case.metadata["active_analysis_job_id"], job.job_id)
        self.assertEqual(case.metadata["active_fact_version_id"], fact_version["fact_version_id"])

    def test_foreign_owner_invalid_payload_is_denied_before_validation_without_queue_rows(self) -> None:
        response = self._start(
            {"unknown": "invalid", "owner_id": self.owner_id},
            client=authenticated_client("usr_phase_02_b3_attacker"),
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")
        self.assertNotIn("details", response.json()["error"])
        self.assertEqual(AnalysisJob.objects.filter(case=self._case()).count(), 0)
        self.assertEqual(AgentWorkItem.objects.count(), 0)

    def test_owner_invalid_extra_field_preserves_validation_contract_without_queue_rows(self) -> None:
        self._confirm()
        response = self._start({"unexpected": "invalid"})

        self.assertEqual(response.status_code, 422, response.content)
        error = response.json()["error"]
        self.assertEqual(error["contract_version"], "request_validation_error.v1")
        self.assertEqual(error["code"], "validation_error")
        self.assertTrue(error["details"])
        self.assertEqual(AnalysisJob.objects.filter(case=self._case()).count(), 0)
        self.assertEqual(AgentWorkItem.objects.count(), 0)

    def test_missing_case_preserves_existing_repository_error_contract(self) -> None:
        response = self.owner_client.post(
            "/api/cases/case_phase_02_b3_missing/analysis/jobs/",
            data={},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404, response.content)
        self.assertEqual(response.json()["error"]["code"], "case_not_found")
        self.assertEqual(response.json()["error"]["status"], 404)
        self.assertEqual(AnalysisJob.objects.count(), 0)
        self.assertEqual(AgentWorkItem.objects.count(), 0)

    def test_confirmed_facts_are_required_before_analysis(self) -> None:
        response = self._start()

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "confirmed_facts_required")
        self.assertEqual(AnalysisJob.objects.filter(case=self._case()).count(), 0)
        self.assertEqual(AgentWorkItem.objects.count(), 0)

    def test_incomplete_facts_preserve_readiness_gate_without_queue_rows(self) -> None:
        fact_version = self._confirm(
            {
                **self.confirmed_payload,
                "facts": {"road_layout": "four_way_intersection"},
            }
        )
        response = self._start({"fact_version_id": fact_version["fact_version_id"]})

        self.assertEqual(response.status_code, 409, response.content)
        error = response.json()["error"]
        self.assertEqual(error["code"], "fact_readiness_not_met")
        self.assertEqual(
            error["details"]["missing_fields"],
            ["vehicle_actions", "signal_priority", "collision_location"],
        )
        self.assertEqual(AnalysisJob.objects.filter(case=self._case()).count(), 0)
        self.assertEqual(AgentWorkItem.objects.count(), 0)

    def test_high_risk_case_preserves_case_conflict_without_queue_rows(self) -> None:
        fact_version = self._confirm()
        case = self._case()
        case.risk_level = "high_risk"
        case.save(update_fields=["risk_level", "updated_at"])

        response = self._start({"fact_version_id": fact_version["fact_version_id"]})

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "case_conflict")
        self.assertEqual(AnalysisJob.objects.filter(case=case).count(), 0)
        self.assertEqual(AgentWorkItem.objects.count(), 0)

    def test_case_without_session_preserves_case_conflict_without_queue_rows(self) -> None:
        fact_version = self._confirm()
        self.session.delete()

        response = self._start({"fact_version_id": fact_version["fact_version_id"]})

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "case_conflict")
        self.assertEqual(AnalysisJob.objects.filter(case=self._case()).count(), 0)
        self.assertEqual(AgentWorkItem.objects.count(), 0)

    def test_empty_fact_version_id_selects_latest_confirmed_fact_version(self) -> None:
        self._confirm()
        latest = self._confirm(
            {
                **self.confirmed_payload,
                "facts": {
                    **self.confirmed_payload["facts"],
                    "collision_location": "rear_right",
                },
            }
        )

        response = self._start({"fact_version_id": ""})

        self.assertEqual(response.status_code, 202, response.content)
        job = AnalysisJob.objects.get(job_id=response.json()["job"]["job_id"])
        self.assertEqual(job.metadata["fact_version_id"], latest["fact_version_id"])

    def test_exact_duplicate_reuses_job_and_work_item_for_same_fact_version(self) -> None:
        fact_version = self._confirm()
        first = self._start({"fact_version_id": fact_version["fact_version_id"]})
        second = self._start({"fact_version_id": fact_version["fact_version_id"]})

        self.assertEqual(first.status_code, 202, first.content)
        self.assertEqual(second.status_code, 202, second.content)
        self.assertEqual(second.json()["job"]["job_id"], first.json()["job"]["job_id"])
        self.assertEqual(
            second.json()["work_item"]["work_item_id"],
            first.json()["work_item"]["work_item_id"],
        )
        self.assertEqual(AnalysisJob.objects.filter(case=self._case()).count(), 1)
        self.assertEqual(AgentWorkItem.objects.count(), 1)
        case = self._case()
        self.assertEqual(case.metadata["active_analysis_job_id"], first.json()["job"]["job_id"])
        self.assertEqual(case.metadata["active_fact_version_id"], fact_version["fact_version_id"])

    def test_new_fact_version_creates_new_job_and_work_item(self) -> None:
        first_fact_version = self._confirm()
        first = self._start({"fact_version_id": first_fact_version["fact_version_id"]})
        next_fact_version = self._confirm(
            {
                **self.confirmed_payload,
                "facts": {
                    **self.confirmed_payload["facts"],
                    "collision_location": "rear_right",
                },
            }
        )
        second = self._start({"fact_version_id": next_fact_version["fact_version_id"]})

        self.assertEqual(first.status_code, 202, first.content)
        self.assertEqual(second.status_code, 202, second.content)
        self.assertNotEqual(second.json()["job"]["job_id"], first.json()["job"]["job_id"])
        self.assertNotEqual(
            second.json()["work_item"]["work_item_id"],
            first.json()["work_item"]["work_item_id"],
        )
        self.assertEqual(AnalysisJob.objects.filter(case=self._case()).count(), 2)
        self.assertEqual(AgentWorkItem.objects.count(), 2)
        self.assertEqual(
            self._case().metadata["active_fact_version_id"],
            next_fact_version["fact_version_id"],
        )

    def test_failed_job_is_not_reused_for_same_fact_version(self) -> None:
        fact_version = self._confirm()
        first = self._start({"fact_version_id": fact_version["fact_version_id"]})
        failed_job = AnalysisJob.objects.get(job_id=first.json()["job"]["job_id"])
        failed_job.status = "failed"
        failed_job.save(update_fields=["status", "updated_at"])

        second = self._start({"fact_version_id": fact_version["fact_version_id"]})

        self.assertEqual(second.status_code, 202, second.content)
        self.assertNotEqual(second.json()["job"]["job_id"], failed_job.job_id)
        self.assertEqual(AnalysisJob.objects.filter(case=self._case()).count(), 2)
        self.assertEqual(AgentWorkItem.objects.count(), 2)

    def test_queue_payload_keeps_private_facts_and_evidence_out_of_public_execution_context(self) -> None:
        fact_version = self._confirm()
        response = self._start({"fact_version_id": fact_version["fact_version_id"]})

        self.assertEqual(response.status_code, 202, response.content)
        work_item = AgentWorkItem.objects.get(work_item_id=response.json()["work_item"]["work_item_id"])
        payload = work_item.payload
        execution_payload = payload["execution_payload"]
        server_context = payload["server_execution_context"]["context"]
        self.assertIn("user_facts", server_context)
        self.assertIn("case_evidence", server_context)
        self.assertNotIn("case_evidence", execution_payload)
        self.assertNotIn("user_facts", execution_payload.get("context", {}))
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(CANONICAL_EVIDENCE_URI, serialized)
        self.assertNotIn("mock://", serialized)

    def test_y_application_derives_owner_from_trusted_identity_and_rolls_back_queue_rows(self) -> None:
        fact_version = self._confirm()
        module = importlib.import_module("app.application.cases.start_analysis")
        case_before = self._case()
        before_status = case_before.status
        before_metadata = dict(case_before.metadata)
        from chatbot.case_repository import enqueue_analysis_job_work as original_enqueue

        def enqueue_then_fail(*args, **kwargs):
            original_enqueue(*args, **kwargs)
            raise RuntimeError("phase-02-b3 enqueue rollback probe")

        with patch("chatbot.case_repository.enqueue_analysis_job_work", side_effect=enqueue_then_fail):
            with self.assertRaisesRegex(RuntimeError, "enqueue rollback probe"):
                module.execute_start_case_analysis(
                    module.StartCaseAnalysisCommand(
                        case_id=self.case_id,
                        identity_payload={"auth_context": {"user_id": self.owner_id}},
                        raw_payload={"fact_version_id": fact_version["fact_version_id"]},
                    )
                )

        self.assertEqual(AnalysisJob.objects.filter(case=self._case()).count(), 0)
        self.assertEqual(AgentWorkItem.objects.count(), 0)
        case_after = self._case()
        self.assertEqual(case_after.status, before_status)
        self.assertEqual(case_after.metadata, before_metadata)

    def test_z_application_command_has_no_http_mock_orm_or_transaction_dependencies_and_view_is_adapter_only(self) -> None:
        module = importlib.import_module("app.application.cases.start_analysis")
        self.assertEqual(
            tuple(module.StartCaseAnalysisCommand.__dataclass_fields__),
            ("case_id", "identity_payload", "raw_payload"),
        )
        application_tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        forbidden_modules = {
            "django.http",
            "django.db",
            "app.mock_runtime",
            "backend.chatbot.views",
            "chatbot.models",
        }
        forbidden_names = {
            "HttpRequest",
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
            if isinstance(node, ast.FunctionDef) and node.name == "consultation_case_analysis_jobs"
        )
        direct_calls = {
            node.func.id
            for node in ast.walk(view)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(
            {
                "authorize_resource_access",
                "get_case_access_metadata",
                "start_case_analysis",
                "_validate_request_dto",
            }.isdisjoint(direct_calls)
        )
