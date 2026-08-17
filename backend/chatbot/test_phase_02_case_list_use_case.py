from __future__ import annotations

import ast
import importlib
from unittest.mock import patch
from datetime import timedelta
from pathlib import Path

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.contracts.consultation_case import ConsultationCaseListResponse
from app.services.google_auth_service import issue_access_token
from chatbot.models import AuthSession, AuthSessionStatus, Case, ChatSession, ChatSessionStatus, UserAccount


TEST_JWT_SIGNING_KEY = "phase-02-d1-case-list-signing-key-is-long-enough"
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
class CaseListUseCaseCharacterizationTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_phase_02_d1_owner"
        self.foreign_owner_id = "usr_phase_02_d1_foreign"
        self.owner_client = authenticated_client(self.owner_id)
        self.owned_first = Case.objects.create(
            case_id="case_phase_02_d1_owned_first",
            owner_id=self.owner_id,
            title="First owner case",
        )
        self.owned_second = Case.objects.create(
            case_id="case_phase_02_d1_owned_second",
            owner_id=self.owner_id,
            title="Second owner case",
        )
        self.foreign_case = Case.objects.create(
            case_id="case_phase_02_d1_foreign",
            owner_id=self.foreign_owner_id,
            title="Foreign case",
        )

    def test_application_derives_owner_from_trusted_identity_and_returns_only_owned_cases(self) -> None:
        module = importlib.import_module("app.application.cases.list_cases")

        result = module.execute_list_consultation_cases(
            module.ListConsultationCasesQuery(
                identity_payload={
                    "owner_id": self.foreign_owner_id,
                    "user_id": self.foreign_owner_id,
                    "auth_context": {"user_id": self.owner_id},
                }
            )
        )

        self.assertEqual(
            [case["case_id"] for case in result.cases],
            [self.owned_second.case_id, self.owned_first.case_id],
        )
        self.assertNotIn(self.foreign_case.case_id, [case["case_id"] for case in result.cases])

    def test_application_rejects_identity_without_trusted_user_context(self) -> None:
        module = importlib.import_module("app.application.cases.list_cases")

        with self.assertRaises(module.CaseListAccessDenied):
            module.execute_list_consultation_cases(
                module.ListConsultationCasesQuery(
                    identity_payload={"owner_id": self.owner_id, "user_id": self.owner_id}
                )
            )

    def test_application_returns_empty_cases_for_authenticated_owner_without_cases(self) -> None:
        module = importlib.import_module("app.application.cases.list_cases")

        result = module.execute_list_consultation_cases(
            module.ListConsultationCasesQuery(
                identity_payload={"auth_context": {"user_id": "usr_phase_02_d1_empty"}}
            )
        )

        self.assertEqual(result.cases, [])

    def test_get_http_contract_preserves_owner_isolation_and_ordering(self) -> None:
        response = self.owner_client.get(
            "/api/cases/?owner_id=usr_phase_02_d1_foreign&user_id=usr_phase_02_d1_foreign"
        )

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        ConsultationCaseListResponse.model_validate(payload)
        self.assertEqual(payload["contract_version"], "consultation_case_list.v2")
        self.assertEqual(
            [case["case_id"] for case in payload["cases"]],
            [self.owned_second.case_id, self.owned_first.case_id],
        )
        self.assertNotIn(self.foreign_case.case_id, [case["case_id"] for case in payload["cases"]])

    def test_post_case_create_contract_remains_unchanged(self) -> None:
        session = ChatSession.objects.create(
            session_id="ses_phase_02_d1_post_isolation",
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
            current_intent="fault_ratio_text",
        )

        response = self.owner_client.post(
            "/api/cases/",
            data={
                "session_id": session.session_id,
                "title": "D1 POST isolation",
                "case_type": "accident_fault",
                "consultation_state": {"schema_version": "consultation_state.v2"},
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["contract_version"], "consultation_case.v2")
        self.assertEqual(response.json()["case"]["owner_id"], self.owner_id)

    def test_get_http_maps_application_access_denied(self) -> None:
        module = importlib.import_module("app.application.cases.list_cases")
        denied = module.CaseListAccessDenied(
            {
                "contract_version": "object_access.v1",
                "allowed": False,
                "reason": "authenticated_user_required",
                "resource": {"type": "consultation_case_list"},
            }
        )

        with patch(
            "chatbot.views.execute_list_consultation_cases",
            side_effect=denied,
        ):
            response = self.owner_client.get("/api/cases/")

        self.assertEqual(response.status_code, 403, response.content)
        error = response.json()["error"]
        self.assertEqual(error["code"], "object_access_denied")
        self.assertEqual(error["access"]["reason"], "authenticated_user_required")
        self.assertEqual(error["access"]["resource"], {"type": "consultation_case_list"})

    def test_z_application_has_no_http_or_mock_dependencies_and_get_view_is_an_adapter(self) -> None:
        module = importlib.import_module("app.application.cases.list_cases")
        application_tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        forbidden_modules = {"django.http", "app.mock_runtime", "backend.chatbot.views"}
        forbidden_names = {
            "HttpRequest",
            "JsonResponse",
            "HttpResponse",
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
        self.assertNotIn("list_cases", direct_calls)
