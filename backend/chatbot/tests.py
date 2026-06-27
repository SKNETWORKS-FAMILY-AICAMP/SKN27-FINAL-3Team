from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase


class ChatbotMockApiTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_AUTHORIZATION="Bearer dev-mock-token")

    def test_health_check_returns_scenarios(self):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(
            {item["scenario"] for item in body["available_scenarios"]},
            {"fine_notice", "fault_ratio"},
        )

    def test_cors_preflight_allows_authorization_header_for_mock_jwt_flow(self):
        response = self.client.options(
            "/api/mock/chat/messages/",
            HTTP_ORIGIN="http://localhost:5173",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="Content-Type, Authorization",
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertIn("Authorization", response["Access-Control-Allow-Headers"])

    def test_public_mock_endpoints_do_not_require_authorization_header(self):
        public_client = Client()

        health_response = public_client.get("/api/health/")
        scenarios_response = public_client.get("/api/mock/chat/scenarios/")

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(scenarios_response.status_code, 200)

    def test_protected_mock_endpoint_requires_authorization_header(self):
        response = Client().post(
            "/api/mock/chat/messages/",
            data={"session_id": "ses_missing_auth", "user_text": "hello"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        error = response.json()["error"]
        self.assertEqual(error["code"], "auth_required")
        self.assertEqual(error["status"], 401)
        self.assertEqual(error["required_action"], "login")
        self.assertEqual(error["auth"]["scheme"], "Bearer")
        self.assertEqual(error["auth"]["reason"], "missing_token")

    def test_protected_canonical_endpoint_requires_authorization_header(self):
        response = Client().post(
            "/api/chat/messages/",
            data={"session_id": "ses_missing_auth", "user_text": "hello"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        error = response.json()["error"]
        self.assertEqual(error["code"], "auth_required")
        self.assertEqual(error["auth"]["reason"], "missing_token")

    def test_protected_mock_endpoint_rejects_expired_mock_token(self):
        response = Client(HTTP_AUTHORIZATION="Bearer expired").post(
            "/api/mock/chat/messages/",
            data={"session_id": "ses_expired_auth", "user_text": "hello"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        error = response.json()["error"]
        self.assertEqual(error["code"], "token_expired")
        self.assertEqual(error["auth"]["reason"], "expired_token")

    def test_submit_fine_notice_message(self):
        session_response = self.client.post(
            "/api/mock/chat/sessions/",
            data={"user_id": "usr_mock"},
            content_type="application/json",
        )
        session_id = session_response.json()["session_id"]

        response = self.client.post(
            "/api/mock/chat/messages/",
            data={
                "session_id": session_id,
                "user_text": "이 고지서로 이의신청서를 만들 수 있을까요?",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["mock_scenario"], "fine_notice")
        self.assertEqual(body["routing_intent"], "objection_request")
        self.assertIn("analysis_plan", body)
        self.assertIn("fine_notice_analysis", {step["node_code"] for step in body["analysis_plan"]["steps"]})
        self.assertIn("report_links", body)

    def test_submit_fault_ratio_message(self):
        response = self.client.post(
            "/api/mock/chat/messages/",
            data={
                "session_id": "ses_fault",
                "user_text": "신호 없는 교차로 사고 과실비율을 확인하고 싶어요.",
                "mock_scenario": "fault_ratio",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["routing_intent"], "fault_ratio")
        self.assertEqual(body["analysis_plan"]["steps"][1]["node_code"], "text_ml_case_search")
        self.assertIn("structured_result", body)
        self.assertIn("similar_cases", body["structured_result"])

    def test_canonical_chat_message_endpoint_reuses_mock_service(self):
        response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_canonical_chat",
                "user_text": "이 고지서로 이의신청서를 만들 수 있을까요?",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["api_surface"], "canonical_mock")
        self.assertEqual(body["execution_mode"], "mock")
        self.assertEqual(body["mock_scenario"], "fine_notice")
        self.assertIn("analysis_plan", body)
        self.assertIn(
            "/api/reports",
            {link["endpoint"] for link in body["report_links"]},
        )

    def test_agent_nodes_endpoint_returns_registry(self):
        response = self.client.get("/api/mock/agents/nodes/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        node_codes = {node["node_code"] for node in body["nodes"]}
        self.assertIn("fine_notice_analysis", node_codes)
        self.assertIn("vision_media_analysis", node_codes)
        fine_notice_node = next(
            node for node in body["nodes"] if node["node_code"] == "fine_notice_analysis"
        )
        self.assertEqual(
            fine_notice_node["adapter_contract"]["function_name"],
            "run_fine_notice_analysis",
        )
        self.assertIn(
            "structured_result",
            fine_notice_node["adapter_contract"]["required_output_fields"],
        )

    def test_canonical_agent_nodes_endpoint_marks_canonical_mock_surface(self):
        response = self.client.get("/api/agents/nodes/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["api_surface"], "canonical_mock")
        self.assertEqual(body["execution_mode"], "mock")
        self.assertIn(
            "fine_notice_analysis",
            {node["node_code"] for node in body["nodes"]},
        )

    def test_agent_node_run_endpoint_returns_envelope(self):
        response = self.client.post(
            "/api/mock/agents/nodes/run/",
            data={
                "node_code": "law_ground_search",
                "user_text": "고지서 관련 법률 근거 확인",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["agent_output"]["node_code"], "law_ground_search")
        self.assertEqual(body["agent_output"]["status"], "success")
        self.assertEqual(body["agent_output"]["evidence"][0]["source_type"], "law")

    def test_agent_plan_run_endpoint_builds_plan_and_executes_nodes(self):
        response = self.client.post(
            "/api/mock/agents/plans/run/",
            data={
                "session_id": "ses_plan",
                "user_text": "이 고지서로 이의신청서를 만들 수 있을까요?",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("analysis_plan", body)
        self.assertIn("node_execution", body)
        self.assertEqual(
            len(body["node_execution"]["executions"]),
            len(body["analysis_plan"]["steps"]),
        )
        self.assertIn(
            "objection_report_generation",
            {
                item["agent_output"]["node_code"]
                for item in body["node_execution"]["executions"]
            },
        )

    def test_attachment_upload_endpoint_returns_metadata_and_handoff(self):
        upload = SimpleUploadedFile(
            "fine_notice.jpg",
            b"mock image",
            content_type="image/jpeg",
        )

        response = self.client.post(
            "/api/mock/attachments/",
            data={
                "session_id": "ses_upload_api",
                "purpose": "fine_notice",
                "file": upload,
            },
        )

        self.assertEqual(response.status_code, 200)
        attachment = response.json()["attachment"]
        self.assertEqual(attachment["purpose"], "fine_notice")
        self.assertEqual(attachment["type"], "image")
        self.assertEqual(attachment["status"], "uploaded")
        self.assertEqual(attachment["agent_handoff"]["attachment_id"], attachment["attachment_id"])

        detail = self.client.get(f"/api/mock/attachments/{attachment['attachment_id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["attachment"]["attachment_id"], attachment["attachment_id"])

    def test_canonical_files_endpoint_reuses_attachment_metadata_service(self):
        response = self.client.post(
            "/api/files/",
            data={
                "session_id": "ses_canonical_files",
                "purpose": "fine_notice",
                "filename": "notice.jpg",
                "content_type": "image/jpeg",
                "size_bytes": 2048,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        attachment = body["attachment"]
        self.assertEqual(body["api_surface"], "canonical_mock")
        self.assertEqual(attachment["purpose"], "fine_notice")

        detail = self.client.get(f"/api/files/{attachment['attachment_id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["api_surface"], "canonical_mock")

    def test_attachment_list_endpoint_filters_by_session(self):
        response = self.client.post(
            "/api/mock/attachments/",
            data={
                "session_id": "ses_meta_api",
                "purpose": "accident_statement",
                "filename": "accident_statement.pdf",
                "content_type": "application/pdf",
                "size_bytes": 1204,
            },
            content_type="application/json",
        )
        attachment_id = response.json()["attachment"]["attachment_id"]

        list_response = self.client.get("/api/mock/attachments/?session_id=ses_meta_api")

        self.assertEqual(list_response.status_code, 200)
        self.assertIn(
            attachment_id,
            {item["attachment_id"] for item in list_response.json()["attachments"]},
        )

    def test_chat_message_resolves_attachment_id_from_upload_metadata(self):
        upload_response = self.client.post(
            "/api/mock/attachments/",
            data={
                "session_id": "ses_chat_attachment",
                "purpose": "fine_notice",
                "filename": "notice.jpg",
                "content_type": "image/jpeg",
                "size_bytes": 2048,
            },
            content_type="application/json",
        )
        attachment_id = upload_response.json()["attachment"]["attachment_id"]

        response = self.client.post(
            "/api/mock/chat/messages/",
            data={
                "session_id": "ses_chat_attachment",
                "user_text": "이 고지서로 이의신청서를 만들 수 있을까요?",
                "attachments": [{"attachment_id": attachment_id}],
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["attachments"][0]["purpose"], "fine_notice")
        self.assertIn("image", body["analysis_plan"]["input_summary"]["modalities"])
        self.assertEqual(
            body["attachment_resolution"]["resolved_attachment_ids"],
            [attachment_id],
        )

    def test_agent_plan_run_resolves_attachment_id_for_node_handoff(self):
        upload_response = self.client.post(
            "/api/mock/attachments/",
            data={
                "session_id": "ses_plan_attachment",
                "purpose": "accident_statement",
                "filename": "accident_statement.pdf",
                "content_type": "application/pdf",
                "size_bytes": 1204,
            },
            content_type="application/json",
        )
        attachment_id = upload_response.json()["attachment"]["attachment_id"]

        response = self.client.post(
            "/api/mock/agents/plans/run/",
            data={
                "session_id": "ses_plan_attachment",
                "user_text": "사고경위서 기반으로 과실비율 봐줘",
                "attachments": [{"attachment_id": attachment_id}],
                "mock_scenario": "fault_ratio",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["analysis_plan"]["input_summary"]["attachment_purposes"],
            ["accident_statement"],
        )
        first_agent_input = body["node_execution"]["executions"][0]["agent_input"]
        self.assertEqual(first_agent_input["attachments"][0]["purpose"], "accident_statement")
        self.assertEqual(first_agent_input["attachments"][0]["type"], "pdf")

    def test_analysis_job_endpoint_creates_and_returns_job_detail(self):
        upload_response = self.client.post(
            "/api/mock/attachments/",
            data={
                "session_id": "ses_job_api",
                "purpose": "fine_notice",
                "filename": "notice.jpg",
                "content_type": "image/jpeg",
                "size_bytes": 2048,
            },
            content_type="application/json",
        )
        attachment_id = upload_response.json()["attachment"]["attachment_id"]

        response = self.client.post(
            "/api/mock/analysis/jobs/",
            data={
                "session_id": "ses_job_api",
                "user_text": "이 고지서로 이의신청서를 만들 수 있을까요?",
                "attachments": [{"attachment_id": attachment_id}],
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        job = response.json()["job"]
        self.assertEqual(job["status"], "success")
        self.assertEqual(job["analysis_plan"]["input_summary"]["attachment_purposes"], ["fine_notice"])
        self.assertEqual(job["node_execution"]["job_id"], job["job_id"])

        detail = self.client.get(f"/api/mock/analysis/jobs/{job['job_id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["job"]["job_id"], job["job_id"])

    def test_canonical_analysis_jobs_endpoint_reuses_mock_job_service(self):
        response = self.client.post(
            "/api/analysis/jobs/",
            data={
                "session_id": "ses_canonical_job",
                "user_text": "이 고지서로 이의신청서를 만들 수 있을까요?",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        job = body["job"]
        self.assertEqual(body["api_surface"], "canonical_mock")
        self.assertEqual(body["execution_mode"], "mock")
        self.assertEqual(job["status"], "success")
        self.assertIn(
            "/api/reports",
            {link["endpoint"] for link in job["chat_response"]["report_links"]},
        )

        detail = self.client.get(f"/api/analysis/jobs/{job['job_id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["api_surface"], "canonical_mock")

    def test_analysis_job_list_endpoint_filters_by_session(self):
        response = self.client.post(
            "/api/mock/analysis/jobs/",
            data={
                "session_id": "ses_job_list",
                "user_text": "사고 과실비율 봐줘",
                "mock_scenario": "fault_ratio",
                "mock_status": "partial",
            },
            content_type="application/json",
        )
        job_id = response.json()["job"]["job_id"]

        list_response = self.client.get("/api/mock/analysis/jobs/?session_id=ses_job_list")

        self.assertEqual(list_response.status_code, 200)
        self.assertIn(job_id, {job["job_id"] for job in list_response.json()["jobs"]})
        self.assertIn("status", list_response.json()["jobs"][0])

    def test_report_download_returns_attachment(self):
        response = self.client.get("/api/mock/reports/rep_mock/download/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])

    def test_canonical_report_download_marks_canonical_mock_surface(self):
        response = self.client.get("/api/reports/rep_mock/download/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-API-Surface"], "canonical_mock")
        self.assertEqual(response["X-Execution-Mode"], "mock")

