from __future__ import annotations

import json
import os
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase
from django.urls import Resolver404, resolve

from app.services.guest_credential_service import issue_guest_credential
from chatbot.api_response import json_response
from chatbot.models import ReportType
from chatbot.runtime_health import build_runtime_health
from chatbot.views import (
    _analysis_job_access_response,
    agent_nodes,
    analysis_jobs,
    analysis_result,
    run_agent_plan,
    submit_chat_message,
)


def _ready_supervisor_state() -> dict:
    slot_state = {
        "contract_version": "slot_filling_state.v1",
        "slots": {"query": {"value": "server query", "status": "filled"}},
    }
    return {
        "contract_version": "supervisor_conversation_state.v2",
        "stage": "agent_execution_ready",
        "slot_state": slot_state,
        "agent_input_packages": [
            {
                "schema_version": "agent_input_schema.v1",
                "node_code": "law_ground_search",
                "status": "ready",
                "required_inputs": ["user_text"],
                "payload": {
                    "user_text": "server approved question",
                    "attachments": [],
                    "slot_state": slot_state,
                },
            }
        ],
    }


def _queued_supervisor_chat_response() -> dict:
    return {
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
            "steps": [
                {
                    "order": 1,
                    "node_code": "law_ground_search",
                    "status": "ready",
                    "depends_on": [],
                }
            ],
        },
        "supervisor_state": _ready_supervisor_state(),
        "attachments": [],
        "blocked_attachments": [],
        "limitations": [],
    }


