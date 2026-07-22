from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import timedelta
import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.chat_orchestration_service import _analysis_plan
from app.services.google_auth_service import issue_access_token
from chatbot.models import (
    AgentWorkItem,
    AnalysisJob,
    AuthSession,
    AuthSessionStatus,
    ChatSession,
    Report,
    UploadedFile,
    UploadedFileStatus,
    UserAccount,
)
from chatbot.repositories import process_agent_work_item


TEST_JWT_SIGNING_KEY = "resource-ownership-e2e-test-signing-key-is-long-enough"


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
        ocr_confirmation={
            "confirmed": True,
            "fields": {
                "fine_type": "fine",
                "notice_stage": "pre_notice",
            },
        },
    )
    packages = [
        {
            "schema_version": "agent_input_schema.v1",
            "node_code": node_code,
            "status": "ready",
            "required_inputs": ["user_text|attachments"],
            "payload": {
                "user_text": "owner-bound fixture facts",
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
    job_id = str(payload.get("job_id") or "chat")
    return _report_ready_chat_response(
        session_id=session_id,
        message_id=f"msg_{session_id}_{job_id}",
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
                            "source_reference": "resource-ownership:notice",
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
                        "source_reference": "resource-ownership:law",
                    }
                ]
            },
            "evidence": [
                {"source_type": "law", "source_reference": "resource-ownership:law"}
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
                            "source_reference": "resource-ownership:law",
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
                "petition_reason": "Review the verified facts and legal grounds.",
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
                {"source_type": "law", "source_reference": "resource-ownership:law"}
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


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class ResourceOwnershipE2ETests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_resource_owner"
        self.attacker_id = "usr_resource_attacker"
        self.owner_client = _authenticated_client(self.owner_id)
        self.attacker_client = _authenticated_client(self.attacker_id)
        self.private_fragments = (
            "s3://private-bucket",
            "private-bucket",
            "reports/owner.docx",
            "storage_backend",
            "resource-ownership:law",
            "source_fingerprint",
            "Review the verified facts and legal grounds.",
        )

    def _create_owner_resources(self) -> dict[str, str]:
        session_id = "ses_resource_owner"
        job_id = "job_resource_owner"
        attachment_id = "att_resource_owner"

        with patch("chatbot.views.submit_message", side_effect=_fixture_submit_message):
            chat = self.owner_client.post(
                "/api/chat/messages/",
                data={
                    "session_id": session_id,
                    "user_text": "Create owner-bound session.",
                },
                content_type="application/json",
            )
            accepted = self.owner_client.post(
                "/api/analysis/jobs/",
                data={
                    "job_id": job_id,
                    "session_id": session_id,
                    "user_text": "Prepare official objection.",
                },
                content_type="application/json",
            )

        self.assertEqual(chat.status_code, 202, chat.content)
        self.assertEqual(accepted.status_code, 202, accepted.content)

        session = ChatSession.objects.get(session_id=session_id)
        UploadedFile.objects.create(
            attachment_id=attachment_id,
            owner_id=self.owner_id,
            session=session,
            purpose="fine_notice",
            original_filename="fixture-notice.png",
            content_type="image/png",
            status=UploadedFileStatus.READY,
            scan_status="clean",
            storage_uri="s3://private-bucket/reports/owner.docx",
        )
        work_item = AgentWorkItem.objects.get(job__job_id=job_id)
        with _patched_report_ready_agents():
            processed = process_agent_work_item(work_item.work_item_id)

        self.assertEqual(processed["status"], "success", processed)
        job = AnalysisJob.objects.select_related("session").get(job_id=job_id)
        report = Report.objects.select_related("session", "job").get(job=job)
        self.assertEqual((job.owner_id, job.session.session_id), (self.owner_id, session_id))
        self.assertEqual(
            (report.owner_id, report.session.session_id, report.job_id),
            (self.owner_id, session_id, job.pk),
        )
        return {
            "session_id": session_id,
            "job_id": job_id,
            "attachment_id": attachment_id,
            "report_id": report.report_id,
        }

    def _assert_object_access_denied(self, response) -> None:
        self.assertEqual(response.status_code, 403, response.content)
        body = response.json()
        self.assertEqual(body["error"]["code"], "object_access_denied")
        rendered = json.dumps(body, sort_keys=True)
        self.assertNotIn(self.owner_id, rendered)
        for fragment in self.private_fragments:
            self.assertNotIn(fragment, rendered)
        self.assertNotIn("Content-Disposition", response.headers)
        self.assertNotEqual(
            response.headers.get("Content-Type"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertFalse(response.content.startswith(b"PK"))

    def test_owner_can_complete_bound_resource_lifecycle_and_download_docx(self) -> None:
        resources = self._create_owner_resources()

        attachment = self.owner_client.get(
            f"/api/files/{resources['attachment_id']}/",
            {"session_id": resources["session_id"]},
        )
        job_list = self.owner_client.get(
            "/api/analysis/jobs/", {"session_id": resources["session_id"]}
        )
        job_detail = self.owner_client.get(f"/api/analysis/jobs/{resources['job_id']}/")
        job_result = self.owner_client.get(f"/api/analysis/results/{resources['job_id']}/")
        report_detail = self.owner_client.get(f"/api/reports/{resources['report_id']}/")
        self.assertEqual(attachment.status_code, 200, attachment.content)
        self.assertEqual(job_list.status_code, 200, job_list.content)
        self.assertEqual(job_detail.status_code, 200, job_detail.content)
        self.assertEqual(job_result.status_code, 200, job_result.content)
        self.assertEqual(report_detail.status_code, 200, report_detail.content)

        confirmation = self.owner_client.post(
            f"/api/reports/{resources['report_id']}/document-confirmation/",
            data={
                "facts_confirmed": True,
                "agency_confirmed": True,
                "deadline_confirmed": True,
                "attachments_confirmed": True,
            },
            content_type="application/json",
        )
        self.assertEqual(confirmation.status_code, 201, confirmation.content)
        download = self.owner_client.get(
            f"/api/reports/{resources['report_id']}/download/?document_type=objection_form"
        )
        self.assertEqual(download.status_code, 200, download.content)
        self.assertEqual(
            download["Content-Type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertIn("attachment", download["Content-Disposition"].lower())
        self.assertTrue(download.content.startswith(b"PK"))

    def test_attacker_cannot_access_or_mutate_any_owner_bound_resource(self) -> None:
        resources = self._create_owner_resources()
        session_id = resources["session_id"]
        job_id = resources["job_id"]
        attachment_id = resources["attachment_id"]
        report_id = resources["report_id"]
        owner_job_count = AnalysisJob.objects.filter(
            session__session_id=session_id
        ).count()

        requests = (
            (
                "job_list",
                lambda: self.attacker_client.get(
                    "/api/analysis/jobs/", {"session_id": session_id}
                ),
            ),
            (
                "job_detail",
                lambda: self.attacker_client.get(f"/api/analysis/jobs/{job_id}/"),
            ),
            (
                "job_result",
                lambda: self.attacker_client.get(f"/api/analysis/results/{job_id}/"),
            ),
            (
                "attachment",
                lambda: self.attacker_client.get(
                    f"/api/files/{attachment_id}/", {"session_id": session_id}
                ),
            ),
            (
                "report_detail",
                lambda: self.attacker_client.get(f"/api/reports/{report_id}/"),
            ),
            (
                "chat_session_reuse",
                lambda: self.attacker_client.post(
                    "/api/chat/messages/",
                    data={"session_id": session_id, "user_text": "attacker write"},
                    content_type="application/json",
                ),
            ),
            (
                "save_state",
                lambda: self.attacker_client.post(
                    "/api/chat/save-state/",
                    data={"session_id": session_id, "save_state": "saved"},
                    content_type="application/json",
                ),
            ),
            (
                "analysis_submit",
                lambda: self.attacker_client.post(
                    "/api/analysis/jobs/",
                    data={
                        "job_id": "job_attacker_attempt",
                        "session_id": session_id,
                        "user_text": "attacker analysis",
                    },
                    content_type="application/json",
                ),
            ),
        )
        for boundary, request in requests:
            with self.subTest(boundary=boundary):
                self._assert_object_access_denied(request())

        with patch("chatbot.views.get_report_download_metadata") as resolve_download:
            denied_download = self.attacker_client.get(
                f"/api/reports/{report_id}/download/?document_type=objection_form"
            )

        self._assert_object_access_denied(denied_download)
        resolve_download.assert_not_called()
        self.assertEqual(
            AnalysisJob.objects.filter(session__session_id=session_id).count(),
            owner_job_count,
        )
        self.assertFalse(AnalysisJob.objects.filter(job_id="job_attacker_attempt").exists())
