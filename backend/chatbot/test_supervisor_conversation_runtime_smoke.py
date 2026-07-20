from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from chatbot.models import AgentWorkItem, AnalysisJob, Report


class SupervisorConversationRuntimeSmokeTests(TestCase):
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