class ProductionApiContractTests(SimpleTestCase):
    def test_canonical_json_response_does_not_inject_runtime_mode_fields(self) -> None:
        request = RequestFactory().get("/api/capabilities/")

        response = json_response(request, {"status": "ready"})

        self.assertJSONEqual(response.content, {"status": "ready"})

    def test_liveness_endpoint_is_public_and_process_only(self) -> None:
        response = self.client.get("/api/health/live/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "live")

    @patch("chatbot.views.get_analysis_job_access_metadata")
    @patch("chatbot.views._canonical_guest_identity_policy_response")
    def test_analysis_result_access_gate_honors_canonical_guest_policy(
        self,
        guest_policy,
        access_metadata,
    ) -> None:
        denied = json_response(
            RequestFactory().get("/api/analysis/results/job_1/"),
            {"error": {"code": "guest_identity_invalid"}},
            status=401,
        )
        guest_policy.return_value = denied
        access_metadata.return_value = None

        response = _analysis_job_access_response(
            RequestFactory().get("/api/analysis/results/job_1/"),
            "job_1",
        )

        self.assertIs(response, denied)
        access_metadata.assert_not_called()

    @patch("chatbot.views.build_runtime_health")
    def test_readiness_endpoint_returns_503_when_a_required_probe_fails(self, health) -> None:
        health.return_value = {
            "status": "not_ready",
            "checks": {"database": "ready", "cache": "unavailable"},
        }

        response = self.client.get("/api/health/ready/")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_ready")

    def test_capability_catalog_exposes_only_supported_runtime_flows(self) -> None:
        response = self.client.get("/api/capabilities/")

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["contract_version"], "capability_catalog.v1")
        self.assertEqual(
            [item["code"] for item in body["capabilities"]],
            [
                "fine_notice_objection",
                "fault_ratio_text",
                "traffic_law_search",
                "saved_report",
            ],
        )
        self.assertNotIn("vision_media_analysis", str(body))
        self.assertNotIn("mock", str(body).lower())

    def test_agent_catalog_exposes_only_typed_production_adapters(self) -> None:
        response = agent_nodes(RequestFactory().get("/api/agents/nodes/"))

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["contract_version"], "agent_capability_catalog.v1")
        self.assertEqual(
            {item["node_code"] for item in body["nodes"]},
            {
                "appeal_decision_flow",
                "attachment_document_classification",
                "fine_notice_analysis",
                "law_ground_search",
                "objection_report_generation",
                "text_ml_case_search",
                "traffic_accident_confirmation_ocr",
                "vision_media_analysis",
            },
        )
        self.assertNotIn("mock", str(body).lower())

    def test_internal_and_legacy_mock_routes_are_not_resolvable(self) -> None:
        removed_paths = [
            "/api/mock/chat/messages/",
            "/api/auth/login/",
            "/api/agents/nodes/run/",
            "/api/agents/plans/run/",
            "/api/agents/work-items/process/",
            "/api/files/att_1/scan/",
        ]

        for path in removed_paths:
            with self.subTest(path=path), self.assertRaises(Resolver404):
                resolve(path)

    def test_report_type_has_one_canonical_value_per_product_report(self) -> None:
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

    @patch("chatbot.views._record_history_safely")
    @patch("chatbot.views.enqueue_analysis_job_work")
    @patch("chatbot.views.record_usage_event")
    @patch("chatbot.views._canonical_guest_identity_policy_response")
    def test_non_case_chat_message_queues_real_plan_and_returns_202(
        self,
        guest_policy,
        usage,
        enqueue,
        _record_history,
    ) -> None:
        guest_policy.return_value = None
        usage.return_value = {"allowed": True}
        enqueue.return_value = {
            "job_id": "job_1",
            "work_item_id": "work_1",
            "work_item_status": "queued",
        }
        request = RequestFactory().post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_1",
                "user_text": "도로교통법 신호위반 조문과 근거가 궁금합니다.",
            },
            content_type="application/json",
        )

        with patch("chatbot.views.get_chat_session_access_metadata", return_value=None):
            response = submit_chat_message(request)

        self.assertEqual(response.status_code, 202)
        body = json.loads(response.content)
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["execution_mode"], "async_worker")
        self.assertEqual(body["work_item"]["work_item_id"], "work_1")
        self.assertEqual(
            body["analysis_progress"],
            {
                "contract_version": "analysis_progress.v1",
                "semantic_status": "queued",
                "terminal": False,
                "retryable": True,
                "next_action": "continue_polling",
                "user_message": (
                    "분석 요청이 대기 중입니다. 순서가 되면 자동으로 진행됩니다."
                ),
                "job_id": "job_1",
                "correlation_id": "work_1",
            },
        )
        self.assertNotIn("mock", str(body).lower())
        queued_payload = enqueue.call_args.args[1]
        self.assertEqual(
            [step["node_code"] for step in queued_payload["analysis_plan"]["steps"]],
            [
                "input_context_validation",
                "law_ground_search",
                "agent_result_validation",
                "final_response_merge",
            ],
        )

    def test_chat_queue_payload_discards_client_execution_controls(self) -> None:
        queue_result = {"job_id": "job_1", "work_item_id": "work_1", "work_item_status": "queued"}
        request = RequestFactory().post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_client",
                "user_text": "check this law",
                "agent_input": {"node_code": "objection_report_generation"},
                "node_code": "objection_report_generation",
                "slot_state": {"client": True},
                "upstream_results": {"law_ground_search": {"status": "success"}},
                "execution_status": "blocked",
                "mock_status": "failed",
                "context": {
                    "notice_image": "unscanned-client-image",
                    "notice_mime_type": "image/png",
                    "vision_evidence": [{"source": "client"}],
                    "case_evidence": {"recipient": "client"},
                    "fine_type": "client-controlled",
                    "supervisor_handoff": {"client": True},
                },
            },
            content_type="application/json",
        )

        with (
            patch("chatbot.views._canonical_guest_identity_policy_response", return_value=None),
            patch("chatbot.views.get_chat_session_access_metadata", return_value=None),
            patch("chatbot.views.apply_attachment_scan_gate", side_effect=lambda payload: payload),
            patch("chatbot.views.record_usage_event", return_value={"allowed": True}),
            patch("chatbot.views.submit_message", return_value=_queued_supervisor_chat_response()),
            patch("chatbot.views.enqueue_analysis_job_work", return_value=queue_result) as enqueue,
            patch("chatbot.views._record_history_safely"),
        ):
            response = submit_chat_message(request)

        self.assertEqual(response.status_code, 202)
        execution_payload = enqueue.call_args.args[0]
        self.assertEqual(execution_payload["session_id"], "ses_server")
        self.assertEqual(execution_payload["message_id"], "msg_server")
        self.assertEqual(execution_payload["upstream_results"], {})
        self.assertEqual(
            execution_payload["context"]["supervisor_handoff"],
            _ready_supervisor_state(),
        )
        self.assertEqual(
            execution_payload["context"],
            {"supervisor_handoff": _ready_supervisor_state()},
        )
        self.assertTrue(execution_payload["requires_supervisor_handoff"])
        for field in ("agent_input", "node_code", "slot_state", "execution_status", "mock_status"):
            self.assertNotIn(field, execution_payload)

    def test_analysis_queue_payload_discards_client_execution_controls(self) -> None:
        queue_result = {
            "backend": "postgresql",
            "status": "queued",
            "execution_mode": "async_worker",
            "job_id": "job_1",
            "work_item_id": "work_1",
            "work_item_status": "queued",
        }
        request = RequestFactory().post(
            "/api/analysis/jobs/",
            data={
                "session_id": "ses_client",
                "user_text": "check this law",
                "agent_input": {"node_code": "objection_report_generation"},
                "node_code": "objection_report_generation",
                "slot_state": {"client": True},
                "upstream_results": {"law_ground_search": {"status": "success"}},
                "execution_status": "blocked",
                "mock_status": "failed",
                "context": {
                    "notice_image": "unscanned-client-image",
                    "notice_mime_type": "image/png",
                    "vision_evidence": [{"source": "client"}],
                    "case_evidence": {"recipient": "client"},
                    "fine_type": "client-controlled",
                    "supervisor_handoff": {"client": True},
                },
            },
            content_type="application/json",
        )

        with (
            patch("chatbot.views.get_chat_session_access_metadata", return_value=None),
            patch("chatbot.views.apply_attachment_scan_gate", side_effect=lambda payload: payload),
            patch("chatbot.views.record_usage_event", return_value={"allowed": True}),
            patch("chatbot.views.submit_message", return_value=_queued_supervisor_chat_response()),
            patch("chatbot.views.enqueue_analysis_job_work", return_value=queue_result) as enqueue,
            patch("chatbot.views._record_history_safely"),
        ):
            response = analysis_jobs(request)

        self.assertEqual(response.status_code, 202)
        execution_payload = enqueue.call_args.args[0]
        self.assertEqual(execution_payload["session_id"], "ses_server")
        self.assertEqual(execution_payload["message_id"], "msg_server")
        self.assertEqual(execution_payload["upstream_results"], {})
        self.assertEqual(
            execution_payload["context"]["supervisor_handoff"],
            _ready_supervisor_state(),
        )
        self.assertEqual(
            execution_payload["context"],
            {"supervisor_handoff": _ready_supervisor_state()},
        )
        self.assertTrue(execution_payload["requires_supervisor_handoff"])
        for field in ("agent_input", "node_code", "slot_state", "execution_status", "mock_status"):
            self.assertNotIn(field, execution_payload)

    def test_supervisor_unavailable_chat_response_is_not_enqueued(self) -> None:
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
        request = RequestFactory().post(
            "/api/chat/messages/",
            data={"session_id": "ses_supervisor_blocked", "user_text": "법령을 찾아줘"},
            content_type="application/json",
        )

        with (
            patch("chatbot.views._canonical_guest_identity_policy_response", return_value=None),
            patch("chatbot.views.get_chat_session_access_metadata", return_value=None),
            patch("chatbot.views.apply_attachment_scan_gate", side_effect=lambda payload: payload),
            patch("chatbot.views.record_usage_event", return_value={"allowed": True}) as usage,
            patch("chatbot.views.submit_message", return_value=blocked_response),
            patch("chatbot.views.enqueue_analysis_job_work") as enqueue,
            patch("chatbot.views._refund_usage_safely") as refund_usage,
        ):
            response = submit_chat_message(request)

        self.assertEqual(response.status_code, 503)
        body = json.loads(response.content)
        self.assertEqual(body["status"], "supervisor_unavailable")
        self.assertEqual(body["execution_mode"], "planning_blocked")
        enqueue.assert_not_called()
        usage.assert_called_once()
        refund_usage.assert_called_once_with(
            {"allowed": True},
            reason="supervisor_unavailable",
        )

    def test_low_information_chat_response_is_not_enqueued(self) -> None:
        candidate = {
            "conversation_summary": "A law reference is still required.",
            "collected_facts": [],
            "missing_fields": [
                {"field": "law_question", "reason": "required_for_search"}
            ],
            "next_questions": [
                {"field": "law_question", "question": "Which law should be reviewed?"}
            ],
            "agent_input_packages": [
                {
                    "node_code": "law_ground_search",
                    "payload": {},
                }
            ],
        }
        server_fallback = {
            "contract_version": "supervisor_conversation_state.v2",
            "scenario": "traffic_law_search",
            "stage": "need_more_input",
            "conversation_turn_count": 1,
            "conversation_summary": "Server requires a law question.",
            "collected_facts": [],
            "missing_fields": [
                {"field": "law_question", "reason": "required_for_search"}
            ],
            "next_questions": [
                {
                    "field": "law_question",
                    "question": "Which law should be reviewed?",
                }
            ],
            "slot_state": {
                "contract_version": "slot_filling_state.v1",
                "slots": {},
            },
            "agent_input_packages": [
                {
                    "schema_version": "agent_input_schema.v1",
                    "node_code": "law_ground_search",
                    "status": "waiting_for_fields",
                    "missing_fields": ["law_question"],
                    "required_inputs": ["search_query"],
                    "payload": {"user_text": "help", "attachments": []},
                }
            ],
            "reporting_payload": None,
        }
        request = RequestFactory().post(
            "/api/chat/messages/",
            data={"session_id": "ses_need_more_input", "user_text": "help"},
            content_type="application/json",
        )

        with (
            patch.dict(
                os.environ,
                {
                    "SUPERVISOR_LLM_ENABLED": "1",
                    "SUPERVISOR_LLM_API_KEY": "sk-test",
                },
            ),
            patch(
                "app.services.supervisor_llm_service._request_supervisor_json",
                return_value=candidate,
            ),
            patch(
                "app.services.chat_orchestration_service._fallback_supervisor_state",
                return_value=server_fallback,
            ),
            patch("chatbot.views._canonical_guest_identity_policy_response", return_value=None),
            patch("chatbot.views.get_chat_session_access_metadata", return_value=None),
            patch("chatbot.views.apply_attachment_scan_gate", side_effect=lambda payload: payload),
            patch("chatbot.views.record_usage_event", return_value={"allowed": True}),
            patch("chatbot.views.enqueue_analysis_job_work") as enqueue,
            patch(
                "chatbot.views.persist_chat_followup_state",
                return_value={
                    "session_id": "ses_need_more_input",
                    "message_id": "msg_followup_saved",
                    "followup_state_version": "chat_session_followup_state.v1",
                },
            ) as persist_followup,
        ):
            response = submit_chat_message(request)

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["status"], "needs_clarification")
        self.assertEqual(body["execution_mode"], "input_clarification")
        self.assertEqual(body["analysis_plan"]["steps"], [])
        self.assertIsNone(body["reporting_payload"])
        self.assertEqual(body["report_links"], [])
        enqueue.assert_not_called()
        persist_followup.assert_called_once()

    def test_exact_low_information_e2e_inputs_never_enqueue_worker(self) -> None:
        for e2e_id, user_text in (
            (10, "아 진짜 짜증나네 씨발"),
            (12, "ㄱㅈㅅ ㅂㄹㅈ ㄴㅂㄱㅎ ㅁㄹㄱㅆㅇ"),
        ):
            with self.subTest(e2e_id=e2e_id):
                request = RequestFactory().post(
                    "/api/chat/messages/",
                    data={
                        "session_id": f"ses_e2e_{e2e_id}",
                        "user_text": user_text,
                    },
                    content_type="application/json",
                )

                with (
                    patch(
                        "chatbot.views._canonical_guest_identity_policy_response",
                        return_value=None,
                    ),
                    patch(
                        "chatbot.views.get_chat_session_access_metadata",
                        return_value=None,
                    ),
                    patch(
                        "chatbot.views.apply_attachment_scan_gate",
                        side_effect=lambda payload: payload,
                    ),
                    patch(
                        "chatbot.views.record_usage_event",
                        return_value={"allowed": True},
                    ),
                    patch("chatbot.views.enqueue_analysis_job_work") as enqueue,
                    patch(
                        "chatbot.views.persist_chat_followup_state",
                        return_value={
                            "session_id": f"ses_e2e_{e2e_id}",
                            "message_id": f"msg_e2e_{e2e_id}",
                            "followup_state_version": "chat_session_followup_state.v1",
                        },
                    ) as persist_followup,
                ):
                    response = submit_chat_message(request)

                self.assertEqual(response.status_code, 200)
                body = json.loads(response.content)
                self.assertEqual(body["status"], "needs_clarification")
                self.assertEqual(body["execution_mode"], "input_clarification")
                self.assertEqual(body["analysis_plan"]["steps"], [])
                self.assertNotIn(user_text, str(body))
                enqueue.assert_not_called()
                persist_followup.assert_called_once()

    def test_scan_blocked_chat_message_does_not_consume_usage_quota(self) -> None:
        request = RequestFactory().post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_chat_scan_blocked",
                "attachments": [{"attachment_id": "att_waiting_scan"}],
            },
            content_type="application/json",
        )
        blocked_response = {
            "session_id": "ses_chat_scan_blocked",
            "message_id": "msg_chat_scan_blocked",
            "status": "queued",
            "analysis_plan": {"plan_id": "plan_chat_scan_blocked", "steps": []},
            "attachments": [],
            "blocked_attachments": [
                {
                    "attachment_id": "att_waiting_scan",
                    "required_action": "wait_for_file_scan",
                }
            ],
            "limitations": [],
        }

        with (
            patch("chatbot.views._canonical_guest_identity_policy_response", return_value=None),
            patch("chatbot.views.get_chat_session_access_metadata", return_value=None),
            patch(
                "chatbot.views.apply_attachment_scan_gate",
                side_effect=lambda payload: {
                    **payload,
                    "attachments": [],
                    "blocked_attachments": blocked_response["blocked_attachments"],
                },
            ),
            patch("chatbot.views.submit_message") as submit_message,
            patch("chatbot.views.record_usage_event") as record_usage,
            patch("chatbot.views.enqueue_analysis_job_work") as enqueue,
        ):
            response = submit_chat_message(request)

        self.assertEqual(response.status_code, 409)
        body = json.loads(response.content)
        self.assertEqual(body["execution_mode"], "scan_blocked")
        self.assertEqual(body["persistence"]["status"], "skipped")
        self.assertFalse(body["usage"]["consumed"])
        submit_message.assert_not_called()
        record_usage.assert_not_called()
        enqueue.assert_not_called()

    def test_analysis_job_rejects_blocked_input_before_reservation_or_usage(self) -> None:
        blocked_credential = "sk-synthetic123456789"
        request = RequestFactory().post(
            "/api/analysis/jobs/",
            data={
                "session_id": "ses_privacy_rejected",
                "job_id": "job_privacy_rejected",
                "user_text": f"API key is {blocked_credential}",
            },
            content_type="application/json",
        )

        with (
            patch("chatbot.views.get_chat_session_access_metadata", return_value=None),
            patch("chatbot.views.reserve_analysis_job_request") as reserve,
            patch("chatbot.views.record_usage_event") as record_usage,
            patch("chatbot.views.submit_message") as submit_message,
            patch("chatbot.views.enqueue_analysis_job_work") as enqueue,
        ):
            response = analysis_jobs(request)

        self.assertEqual(response.status_code, 400)
        body = json.loads(response.content)
        self.assertEqual(body["error"]["code"], "chat_input_rejected")
        self.assertEqual(body["error"]["required_action"], "remove_sensitive_input")
        self.assertNotIn(blocked_credential, str(body))
        reserve.assert_not_called()
        record_usage.assert_not_called()
        submit_message.assert_not_called()
        enqueue.assert_not_called()

    def test_chat_message_rejects_blocked_input_before_usage_or_queueing(self) -> None:
        blocked_credential = "sk-synthetic123456789"
        request = RequestFactory().post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_chat_privacy_rejected",
                "user_text": f"API key is {blocked_credential}",
            },
            content_type="application/json",
        )

        with (
            patch("chatbot.views._canonical_guest_identity_policy_response", return_value=None),
            patch("chatbot.views.get_chat_session_access_metadata", return_value=None),
            patch("chatbot.views.record_usage_event", return_value={"allowed": True}) as record_usage,
            patch("chatbot.views.submit_message", side_effect=AssertionError("planner must not run")) as submit,
            patch("chatbot.views.enqueue_analysis_job_work") as enqueue,
        ):
            response = submit_chat_message(request)

        self.assertEqual(response.status_code, 400)
        body = json.loads(response.content)
        self.assertEqual(body["error"]["code"], "chat_input_rejected")
        self.assertEqual(body["error"]["required_action"], "remove_sensitive_input")
        self.assertNotIn(blocked_credential, str(body))
        record_usage.assert_not_called()
        submit.assert_not_called()
        enqueue.assert_not_called()

    def test_chat_message_rejects_exact_e2e_identity_input_before_usage_or_queueing(
        self,
    ) -> None:
        raw_resident_id = "900101-1234567"
        raw_driver_license = "11-22-333333-44"
        request = RequestFactory().post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_chat_identity_rejected",
                "user_text": (
                    f"제 주민등록번호는 {raw_resident_id}이고 "
                    f"운전면허번호는 {raw_driver_license}입니다."
                ),
            },
            content_type="application/json",
        )

        with (
            patch("chatbot.views._canonical_guest_identity_policy_response", return_value=None),
            patch("chatbot.views.get_chat_session_access_metadata", return_value=None),
            patch("chatbot.views.record_usage_event", return_value={"allowed": True}) as record_usage,
            patch("chatbot.views.submit_message", side_effect=AssertionError("planner must not run")) as submit,
            patch("chatbot.views.enqueue_analysis_job_work") as enqueue,
        ):
            response = submit_chat_message(request)

        self.assertEqual(response.status_code, 400)
        body = json.loads(response.content)
        self.assertEqual(body["error"]["code"], "chat_input_rejected")
        self.assertEqual(
            body["error"]["privacy_gateway"]["blocked_categories"],
            ["resident_id", "driver_license"],
        )
        self.assertNotIn(raw_resident_id, str(body))
        self.assertNotIn(raw_driver_license, str(body))
        record_usage.assert_not_called()
        submit.assert_not_called()
        enqueue.assert_not_called()

    def test_agent_plan_rejects_blocked_input_before_planning_or_execution(self) -> None:
        blocked_credential = "sk-synthetic123456789"
        request = RequestFactory().post(
            "/api/agent-plan/",
            data={
                "session_id": "ses_agent_plan_privacy_rejected",
                "user_text": f"API key is {blocked_credential}",
            },
            content_type="application/json",
        )

        with (
            patch("chatbot.views.apply_attachment_scan_gate", side_effect=lambda payload: payload),
            patch("chatbot.views.submit_message", side_effect=AssertionError("planner must not run")) as submit,
            patch("chatbot.views.execute_agent_plan") as execute,
            patch("chatbot.views.enqueue_analysis_job_work") as enqueue,
            patch("chatbot.views.persist_analysis_job_execution") as persist,
        ):
            response = run_agent_plan(request)

        self.assertEqual(response.status_code, 400)
        body = json.loads(response.content)
        self.assertEqual(body["error"]["code"], "chat_input_rejected")
        self.assertEqual(body["error"]["required_action"], "remove_sensitive_input")
        self.assertNotIn(blocked_credential, str(body))
        submit.assert_not_called()
        execute.assert_not_called()
        enqueue.assert_not_called()
        persist.assert_not_called()

    def test_agent_plan_returns_scope_guidance_without_execution(self) -> None:
        request = RequestFactory().post(
            "/api/agent-plan/",
            data={
                "session_id": "ses_scope_guidance",
                "user_text": "차가 보행자와 충돌한 사고의 과실을 확정해 주세요.",
            },
            content_type="application/json",
        )

        with (
            patch("chatbot.views.apply_attachment_scan_gate", side_effect=lambda payload: payload),
            patch(
                "chatbot.views.execute_agent_plan",
                return_value={"executions": [], "status_counts": {}},
            ) as execute,
            patch("chatbot.views.enqueue_analysis_job_work") as enqueue,
            patch(
                "chatbot.views.persist_analysis_job_execution",
                return_value={"backend": "postgresql", "status": "saved"},
            ) as persist,
            patch("chatbot.views._record_agent_events_safely") as record_events,
        ):
            response = run_agent_plan(request)

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["execution_mode"], "scope_guidance")
        self.assertEqual(body["chat_response"]["status"], "scope_guidance")
        self.assertEqual(body["analysis_plan"]["steps"], [])
        execute.assert_not_called()
        enqueue.assert_not_called()
        persist.assert_not_called()
        record_events.assert_not_called()

    def test_agent_plan_rejects_out_of_scope_input_when_plan_is_supplied(self) -> None:
        request = RequestFactory().post(
            "/api/agent-plan/",
            data={
                "session_id": "ses_scope_prebuilt_plan",
                "user_text": "차가 보행자와 충돌한 사고의 과실을 확정해 주세요.",
                "analysis_plan": {
                    "plan_id": "plan_scope_prebuilt",
                    "routing_intent": "accident_initial_consultation",
                    "steps": [{"order": 1, "node_code": "law_ground_search"}],
                },
            },
            content_type="application/json",
        )

        with (
            patch("chatbot.views.apply_attachment_scan_gate", side_effect=lambda payload: payload),
            patch(
                "chatbot.views.execute_agent_plan",
                return_value={"executions": [], "status_counts": {}},
            ) as execute,
            patch("chatbot.views.enqueue_analysis_job_work") as enqueue,
            patch(
                "chatbot.views.persist_analysis_job_execution",
                return_value={"backend": "postgresql", "status": "saved"},
            ) as persist,
            patch("chatbot.views._record_agent_events_safely") as record_events,
        ):
            response = run_agent_plan(request)

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["execution_mode"], "scope_guidance")
        self.assertEqual(body["chat_response"]["status"], "scope_guidance")
        self.assertEqual(body["analysis_plan"]["steps"], [])
        execute.assert_not_called()
        enqueue.assert_not_called()
        persist.assert_not_called()
        record_events.assert_not_called()

    def test_analysis_job_post_queues_plan_without_inline_agent_execution(self) -> None:
        chat_response = {
            "contract_version": "chat_message_accepted.v2",
            "session_id": "ses_analysis_queue",
            "message_id": "msg_analysis_queue",
            "routing_intent": "traffic_law_search",
            "status": "queued",
            "progress": {
                "status": "queued",
                "active_node": "law_ground_search",
                "message": "Analysis queued.",
            },
            "analysis_plan": {
                "plan_id": "plan_analysis_queue",
                "routing_intent": "traffic_law_search",
                "steps": [
                    {
                        "order": 1,
                        "node_code": "law_ground_search",
                        "status": "queued",
                    }
                ],
            },
            "attachments": [],
            "blocked_attachments": [],
            "limitations": [],
        }
        queue_result = {
            "backend": "postgresql",
            "status": "queued",
            "execution_mode": "async_worker",
            "job_id": "job_analysis_queue",
            "work_item_id": "work_job_analysis_queue",
            "work_item_status": "queued",
        }
        request = RequestFactory().post(
            "/api/analysis/jobs/",
            data={
                "session_id": "ses_analysis_queue",
                "user_text": "도로교통법 근거를 찾아줘",
            },
            content_type="application/json",
        )

        with (
            patch("chatbot.views.get_chat_session_access_metadata", return_value=None),
            patch(
                "chatbot.views.record_usage_event",
                return_value={"allowed": True},
            ) as record_usage,
            patch("chatbot.views.submit_message", return_value=chat_response),
            patch("chatbot.views.enqueue_analysis_job_work", return_value=queue_result) as enqueue,
            patch(
                "chatbot.views.create_analysis_job",
                side_effect=AssertionError("legacy synchronous job service must not run"),
            ),
            patch(
                "chatbot.views.execute_agent_plan",
                side_effect=AssertionError("agent plan must execute only in the worker"),
            ),
            patch("chatbot.views._record_history_safely"),
            patch("chatbot.views._record_agent_events_safely") as record_agent_events,
        ):
            response = analysis_jobs(request)

        self.assertEqual(response.status_code, 202)
        body = json.loads(response.content)
        job = body["job"]
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["execution_mode"], "async_worker")
        self.assertEqual(job["node_execution"]["executions"], [])
        self.assertEqual(job["work_item"]["work_item_id"], "work_job_analysis_queue")
        self.assertEqual(enqueue.call_args.args[1]["status"], "queued")
        self.assertNotIn("도로교통법 근거를 찾아줘", str(body))
        record_agent_events.assert_not_called()
        record_usage.assert_called_once()

    def test_analysis_job_queue_failures_refund_precharged_usage(self) -> None:
        chat_response = {
            "session_id": "ses_analysis_queue_failure",
            "message_id": "msg_analysis_queue_failure",
            "routing_intent": "traffic_law_search",
            "status": "queued",
            "analysis_plan": {
                "plan_id": "plan_analysis_queue_failure",
                "steps": [
                    {
                        "order": 1,
                        "node_code": "law_ground_search",
                        "status": "queued",
                    }
                ],
            },
            "attachments": [],
            "blocked_attachments": [],
            "limitations": [],
        }
        cases = (
            (PermissionError("owner mismatch"), 403, "analysis_queue_access_denied"),
            (ValueError("job conflict"), 409, "analysis_queue_conflict"),
            (RuntimeError("database unavailable"), 503, "analysis_queue_failed"),
        )

        for queue_error, expected_status, expected_reason in cases:
            with self.subTest(queue_error=queue_error.__class__.__name__):
                request = RequestFactory().post(
                    "/api/analysis/jobs/",
                    data={"session_id": "ses_analysis_queue_failure"},
                    content_type="application/json",
                )
                with (
                    patch("chatbot.views.get_chat_session_access_metadata", return_value=None),
                    patch(
                        "chatbot.views.record_usage_event",
                        return_value={"allowed": True},
                    ),
                    patch("chatbot.views.submit_message", return_value=chat_response),
                    patch(
                        "chatbot.views.enqueue_analysis_job_work",
                        side_effect=queue_error,
                    ),
                    patch("chatbot.views._refund_usage_safely") as refund_usage,
                ):
                    response = analysis_jobs(request)

                self.assertEqual(response.status_code, expected_status)
                refund_usage.assert_called_once_with(
                    {"allowed": True},
                    reason=expected_reason,
                )

    def test_analysis_job_post_rejects_non_executable_plan_without_queueing(self) -> None:
        chat_response = {
            "contract_version": "chat_message_accepted.v2",
            "session_id": "ses_analysis_needs_input",
            "message_id": "msg_analysis_needs_input",
            "routing_intent": "fault_ratio_analysis",
            "status": "needs_input",
            "assistant_message": "추가 사실을 확인해야 분석을 시작할 수 있습니다.",
            "consultation_state": {"required_action": "answer_questions"},
            "case_status": "awaiting_fact_confirmation",
            "progress": {
                "status": "needs_input",
                "active_node": "input_context_validation",
                "message": "More input is required.",
            },
            "analysis_plan": {
                "plan_id": "plan_analysis_needs_input",
                "routing_intent": "fault_ratio_analysis",
                "steps": [],
            },
            "pending_questions": [{"field": "accident_description"}],
            "attachments": [],
            "blocked_attachments": [],
            "limitations": [],
        }
        request = RequestFactory().post(
            "/api/analysis/jobs/",
            data={
                "session_id": "ses_analysis_needs_input",
                "user_text": "과실비율 알려줘",
            },
            content_type="application/json",
        )

        with (
            patch("chatbot.views.get_chat_session_access_metadata", return_value=None),
            patch(
                "chatbot.views.record_usage_event",
                return_value={"allowed": True},
            ) as record_usage,
            patch("chatbot.views.submit_message", return_value=chat_response),
            patch("chatbot.views.enqueue_analysis_job_work") as enqueue,
            patch("chatbot.views._refund_usage_safely") as refund_usage,
            patch("chatbot.views._record_history_safely"),
        ):
            response = analysis_jobs(request)

        self.assertEqual(response.status_code, 409)
        body = json.loads(response.content)
        self.assertEqual(body["error"]["code"], "analysis_plan_not_executable")
        self.assertEqual(body["analysis"]["status"], "needs_input")
        self.assertEqual(
            body["analysis"]["assistant_message"],
            "추가 사실을 확인해야 분석을 시작할 수 있습니다.",
        )
        self.assertEqual(
            body["analysis"]["consultation_state"],
            {"required_action": "answer_questions"},
        )
        self.assertEqual(body["analysis"]["case_status"], "awaiting_fact_confirmation")
        self.assertEqual(body["analysis"]["pending_questions"], [{"field": "accident_description"}])
        enqueue.assert_not_called()
        record_usage.assert_called_once()
        refund_usage.assert_called_once_with(
            {"allowed": True},
            reason="analysis_plan_not_executable",
        )

    def test_analysis_job_post_does_not_queue_scan_blocked_attachments(self) -> None:
        chat_response = {
            **{
                "contract_version": "chat_message_accepted.v2",
                "session_id": "ses_analysis_scan_blocked",
                "message_id": "msg_analysis_scan_blocked",
                "routing_intent": "traffic_law_search",
                "status": "queued",
                "progress": {"status": "queued", "active_node": "law_ground_search"},
                "analysis_plan": {
                    "plan_id": "plan_analysis_scan_blocked",
                    "steps": [{"order": 1, "node_code": "law_ground_search"}],
                },
                "attachments": [],
                "limitations": [],
            },
            "blocked_attachments": [
                {
                    "attachment_id": "att_waiting_scan",
                    "required_action": "wait_for_file_scan",
                }
            ],
        }
        request = RequestFactory().post(
            "/api/analysis/jobs/",
            data={"session_id": "ses_analysis_scan_blocked"},
            content_type="application/json",
        )

        with (
            patch("chatbot.views.get_chat_session_access_metadata", return_value=None),
            patch(
                "chatbot.views.apply_attachment_scan_gate",
                side_effect=lambda payload: {
                    **payload,
                    "attachments": [],
                    "blocked_attachments": chat_response["blocked_attachments"],
                },
            ),
            patch("chatbot.views.record_usage_event") as record_usage,
            patch("chatbot.views.submit_message") as submit_message,
            patch("chatbot.views.enqueue_analysis_job_work") as enqueue,
            patch("chatbot.views._record_history_safely"),
        ):
            response = analysis_jobs(request)

        self.assertEqual(response.status_code, 409)
        body = json.loads(response.content)
        self.assertEqual(body["error"]["code"], "attachment_scan_blocked")
        self.assertEqual(body["analysis"]["scan_gate"]["worker_action"], "not_queued")
        submit_message.assert_not_called()
        enqueue.assert_not_called()
        record_usage.assert_not_called()

    def test_analysis_job_post_rejects_plan_with_only_blocked_steps(self) -> None:
        chat_response = {
            "session_id": "ses_analysis_plan_blocked",
            "message_id": "msg_analysis_plan_blocked",
            "routing_intent": "traffic_law_search",
            "status": "queued",
            "progress": {"status": "queued", "active_node": "law_ground_search"},
            "analysis_plan": {
                "plan_id": "plan_analysis_plan_blocked",
                "steps": [
                    {
                        "order": 1,
                        "node_code": "law_ground_search",
                        "status": "blocked",
                    }
                ],
            },
            "attachments": [],
            "blocked_attachments": [],
            "limitations": [],
        }
        request = RequestFactory().post(
            "/api/analysis/jobs/",
            data={"session_id": "ses_analysis_plan_blocked"},
            content_type="application/json",
        )

        with (
            patch("chatbot.views.get_chat_session_access_metadata", return_value=None),
            patch(
                "chatbot.views.record_usage_event",
                return_value={"allowed": True},
            ) as record_usage,
            patch("chatbot.views.submit_message", return_value=chat_response),
            patch("chatbot.views.enqueue_analysis_job_work") as enqueue,
            patch("chatbot.views._refund_usage_safely") as refund_usage,
        ):
            response = analysis_jobs(request)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "analysis_plan_not_executable",
        )
        enqueue.assert_not_called()
        record_usage.assert_called_once()
        refund_usage.assert_called_once_with(
            {"allowed": True},
            reason="analysis_plan_not_executable",
        )

    @patch("chatbot.views.get_analysis_job_access_metadata", return_value=None)
    @patch("chatbot.views.get_analysis_job_record")
    def test_analysis_result_uses_persisted_agent_outputs(
        self,
        get_job,
        _get_access_metadata,
    ) -> None:
        get_job.return_value = {
            "job_id": "job_1",
            "status": "partial",
            "status_counts": {"success": 1, "partial": 1},
            "agent_results": [
                {
                    "node_code": "text_ml_case_search",
                    "status": "success",
                    "summary": "유사 사례를 찾았습니다.",
                    "structured_result": {"ratio": "70:30"},
                    "evidence": [{"source_reference": "review:1"}],
                    "limitations": [],
                },
                {
                    "node_code": "law_ground_search",
                    "status": "partial",
                    "summary": "법령 후보를 확인했습니다.",
                    "structured_result": {},
                    "evidence": [],
                    "limitations": ["추가 확인 필요"],
                },
            ],
            "cards": [{"card_type": "law", "title": "법령 근거"}],
            "pending_questions": [{"field": "evidence", "question": "자료가 더 있나요?"}],
            "reporting_payload": {"report_type": "initial_consultation"},
            "supervisor_state": {"status": "completed"},
            "work_item": {"work_item_id": "work_1", "status": "success"},
            "progress_state": {"state": "success"},
        }
        request = RequestFactory().get("/api/analysis/results/job_1/")

        response = analysis_result(request, "job_1")

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)["result"]
        self.assertEqual(body["status"], "partial")
        self.assertEqual(
            body["assistant_message"]["answer"],
            "유사 사례를 찾았습니다.\n\n법령 후보를 확인했습니다.",
        )
        self.assertEqual(body["cards"][0]["title"], "법령 근거")
        self.assertEqual(body["pending_questions"][0]["field"], "evidence")
        self.assertEqual(body["reporting_payload"]["report_type"], "initial_consultation")
        self.assertEqual(body["work_item"]["status"], "success")
        self.assertEqual(body["progress_state"]["state"], "success")
        self.assertNotIn("mock", str(body).lower())

    @patch("chatbot.views._canonical_guest_identity_policy_response", return_value=None)
    @patch("chatbot.views._get_current_auth_subject")
    @patch("chatbot.views.get_chat_session_access_metadata")
    @patch("chatbot.views.get_analysis_job_access_metadata")
    @patch("chatbot.views.get_analysis_job_record")
    def test_guest_can_poll_its_own_queued_analysis_result(
        self,
        get_job,
        get_access_metadata,
        get_session_access,
        get_auth_subject,
        _guest_policy,
    ) -> None:
        get_job.return_value = {
            "job_id": "job_guest_owned",
            "session_id": "ses_guest_owned",
            "status": "queued",
        }
        get_access_metadata.return_value = {
            "type": "analysis_job",
            "job_id": "job_guest_owned",
            "owner_id": "",
            "session_id": "ses_guest_owned",
        }
        get_session_access.return_value = {
            "type": "chat_session",
            "session_id": "ses_guest_owned",
            "owner_id": "",
            "guest_id": "gst_owner",
        }
        get_auth_subject.return_value = (
            200,
            {
                "subject": {
                    "subject_type": "guest",
                    "subject_id": "guest:gst_owner",
                    "guest_id": "gst_owner",
                }
            },
        )

        response = self.client.get(
            "/api/analysis/results/job_guest_owned/",
            HTTP_X_GUEST_ID="gst_owner",
            HTTP_X_GUEST_CREDENTIAL=issue_guest_credential("gst_owner")[0],
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["result"]["status"], "queued")

    @patch("chatbot.views._canonical_guest_identity_policy_response", return_value=None)
    @patch("chatbot.views._get_current_auth_subject")
    @patch("chatbot.views.get_chat_session_access_metadata")
    @patch("chatbot.views.get_analysis_job_access_metadata")
    @patch("chatbot.views.get_analysis_job_record")
    def test_guest_cannot_poll_another_guests_analysis_result(
        self,
        get_job,
        get_access_metadata,
        get_session_access,
        get_auth_subject,
        _guest_policy,
    ) -> None:
        get_job.return_value = {
            "job_id": "job_guest_owned",
            "session_id": "ses_guest_owned",
            "status": "queued",
        }
        get_access_metadata.return_value = {
            "type": "analysis_job",
            "job_id": "job_guest_owned",
            "owner_id": "",
            "session_id": "ses_guest_owned",
        }
        get_session_access.return_value = {
            "type": "chat_session",
            "session_id": "ses_guest_owned",
            "owner_id": "",
            "guest_id": "gst_owner",
        }
        get_auth_subject.return_value = (
            200,
            {
                "subject": {
                    "subject_type": "guest",
                    "subject_id": "guest:gst_other",
                    "guest_id": "gst_other",
                }
            },
        )

        response = self.client.get(
            "/api/analysis/results/job_guest_owned/",
            HTTP_X_GUEST_ID="gst_other",
            HTTP_X_GUEST_CREDENTIAL=issue_guest_credential("gst_other")[0],
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "object_access_denied")
        self.assertEqual(response.json()["error"]["access"]["reason"], "guest_mismatch")


