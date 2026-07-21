from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import timedelta
import hashlib
import json
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.chat_orchestration_service import _analysis_plan
from app.services.guest_credential_service import issue_guest_credential
from app.services.google_auth_service import issue_access_token
from chatbot.models import (
    AgentWorkItem,
    AnalysisJob,
    AuthSession,
    AuthSessionStatus,
    Case,
    ChatSession,
    Report,
    UploadedFile,
    UserAccount,
)
from chatbot.repositories import process_agent_work_item


TEST_JWT_SIGNING_KEY = "guest-login-ownership-e2e-test-signing-key-is-long-enough"


class _GoogleResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _authenticated_client(user_id: str) -> Client:
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


def _report_ready_chat_response(*, session_id: str, message_id: str) -> dict:
    slot_state = {"contract_version": "slot_filling_state.v1", "slots": {}}
    supervisor_state = {
        "contract_version": "supervisor_conversation_state.v2",
        "next_questions": [],
    }
    analysis_plan = _analysis_plan(
        session_id=session_id,
        message_id=message_id,
        routing_intent="fine_notice_analysis",
        supervisor_state=supervisor_state,
        report_requested=True,
    )
    packages = [
        {
            "schema_version": "agent_input_schema.v1",
            "node_code": node_code,
            "status": "ready",
            "required_inputs": ["user_text|attachments"],
            "payload": {
                "user_text": "guest ownership fixture facts",
                "attachments": [],
                "slot_state": slot_state,
            },
        }
        for node_code in (
            "fine_notice_analysis",
            "law_ground_search",
            "appeal_decision_flow",
            "objection_report_generation",
        )
    ]
    return {
        "contract_version": "chat_message_accepted.v2",
        "session_id": session_id,
        "message_id": message_id,
        "routing_intent": "fine_notice_analysis",
        "status": "queued",
        "progress": {
            "status": "queued",
            "active_node": "fine_notice_analysis",
            "message": "Queued.",
        },
        "assistant_message": {"answer": "Queued.", "summary": "Queued."},
        "analysis_plan": analysis_plan,
        "supervisor_state": {
            **supervisor_state,
            "stage": "agent_execution_ready",
            "llm": {"status": "used", "provider": "fixture", "model": "fixture"},
            "slot_state": slot_state,
            "agent_input_packages": packages,
            "reporting_payload": {
                "contract_version": "reporting_payload.v2",
                "report_type": "fine_notice_objection",
            },
        },
        "reporting_payload": {
            "contract_version": "reporting_payload.v2",
            "report_type": "fine_notice_objection",
        },
        "attachments": [],
        "blocked_attachments": [],
        "limitations": [],
    }


def _fixture_submit_message(payload: dict, **_kwargs) -> dict:
    session_id = str(payload["session_id"])
    message_seed = str(payload.get("job_id") or payload.get("user_text") or "chat")
    message_hash = hashlib.sha256(message_seed.encode("utf-8")).hexdigest()[:12]
    return _report_ready_chat_response(
        session_id=session_id,
        message_id=f"msg_{session_id}_{message_hash}",
    )


