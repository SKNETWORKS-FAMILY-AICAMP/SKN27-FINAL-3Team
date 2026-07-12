from __future__ import annotations

from importlib import import_module, util
from pathlib import Path

from django.apps import apps
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from chatbot.case_repository import CaseOwnerMismatch, create_case
from chatbot.models import (
    Case,
    ChatSession,
    ChatSessionStatus,
    ConfirmedFactVersion,
    Report,
    ReportType,
    UploadedFile,
)
from chatbot.repositories import persist_report_action, persist_uploaded_file_metadata


ROOT = Path(__file__).resolve().parents[2]
TEST_JWT_SIGNING_KEY = "consultation-v2-test-signing-key-is-long-enough"


def authenticated_client(user_id: str) -> Client:
    token, _claims = issue_access_token(
        user_id=user_id,
        auth_session_id=f"auth_{user_id}",
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
        created = create_response.json()["case"]
        self.assertEqual(create_response.json()["contract_version"], "consultation_case.v2")
        self.assertEqual(created["owner_id"], self.owner_id)
        self.assertEqual(created["status"], "awaiting_fact_confirmation")

        list_response = self.client.get("/api/cases/")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual([item["case_id"] for item in list_response.json()["cases"]], [created["case_id"]])

        workspace_response = self.client.get(f"/api/cases/{created['case_id']}/workspace/")
        self.assertEqual(workspace_response.status_code, 200)
        workspace = workspace_response.json()["workspace"]
        self.assertEqual(workspace["contract_version"], "case_workspace.v2")
        self.assertEqual(workspace["case"]["case_id"], created["case_id"])
        self.assertEqual(workspace["confirmed_facts"], [])

        other_client = authenticated_client("usr_other_case_owner")
        denied = other_client.get(f"/api/cases/{created['case_id']}/workspace/")
        self.assertEqual(denied.status_code, 403)
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
        self.assertEqual(premature.json()["error"]["code"], "confirmed_facts_required")

        facts_response = self.client.post(
            f"/api/cases/{created['case_id']}/facts/confirm/",
            data={
                "facts": {
                    "road_layout": "four_way_intersection",
                    "vehicle_actions": "ego_straight_other_left_turn",
                    "signal_priority": "ego_green",
                    "collision_location": "front_left",
                },
                "sources": [{"source_type": "user_confirmation", "source_ref": "case-form"}],
                "conflicts": [],
                "user_edit_history": [],
            },
            content_type="application/json",
        )
        self.assertEqual(facts_response.status_code, 201)
        fact_version = facts_response.json()["fact_version"]
        self.assertEqual(fact_version["schema_version"], "confirmed_facts.v1")
        self.assertEqual(fact_version["version_no"], 1)

        job_response = self.client.post(
            f"/api/cases/{created['case_id']}/analysis/jobs/",
            data={"fact_version_id": fact_version["fact_version_id"]},
            content_type="application/json",
        )
        self.assertEqual(job_response.status_code, 202)
        body = job_response.json()
        self.assertEqual(body["contract_version"], "case_analysis_job.v2")
        self.assertEqual(body["job"]["status"], "queued")
        self.assertEqual(body["work_item"]["status"], "queued")
        self.assertEqual(
            body["analysis_plan"]["node_codes"],
            ["text_ml_case_search", "law_ground_search"],
        )

        analysis_job = apps.get_model("chatbot", "AnalysisJob").objects.get(
            job_id=body["job"]["job_id"]
        )
        self.assertEqual(analysis_job.case.case_id, created["case_id"])
        self.assertEqual(analysis_job.owner_id, self.owner_id)
        self.assertEqual(analysis_job.work_items.get().work_item_id, body["work_item"]["work_item_id"])

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
        self.assertEqual(response.json()["error"]["code"], "login_required")

    def test_case_creation_validates_typed_request_before_repository(self) -> None:
        response = self.client.post(
            "/api/cases/",
            data={"title": "session 없는 사건", "case_type": "accident_fault"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 422)
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
            "storage_uri": f"mock://uploads/{attachment_id}",
            "status": "uploaded",
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
            payload={"session_id": guest_session.session_id},
        )

        uploaded_file = UploadedFile.objects.get(attachment_id=attachment["attachment_id"])
        remaining_days = (uploaded_file.retention_expires_at - timezone.now()).days
        expected_case_id = Case.objects.get(case_id=created_case["case_id"]).id
        self.assertEqual(uploaded_file.case_id, expected_case_id)
        self.assertIn(remaining_days, {364, 365})

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

    def test_report_api_returns_conflict_for_unknown_fact_version(self) -> None:
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
        self.assertEqual(response.json()["error"]["code"], "invalid_report_reference")
