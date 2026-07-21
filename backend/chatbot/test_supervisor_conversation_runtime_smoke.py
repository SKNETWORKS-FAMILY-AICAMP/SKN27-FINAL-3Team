from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from chatbot.models import (
    AgentWorkItem,
    AnalysisJob,
    ChatSession,
    ChatSessionStatus,
    Report,
)


class SupervisorConversationRuntimeSmokeTests(TestCase):
    def test_smoke_output_normalizes_untrusted_reason_and_excludes_identifiers(self) -> None:
        from chatbot.management.commands import smoke_supervisor_conversation_runtime as smoke

        raw_reason = (
            "Kim Hye-rim 010-1234-5678 900101-1234567 123 Test-ro "
            "12A3456 fine-notice.png C:\\private\\fine-notice.png "
            "s3://private-bucket/fine-notice.png sk-private-token gpt-private"
        )
        result = smoke._safe_llm(
            {
                "llm": {
                    "status": "failed",
                    "reason": raw_reason,
                    "provider": "provider-private",
                    "model": "gpt-private",
                }
            }
        )

        self.assertEqual(result, {"status": "failed", "reason": "unspecified"})
        self.assertNotIn("Kim Hye-rim", repr(result))
        self.assertNotIn("s3://private-bucket", repr(result))
        self.assertNotIn("gpt-private", repr(result))

    def test_smoke_output_preserves_allowed_reason_code(self) -> None:
        from chatbot.management.commands import smoke_supervisor_conversation_runtime as smoke

        self.assertEqual(
            smoke._safe_llm({"llm": {"status": "failed", "reason": "missing_config"}}),
            {"status": "failed", "reason": "missing_config"},
        )

    def test_smoke_output_maps_disabled_state_to_disabled_reason(self) -> None:
        from chatbot.management.commands import smoke_supervisor_conversation_runtime as smoke

        self.assertEqual(
            smoke._safe_llm(
                {"llm": {"status": "disabled", "reason": "SUPERVISOR_LLM_ENABLED is off"}}
            ),
            {"status": "disabled", "reason": "disabled"},
        )

    def test_strict_checks_reject_disabled_llm_and_non_real_agent_results(self) -> None:
        from chatbot.management.commands import smoke_supervisor_conversation_runtime as smoke

        failed = smoke._failed_checks(
            {
                "chat": {"status": "queued"},
                "llm": {"status": "disabled"},
                "checks": {
                    "job_success": True,
                    "all_agent_results_success": True,
                    "real_agent_results": False,
                    "persisted_handoff_consumed": True,
                    "report_ready": True,
                    "analysis_display_persisted": True,
                    "public_result_loaded": True,
                },
            },
            {
                "require_llm_used": True,
                "require_real_agent_results": True,
                "require_persisted_handoff": True,
                "require_report": True,
            },
        )

        self.assertEqual(failed, ["llm_used", "real_agent_results"])

    def test_report_requested_supervisor_plan_keeps_reporting_step_final(self) -> None:
        from app.services.chat_orchestration_service import _analysis_plan

        plan = _analysis_plan(
            session_id="ses_report_plan",
            message_id="msg_report_plan",
            routing_intent="fine_notice_analysis",
            supervisor_state={
                "contract_version": "supervisor_conversation_state.v2",
                "next_questions": [],
            },
            report_requested=True,
        )

        node_codes = [step["node_code"] for step in plan["steps"]]
        self.assertEqual(node_codes[-1], "objection_report_generation")
        self.assertIn("final_response_merge", node_codes)
        self.assertEqual(plan["steps"][-1]["depends_on"], ["final_response_merge"])

    def test_command_requires_explicit_paid_call_consent_before_creating_rows(self) -> None:
        with self.assertRaisesMessage(CommandError, "--allow-paid-provider-call"):
            call_command("smoke_supervisor_conversation_runtime", stdout=StringIO())

        self.assertFalse(AnalysisJob.objects.exists())
        self.assertFalse(AgentWorkItem.objects.exists())
        self.assertFalse(Report.objects.exists())

    def test_command_requires_clean_fixture_before_creating_rows(self) -> None:
        with self.assertRaisesMessage(CommandError, "--fine-notice-fixture-s3-uri"):
            call_command(
                "smoke_supervisor_conversation_runtime",
                allow_paid_provider_call=True,
                stdout=StringIO(),
            )

        self.assertFalse(AnalysisJob.objects.exists())
        self.assertFalse(AgentWorkItem.objects.exists())
        self.assertFalse(Report.objects.exists())

    def test_supervisor_failure_creates_no_followup_rows_for_smoke_session(self) -> None:
        from chatbot.management.commands import smoke_supervisor_conversation_runtime as smoke

        existing_session = ChatSession.objects.create(
            session_id="ses_existing_runtime_smoke",
            status=ChatSessionStatus.ACTIVE.value,
        )
        AnalysisJob.objects.create(
            job_id="job_existing_runtime_smoke",
            session=existing_session,
        )
        blocked_response = {
            "contract_version": "chat_message_accepted.v2",
            "session_id": "ses_supervisor_blocked",
            "message_id": "msg_supervisor_blocked",
            "routing_intent": "traffic_law_search",
            "status": "supervisor_unavailable",
            "progress": {"status": "blocked", "active_node": "", "message": "Planning unavailable."},
            "assistant_message": {"answer": "Planning unavailable.", "summary": "Planning unavailable."},
            "analysis_plan": {"plan_id": "plan_supervisor_blocked", "steps": []},
            "supervisor_state": {"llm": {"status": "failed", "reason": "provider_unavailable"}},
            "reporting_payload": None,
            "attachments": [],
            "blocked_attachments": [],
            "limitations": ["Supervisor planning is temporarily unavailable."],
        }

        with patch("chatbot.views.submit_message", return_value=blocked_response):
            result = smoke._run_smoke(
                {
                    "content_type": "image/png",
                    "storage_uri": "s3://clean-bucket/canonical/acceptance/fixture.png",
                    "object_storage": {"resource_type": "uploaded_file", "provider": "s3", "bucket": "clean-bucket", "key": "canonical/acceptance/fixture.png"},
                }
            )

        self.assertEqual(result["chat"]["http_status"], 503)
        self.assertEqual(result["chat"]["status"], "supervisor_unavailable")
        self.assertTrue(result["checks"]["planning_failure_has_no_followup_rows"])
        self.assertEqual(AnalysisJob.objects.count(), 1)

    def test_runtime_uses_public_chat_queue_and_worker_result(self) -> None:
        from chatbot.management.commands import smoke_supervisor_conversation_runtime as smoke

        slot_state = {"contract_version": "slot_filling_state.v1", "slots": {}}
        chat_response = {
            "contract_version": "chat_message_accepted.v2",
            "session_id": "ses_server",
            "message_id": "msg_server",
            "routing_intent": "traffic_law_search",
            "status": "queued",
            "progress": {"status": "queued", "active_node": "law_ground_search", "message": "Queued."},
            "assistant_message": {"answer": "Queued.", "summary": "Queued."},
            "analysis_plan": {
                "plan_id": "plan_server",
                "routing_intent": "traffic_law_search",
                "steps": [{"order": 1, "node_code": "law_ground_search", "status": "ready", "depends_on": []}],
            },
            "supervisor_state": {
                "contract_version": "supervisor_conversation_state.v2",
                "stage": "agent_execution_ready",
                "llm": {"status": "used", "provider": "test", "model": "test"},
                "slot_state": slot_state,
                "agent_input_packages": [
                    {
                        "schema_version": "agent_input_schema.v1",
                        "node_code": "law_ground_search",
                        "status": "ready",
                        "required_inputs": ["user_text"],
                        "payload": {"user_text": "server approved", "attachments": [], "slot_state": slot_state},
                    }
                ],
                "reporting_payload": None,
            },
            "attachments": [],
            "blocked_attachments": [],
            "limitations": [],
        }

        def run_law(_agent_input, _adapter_context):
            return {"status": "success", "summary": "Fixture law result.", "structured_result": {"matched_laws": []}, "evidence": [], "next_actions": [], "limitations": []}

        with (
            patch("chatbot.views.submit_message", return_value=chat_response),
            patch("ai.agents.law_ground_search.run_law_ground_search", side_effect=run_law),
        ):
            result = smoke._run_smoke(
                {
                    "content_type": "image/png",
                    "storage_uri": "s3://clean-bucket/canonical/acceptance/fixture.png",
                    "object_storage": {"resource_type": "uploaded_file", "provider": "s3", "bucket": "clean-bucket", "key": "canonical/acceptance/fixture.png"},
                }
            )

        self.assertEqual(result["chat"], {"http_status": 202, "status": "queued", "execution_mode": "async_worker"})
        self.assertEqual(result["llm"]["status"], "used")
        self.assertTrue(result["checks"]["queued"])
        self.assertTrue(result["checks"]["worker_completed"])
        self.assertTrue(result["checks"]["public_result_loaded"])

    def test_runtime_persists_supervisor_handoff_and_ready_report(self) -> None:
        from ai.agents.appeal_decision_flow import graph as appeal_graph
        from ai.agents.fine_notice_analysis import graph as fine_notice_graph
        from app.services.chat_orchestration_service import _analysis_plan
        from chatbot.management.commands import smoke_supervisor_conversation_runtime as smoke

        slot_state = {"contract_version": "slot_filling_state.v1", "slots": {}}
        plan_state = {
            "contract_version": "supervisor_conversation_state.v2",
            "next_questions": [],
        }
        analysis_plan = _analysis_plan(
            session_id="ses_server",
            message_id="msg_server",
            routing_intent="fine_notice_analysis",
            supervisor_state=plan_state,
            report_requested=True,
        )
        packages = [
            {
                "schema_version": "agent_input_schema.v1",
                "node_code": node_code,
                "status": "ready",
                "required_inputs": ["user_text|attachments"],
                "payload": {
                    "user_text": "server approved fine-notice facts",
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
        chat_response = {
            "contract_version": "chat_message_accepted.v2",
            "session_id": "ses_server",
            "message_id": "msg_server",
            "routing_intent": "fine_notice_analysis",
            "status": "queued",
            "progress": {"status": "queued", "active_node": "fine_notice_analysis", "message": "Queued."},
            "assistant_message": {"answer": "Queued.", "summary": "Queued."},
            "analysis_plan": analysis_plan,
            "supervisor_state": {
                **plan_state,
                "stage": "agent_execution_ready",
                "llm": {"status": "used", "provider": "test", "model": "test"},
                "slot_state": slot_state,
                "agent_input_packages": packages,
                "reporting_payload": {"contract_version": "reporting_payload.v2", "report_type": "fine_notice_objection"},
            },
            "reporting_payload": {"contract_version": "reporting_payload.v2", "report_type": "fine_notice_objection"},
            "attachments": [],
            "blocked_attachments": [],
            "limitations": [],
        }

        def run_fine_notice(_state):
            return {
                "agent_results": {
                    "fine_notice_analysis": {
                        "status": "success",
                        "summary": "Sanitized notice parsed.",
                        "structured_result": {
                            "ocr_status": "success",
                            "fine_type": "과태료",
                            "notice_stage": "사전통지",
                            "violation_text": "Acceptance fixture violation.",
                            "opinion_deadline": "2026-12-31",
                            "issuing_authority": "Acceptance Traffic Authority",
                        },
                        "evidence": [{"source_type": "user_uploaded_file", "source_reference": "acceptance-fixture:1"}],
                        "next_actions": [],
                        "limitations": [],
                    }
                }
            }

        def run_law(_agent_input, _adapter_context):
            return {
                "status": "success",
                "summary": "Persisted law result.",
                "structured_result": {"matched_laws": [{"law_name": "Road Traffic Act", "article": "Article 1", "summary": "Fixture provision.", "source_reference": "law-smoke:1"}]},
                "evidence": [{"source_type": "law", "source_reference": "law-smoke:1"}],
                "next_actions": [],
                "limitations": [],
            }

        def run_appeal(_state):
            return {
                "agent_results": {
                    "appeal_judgment": {
                        "status": "success",
                        "summary": "Appeal review completed.",
                        "structured_result": {"judgment_status": "success", "overall_possibility": "review_available", "guide": {"summary": "Review supporting evidence."}},
                        "evidence": [{"source_type": "law", "source_reference": "law-smoke:1"}],
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
                "summary": "Official objection draft is ready for review.",
                "structured_result": {
                    "document_type": "objection_form",
                    "document_variant": "fine_notice",
                    "document_title": "과태료 처분에 대한 이의신청서",
                    "form_sections": [{"title": "신청 취지", "items": ["처분 재검토를 요청합니다."]}],
                    "form_data": {"applicant_name": "검토 필요"},
                    "petition_purpose": "처분 재검토를 요청합니다.",
                    "petition_reason": "검증된 사실과 법령 근거를 검토해 주세요.",
                    "drafting_source": "rule_based_fixture",
                    "appeal_gate": {"status": "ready"},
                    "document_readiness": {"status": "review_required"},
                    "report_actions": [{"action": "download_objection", "label": "이의신청서 다운로드"}],
                    "supervisor_handoff": {
                        "contract_version": handoff["contract_version"],
                        "handoff_id": handoff["handoff_id"],
                        "gate_status": handoff["gate"]["status"],
                        "source_fingerprint": source["fingerprint"],
                        "source_result_ids": source["result_ids"],
                    },
                },
                "evidence": [{"source_type": "law", "source_reference": "law-smoke:1"}],
                "next_actions": ["review_objection_draft", "download_objection", "review_report_screen"],
                "limitations": [],
            }

        with (
            patch("chatbot.views.submit_message", return_value=chat_response),
            patch.object(fine_notice_graph, "invoke", side_effect=run_fine_notice),
            patch("ai.agents.law_ground_search.run_law_ground_search", side_effect=run_law),
            patch.object(appeal_graph, "invoke", side_effect=run_appeal),
            patch("ai.agents.objection_report_generation.run_objection_report_generation", side_effect=run_report),
        ):
            result = smoke._run_smoke(
                {
                    "content_type": "image/png",
                    "storage_uri": "s3://clean-bucket/canonical/acceptance/fixture.png",
                    "object_storage": {"resource_type": "uploaded_file", "provider": "s3", "bucket": "clean-bucket", "key": "canonical/acceptance/fixture.png"},
                }
            )

        self.assertEqual(result["llm"]["status"], "used")
        self.assertTrue(result["checks"]["job_success"], result)
        self.assertTrue(result["checks"]["all_agent_results_success"])
        self.assertTrue(result["checks"]["real_agent_results"])
        self.assertTrue(result["checks"]["persisted_handoff_consumed"])
        self.assertTrue(result["checks"]["report_ready"])
        self.assertTrue(result["checks"]["analysis_display_persisted"])
        self.assertTrue(result["checks"]["public_result_loaded"])