@contextmanager
def _patched_report_ready_agents():
    from ai.agents.appeal_decision_flow import graph as appeal_graph
    from ai.agents.fine_notice_analysis import graph as fine_notice_graph

    def run_fine_notice(_state):
        return {
            "agent_results": {
                "fine_notice_analysis": {
                    "status": "success",
                    "summary": "Fixture notice parsed.",
                    "structured_result": {
                        "ocr_status": "success",
                        "fine_type": "fine",
                        "notice_stage": "pre_notice",
                        "violation_text": "Fixture violation.",
                        "opinion_deadline": "2026-12-31",
                        "issuing_authority": "Fixture Traffic Authority",
                    },
                    "evidence": [
                        {
                            "source_type": "fixture",
                            "source_reference": "guest-ownership:notice",
                        }
                    ],
                    "next_actions": [],
                    "limitations": [],
                }
            }
        }

    def run_law(_agent_input, _adapter_context):
        return {
            "status": "success",
            "summary": "Fixture law result.",
            "structured_result": {
                "matched_laws": [
                    {
                        "law_name": "Road Traffic Act",
                        "article": "Article 1",
                        "summary": "Fixture provision.",
                        "source_reference": "guest-ownership:law",
                    }
                ]
            },
            "evidence": [
                {"source_type": "law", "source_reference": "guest-ownership:law"}
            ],
            "next_actions": [],
            "limitations": [],
        }

    def run_appeal(_state):
        return {
            "agent_results": {
                "appeal_judgment": {
                    "status": "success",
                    "summary": "Appeal review complete.",
                    "structured_result": {
                        "judgment_status": "success",
                        "overall_possibility": "review_available",
                        "guide": {"summary": "Review supporting evidence."},
                    },
                    "evidence": [
                        {
                            "source_type": "law",
                            "source_reference": "guest-ownership:law",
                        }
                    ],
                    "next_actions": [],
                    "limitations": [],
                }
            }
        }

    def run_report(agent_input, _adapter_context):
        handoff = agent_input["context"]["supervisor_reporting_handoff"]
        source = handoff["source"]
        return {
            "status": "success",
            "summary": "Official objection draft ready.",
            "structured_result": {
                "document_type": "objection_form",
                "document_variant": "fine_notice",
                "document_title": "Fine objection form",
                "form_sections": [
                    {"title": "Petition", "items": ["Review the disposition."]}
                ],
                "form_data": {"applicant_name": "Review required"},
                "petition_purpose": "Review the disposition.",
                "petition_reason": "Review verified facts and legal grounds.",
                "drafting_source": "rule_based_fixture",
                "appeal_gate": {"status": "ready"},
                "document_readiness": {"status": "review_required"},
                "report_actions": [
                    {
                        "action": "download_objection",
                        "label": "Download objection form",
                    }
                ],
                "supervisor_handoff": {
                    "contract_version": handoff["contract_version"],
                    "handoff_id": handoff["handoff_id"],
                    "gate_status": handoff["gate"]["status"],
                    "source_fingerprint": source["fingerprint"],
                    "source_result_ids": source["result_ids"],
                },
            },
            "evidence": [
                {"source_type": "law", "source_reference": "guest-ownership:law"}
            ],
            "next_actions": ["review_objection_draft", "download_objection"],
            "limitations": [],
        }

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(fine_notice_graph, "invoke", side_effect=run_fine_notice)
        )
        stack.enter_context(
            patch(
                "ai.agents.law_ground_search.run_law_ground_search",
                side_effect=run_law,
            )
        )
        stack.enter_context(patch.object(appeal_graph, "invoke", side_effect=run_appeal))
        stack.enter_context(
            patch(
                "ai.agents.objection_report_generation.run_objection_report_generation",
                side_effect=run_report,
            )
        )
        yield


