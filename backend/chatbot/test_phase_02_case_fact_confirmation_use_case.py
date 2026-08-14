from __future__ import annotations

import ast
import importlib
import json
from datetime import timedelta
from pathlib import Path

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
    ConfirmedFactVersion,
    UserAccount,
)


TEST_JWT_SIGNING_KEY = "phase-02-b2-case-fact-confirmation-signing-key-is-long-enough"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


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
class CaseFactConfirmationUseCaseCharacterizationTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_phase_02_b2_owner"
        self.owner_client = authenticated_client(self.owner_id)
        self.session = ChatSession.objects.create(
            session_id="ses_phase_02_b2_confirmation",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
            current_intent="fault_ratio_text",
        )
        response = self.owner_client.post(
            "/api/cases/",
            data={
                "session_id": self.session.session_id,
                "title": "Phase 2 B2 fact confirmation characterization",
                "case_type": "accident_fault",
                "consultation_state": {"schema_version": "consultation_state.v2"},
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.case_id = response.json()["case"]["case_id"]
        self.confirm_url = f"/api/cases/{self.case_id}/facts/confirm/"
        self.payload = {
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

    def _confirm(self, payload: dict[str, object] | None = None):
        return self.owner_client.post(
            self.confirm_url,
            data=self.payload if payload is None else payload,
            content_type="application/json",
        )

    def _case(self) -> Case:
        return Case.objects.get(case_id=self.case_id)

    def test_owner_success_preserves_confirmed_fact_contract_and_case_projection(self) -> None:
        response = self._confirm()

        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        fact_version = payload["fact_version"]
        self.assertEqual(payload["contract_version"], "confirmed_facts.v1")
        self.assertEqual(fact_version["schema_version"], "confirmed_facts.v1")
        self.assertEqual(fact_version["version_no"], 1)
        self.assertEqual(fact_version["confirmed_by"], self.owner_id)
        case = self._case()
        self.assertEqual(case.current_fact_version, 1)
        self.assertEqual(case.status, "intake")
        self.assertEqual(case.metadata["active_fact_version_id"], fact_version["fact_version_id"])
        self.assertEqual(
            case.metadata["fact_confirmation"]["contract_version"],
            "confirmed_facts_idempotency.v1",
        )

    def test_exact_replay_reuses_fact_version_and_preserves_active_analysis_metadata(self) -> None:
        first = self._confirm()
        self.assertEqual(first.status_code, 201, first.content)
        first_fact_version_id = first.json()["fact_version"]["fact_version_id"]
        case = self._case()
        case.metadata = {**case.metadata, "active_analysis_job_id": "job_existing_active"}
        case.save(update_fields=["metadata", "updated_at"])

        replay = self._confirm()

        self.assertEqual(replay.status_code, 201, replay.content)
        self.assertEqual(replay.json()["fact_version"]["fact_version_id"], first_fact_version_id)
        self.assertEqual(ConfirmedFactVersion.objects.filter(case=case).count(), 1)
        case.refresh_from_db()
        self.assertEqual(case.current_fact_version, 1)
        self.assertEqual(case.metadata["active_analysis_job_id"], "job_existing_active")

    def test_changed_payload_creates_next_version_and_resets_active_analysis_projection(self) -> None:
        first = self._confirm()
        self.assertEqual(first.status_code, 201, first.content)
        case = self._case()
        case.metadata = {**case.metadata, "active_analysis_job_id": "job_existing_active"}
        case.save(update_fields=["metadata", "updated_at"])
        changed_payload = {
            **self.payload,
            "facts": {**self.payload["facts"], "collision_location": "rear_right"},
        }

        response = self._confirm(changed_payload)

        self.assertEqual(response.status_code, 201, response.content)
        fact_version = response.json()["fact_version"]
        self.assertEqual(fact_version["version_no"], 2)
        self.assertEqual(ConfirmedFactVersion.objects.filter(case=case).count(), 2)
        case.refresh_from_db()
        self.assertEqual(case.current_fact_version, 2)
        self.assertEqual(case.metadata["active_fact_version_id"], fact_version["fact_version_id"])
        self.assertEqual(case.metadata["active_analysis_job_id"], "")

    def test_foreign_owner_invalid_payload_is_denied_before_validation(self) -> None:
        response = authenticated_client("usr_phase_02_b2_attacker").post(
            self.confirm_url,
            data={"facts": []},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403, response.content)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "object_access_denied")
        self.assertEqual(payload["error"]["required_action"], "login_or_owner_match")
        self.assertNotIn("details", payload["error"])
        self.assertEqual(ConfirmedFactVersion.objects.filter(case__case_id=self.case_id).count(), 0)

    def test_owner_invalid_payload_preserves_validation_error_contract(self) -> None:
        response = self._confirm({"facts": []})

        self.assertEqual(response.status_code, 422, response.content)
        payload = response.json()
        self.assertEqual(payload["error"]["contract_version"], "request_validation_error.v1")
        self.assertEqual(payload["error"]["type"], "validation")
        self.assertEqual(payload["error"]["code"], "validation_error")
        self.assertEqual(payload["error"]["status"], 422)
        self.assertTrue(payload["error"]["details"])
        self.assertEqual(set(payload["error"]["details"][0]), {"field", "type", "message"})
        self.assertEqual(ConfirmedFactVersion.objects.filter(case__case_id=self.case_id).count(), 0)

    def test_missing_case_preserves_repository_error_contract(self) -> None:
        response = self.owner_client.post(
            "/api/cases/case_phase_02_b2_missing/facts/confirm/",
            data=self.payload,
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404, response.content)
        self.assertEqual(
            response.json()["error"],
            {
                "contract_version": "consultation_case_error.v2",
                "type": "case",
                "code": "case_not_found",
                "status": 404,
                "message": "case was not found",
            },
        )

    def test_confirmation_has_no_queue_side_effect(self) -> None:
        response = self._confirm()

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(AnalysisJob.objects.filter(case__case_id=self.case_id).count(), 0)
        self.assertEqual(AgentWorkItem.objects.count(), 0)

    def test_z_application_command_has_no_http_mock_orm_or_transaction_dependencies_and_view_is_adapter_only(self) -> None:
        module = importlib.import_module("app.application.cases.confirm_facts")

        result = module.execute_confirm_case_facts(
            module.ConfirmCaseFactsCommand(
                case_id=self.case_id,
                owner_id=self.owner_id,
                identity_payload={"auth_context": {"user_id": self.owner_id}},
                raw_payload=self.payload,
            )
        )
        self.assertEqual(result.fact_version["schema_version"], "confirmed_facts.v1")
        self.assertEqual(result.fact_version["version_no"], 1)
        self.assertNotIn("mock_scenario", json.dumps(result.fact_version, sort_keys=True))

        application_path = Path(module.__file__)
        application_tree = ast.parse(application_path.read_text(encoding="utf-8"))
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

        views_path = REPOSITORY_ROOT / "backend" / "chatbot" / "views.py"
        views_tree = ast.parse(views_path.read_text(encoding="utf-8-sig"))
        view = next(
            node
            for node in views_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "consultation_case_fact_confirmation"
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
                "confirm_case_facts",
                "_validate_request_dto",
            }.isdisjoint(direct_calls)
        )
