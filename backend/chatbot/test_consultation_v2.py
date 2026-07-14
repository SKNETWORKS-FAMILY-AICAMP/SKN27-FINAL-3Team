from __future__ import annotations

from datetime import timedelta
from importlib import import_module, util
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.apps import apps
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from app.contracts.consultation_case import (
    CaseApiErrorResponse,
    ConfirmCaseFactsResponse,
    ConsultationCaseListResponse,
    ConsultationCaseWorkspaceResponse,
    CreateConsultationCaseResponse,
    StartCaseAnalysisResponse,
)
from app.services.google_auth_service import issue_access_token
from chatbot.case_repository import (
    CaseAnalysisInProgress,
    CaseOwnerMismatch,
    create_case,
)
from chatbot.models import (
    AgentWorkItem,
    AgentWorkItemStatus,
    AnalysisJob,
    AuthSession,
    AuthSessionStatus,
    Case,
    ChatSession,
    ChatSessionStatus,
    ConfirmedFactVersion,
    Report,
    ReportType,
    UploadedFile,
    UserAccount,
)
from chatbot.repositories import (
    list_uploaded_files,
    persist_report_action,
    persist_uploaded_file_metadata,
    purge_pending_report_staging,
    reserve_analysis_job_request,
)


ROOT = Path(__file__).resolve().parents[2]
TEST_JWT_SIGNING_KEY = "consultation-v2-test-signing-key-is-long-enough"


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


def consultation_service():
    module_name = "app.services.consultation_v2_service"
    assert util.find_spec(module_name) is not None, "consultation v2 service is missing"
    return import_module(module_name)


class ConsultationStateV2Tests(SimpleTestCase):
    def test_partial_accident_state_requests_only_missing_core_facts(self) -> None:
        service = consultation_service()

        state = service.build_consultation_state_v2(
            user_text="교차로에서 직진 중 옆 차량과 충돌했습니다.",
            facts={
                "road_layout": "four_way_intersection",
                "vehicle_actions": "ego_straight_other_unknown",
            },
            sources=[{"field": "road_layout", "source_type": "user_statement"}],
            conflicts=[],
        )

        self.assertEqual(state["schema_version"], "consultation_state.v2")
        self.assertEqual(state["risk_gate"]["level"], "standard")
        self.assertFalse(state["readiness"]["ready_for_fault_range"])
        self.assertEqual(
            state["readiness"]["missing_fields"],
            ["signal_priority", "collision_location"],
        )
        self.assertEqual(
            [question["field"] for question in state["next_questions"]],
            ["signal_priority", "collision_location"],
        )
        self.assertEqual(
            {card["category"] for card in state["fact_cards"]},
            {"user_statement", "unconfirmed"},
        )

    def test_high_risk_state_blocks_fault_range_and_requires_handoff(self) -> None:
        service = consultation_service()

        state = service.build_consultation_state_v2(
            user_text="보행자가 크게 다쳐 의식이 없고 구급차를 기다리고 있습니다.",
            facts={},
            sources=[],
            conflicts=[],
        )

        self.assertEqual(state["risk_gate"]["level"], "high_risk")
        self.assertFalse(state["risk_gate"]["allows_fault_range"])
        self.assertEqual(state["next_action"], "expert_handoff")
        self.assertFalse(state["readiness"]["ready_for_fault_range"])
        self.assertIn("preserve_evidence", state["risk_gate"]["required_actions"])


class ConsultationV2ModelContractTests(SimpleTestCase):
    def test_case_models_and_report_types_form_the_versioned_domain(self) -> None:
        case_model = apps.all_models["chatbot"].get("case")
        fact_model = apps.all_models["chatbot"].get("confirmedfactversion")

        self.assertIsNotNone(case_model)
        self.assertIsNotNone(fact_model)
        self.assertEqual(
            set(ReportType.values),
            {
                "fine_notice_objection",
                "fault_ratio_analysis",
                "general",
                "initial_consultation",
                "expert_handoff",
            },
        )
        self.assertEqual(
            {field.name for field in case_model._meta.fields} & {
                "case_id",
                "owner_id",
                "status",
                "risk_level",
                "current_fact_version",
                "current_report_version",
            },
            {
                "case_id",
                "owner_id",
                "status",
                "risk_level",
                "current_fact_version",
                "current_report_version",
            },
        )

        for model_name in ("chatsession", "uploadedfile", "analysisjob", "report"):
            model = apps.all_models["chatbot"][model_name]
            self.assertIn("case", {field.name for field in model._meta.fields})

        report_fields = {field.name for field in apps.all_models["chatbot"]["report"]._meta.fields}
        self.assertIn("source_fact_version", report_fields)
        self.assertIn("version_no", report_fields)