@override_settings(
    APP_JWT_SECRET=TEST_JWT_SIGNING_KEY,
    GOOGLE_CLIENT_ID="guest-ownership.apps.googleusercontent.com",
    GOOGLE_CLIENT_SECRET="[MASKED]",
    GOOGLE_POPUP_REDIRECT_URI="https://app.example.test",
    GOOGLE_TOKEN_ENDPOINT="https://oauth2.googleapis.com/token",
    GOOGLE_USERINFO_ENDPOINT="https://openidconnect.googleapis.com/v1/userinfo",
)
class GuestLoginSessionOwnershipE2ETests(TestCase):
    def _successful_google_exchange(self, request, timeout=0):
        self.assertEqual(timeout, 10)
        if request.full_url == "https://oauth2.googleapis.com/token":
            return _GoogleResponse(
                {
                    "access_token": "guest-ownership-provider-access-token",
                    "expires_in": 3600,
                    "scope": "openid email profile",
                    "token_type": "Bearer",
                }
            )
        if request.full_url == "https://openidconnect.googleapis.com/v1/userinfo":
            self.assertEqual(
                request.headers["Authorization"],
                "Bearer guest-ownership-provider-access-token",
            )
            return _GoogleResponse(
                {
                    "sub": "guest-ownership-google-subject",
                    "email": "guest.owner@example.test",
                    "email_verified": True,
                    "name": "Guest Ownership User",
                }
            )
        self.fail(f"Unexpected Google URL: {request.full_url}")

    def _google_login_payload(
        self,
        *,
        guest_id: str,
        session_id: str,
        code_suffix: str,
    ) -> dict[str, str]:
        return {
            "provider": "google",
            "code": f"mock_google_code:{code_suffix}",
            "purpose": "LOGIN",
            "scope": "openid email profile",
            "client_id": "guest-ownership.apps.googleusercontent.com",
            "redirect_uri": "https://app.example.test",
            "email": "guest.owner@example.test",
            "display_name": "Guest Ownership User",
            "guest_id": guest_id,
            "session_id": session_id,
        }

    def _google_login(
        self,
        *,
        guest_id: str,
        guest_credential: str,
        session_id: str,
        code_suffix: str,
    ) -> tuple[Client, str, str]:
        with patch(
            "app.services.google_auth_service.urllib_request.urlopen",
            side_effect=self._successful_google_exchange,
        ) as urlopen:
            response = Client().post(
                "/api/auth/google/code/",
                data=self._google_login_payload(
                    guest_id=guest_id,
                    session_id=session_id,
                    code_suffix=code_suffix,
                ),
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
                HTTP_X_GUEST_CREDENTIAL=guest_credential,
            )
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        owner_id = body["subject"]["user_id"]
        auth_session_id = body["subject"]["auth_session_id"]
        return (
            Client(
                HTTP_AUTHORIZATION=f"Bearer {body['access_token']}",
                HTTP_X_GUEST_ID=guest_id,
                HTTP_X_GUEST_CREDENTIAL=guest_credential,
                HTTP_X_AUTH_SESSION_ID=auth_session_id,
            ),
            owner_id,
            auth_session_id,
        )

    def _create_guest_resources(self) -> dict[str, str]:
        session_id = "ses_guest_ownership_owner"

        initial_guest_session = Client().post(
            "/api/auth/guest-session/",
            data={},
            content_type="application/json",
        )
        self.assertEqual(initial_guest_session.status_code, 200, initial_guest_session.content)
        guest_id = initial_guest_session.json()["guest"]["guest_id"]
        guest_credential = initial_guest_session.json()["guest_credential"]
        guest_session = Client(HTTP_X_GUEST_CREDENTIAL=guest_credential).post(
            "/api/auth/guest-session/",
            data={"guest_id": guest_id, "session_id": session_id},
            content_type="application/json",
        )
        self.assertEqual(guest_session.status_code, 200, guest_session.content)
        self.assertEqual(guest_session.json()["guest"]["guest_id"], guest_id)
        guest_credential = guest_session.json()["guest_credential"]

        guest_client = Client(
            HTTP_X_GUEST_ID=guest_id,
            HTTP_X_GUEST_CREDENTIAL=guest_credential,
        )
        upload = guest_client.post(
            "/api/files/",
            data={
                "session_id": session_id,
                "purpose": "fine_notice",
                "file": SimpleUploadedFile(
                    "guest-fine-notice.txt",
                    b"guest-owned fine notice fixture",
                    content_type="text/plain",
                ),
            },
        )
        self.assertEqual(upload.status_code, 200, upload.content)
        attachment_id = upload.json()["attachment"]["attachment_id"]

        with patch("chatbot.views.submit_message", side_effect=_fixture_submit_message):
            chat = guest_client.post(
                "/api/chat/messages/",
                data={
                    "session_id": session_id,
                    "user_text": "Prepare a fine-notice objection draft.",
                },
                content_type="application/json",
            )
        self.assertEqual(chat.status_code, 202, chat.content)
        job_id = chat.json()["work_item"]["job_id"]

        work_item = AgentWorkItem.objects.get(job__job_id=job_id)
        with _patched_report_ready_agents():
            processed = process_agent_work_item(work_item.work_item_id)
        self.assertEqual(processed["status"], "success", processed)

        session = ChatSession.objects.get(session_id=session_id)
        job = AnalysisJob.objects.select_related("session").get(job_id=job_id)
        attachment = UploadedFile.objects.get(attachment_id=attachment_id)
        report = Report.objects.select_related("session", "job").get(job=job)
        self.assertEqual(session.owner_id, "")
        self.assertEqual(job.owner_id, "")
        self.assertEqual(attachment.owner_id, "")
        self.assertEqual(report.owner_id, "")
        self.assertEqual(session.metadata["auth_context"]["guest_id"], guest_id)
        return {
            "guest_id": guest_id,
            "guest_credential": guest_credential,
            "session_id": session_id,
            "job_id": job_id,
            "attachment_id": attachment_id,
            "report_id": report.report_id,
        }

    def _promote_resources_to_case(
        self,
        *,
        resources: dict[str, str],
        owner_client: Client,
    ) -> str:
        save_state = owner_client.post(
            "/api/chat/save-state/",
            data={"session_id": resources["session_id"], "save_state": "saved"},
            content_type="application/json",
        )
        self.assertEqual(save_state.status_code, 200, save_state.content)

        created = owner_client.post(
            "/api/cases/",
            data={
                "session_id": resources["session_id"],
                "title": "Guest fine notice consultation",
                "case_type": "accident_fault",
                "consultation_state": {
                    "schema_version": "consultation_state.v2",
                    "risk_gate": {"level": "standard"},
                },
            },
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        return created.json()["case"]["case_id"]

    @staticmethod
    def _resource_snapshot() -> dict[str, list[dict]]:
        return {
            "auth_sessions": list(
                AuthSession.objects.order_by("auth_session_id").values(
                    "auth_session_id",
                    "user_id",
                    "guest_id",
                    "subject_id",
                    "status",
                )
            ),
            "chat_sessions": list(
                ChatSession.objects.order_by("session_id").values(
                    "session_id",
                    "owner_id",
                    "case_id",
                    "metadata",
                )
            ),
            "analysis_jobs": list(
                AnalysisJob.objects.order_by("job_id").values(
                    "job_id",
                    "owner_id",
                    "session_id",
                    "case_id",
                    "status",
                )
            ),
            "uploaded_files": list(
                UploadedFile.objects.order_by("attachment_id").values(
                    "attachment_id",
                    "owner_id",
                    "session_id",
                    "case_id",
                    "status",
                    "scan_status",
                )
            ),
            "reports": list(
                Report.objects.order_by("report_id").values(
                    "report_id",
                    "owner_id",
                    "session_id",
                    "job_id",
                    "case_id",
                    "status",
                )
            ),
            "cases": list(
                Case.objects.order_by("case_id").values(
                    "case_id",
                    "owner_id",
                    "status",
                )
            ),
        }

    def _assert_safe_denial(
        self,
        response,
        *,
        code: str,
        forbidden: tuple[str, ...],
    ) -> None:
        self.assertEqual(response.status_code, 403, response.content)
        body = response.json()
        self.assertEqual(body["error"]["code"], code)
        rendered = json.dumps(body, sort_keys=True)
        for fragment in forbidden:
            self.assertNotIn(fragment, rendered)
        self.assertNotIn("Content-Disposition", response.headers)
        self.assertNotEqual(
            response.headers.get("Content-Type"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertFalse(response.content.startswith(b"PK"))

    def test_matching_guest_login_can_promote_all_resources_to_one_case(self) -> None:
        resources = self._create_guest_resources()

        owner_client, owner_id, _auth_session_id = self._google_login(
            guest_id=resources["guest_id"],
            guest_credential=resources["guest_credential"],
            session_id=resources["session_id"],
            code_suffix="guest-ownership-owner",
        )
        session = ChatSession.objects.get(session_id=resources["session_id"])
        self.assertEqual(session.owner_id, owner_id)
        self.assertEqual(session.metadata["auth_context"]["guest_id"], resources["guest_id"])

        for response in (
            owner_client.get(f"/api/analysis/jobs/{resources['job_id']}/"),
            owner_client.get(f"/api/analysis/results/{resources['job_id']}/"),
            owner_client.get(
                f"/api/files/{resources['attachment_id']}/",
                {"session_id": resources["session_id"]},
            ),
            owner_client.get(f"/api/reports/{resources['report_id']}/"),
        ):
            self.assertEqual(response.status_code, 200, response.content)

        case_id = self._promote_resources_to_case(
            resources=resources,
            owner_client=owner_client,
        )

        workspace = owner_client.get(f"/api/cases/{case_id}/workspace/")
        self.assertEqual(workspace.status_code, 200, workspace.content)
        with patch("chatbot.views.submit_message", side_effect=_fixture_submit_message):
            follow_up = owner_client.post(
                "/api/chat/messages/",
                data={
                    "session_id": resources["session_id"],
                    "user_text": "Continue with the saved consultation.",
                },
                content_type="application/json",
            )
        self.assertEqual(follow_up.status_code, 202, follow_up.content)

        case = Case.objects.get(case_id=case_id)
        session = ChatSession.objects.get(session_id=resources["session_id"])
        job = AnalysisJob.objects.get(job_id=resources["job_id"])
        attachment = UploadedFile.objects.get(attachment_id=resources["attachment_id"])
        report = Report.objects.get(report_id=resources["report_id"])
        self.assertEqual((session.owner_id, session.case_id), (owner_id, case.pk))
        self.assertEqual((job.owner_id, job.case_id), (owner_id, case.pk))
        self.assertEqual((attachment.owner_id, attachment.case_id), (owner_id, case.pk))
        self.assertEqual((report.owner_id, report.case_id), (owner_id, case.pk))

    def test_mismatched_or_already_owned_google_login_preserves_resources(self) -> None:
        resources = self._create_guest_resources()
        forbidden = (
            resources["session_id"],
            resources["job_id"],
            resources["attachment_id"],
            resources["report_id"],
            "guest-fine-notice.txt",
            "Review verified facts and legal grounds.",
        )
        before_mismatch = self._resource_snapshot()
        with patch(
            "chatbot.views._create_google_code_login",
            side_effect=AssertionError("Google provider must not be called"),
        ) as provider:
            mismatch = Client().post(
                "/api/auth/google/code/",
                data=self._google_login_payload(
                    guest_id="gst_guest_ownership_other",
                    session_id=resources["session_id"],
                    code_suffix="guest-ownership-mismatch",
                ),
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
                HTTP_X_GUEST_CREDENTIAL=issue_guest_credential("gst_guest_ownership_other")[0],
            )
        self._assert_safe_denial(mismatch, code="forbidden", forbidden=forbidden)
        self.assertEqual(
            mismatch.json()["error"]["auth"]["reason"],
            "google_guest_session_mismatch",
        )
        provider.assert_not_called()
        self.assertEqual(self._resource_snapshot(), before_mismatch)

        _owner_client, owner_id, _auth_session_id = self._google_login(
            guest_id=resources["guest_id"],
            guest_credential=resources["guest_credential"],
            session_id=resources["session_id"],
            code_suffix="guest-ownership-owner",
        )
        before_relogin = self._resource_snapshot()
        with patch(
            "chatbot.views._create_google_code_login",
            side_effect=AssertionError("Google provider must not be called"),
        ) as provider:
            relogin = Client().post(
                "/api/auth/google/code/",
                data=self._google_login_payload(
                    guest_id=resources["guest_id"],
                    session_id=resources["session_id"],
                    code_suffix="guest-ownership-relogin",
                ),
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
                HTTP_X_GUEST_CREDENTIAL=resources["guest_credential"],
            )
        self._assert_safe_denial(
            relogin,
            code="forbidden",
            forbidden=(*forbidden, owner_id),
        )
        self.assertEqual(
            relogin.json()["error"]["auth"]["reason"],
            "google_session_already_owned",
        )
        provider.assert_not_called()
        self.assertEqual(self._resource_snapshot(), before_relogin)

    def test_other_user_cannot_read_mutate_or_claim_promoted_resources(self) -> None:
        resources = self._create_guest_resources()
        owner_client, owner_id, _auth_session_id = self._google_login(
            guest_id=resources["guest_id"],
            guest_credential=resources["guest_credential"],
            session_id=resources["session_id"],
            code_suffix="guest-ownership-owner",
        )
        case_id = self._promote_resources_to_case(
            resources=resources,
            owner_client=owner_client,
        )
        attacker_client = _authenticated_client("usr_guest_ownership_attacker")
        forbidden = (
            owner_id,
            resources["guest_id"],
            resources["session_id"],
            resources["job_id"],
            resources["attachment_id"],
            resources["report_id"],
            case_id,
            "guest-fine-notice.txt",
            "Review verified facts and legal grounds.",
        )
        before_attacks = self._resource_snapshot()

        denied_requests = (
            attacker_client.get(f"/api/analysis/jobs/{resources['job_id']}/"),
            attacker_client.get(f"/api/analysis/results/{resources['job_id']}/"),
            attacker_client.get(
                f"/api/files/{resources['attachment_id']}/",
                {"session_id": resources["session_id"]},
            ),
            attacker_client.get(f"/api/reports/{resources['report_id']}/"),
            attacker_client.get(f"/api/cases/{case_id}/workspace/"),
            attacker_client.post(
                "/api/chat/save-state/",
                data={"session_id": resources["session_id"], "save_state": "saved"},
                content_type="application/json",
            ),
        )
        for response in denied_requests:
            self._assert_safe_denial(
                response,
                code="object_access_denied",
                forbidden=forbidden,
            )

        case_claim = attacker_client.post(
            "/api/cases/",
            data={
                "session_id": resources["session_id"],
                "title": "Attacker claim",
                "case_type": "accident_fault",
            },
            content_type="application/json",
        )
        self._assert_safe_denial(
            case_claim,
            code="case_owner_mismatch",
            forbidden=forbidden,
        )

        with patch("chatbot.views.get_report_download_metadata") as resolve_download:
            denied_download = attacker_client.get(
                f"/api/reports/{resources['report_id']}/download/?document_type=objection_form"
            )
        self._assert_safe_denial(
            denied_download,
            code="object_access_denied",
            forbidden=forbidden,
        )
        resolve_download.assert_not_called()
        self.assertEqual(self._resource_snapshot(), before_attacks)
