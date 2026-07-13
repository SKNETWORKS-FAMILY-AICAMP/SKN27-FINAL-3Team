from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase
from django.urls import Resolver404, resolve

from chatbot.api_response import json_response
from chatbot.models import ReportType
from chatbot.runtime_health import build_runtime_health
from chatbot.views import analysis_result, submit_chat_message


class ProductionApiContractTests(SimpleTestCase):
    def test_canonical_json_response_does_not_inject_runtime_mode_fields(self) -> None:
        request = RequestFactory().get("/api/capabilities/")

        response = json_response(request, {"status": "ready"})

        self.assertJSONEqual(response.content, {"status": "ready"})

    def test_liveness_endpoint_is_public_and_process_only(self) -> None:
        response = self.client.get("/api/health/live/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "live")

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

        response = submit_chat_message(request)

        self.assertEqual(response.status_code, 202)
        body = json.loads(response.content)
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["execution_mode"], "async_worker")
        self.assertEqual(body["work_item"]["work_item_id"], "work_1")
        self.assertNotIn("mock", str(body).lower())
        queued_payload = enqueue.call_args.args[1]
        self.assertEqual(
            [step["node_code"] for step in queued_payload["analysis_plan"]["steps"]],
            ["law_ground_search"],
        )

    @patch("chatbot.views.get_analysis_job_record")
    def test_analysis_result_uses_persisted_agent_outputs(self, get_job) -> None:
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
    @patch("chatbot.views.get_analysis_job_record")
    def test_guest_can_poll_its_own_queued_analysis_result(
        self,
        get_job,
        get_session_access,
        get_auth_subject,
        _guest_policy,
    ) -> None:
        get_job.return_value = {
            "job_id": "job_guest_owned",
            "session_id": "ses_guest_owned",
            "status": "queued",
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
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["result"]["status"], "queued")

    @patch("chatbot.views._canonical_guest_identity_policy_response", return_value=None)
    @patch("chatbot.views._get_current_auth_subject")
    @patch("chatbot.views.get_chat_session_access_metadata")
    @patch("chatbot.views.get_analysis_job_record")
    def test_guest_cannot_poll_another_guests_analysis_result(
        self,
        get_job,
        get_session_access,
        get_auth_subject,
        _guest_policy,
    ) -> None:
        get_job.return_value = {
            "job_id": "job_guest_owned",
            "session_id": "ses_guest_owned",
            "status": "queued",
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
    @patch("chatbot.management.commands.process_uploaded_file_scans.time.sleep")
    @patch("chatbot.management.commands.process_uploaded_file_scans.process_uploaded_file_scans")
    def test_scan_worker_can_poll_until_max_loops(self, process_scans, sleep) -> None:
        process_scans.return_value = {
            "status": "success",
            "processed": 0,
            "clean": 0,
            "rejected": 0,
            "results": [],
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
        sleep.assert_called_once_with(1)
