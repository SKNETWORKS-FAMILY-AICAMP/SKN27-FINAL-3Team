from __future__ import annotations

import ast
import importlib
import json
from datetime import timedelta
from pathlib import Path

from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from chatbot.models import AuthSession, AuthSessionStatus, ChatSession, ChatSessionStatus, UserAccount


TEST_JWT_SIGNING_KEY = "phase-02-b1-case-workspace-signing-key-is-long-enough"
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
class CaseWorkspaceUseCaseCharacterizationTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_phase_02_b1_owner"
        self.owner_client = authenticated_client(self.owner_id)
        self.session = ChatSession.objects.create(
            session_id="ses_phase_02_b1_workspace",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
            current_intent="fault_ratio_text",
        )
        response = self.owner_client.post(
            "/api/cases/",
            data={
                "session_id": self.session.session_id,
                "title": "Phase 2 B1 workspace characterization",
                "case_type": "accident_fault",
                "consultation_state": {"schema_version": "consultation_state.v2"},
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.case_id = response.json()["case"]["case_id"]
        self.workspace_url = f"/api/cases/{self.case_id}/workspace/"

    def test_foreign_owner_is_denied_with_public_access_payload(self) -> None:
        response = authenticated_client("usr_phase_02_b1_attacker").get(self.workspace_url)

        self.assertEqual(response.status_code, 403, response.content)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "object_access_denied")
        self.assertEqual(payload["error"]["required_action"], "login_or_owner_match")
        self.assertEqual(
            payload["error"]["access"],
            {
                "allowed": False,
                "contract_version": "object_access.v1",
                "reason": "owner_mismatch",
                "resource": {"type": "case"},
            },
        )
        self.assertNotIn("workspace", payload)

    def test_missing_case_preserves_repository_error_contract(self) -> None:
        response = self.owner_client.get("/api/cases/case_phase_02_b1_missing/workspace/")

        self.assertEqual(response.status_code, 404, response.content)
        payload = response.json()
        self.assertEqual(
            payload["error"],
            {
                "contract_version": "consultation_case_error.v2",
                "type": "case",
                "code": "case_not_found",
                "status": 404,
                "message": "case was not found",
            },
        )
        self.assertNotIn("workspace", payload)

    def test_owner_workspace_http_contract_is_canonical_and_mock_free(self) -> None:
        response = self.owner_client.get(self.workspace_url)

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        workspace = payload["workspace"]
        self.assertEqual(workspace["contract_version"], "case_workspace.v2")
        self.assertEqual(workspace["case"]["case_id"], self.case_id)
        for key in (
            "case",
            "confirmed_facts",
            "case_evidence",
            "analysis_jobs",
            "reports",
            "attachments",
        ):
            self.assertIn(key, workspace)
        self.assertNotIn("mock_scenario", json.dumps(workspace, sort_keys=True))

    def test_unauthenticated_route_is_rejected_by_transport_auth_contract(self) -> None:
        response = Client().get(self.workspace_url)

        self.assertEqual(response.status_code, 401, response.content)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "auth_required")
        self.assertEqual(payload["error"]["required_action"], "login")
        self.assertNotIn("action", payload["error"])
        self.assertNotIn("workspace", payload)

    def test_unauthenticated_adapter_requires_login_for_case_workspace(self) -> None:
        from chatbot.views import consultation_case_workspace

        response = consultation_case_workspace(
            RequestFactory().get(self.workspace_url),
            self.case_id,
        )

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(payload["error"]["code"], "login_required")
        self.assertEqual(payload["error"]["required_action"], "login")
        self.assertEqual(payload["error"]["action"], "case_workspace")
        self.assertNotIn("workspace", payload)

    def test_z_application_use_case_has_no_http_or_mock_dependencies_and_view_is_adapter_only(self) -> None:
        module = importlib.import_module("app.application.cases.get_workspace")

        result = module.execute_get_case_workspace(
            module.GetCaseWorkspaceQuery(
                case_id=self.case_id,
                identity_payload={"auth_context": {"user_id": self.owner_id}},
            )
        )
        self.assertEqual(result.workspace["contract_version"], "case_workspace.v2")
        self.assertEqual(result.workspace["case"]["case_id"], self.case_id)
        with self.assertRaises(ValueError):
            module.execute_get_case_workspace(
                module.GetCaseWorkspaceQuery(case_id="", identity_payload={})
            )

        application_path = Path(module.__file__)
        application_tree = ast.parse(application_path.read_text(encoding="utf-8"))
        forbidden_modules = {"django.http", "app.mock_runtime", "backend.chatbot.views"}
        forbidden_names = {
            "HttpRequest",
            "JsonResponse",
            "csrf_exempt",
            "require_http_methods",
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
        views_tree = ast.parse(views_path.read_text(encoding="utf-8"))
        view = next(
            node
            for node in views_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "consultation_case_workspace"
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
                "get_case_workspace",
            }.isdisjoint(direct_calls)
        )