class RuntimeHealthTests(SimpleTestCase):
    def test_runtime_is_ready_only_when_database_and_cache_probes_pass(self) -> None:
        ready = build_runtime_health(database_probe=lambda: None, cache_probe=lambda: None)

        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["checks"], {"database": "ready", "cache": "ready"})

    def test_runtime_reports_probe_exception_without_exposing_details(self) -> None:
        def unavailable_cache() -> None:
            raise ConnectionError("redis://user:secret@example.internal")

        result = build_runtime_health(
            database_probe=lambda: None,
            cache_probe=unavailable_cache,
        )

        self.assertEqual(result["status"], "not_ready")
        self.assertEqual(result["checks"]["cache"], "unavailable")
        self.assertNotIn("secret", str(result).lower())


class FileScanWorkerCommandTests(SimpleTestCase):
    @patch("chatbot.management.commands.process_uploaded_file_scans.purge_expired_uploads")
    @patch("chatbot.management.commands.process_uploaded_file_scans.time.sleep")
    @patch("chatbot.management.commands.process_uploaded_file_scans.process_uploaded_file_scans")
    def test_scan_worker_can_poll_until_max_loops(
        self,
        process_scans,
        sleep,
        purge_expired,
    ) -> None:
        process_scans.return_value = {
            "status": "success",
            "processed": 0,
            "clean": 0,
            "rejected": 0,
            "results": [],
        }
        purge_expired.return_value = {
            "status": "pass",
            "dry_run": False,
            "selected": 0,
            "purged": 0,
            "retryable": 0,
            "skipped": 0,
        }
        output = StringIO()

        call_command(
            "process_uploaded_file_scans",
            "--loop",
            "--max-loops",
            "2",
            "--sleep-seconds",
            "1",
            "--format",
            "json",
            stdout=output,
        )

        self.assertEqual(process_scans.call_count, 2)
        self.assertEqual(purge_expired.call_count, 2)
        sleep.assert_called_once_with(1)
