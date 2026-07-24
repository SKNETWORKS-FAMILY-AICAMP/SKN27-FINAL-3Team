"""Deterministic API-to-worker coverage for the representative user journey."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import timedelta
import os
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.chat_orchestration_service import _analysis_plan
from app.services.google_auth_service import issue_access_token
from chatbot.file_scan_service import process_uploaded_file_scans
from chatbot.models import AgentWorkItem, AuthSession, AuthSessionStatus, Report, UserAccount
from chatbot.repositories import process_agent_work_item


TEST_JWT_SIGNING_KEY = "canonical-user-flow-e2e-test-signing-key-is-long-enough"


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


def _queued_chat_response(
    *,
    session_id: str,
    message_id: str,
    attachments: list[dict],
    ocr_confirmation: dict,
) -> dict:
    slot_state = {"contract_version": "slot_filling_state.v1", "slots": {}}
    supervisor_state = {
        "contract_version": "supervisor_conversation_state.v2",
        "stage": "agent_execution_ready",
        "next_questions": [],
        "slot_state": slot_state,
        "collected_facts": {"notice_number": "FN-2026-001"},
        "case_evidence": {
            "claims": {
                "driver_statement": {
                    "value": "The signal was yellow.",
                    "evidence_source": {
                        "source_type": "user_statement",
                        "source_ref": "private-upload-reference",
                        "source_message_id": "private-message-reference",
                    },
                }
            }
        },
    }
    analysis_plan = _analysis_plan(
        session_id=session_id,
        message_id=message_id,
        routing_intent="fine_notice_analysis",
        supervisor_state=supervisor_state,
        report_requested=True,
        ocr_confirmation=ocr_confirmation,
    )
    attachment_selectors = [
        {"attachment_id": attachment["attachment_id"]}
        for attachment in attachments
        if isinstance(attachment, dict) and attachment.get("attachment_id")
    ]
    packages = [
        {
            "schema_version": "agent_input_schema.v1",
            "node_code": node_code,
            "status": "ready",
            "required_inputs": ["user_text|attachments"],
            "payload": {
                "user_text": "fixture notice facts",
                "attachments": attachment_selectors,
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
        "progress": {"status": "queued", "active_node": "fine_notice_analysis"},
        "assistant_message": {"answer": "Queued.", "summary": "Queued."},
        "analysis_plan": analysis_plan,
        "supervisor_state": {
            **supervisor_state,
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
        "attachments": attachments,
        "blocked_attachments": [],
        "limitations": [],
    }


def _fixture_submit_message(payload: dict, **_kwargs) -> dict:
    session_id = str(payload["session_id"])
    return _queued_chat_response(
        session_id=session_id,
        message_id=f"msg_{session_id}",
        attachments=list(payload.get("attachments") or []),
        ocr_confirmation=dict(payload.get("ocr_confirmation") or {}),
    )


@contextmanager
def _patched_agents(*, law_status: str = "success"):
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
                        "opinion_deadline": "2026-12-31",
                        "issuing_authority": "Fixture Traffic Authority",
                    },
                    "evidence": [{"source_type": "fixture", "source_reference": "fixture:notice"}],
                    "next_actions": [],
                    "limitations": [],
                }
            }
        }

    def run_law(_agent_input, _adapter_context):
        return {
            "status": law_status,
            "summary": "Fixture law result.",
            "structured_result": {"matched_laws": [{"law_name": "Road Traffic Act"}]},
            "evidence": [{"source_type": "law", "source_reference": "fixture:law"}],
            "next_actions": ["review_legal_basis"] if law_status == "partial" else [],
            "limitations": ["Legal search requires review."] if law_status == "partial" else [],
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
                    },
                    "evidence": [
                        {"source_type": "law", "source_reference": "fixture:law"}
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
                "form_sections": [{"title": "Petition", "items": ["Review disposition."]}],
                "form_data": {"applicant_name": "Review required"},
                "petition_purpose": "Review disposition.",
                "petition_reason": "Review verified facts and legal grounds.",
                "drafting_source": "rule_based_fixture",
                "appeal_gate": {"status": "ready"},
                "document_readiness": {"status": "review_required"},
                "report_actions": [{"action": "download_objection", "label": "Download form"}],
                "supervisor_handoff": {
                    "contract_version": handoff["contract_version"],
                    "handoff_id": handoff["handoff_id"],
                    "gate_status": handoff["gate"]["status"],
                    "source_fingerprint": source["fingerprint"],
                    "source_result_ids": source["result_ids"],
                },
            },
            "evidence": [],
            "next_actions": ["review_objection_draft", "download_objection"],
            "limitations": [],
        }

    with ExitStack() as stack:
        stack.enter_context(patch.object(fine_notice_graph, "invoke", side_effect=run_fine_notice))
        stack.enter_context(patch("ai.agents.law_ground_search.run_law_ground_search", side_effect=run_law))
        stack.enter_context(patch.object(appeal_graph, "invoke", side_effect=run_appeal))
        stack.enter_context(
            patch("ai.agents.objection_report_generation.run_objection_report_generation", side_effect=run_report)
        )
        yield


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class CanonicalUserFlowE2ETests(TestCase):
    def setUp(self) -> None:
        self.object_root = tempfile.TemporaryDirectory()
        self.upload_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.object_root.cleanup)
        self.addCleanup(self.upload_root.cleanup)
        self.storage_override = override_settings(
            OBJECT_STORAGE_PROVIDER="mock_s3",
            OBJECT_STORAGE_BUCKET="canonical-e2e-clean",
            OBJECT_STORAGE_QUARANTINE_BUCKET="canonical-e2e-quarantine",
            OBJECT_STORAGE_LOCAL_ROOT=self.object_root.name,
            MOCK_UPLOAD_ROOT=self.upload_root.name,
            FILE_SCAN_PROVIDER="local_policy",
        )
        self.storage_override.enable()
        self.addCleanup(self.storage_override.disable)
        self.upload_root_override = patch.dict(
            os.environ,
            {"MOCK_UPLOAD_ROOT": self.upload_root.name},
        )
        self.upload_root_override.start()
        self.addCleanup(self.upload_root_override.stop)
        self.owner_client = _authenticated_client("usr_canonical_owner")
        self.attacker_client = _authenticated_client("usr_canonical_attacker")

    def _queue_clean_flow(self) -> dict[str, str]:
        created = self.owner_client.post("/api/chat/sessions/", data={}, content_type="application/json")
        self.assertEqual(created.status_code, 200, created.content)
        session_id = created.json()["session_id"]

        uploaded = self.owner_client.post(
            "/api/files/",
            data={
                "session_id": session_id,
                "purpose": "fine_notice",
                "file": SimpleUploadedFile("notice.png", b"fixture clean notice", content_type="image/png"),
            },
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.content)
        attachment_id = uploaded.json()["attachment"]["attachment_id"]
        scan = process_uploaded_file_scans(limit=1)
        self.assertEqual(scan["clean"], 1, scan)

        with patch("chatbot.views.submit_message", side_effect=_fixture_submit_message):
            queued = self.owner_client.post(
                "/api/chat/messages/",
                data={
                    "session_id": session_id,
                    "user_text": "Please review this fine notice.",
                    "attachments": [{"attachment_id": attachment_id}],
                    "ocr_confirmation": {
                        "confirmed": True,
                        "fields": {
                            "fine_type": "fine",
                            "notice_stage": "pre_notice",
                        },
                    },
                },
                content_type="application/json",
            )
        self.assertEqual(queued.status_code, 202, queued.content)
        work_item = queued.json()["work_item"]
        return {
            "session_id": session_id,
            "attachment_id": attachment_id,
            "job_id": work_item["job_id"],
            "work_item_id": work_item["work_item_id"],
        }

    def _process(self, work_item_id: str, *, law_status: str = "success") -> Report | None:
        with _patched_agents(law_status=law_status):
            processed = process_agent_work_item(work_item_id)
        self.assertEqual(processed["status"], "success", processed)
        work_item = AgentWorkItem.objects.select_related("job").get(work_item_id=work_item_id)
        return Report.objects.filter(job=work_item.job).first()

    def test_canonical_flow_returns_confirmed_facts_claims_and_docx(self) -> None:
        resources = self._queue_clean_flow()
        pending = self.owner_client.get(f"/api/analysis/results/{resources['job_id']}/")
        self.assertEqual(pending.status_code, 202, pending.content)
        self.assertEqual(pending.json()["result"]["status"], "queued")
        self.assertNotIn("user_claims", pending.json()["result"])

        report = self._process(resources["work_item_id"])
        self.assertIsNotNone(
            report,
            AgentWorkItem.objects.select_related("job")
            .get(work_item_id=resources["work_item_id"])
            .job.metadata,
        )
        result = self.owner_client.get(f"/api/analysis/results/{resources['job_id']}/")
        self.assertEqual(result.status_code, 200, result.content)
        payload = result.json()["result"]
        self.assertEqual(payload["supervisor_state"]["collected_facts"], {"notice_number": "FN-2026-001"})
        self.assertEqual(payload["user_claims"], [{"field": "driver_statement", "value": "The signal was yellow.", "source_type": "user_statement"}])
        self.assertNotIn("private-upload-reference", str(payload))
        self.assertNotIn("private-message-reference", str(payload))

        report_detail = self.owner_client.get(f"/api/reports/{report.report_id}/")
        self.assertEqual(report_detail.status_code, 200, report_detail.content)
        self.assertEqual(report_detail.json()["report"]["report_id"], report.report_id)
        confirmation = self.owner_client.post(
            f"/api/reports/{report.report_id}/document-confirmation/",
            data={"facts_confirmed": True, "agency_confirmed": True, "deadline_confirmed": True, "attachments_confirmed": True},
            content_type="application/json",
        )
        self.assertEqual(confirmation.status_code, 201, confirmation.content)
        download = self.owner_client.get(f"/api/reports/{report.report_id}/download/?document_type=objection_form")
        self.assertEqual(download.status_code, 200, download.content)
        self.assertEqual(download["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertIn("attachment", download["Content-Disposition"].lower())
        self.assertTrue(download.content.startswith(b"PK"))

    def test_partial_law_result_keeps_limitations_without_report(self) -> None:
        resources = self._queue_clean_flow()
        report = self._process(resources["work_item_id"], law_status="partial")
        self.assertIsNone(report)
        result = self.owner_client.get(f"/api/analysis/results/{resources['job_id']}/")
        self.assertEqual(result.status_code, 200, result.content)
        payload = result.json()["result"]
        self.assertEqual(payload["status"], "partial")
        self.assertTrue(payload["limitations"])
        self.assertTrue(payload["next_actions"])
        self.assertEqual(payload["report_links"], [])

    def test_foreign_owner_cannot_read_result_report_or_docx(self) -> None:
        resources = self._queue_clean_flow()
        report = self._process(resources["work_item_id"])
        self.assertIsNotNone(
            report,
            AgentWorkItem.objects.select_related("job")
            .get(work_item_id=resources["work_item_id"])
            .job.metadata,
        )
        for response in (
            self.attacker_client.get(f"/api/analysis/results/{resources['job_id']}/"),
            self.attacker_client.get(f"/api/reports/{report.report_id}/"),
            self.attacker_client.get(f"/api/reports/{report.report_id}/download/?document_type=objection_form"),
        ):
            self.assertEqual(response.status_code, 403, response.content)
            self.assertEqual(response.json()["error"]["code"], "object_access_denied")
            self.assertNotIn("Content-Disposition", response.headers)
            self.assertFalse(response.content.startswith(b"PK"))