class ConsultationV2MigrationTests(TestCase):
    def test_backfill_promotes_only_authenticated_fault_sessions_to_cases(self) -> None:
        migration = import_module("chatbot.migrations.0009_consultation_case_v2")
        self.assertTrue(hasattr(migration, "backfill_authenticated_fault_cases"))
        fault_session = ChatSession.objects.create(
            session_id="ses_backfill_fault",
            owner_id="usr_backfill",
            title="기존 과실상담",
            status=ChatSessionStatus.ACTIVE,
            current_intent="fault_ratio_text",
        )
        ChatSession.objects.create(
            session_id="ses_backfill_general",
            owner_id="usr_backfill",
            status=ChatSessionStatus.ACTIVE,
            current_intent="traffic_law_search",
        )
        ChatSession.objects.create(
            session_id="ses_backfill_guest",
            owner_id="",
            status=ChatSessionStatus.ACTIVE,
            current_intent="fault_ratio_text",
        )

        migration.backfill_authenticated_fault_cases(apps, None)

        fault_session.refresh_from_db()
        self.assertIsNotNone(fault_session.case_id)
        self.assertEqual(fault_session.case.owner_id, "usr_backfill")
        self.assertEqual(
            fault_session.case.metadata["backfill_source"],
            "authenticated_fault_ratio_session",
        )
        self.assertIsNone(ChatSession.objects.get(session_id="ses_backfill_general").case_id)
        self.assertIsNone(ChatSession.objects.get(session_id="ses_backfill_guest").case_id)


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class ConsultationCaseApiTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_consultation_owner"
        self.client = authenticated_client(self.owner_id)
        self.session = ChatSession.objects.create(
            session_id="ses_consultation_v2",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
            current_intent="fault_ratio_text",
        )

    def test_authenticated_user_creates_lists_and_reads_case_workspace(self) -> None:
        create_response = self.client.post(
            "/api/cases/",
            data={
                "session_id": self.session.session_id,
                "title": "교차로 충돌 초기상담",
                "case_type": "accident_fault",
                "consultation_state": {
                    "schema_version": "consultation_state.v2",
                    "risk_gate": {"level": "standard"},
                },
            },
            content_type="application/json",
        )

        self.assertEqual(create_response.status_code, 201)
        CreateConsultationCaseResponse.model_validate(create_response.json())
        created = create_response.json()["case"]
        self.assertEqual(create_response.json()["contract_version"], "consultation_case.v2")
        self.assertEqual(created["owner_id"], self.owner_id)
        self.assertEqual(created["status"], "awaiting_fact_confirmation")

        list_response = self.client.get("/api/cases/")
        self.assertEqual(list_response.status_code, 200)
        ConsultationCaseListResponse.model_validate(list_response.json())
        self.assertEqual([item["case_id"] for item in list_response.json()["cases"]], [created["case_id"]])

        workspace_response = self.client.get(f"/api/cases/{created['case_id']}/workspace/")
        self.assertEqual(workspace_response.status_code, 200)
        ConsultationCaseWorkspaceResponse.model_validate(workspace_response.json())
        workspace = workspace_response.json()["workspace"]
        self.assertEqual(workspace["contract_version"], "case_workspace.v2")
        self.assertEqual(workspace["case"]["case_id"], created["case_id"])
        self.assertEqual(workspace["confirmed_facts"], [])

        other_client = authenticated_client("usr_other_case_owner")
        denied = other_client.get(f"/api/cases/{created['case_id']}/workspace/")
        self.assertEqual(denied.status_code, 403)
        CaseApiErrorResponse.model_validate(denied.json())
        self.assertEqual(denied.json()["error"]["code"], "object_access_denied")

    def test_fact_confirmation_precedes_real_worker_queue(self) -> None:
        create_response = self.client.post(
            "/api/cases/",
            data={
                "session_id": self.session.session_id,
                "title": "사실확정 테스트",
                "case_type": "accident_fault",
                "consultation_state": {"schema_version": "consultation_state.v2"},
            },
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()["case"]

        premature = self.client.post(
            f"/api/cases/{created['case_id']}/analysis/jobs/",
            data={},
            content_type="application/json",
        )
        self.assertEqual(premature.status_code, 409)
        CaseApiErrorResponse.model_validate(premature.json())
        self.assertEqual(premature.json()["error"]["code"], "confirmed_facts_required")

        confirmed_facts_payload = {
            "facts": {
                "road_layout": "four_way_intersection",
                "vehicle_actions": "ego_straight_other_left_turn",
                "signal_priority": "ego_green",
                "collision_location": "front_left",
            },
            "sources": [{"source_type": "user_confirmation", "source_ref": "case-form"}],
            "conflicts": [],
            "user_edit_history": [],
        }
        facts_response = self.client.post(
            f"/api/cases/{created['case_id']}/facts/confirm/",
            data=confirmed_facts_payload,
            content_type="application/json",
        )
        self.assertEqual(facts_response.status_code, 201)
        ConfirmCaseFactsResponse.model_validate(facts_response.json())
        fact_version = facts_response.json()["fact_version"]
        self.assertEqual(fact_version["schema_version"], "confirmed_facts.v1")
        self.assertEqual(fact_version["version_no"], 1)

        job_response = self.client.post(
            f"/api/cases/{created['case_id']}/analysis/jobs/",
            data={"fact_version_id": fact_version["fact_version_id"]},
            content_type="application/json",
        )
        self.assertEqual(job_response.status_code, 202)
        StartCaseAnalysisResponse.model_validate(job_response.json())
        body = job_response.json()
        self.assertEqual(body["contract_version"], "case_analysis_job.v2")
        self.assertEqual(body["job"]["status"], "queued")
        self.assertEqual(body["work_item"]["status"], "queued")
        self.assertEqual(
            body["analysis_plan"]["node_codes"],
            [
                "text_ml_case_search",
                "law_ground_search",
                "objection_report_generation",
            ],
        )

        analysis_job = apps.get_model("chatbot", "AnalysisJob").objects.get(
            job_id=body["job"]["job_id"]
        )
        self.assertEqual(analysis_job.case.case_id, created["case_id"])
        self.assertEqual(analysis_job.owner_id, self.owner_id)
        self.assertEqual(analysis_job.work_items.get().work_item_id, body["work_item"]["work_item_id"])
        self.assertIn(
            '"road_layout":"four_way_intersection"',
            analysis_job.work_items.get().payload["execution_payload"]["context"]["user_facts"],
        )

        facts_retry_response = self.client.post(
            f"/api/cases/{created['case_id']}/facts/confirm/",
            data=confirmed_facts_payload,
            content_type="application/json",
        )
        self.assertEqual(facts_retry_response.status_code, 201)
        self.assertEqual(
            facts_retry_response.json()["fact_version"]["fact_version_id"],
            fact_version["fact_version_id"],
        )
        self.assertEqual(
            apps.get_model("chatbot", "ConfirmedFactVersion").objects.filter(
                case__case_id=created["case_id"]
            ).count(),
            1,
        )
        case_after_retry = apps.get_model("chatbot", "Case").objects.get(
            case_id=created["case_id"]
        )
        self.assertEqual(
            case_after_retry.metadata["active_analysis_job_id"],
            analysis_job.job_id,
        )

        duplicate_response = self.client.post(
            f"/api/cases/{created['case_id']}/analysis/jobs/",
            data={"fact_version_id": fact_version["fact_version_id"]},
            content_type="application/json",
        )
        self.assertEqual(duplicate_response.status_code, 202)
        StartCaseAnalysisResponse.model_validate(duplicate_response.json())
        duplicate = duplicate_response.json()
        self.assertEqual(duplicate["job"]["job_id"], body["job"]["job_id"])
        self.assertEqual(
            duplicate["work_item"]["work_item_id"],
            body["work_item"]["work_item_id"],
        )
        case_model = apps.get_model("chatbot", "Case")
        work_item_model = apps.get_model("chatbot", "AgentWorkItem")
        self.assertEqual(case_model.objects.get(case_id=created["case_id"]).analysis_jobs.count(), 1)
        self.assertEqual(work_item_model.objects.filter(job=analysis_job).count(), 1)

    def test_incomplete_confirmed_facts_do_not_start_analysis(self) -> None:
        create_response = self.client.post(
            "/api/cases/",
            data={
                "session_id": self.session.session_id,
                "title": "불완전 사실 테스트",
                "case_type": "accident_fault",
                "consultation_state": {"schema_version": "consultation_state.v2"},
            },
            content_type="application/json",
        )
        case_id = create_response.json()["case"]["case_id"]
        facts_response = self.client.post(
            f"/api/cases/{case_id}/facts/confirm/",
            data={
                "facts": {"road_layout": "four_way_intersection"},
                "sources": [{"source_type": "user_confirmation", "source_ref": "case-form"}],
                "conflicts": [],
            },
            content_type="application/json",
        )
        fact_version_id = facts_response.json()["fact_version"]["fact_version_id"]

        response = self.client.post(
            f"/api/cases/{case_id}/analysis/jobs/",
            data={"fact_version_id": fact_version_id},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        CaseApiErrorResponse.model_validate(response.json())
        error = response.json()["error"]
        self.assertEqual(error["code"], "fact_readiness_not_met")
        self.assertEqual(
            error["details"]["missing_fields"],
            ["vehicle_actions", "signal_priority", "collision_location"],
        )
        self.assertFalse(apps.get_model("chatbot", "AgentWorkItem").objects.exists())

    def test_case_creation_requires_authenticated_user(self) -> None:
        response = Client().post(
            "/api/cases/",
            data={"session_id": self.session.session_id, "case_type": "accident_fault"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        CaseApiErrorResponse.model_validate(response.json())
        self.assertEqual(response.json()["error"]["code"], "login_required")

    def test_case_creation_validates_typed_request_before_repository(self) -> None:
        response = self.client.post(
            "/api/cases/",
            data={"title": "session 없는 사건", "case_type": "accident_fault"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 422)
        CaseApiErrorResponse.model_validate(response.json())
        error = response.json()["error"]
        self.assertEqual(error["contract_version"], "request_validation_error.v1")
        self.assertEqual(error["code"], "validation_error")
        self.assertIn("session_id", {item["field"] for item in error["details"]})
        case_model = apps.get_model("chatbot", "Case")
        self.assertFalse(case_model.objects.exists())

    def test_accident_chat_collects_missing_facts_before_worker_queue(self) -> None:
        response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": self.session.session_id,
                "user_text": "교차로 사고 과실을 확인하고 싶습니다.",
                "facts": {"road_layout": "four_way_intersection"},
                "fact_sources": [
                    {"field": "road_layout", "source_type": "user_statement"},
                ],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["routing_intent"], "fault_ratio_text")
        self.assertEqual(body["status"], "needs_input")
        self.assertEqual(body["execution_mode"], "input_collection")
        state = body["consultation_state"]["v2"]
        self.assertEqual(state["schema_version"], "consultation_state.v2")
        self.assertEqual(
            [item["field"] for item in body["pending_questions"]],
            ["vehicle_actions", "signal_priority", "collision_location"],
        )
        self.assertFalse(apps.get_model("chatbot", "AgentWorkItem").objects.exists())

    def test_high_risk_accident_chat_returns_handoff_without_worker_queue(self) -> None:
        response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": self.session.session_id,
                "user_text": "보행자가 크게 다쳐 의식이 없고 구급차를 기다리고 있습니다.",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["routing_intent"], "fault_ratio_text")
        self.assertEqual(body["status"], "high_risk_handoff")
        self.assertEqual(body["execution_mode"], "expert_handoff")
        self.assertEqual(body["consultation_state"]["v2"]["next_action"], "expert_handoff")
        self.assertNotIn("work_item", body)
        self.assertFalse(apps.get_model("chatbot", "AgentWorkItem").objects.exists())

    def test_complete_accident_intake_requires_case_before_worker_queue(self) -> None:
        response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": self.session.session_id,
                "user_text": "교차로 충돌 사고의 과실을 확인하고 싶습니다.",
                "facts": {
                    "road_layout": "four_way_intersection",
                    "vehicle_actions": "ego_straight_other_left_turn",
                    "signal_priority": "ego_green",
                    "collision_location": "front_left",
                },
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "case_ready")
        self.assertEqual(body["execution_mode"], "case_creation_required")
        self.assertEqual(body["consultation_state"]["v2"]["next_action"], "confirm_facts")
        self.assertNotIn("work_item", body)
        self.assertFalse(apps.get_model("chatbot", "AgentWorkItem").objects.exists())


class ConsultationV2DesignContractTests(SimpleTestCase):
    def test_design_document_keeps_vision_and_neo4j_as_product_core(self) -> None:
        path = ROOT / "docs/architecture/ai-traffic-dispute-consultation-v2-implementation-design-2026-07-10.md"

        self.assertTrue(path.exists())
        content = path.read_text(encoding="utf-8")
        for required in (
            "Vision",
            "Neo4j",
            "confirmed_facts.v1",
            "consultation_state.v2",
            "fault_assessment.v2",
            "consultation_report.v2",
            "OpenSearch + pgvector + Neo4j",
        ):
            self.assertIn(required, content)

        migration = ROOT / "backend/chatbot/migrations/0009_consultation_case_v2.py"
        self.assertTrue(migration.exists())


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class ConsultationPersistenceSafetyTests(TestCase):
    def setUp(self) -> None:
        self.object_storage_dir = TemporaryDirectory()
        self.addCleanup(self.object_storage_dir.cleanup)
        storage_settings = override_settings(
            OBJECT_STORAGE_LOCAL_ROOT=self.object_storage_dir.name,
        )
        storage_settings.enable()
        self.addCleanup(storage_settings.disable)
        self.owner_id = "usr_case_owner"
        self.case = Case.objects.create(
            case_id="case_persistence_safety",
            owner_id=self.owner_id,
            title="Persistence safety",
        )
        self.session = ChatSession.objects.create(
            session_id="ses_persistence_safety",
            owner_id=self.owner_id,
            case=self.case,
            status=ChatSessionStatus.ACTIVE,
        )
        self.fact_version = ConfirmedFactVersion.objects.create(
            fact_version_id="fact_persistence_safety",
            case=self.case,
            version_no=1,
            status="confirmed",
            facts={"road_layout": "intersection"},
            confirmed_by=self.owner_id,
            confirmed_at=timezone.now(),
        )

    def _attachment(self, *, attachment_id: str, file_type: str, content_type: str) -> dict:
        return {
            "attachment_id": attachment_id,
            "session_id": self.session.session_id,
            "purpose": "supporting_evidence",
            "type": file_type,
            "original_filename": f"{attachment_id}.{file_type}",
            "content_type": content_type,
            "size_bytes": 128,
            "storage_uri": f"mock://metadata/{attachment_id}",
            "status": "metadata_registered",
            "agent_handoff": {},
        }

    def test_case_repository_rejects_empty_owner_even_for_ownerless_session(self) -> None:
        guest_session = ChatSession.objects.create(
            session_id="ses_ownerless_case",
            owner_id="",
            status=ChatSessionStatus.ACTIVE,
        )

        with self.assertRaises(CaseOwnerMismatch):
            create_case(owner_id="", payload={"session_id": guest_session.session_id})

    def test_guest_case_promotion_requires_matching_guest_identity(self) -> None:
        guest_session = ChatSession.objects.create(
            session_id="ses_guest_identity_guard",
            owner_id="",
            status=ChatSessionStatus.ACTIVE,
            metadata={"auth_context": {"guest_id": "gst_original"}},
        )

        with self.assertRaises(CaseOwnerMismatch):
            create_case(
                owner_id="usr_attacker",
                guest_id="gst_other",
                payload={"session_id": guest_session.session_id},
            )

    def test_guest_case_promotion_rejects_active_unbound_worker_jobs(self) -> None:
        for work_status in (
            AgentWorkItemStatus.QUEUED,
            AgentWorkItemStatus.RETRYING,
            AgentWorkItemStatus.RUNNING,
        ):
            with self.subTest(work_status=work_status):
                suffix = str(work_status)
                guest_id = f"gst_active_{suffix}"
                owner_id = f"usr_active_{suffix}"
                guest_session = ChatSession.objects.create(
                    session_id=f"ses_guest_active_{suffix}",
                    owner_id="",
                    status=ChatSessionStatus.ACTIVE,
                    metadata={"auth_context": {"guest_id": guest_id}},
                )
                job = AnalysisJob.objects.create(
                    job_id=f"job_guest_active_{suffix}",
                    session=guest_session,
                    owner_id="",
                    status="queued",
                )
                AgentWorkItem.objects.create(
                    work_item_id=f"work_guest_active_{suffix}",
                    job=job,
                    status=work_status,
                    attempt_no=1 if work_status == AgentWorkItemStatus.RUNNING else 0,
                    locked_at=(
                        timezone.now()
                        if work_status == AgentWorkItemStatus.RUNNING
                        else None
                    ),
                )

                with self.assertRaises(CaseAnalysisInProgress):
                    create_case(
                        owner_id=owner_id,
                        guest_id=guest_id,
                        payload={"session_id": guest_session.session_id},
                    )

                guest_session.refresh_from_db()
                job.refresh_from_db()
                self.assertIsNone(guest_session.case_id)
                self.assertEqual(guest_session.owner_id, "")
                self.assertIsNone(job.case_id)
                self.assertEqual(job.owner_id, "")
                self.assertFalse(Case.objects.filter(owner_id=owner_id).exists())

    def test_guest_case_promotion_succeeds_after_worker_becomes_terminal(self) -> None:
        guest_session = ChatSession.objects.create(
            session_id="ses_guest_terminal_promotion",
            owner_id="",
            status=ChatSessionStatus.ACTIVE,
            metadata={"auth_context": {"guest_id": "gst_terminal_promotion"}},
        )
        job = AnalysisJob.objects.create(
            job_id="job_guest_terminal_promotion",
            session=guest_session,
            owner_id="",
            status="success",
        )
        AgentWorkItem.objects.create(
            work_item_id="work_guest_terminal_promotion",
            job=job,
            status=AgentWorkItemStatus.SUCCESS,
            attempt_no=1,
            completed_at=timezone.now(),
        )

        created_case = create_case(
            owner_id="usr_terminal_promotion",
            guest_id="gst_terminal_promotion",
            payload={"session_id": guest_session.session_id},
        )

        job.refresh_from_db()
        self.assertEqual(job.owner_id, "usr_terminal_promotion")
        self.assertEqual(job.case.case_id, created_case["case_id"])

    def test_case_creation_rejects_an_unpromoted_analysis_reservation(self) -> None:
        owner_id = "usr_case_reservation_guard"
        session = ChatSession.objects.create(
            session_id="ses_case_reservation_guard",
            owner_id=owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        reserve_analysis_job_request(
            {
                "owner_id": owner_id,
                "user_id": owner_id,
                "session_id": session.session_id,
                "user_text": "reserved analysis request",
            },
            job_id="job_case_reservation_guard",
            request_fingerprint="sha256:case-reservation-guard",
        )

        with self.assertRaises(CaseAnalysisInProgress):
            create_case(
                owner_id=owner_id,
                payload={"session_id": session.session_id},
            )

        session.refresh_from_db()
        reservation = AnalysisJob.objects.get(job_id="job_case_reservation_guard")
        self.assertIsNone(session.case_id)
        self.assertIsNone(reservation.case_id)
        self.assertFalse(Case.objects.filter(owner_id=owner_id).exists())

    def test_case_upload_rejects_missing_authenticated_owner(self) -> None:
        with self.assertRaises(PermissionError):
            persist_uploaded_file_metadata(
                self._attachment(
                    attachment_id="att_missing_owner",
                    file_type="image",
                    content_type="image/jpeg",
                ),
                owner_id="",
                raw_payload={"case_id": self.case.case_id},
            )

    @override_settings(GUEST_RETENTION_DAYS=7, USER_RETENTION_DAYS=365)
    def test_guest_document_is_relinked_and_extended_when_session_becomes_a_case(self) -> None:
        guest_session = ChatSession.objects.create(
            session_id="ses_guest_promotion",
            owner_id="",
            status=ChatSessionStatus.ACTIVE,
            metadata={"auth_context": {"guest_id": "gst_promotion"}},
        )
        attachment = self._attachment(
            attachment_id="att_guest_promotion",
            file_type="pdf",
            content_type="application/pdf",
        )
        attachment["session_id"] = guest_session.session_id
        persist_uploaded_file_metadata(
            attachment,
            owner_id="",
            raw_payload={"guest_id": "gst_promotion"},
        )

        created_case = create_case(
            owner_id="usr_promoted",
            guest_id="gst_promotion",
            payload={"session_id": guest_session.session_id},
        )

        uploaded_file = UploadedFile.objects.get(attachment_id=attachment["attachment_id"])
        remaining_days = (uploaded_file.retention_expires_at - timezone.now()).days
        expected_case_id = Case.objects.get(case_id=created_case["case_id"]).id
        self.assertEqual(uploaded_file.case_id, expected_case_id)
        self.assertEqual(uploaded_file.owner_id, "usr_promoted")
        self.assertIn(remaining_days, {364, 365})
        self.assertEqual(
            [item["attachment_id"] for item in list_uploaded_files(owner_id="usr_promoted")],
            [attachment["attachment_id"]],
        )

    def test_guest_case_promotion_transfers_job_and_report_ownership(self) -> None:
        guest_session = ChatSession.objects.create(
            session_id="ses_guest_related_records",
            owner_id="",
            status=ChatSessionStatus.ACTIVE,
            metadata={"auth_context": {"guest_id": "gst_related_records"}},
        )
        job = AnalysisJob.objects.create(
            job_id="job_guest_related_records",
            session=guest_session,
            owner_id="",
        )
        report = Report.objects.create(
            report_id="rep_guest_related_records",
            session=guest_session,
            owner_id="",
            version_no=1,
        )

        created_case = create_case(
            owner_id="usr_promoted_records",
            guest_id="gst_related_records",
            payload={"session_id": guest_session.session_id},
        )

        expected_case = Case.objects.get(case_id=created_case["case_id"])
        job.refresh_from_db()
        report.refresh_from_db()
        self.assertEqual((job.owner_id, job.case_id), ("usr_promoted_records", expected_case.id))
        self.assertEqual(
            (report.owner_id, report.case_id, report.version_no),
            ("usr_promoted_records", expected_case.id, 1),
        )
        self.assertEqual(expected_case.current_report_version, 1)

    def test_attachment_id_collision_is_rejected_before_object_write(self) -> None:
        other_session = ChatSession.objects.create(
            session_id="ses_existing_attachment_owner",
            owner_id="usr_existing_attachment_owner",
            status=ChatSessionStatus.ACTIVE,
        )
        existing = UploadedFile.objects.create(
            attachment_id="att_owner_collision",
            owner_id="usr_existing_attachment_owner",
            session=other_session,
            original_filename="existing.pdf",
        )

        with patch(
            "chatbot.repositories.write_object_from_source_uri",
            return_value={
                "status": "written",
                "writes_binary": True,
                "persistence_state": "persisted",
            },
        ) as storage_write:
            with self.assertRaises(PermissionError):
                persist_uploaded_file_metadata(
                    self._attachment(
                        attachment_id=existing.attachment_id,
                        file_type="pdf",
                        content_type="application/pdf",
                    ),
                    owner_id=self.owner_id,
                    raw_payload={"case_id": self.case.case_id},
                )

        storage_write.assert_not_called()
        existing.refresh_from_db()
        self.assertEqual(existing.owner_id, "usr_existing_attachment_owner")

    def test_file_api_ignores_client_supplied_attachment_id(self) -> None:
        client = authenticated_client(self.owner_id)
        server_attachment = self._attachment(
            attachment_id="att_server_generated",
            file_type="pdf",
            content_type="application/pdf",
        )
        with (
            patch(
                "chatbot.repositories.register_mock_attachment",
                return_value=server_attachment,
            ) as register_attachment,
            patch(
                "chatbot.repositories.write_object_from_source_uri",
                return_value={
                    "status": "written",
                    "writes_binary": True,
                    "persistence_state": "persisted",
                },
            ),
        ):
            response = client.post(
                "/api/files/",
                data={
                    "attachment_id": "att_client_controlled",
                    "session_id": self.session.session_id,
                    "case_id": self.case.case_id,
                    "purpose": "supporting_evidence",
                    "filename": "evidence.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 128,
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content)
        registration_payload = register_attachment.call_args.args[0]
        self.assertNotIn("attachment_id", registration_payload)
        self.assertNotEqual(
            response.json()["attachment"]["attachment_id"],
            "att_client_controlled",
        )

    @override_settings(RAW_MEDIA_RETENTION_DAYS=45, USER_RETENTION_DAYS=365)
    def test_upload_retention_uses_media_and_authenticated_document_settings(self) -> None:
        media = persist_uploaded_file_metadata(
            self._attachment(
                attachment_id="att_media_retention",
                file_type="image",
                content_type="image/jpeg",
            ),
            owner_id=self.owner_id,
            raw_payload={"case_id": self.case.case_id},
        )
        document = persist_uploaded_file_metadata(
            self._attachment(
                attachment_id="att_document_retention",
                file_type="pdf",
                content_type="application/pdf",
            ),
            owner_id=self.owner_id,
            raw_payload={"case_id": self.case.case_id},
        )

        media_record = UploadedFile.objects.get(attachment_id=media["attachment_id"])
        document_record = UploadedFile.objects.get(attachment_id=document["attachment_id"])
        media_days = (media_record.retention_expires_at - timezone.now()).days
        document_days = (document_record.retention_expires_at - timezone.now()).days
        self.assertIn(media_days, {44, 45})
        self.assertIn(document_days, {364, 365})

    def test_report_rejects_case_owner_mismatch_and_unknown_fact_version(self) -> None:
        with self.assertRaises(PermissionError):
            persist_report_action(
                {
                    "owner_id": "usr_other",
                    "session_id": self.session.session_id,
                    "case_id": self.case.case_id,
                    "action": "save",
                },
                {"report_id": "rep_wrong_owner", "status": "ready"},
            )

        with self.assertRaises(ValueError):
            persist_report_action(
                {
                    "owner_id": self.owner_id,
                    "session_id": self.session.session_id,
                    "case_id": self.case.case_id,
                    "source_fact_version": "fact_unknown",
                    "action": "save",
                },
                {"report_id": "rep_unknown_fact", "status": "ready"},
            )

    def test_report_rejects_cross_case_job_provenance_before_object_write(self) -> None:
        other_case = Case.objects.create(
            case_id="case_same_owner_other_context",
            owner_id=self.owner_id,
        )
        ChatSession.objects.create(
            session_id="ses_same_owner_other_context",
            owner_id=self.owner_id,
            case=other_case,
            status=ChatSessionStatus.ACTIVE,
        )
        job = AnalysisJob.objects.create(
            job_id="job_original_case_context",
            session=self.session,
            case=self.case,
            owner_id=self.owner_id,
        )
        other_fact = ConfirmedFactVersion.objects.create(
            fact_version_id="fact_same_owner_other_context",
            case=other_case,
            version_no=1,
            status="confirmed",
            facts={"road_layout": "other"},
        )

        with patch(
            "chatbot.repositories.write_object",
            return_value={
                "status": "written",
                "writes_binary": True,
                "persistence_state": "persisted",
            },
        ) as storage_write:
            with self.assertRaises(ValueError):
                persist_report_action(
                    {
                        "owner_id": self.owner_id,
                        "job_id": job.job_id,
                        "case_id": other_case.case_id,
                        "source_fact_version": other_fact.fact_version_id,
                        "action": "save",
                    },
                    {"report_id": "rep_cross_case_provenance", "status": "ready"},
                )

        storage_write.assert_not_called()

    def test_report_id_is_idempotent_only_for_the_same_request(self) -> None:
        storage_result = {
            "status": "written",
            "writes_binary": True,
            "persistence_state": "persisted",
        }
        base_payload = {
            "owner_id": self.owner_id,
            "session_id": self.session.session_id,
            "case_id": self.case.case_id,
            "source_fact_version": self.fact_version.fact_version_id,
            "reporting_payload": {"summary": "same"},
            "action": "save",
        }
        report_payload = {"report_id": "rep_idempotent_request", "status": "ready"}

        with (
            patch("chatbot.repositories.write_object", return_value=storage_result) as storage_write,
            patch(
                "chatbot.repositories.copy_object",
                return_value={
                    "status": "copied",
                    "writes_binary": True,
                    "persistence_state": "persisted",
                },
            ),
            patch(
                "chatbot.repositories.delete_object",
                return_value={"status": "deleted"},
            ),
        ):
            first = persist_report_action(dict(base_payload), dict(report_payload))
            second = persist_report_action(dict(base_payload), dict(report_payload))
            with self.assertRaises(ValueError):
                persist_report_action(
                    {**base_payload, "reporting_payload": {"summary": "changed"}},
                    dict(report_payload),
                )

        self.assertEqual(first["report_id"], second["report_id"])
        self.assertEqual(storage_write.call_count, 1)
        self.assertEqual(Report.objects.get(report_id=first["report_id"]).version_no, 1)

    def test_report_storage_is_staged_only_after_database_reservation(self) -> None:
        def assert_reserved_before_write(reference, *_args, **_kwargs):
            self.assertTrue(Report.objects.filter(report_id="rep_staged_write").exists())
            self.assertIn("/staging/", f"/{reference['key']}")
            return {
                "status": "written",
                "writes_binary": True,
                "persistence_state": "persisted",
            }

        with (
            patch("chatbot.repositories.write_object", side_effect=assert_reserved_before_write),
            patch(
                "chatbot.repositories.copy_object",
                create=True,
                return_value={
                    "status": "copied",
                    "writes_binary": True,
                    "persistence_state": "persisted",
                },
            ) as promote_object,
            patch("chatbot.repositories.delete_object", create=True, return_value={"status": "deleted"}) as cleanup,
        ):
            persist_report_action(
                {
                    "owner_id": self.owner_id,
                    "session_id": self.session.session_id,
                    "case_id": self.case.case_id,
                    "source_fact_version": self.fact_version.fact_version_id,
                    "action": "save",
                },
                {"report_id": "rep_staged_write", "status": "ready"},
            )

        promote_object.assert_called_once()
        cleanup.assert_called_once()

    def test_idempotent_report_retry_resumes_failed_storage_finalization(self) -> None:
        failed_write = {
            "status": "skipped",
            "writes_binary": False,
            "persistence_state": "metadata_only_adapter",
        }
        successful_write = {
            "status": "written",
            "writes_binary": True,
            "persistence_state": "binary_adapter",
        }
        promoted = {
            "status": "copied",
            "writes_binary": True,
            "persistence_state": "binary_adapter",
        }
        payload = {
            "owner_id": self.owner_id,
            "session_id": self.session.session_id,
            "case_id": self.case.case_id,
            "source_fact_version": self.fact_version.fact_version_id,
            "action": "save",
        }
        report_payload = {"report_id": "rep_retry_storage", "status": "ready"}

        with (
            patch(
                "chatbot.repositories.write_object",
                side_effect=[failed_write, successful_write],
            ) as storage_write,
            patch("chatbot.repositories.copy_object", return_value=promoted) as promote_object,
            patch("chatbot.repositories.delete_object", return_value={"status": "deleted"}),
        ):
            persist_report_action(dict(payload), dict(report_payload))
            persist_report_action(dict(payload), dict(report_payload))

        report = Report.objects.get(report_id=report_payload["report_id"])
        self.assertEqual(storage_write.call_count, 2)
        promote_object.assert_called_once()
        self.assertEqual(report.metadata["persistence_state"], "finalized")

    def test_report_staging_cleanup_failure_is_pending_until_worker_retry(self) -> None:
        payload = {
            "owner_id": self.owner_id,
            "session_id": self.session.session_id,
            "case_id": self.case.case_id,
            "source_fact_version": self.fact_version.fact_version_id,
            "action": "save",
        }
        report_payload = {
            "report_id": "rep_staging_cleanup_retry",
            "status": "ready",
        }
        with (
            patch(
                "chatbot.repositories.write_object",
                return_value={
                    "status": "written",
                    "writes_binary": True,
                    "persistence_state": "binary_adapter",
                },
            ),
            patch(
                "chatbot.repositories.copy_object",
                return_value={
                    "status": "copied",
                    "writes_binary": True,
                    "persistence_state": "binary_adapter",
                },
            ),
            patch(
                "chatbot.repositories.delete_object",
                side_effect=[
                    {"status": "skipped", "reason": "storage_unavailable"},
                    {"status": "deleted"},
                ],
            ) as cleanup,
        ):
            persist_report_action(dict(payload), dict(report_payload))
            report = Report.objects.get(report_id=report_payload["report_id"])
            self.assertEqual(
                report.metadata["persistence_state"],
                "staging_cleanup_pending",
            )

            batch = purge_pending_report_staging(limit=10)

        self.assertEqual(cleanup.call_count, 2)
        self.assertEqual(batch["cleaned"], 1)
        self.assertEqual(batch["retryable"], 0)
        report.refresh_from_db()
        self.assertEqual(report.metadata["persistence_state"], "finalized")

    def test_ambiguous_staging_write_is_cleaned_before_storage_failure(self) -> None:
        payload = {
            "owner_id": self.owner_id,
            "session_id": self.session.session_id,
            "case_id": self.case.case_id,
            "source_fact_version": self.fact_version.fact_version_id,
            "action": "save",
        }
        report_payload = {
            "report_id": "rep_ambiguous_staging_write",
            "status": "ready",
        }
        with (
            patch(
                "chatbot.repositories.write_object",
                return_value={
                    "status": "skipped",
                    "reason": "response_lost",
                    "writes_binary": False,
                    "persistence_state": "metadata_only_adapter",
                },
            ),
            patch("chatbot.repositories.copy_object") as promotion,
            patch(
                "chatbot.repositories.delete_object",
                side_effect=[
                    {"status": "skipped", "reason": "storage_unavailable"},
                    {"status": "deleted"},
                ],
            ) as cleanup,
        ):
            persist_report_action(dict(payload), dict(report_payload))
            report = Report.objects.get(report_id=report_payload["report_id"])
            self.assertEqual(
                report.metadata["persistence_state"],
                "staging_cleanup_pending",
            )
            self.assertEqual(
                report.metadata["staging_cleanup_target_state"],
                "storage_failed",
            )

            batch = purge_pending_report_staging(limit=10)

        promotion.assert_not_called()
        self.assertEqual(cleanup.call_count, 2)
        self.assertEqual(batch["cleaned"], 1)
        report.refresh_from_db()
        self.assertEqual(report.metadata["persistence_state"], "storage_failed")

    def test_idempotent_report_retry_only_retries_pending_staging_delete(self) -> None:
        payload = {
            "owner_id": self.owner_id,
            "session_id": self.session.session_id,
            "case_id": self.case.case_id,
            "source_fact_version": self.fact_version.fact_version_id,
            "action": "save",
        }
        report_payload = {
            "report_id": "rep_staging_cleanup_idempotent",
            "status": "ready",
        }
        successful_write = {
            "status": "written",
            "writes_binary": True,
            "persistence_state": "binary_adapter",
        }
        promoted = {
            "status": "copied",
            "writes_binary": True,
            "persistence_state": "binary_adapter",
        }
        with (
            patch(
                "chatbot.repositories.write_object",
                return_value=successful_write,
            ) as staging_write,
            patch(
                "chatbot.repositories.copy_object",
                return_value=promoted,
            ) as promotion,
            patch(
                "chatbot.repositories.delete_object",
                side_effect=[
                    {"status": "skipped", "reason": "storage_unavailable"},
                    {"status": "deleted"},
                ],
            ),
        ):
            persist_report_action(dict(payload), dict(report_payload))
            persist_report_action(dict(payload), dict(report_payload))

        staging_write.assert_called_once()
        promotion.assert_called_once()
        report = Report.objects.get(report_id=report_payload["report_id"])
        self.assertEqual(report.metadata["persistence_state"], "finalized")

    def test_report_storage_exception_marks_reservation_failed_and_cleans_staging(self) -> None:
        with (
            patch("chatbot.repositories.write_object", side_effect=OSError("storage down")),
            patch("chatbot.repositories.delete_object", return_value={"status": "not_found"}) as cleanup,
        ):
            with self.assertRaises(OSError):
                persist_report_action(
                    {
                        "owner_id": self.owner_id,
                        "session_id": self.session.session_id,
                        "case_id": self.case.case_id,
                        "source_fact_version": self.fact_version.fact_version_id,
                        "action": "save",
                    },
                    {"report_id": "rep_storage_exception", "status": "ready"},
                )

        cleanup.assert_called_once()
        report = Report.objects.get(report_id="rep_storage_exception")
        self.assertEqual(report.metadata["persistence_state"], "storage_failed")
        self.assertEqual(report.metadata["object_storage_status"], "failed")

    def test_report_promotion_exception_cleans_staging_and_marks_failure(self) -> None:
        with (
            patch(
                "chatbot.repositories.write_object",
                return_value={
                    "status": "written",
                    "writes_binary": True,
                    "persistence_state": "binary_adapter",
                },
            ),
            patch("chatbot.repositories.copy_object", side_effect=OSError("copy down")),
            patch("chatbot.repositories.delete_object", return_value={"status": "deleted"}) as cleanup,
        ):
            with self.assertRaises(OSError):
                persist_report_action(
                    {
                        "owner_id": self.owner_id,
                        "session_id": self.session.session_id,
                        "case_id": self.case.case_id,
                        "source_fact_version": self.fact_version.fact_version_id,
                        "action": "save",
                    },
                    {"report_id": "rep_promotion_exception", "status": "ready"},
                )

        cleanup.assert_called_once()
        report = Report.objects.get(report_id="rep_promotion_exception")
        self.assertEqual(report.metadata["persistence_state"], "storage_failed")
        self.assertEqual(report.metadata["object_storage_status"], "failed")

    def test_foreign_report_id_is_rejected_before_object_write(self) -> None:
        other_case = Case.objects.create(case_id="case_foreign_report", owner_id="usr_other")
        Report.objects.create(
            report_id="rep_foreign_existing",
            owner_id="usr_other",
            case=other_case,
            version_no=1,
        )

        with patch(
            "chatbot.repositories.write_object",
            return_value={
                "status": "written",
                "writes_binary": True,
                "persistence_state": "persisted",
            },
        ) as storage_write:
            with self.assertRaises(PermissionError):
                persist_report_action(
                    {
                        "owner_id": self.owner_id,
                        "session_id": self.session.session_id,
                        "case_id": self.case.case_id,
                        "source_fact_version": self.fact_version.fact_version_id,
                        "action": "save",
                    },
                    {"report_id": "rep_foreign_existing", "status": "ready"},
                )

        storage_write.assert_not_called()

    def test_report_version_is_server_managed_and_advances_case_atomically(self) -> None:
        persist_report_action(
            {
                "owner_id": self.owner_id,
                "session_id": self.session.session_id,
                "case_id": self.case.case_id,
                "source_fact_version": self.fact_version.fact_version_id,
                "version_no": 99,
                "action": "save",
            },
            {"report_id": "rep_server_version_1", "status": "ready"},
        )
        persist_report_action(
            {
                "owner_id": self.owner_id,
                "session_id": self.session.session_id,
                "case_id": self.case.case_id,
                "source_fact_version": self.fact_version.fact_version_id,
                "version_no": 99,
                "action": "save",
            },
            {"report_id": "rep_server_version_2", "status": "ready"},
        )

        versions = list(
            Report.objects.filter(case=self.case)
            .order_by("version_no")
            .values_list("version_no", flat=True)
        )
        self.case.refresh_from_db()
        self.assertEqual(versions, [1, 2])
        self.assertEqual(self.case.current_report_version, 2)

    def test_file_api_returns_forbidden_for_another_users_case(self) -> None:
        other_client = authenticated_client("usr_other")
        other_client.raise_request_exception = False
        other_session = ChatSession.objects.create(
            session_id="ses_other_upload",
            owner_id="usr_other",
            status=ChatSessionStatus.ACTIVE,
        )

        response = other_client.post(
            "/api/files/",
            data={
                "session_id": other_session.session_id,
                "case_id": self.case.case_id,
                "purpose": "supporting_evidence",
                "filename": "other.pdf",
                "content_type": "application/pdf",
                "size_bytes": 128,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")

    def test_report_api_returns_forbidden_for_another_users_case(self) -> None:
        other_client = authenticated_client("usr_other")
        other_client.raise_request_exception = False

        response = other_client.post(
            "/api/reports/",
            data={
                "session_id": self.session.session_id,
                "case_id": self.case.case_id,
                "action": "save",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")

    def test_report_api_requires_the_persisted_worker_report(self) -> None:
        client = authenticated_client(self.owner_id)
        client.raise_request_exception = False

        response = client.post(
            "/api/reports/",
            data={
                "session_id": self.session.session_id,
                "case_id": self.case.case_id,
                "source_fact_version": "fact_unknown",
                "action": "save",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        error = response.json()["error"]
        self.assertEqual(error["code"], "worker_report_action_required")
        self.assertEqual(error["required_action"], "use_persisted_worker_report")
        self.assertNotIn("fact_unknown", error["message"])

    def test_object_access_denied_message_is_readable_korean(self) -> None:
        other_client = authenticated_client("usr_other")
        response = other_client.get(f"/api/cases/{self.case.case_id}/workspace/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["error"]["message"],
            "요청한 데이터에 접근할 권한이 없습니다.",
        )
