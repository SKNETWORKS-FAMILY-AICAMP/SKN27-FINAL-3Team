import json
import os
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from chatbot.models import (
    AgentFeedbackEvent,
    AgentInvocation,
    AgentInvocationStatus,
    AgentNodeDefinition,
    AgentResult,
    AgentResultStatus,
    AnalysisDisplayResult,
    AnalysisJob,
    AnalysisJobEvent,
    AnalysisJobStatus,
    AuthSession,
    AuthSessionStatus,
    ChatMessage,
    ChatSession,
    ChatSessionStatus,
    CodeGroup,
    CodeItem,
    GuestIdentity,
    GuestIdentityStatus,
    AiSession,
    MessageRole,
    Report,
    ReportStatus,
    ReportType,
    Subscription,
    SubscriptionStatus,
    UsageEvent,
    UsageQuota,
    UserAccount,
    UserAccountStatus,
    UploadedFile,
    UploadedFileStatus,
)


class ChatbotPersistenceModelTests(TestCase):
    def test_storage_foundation_uses_postgresql_erd_table_names(self):
        self.assertEqual(ChatSession._meta.db_table, "chat_sessions")
        self.assertEqual(ChatMessage._meta.db_table, "chat_messages")
        self.assertEqual(UploadedFile._meta.db_table, "uploaded_files")
        self.assertEqual(AnalysisJob._meta.db_table, "analysis_jobs")
        self.assertEqual(AnalysisJobEvent._meta.db_table, "analysis_job_events")
        self.assertEqual(AgentResult._meta.db_table, "agent_results")
        self.assertEqual(AnalysisDisplayResult._meta.db_table, "analysis_display_results")
        self.assertEqual(Report._meta.db_table, "reports")
        self.assertEqual(UserAccount._meta.db_table, "users")
        self.assertEqual(GuestIdentity._meta.db_table, "guest_identities")
        self.assertEqual(AuthSession._meta.db_table, "auth_sessions")
        self.assertEqual(CodeGroup._meta.db_table, "code_groups")
        self.assertEqual(CodeItem._meta.db_table, "code_items")
        self.assertEqual(AgentNodeDefinition._meta.db_table, "agent_nodes")
        self.assertEqual(AiSession._meta.db_table, "ai_sessions")
        self.assertEqual(AgentInvocation._meta.db_table, "agent_invocations")
        self.assertEqual(AgentFeedbackEvent._meta.db_table, "agent_feedback_events")
        self.assertEqual(Subscription._meta.db_table, "subscriptions")
        self.assertEqual(UsageQuota._meta.db_table, "usage_quotas")
        self.assertEqual(UsageEvent._meta.db_table, "usage_events")

    def test_auth_agent_code_and_quota_tables_link_without_replacing_mvp_backbone(self):
        user = UserAccount.objects.create(
            user_id="usr_identity_foundation",
            email="tester@example.com",
            display_name="테스터",
            status=UserAccountStatus.ACTIVE,
        )
        guest = GuestIdentity.objects.create(
            guest_id="gst_identity_foundation",
            status=GuestIdentityStatus.ACTIVE,
        )
        auth_session = AuthSession.objects.create(
            auth_session_id="auth_identity_foundation",
            user=user,
            guest=guest,
            subject_type="user",
            subject_id=f"user:{user.user_id}",
            status=AuthSessionStatus.ACTIVE,
        )
        code_group = CodeGroup.objects.create(
            group_code="agent_status",
            name="Agent 상태",
        )
        code_item = CodeItem.objects.create(
            group=code_group,
            code="success",
            label="성공",
            sort_order=10,
        )
        subscription = Subscription.objects.create(
            subscription_id="sub_identity_foundation",
            user=user,
            plan_code="free",
            status=SubscriptionStatus.FREE,
        )
        quota = UsageQuota.objects.create(
            quota_id="quota_identity_foundation",
            subject_id=f"user:{user.user_id}",
            scope="agent_run",
            limit_count=10,
            used_count=1,
        )
        usage = UsageEvent.objects.create(
            usage_event_id="use_identity_foundation",
            subject_id=f"user:{user.user_id}",
            scope="agent_run",
            quota_key=f"rate_limit:user:{user.user_id}:agent_run",
        )

        session = ChatSession.objects.create(
            session_id="ses_identity_foundation",
            owner_id=user.user_id,
            status=ChatSessionStatus.ACTIVE,
        )
        job = AnalysisJob.objects.create(
            job_id="job_identity_foundation",
            session=session,
            owner_id=user.user_id,
            routing_intent="fault_ratio",
            status=AnalysisJobStatus.RUNNING,
        )
        agent_node = AgentNodeDefinition.objects.create(
            node_code="text_ml_case_search",
            node_name="텍스트 ML/사례 검색",
            status="active",
            owner="leejaegang27",
            contract_version="agent_adapter.v1",
        )
        ai_session = AiSession.objects.create(
            ai_session_id="ais_identity_foundation",
            session=session,
            user=user,
            guest=guest,
            owner_id=user.user_id,
            status="active",
            routing_intent="fault_ratio",
            quota_key=f"rate_limit:user:{user.user_id}:agent_run",
        )
        invocation = AgentInvocation.objects.create(
            invocation_id="ainv_identity_foundation",
            ai_session=ai_session,
            job=job,
            agent_node=agent_node,
            node_code=agent_node.node_code,
            status=AgentInvocationStatus.SUCCESS,
            execution_mode="mock",
            evidence_count=1,
            limitation_count=0,
        )
        agent_result = AgentResult.objects.create(
            result_id="res_identity_foundation",
            job=job,
            node_code=agent_node.node_code,
            node_name=agent_node.node_name,
            status=AgentResultStatus.SUCCESS,
            summary="계약 테이블 연결 확인용 결과입니다.",
        )
        feedback = AgentFeedbackEvent.objects.create(
            feedback_id="afb_identity_foundation",
            invocation=invocation,
            agent_result=agent_result,
            feedback_type="useful",
            rating=5,
        )

        self.assertEqual(auth_session.user, user)
        self.assertEqual(code_item.group, code_group)
        self.assertEqual(subscription.user, user)
        self.assertEqual(quota.subject_id, f"user:{user.user_id}")
        self.assertEqual(usage.scope, "agent_run")
        self.assertEqual(invocation.ai_session, ai_session)
        self.assertEqual(invocation.agent_node, agent_node)
        self.assertEqual(feedback.agent_result, agent_result)

    def test_storage_foundation_links_session_files_jobs_results_and_reports(self):
        session = ChatSession.objects.create(
            session_id="ses_db_foundation",
            owner_id="usr_db",
            title="Storage foundation",
            status=ChatSessionStatus.ACTIVE,
            current_intent="objection_request",
        )
        message = ChatMessage.objects.create(
            message_id="msg_db_foundation",
            session=session,
            role=MessageRole.USER,
            content="Prepare an objection draft.",
            routing_intent="objection_request",
        )
        upload = UploadedFile.objects.create(
            attachment_id="att_db_foundation",
            owner_id="usr_db",
            session=session,
            purpose="fine_notice",
            file_type="image",
            original_filename="notice.jpg",
            content_type="image/jpeg",
            size_bytes=2048,
            storage_uri="s3://mock-bucket/uploads/usr_db/ses_db_foundation/notice.jpg",
            status=UploadedFileStatus.READY,
            agent_handoff={"attachment_id": "att_db_foundation", "purpose": "fine_notice"},
        )
        job = AnalysisJob.objects.create(
            job_id="job_db_foundation",
            session=session,
            message=message,
            owner_id="usr_db",
            routing_intent="objection_request",
            status=AnalysisJobStatus.RUNNING,
            active_node="fine_notice_analysis",
            progress_message="Analyzing fine notice.",
            analysis_plan_id="plan_db_foundation",
            status_counts={"success": 1, "partial": 0, "failed": 0},
        )
        event = AnalysisJobEvent.objects.create(
            job=job,
            status=AnalysisJobStatus.RUNNING,
            active_node="fine_notice_analysis",
            message="Fine notice analysis started.",
        )
        agent_result = AgentResult.objects.create(
            result_id="res_agent_db_foundation",
            job=job,
            node_code="fine_notice_analysis",
            node_name="Fine notice analysis",
            status=AgentResultStatus.SUCCESS,
            summary="Fine notice fields extracted.",
            structured_result={"notice_type": "traffic_fine_notice"},
            evidence=[
                {
                    "source_type": "user_uploaded_file",
                    "source_reference": upload.attachment_id,
                }
            ],
            next_actions=["Generate objection draft"],
            limitations=["Mock persistence foundation sample."],
        )
        display_result = AnalysisDisplayResult.objects.create(
            display_result_id="disp_db_foundation",
            job=job,
            assistant_message={
                "answer": "Fine notice analysis is ready.",
                "limitations": [],
            },
            progress=[{"node_code": "fine_notice_analysis", "status": "done"}],
            cards=[{"card_type": "fine_notice", "title": "Fine notice"}],
            attachments=[{"attachment_id": upload.attachment_id, "purpose": upload.purpose}],
            report_links=[{"action": "download", "endpoint": "/api/reports/rep_db/download/"}],
        )
        report = Report.objects.create(
            report_id="rep_db_foundation",
            owner_id="usr_db",
            session=session,
            job=job,
            display_result=display_result,
            report_type=ReportType.OBJECTION_DRAFT,
            status=ReportStatus.READY,
            title="Objection draft",
            storage_uri="s3://mock-bucket/reports/usr_db/rep_db_foundation.txt",
            content_summary="Draft generated from fine notice analysis.",
            content={"format": "text"},
        )

        self.assertEqual(str(session), "ses_db_foundation")
        self.assertEqual(str(event), "job_db_foundation:running")
        self.assertEqual(session.messages.get(), message)
        self.assertEqual(session.uploaded_files.get(), upload)
        self.assertEqual(session.analysis_jobs.get(), job)
        self.assertEqual(job.events.get(), event)
        self.assertEqual(job.agent_results.get(), agent_result)
        self.assertEqual(job.display_result, display_result)
        self.assertEqual(job.reports.get(), report)
        self.assertEqual(agent_result.evidence[0]["source_reference"], "att_db_foundation")
        self.assertEqual(display_result.cards[0]["card_type"], "fine_notice")
        self.assertEqual(report.content["format"], "text")


class ChatbotMockApiTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_AUTHORIZATION="Bearer dev-mock-token")
        self._history_root = tempfile.TemporaryDirectory()
        self._previous_history_root = os.environ.get("MOCK_HISTORY_EVENT_ROOT")
        os.environ["MOCK_HISTORY_EVENT_ROOT"] = self._history_root.name

    def tearDown(self):
        if self._previous_history_root is None:
            os.environ.pop("MOCK_HISTORY_EVENT_ROOT", None)
        else:
            os.environ["MOCK_HISTORY_EVENT_ROOT"] = self._previous_history_root
        self._history_root.cleanup()

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
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="Content-Type, Authorization, X-Guest-Id",
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertIn("Authorization", response["Access-Control-Allow-Headers"])
        self.assertIn("X-Guest-Id", response["Access-Control-Allow-Headers"])

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
        self.assertEqual(
            response["WWW-Authenticate"],
            'Bearer error="auth_required", error_description="missing_token"',
        )
        error = response.json()["error"]
        self.assertEqual(error["contract_version"], "auth_error.v1")
        self.assertEqual(error["type"], "auth")
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

    def test_protected_endpoint_rejects_malformed_authorization_header(self):
        response = Client(HTTP_AUTHORIZATION="Token dev-mock-token").post(
            "/api/mock/chat/messages/",
            data={"session_id": "ses_malformed_auth", "user_text": "hello"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response["WWW-Authenticate"],
            'Bearer error="token_invalid", error_description="malformed_authorization_header"',
        )
        error = response.json()["error"]
        self.assertEqual(error["contract_version"], "auth_error.v1")
        self.assertEqual(error["type"], "auth")
        self.assertEqual(error["code"], "token_invalid")
        self.assertEqual(error["auth"]["reason"], "malformed_authorization_header")

    def test_protected_mock_endpoint_rejects_expired_mock_token(self):
        response = Client(HTTP_AUTHORIZATION="Bearer expired").post(
            "/api/mock/chat/messages/",
            data={"session_id": "ses_expired_auth", "user_text": "hello"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response["WWW-Authenticate"],
            'Bearer error="token_expired", error_description="expired_token"',
        )
        error = response.json()["error"]
        self.assertEqual(error["contract_version"], "auth_error.v1")
        self.assertEqual(error["code"], "token_expired")
        self.assertEqual(error["auth"]["reason"], "expired_token")

    def test_auth_guest_session_issues_guest_identity_without_login(self):
        response = Client().post(
            "/api/auth/guest-session/",
            data={"guest_id": "gst_existing", "session_id": "ses_guest_chat"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["api_surface"], "canonical_mock")
        self.assertEqual(body["execution_mode"], "mock")
        self.assertEqual(body["auth_state"], "guest")
        self.assertEqual(body["guest"]["guest_id"], "gst_existing")
        self.assertEqual(body["subject"]["subject_id"], "guest:gst_existing")
        self.assertIsNone(body["subject"]["auth_session_id"])
        self.assertEqual(body["session_binding"]["session_id"], "ses_guest_chat")
        self.assertFalse(body["merge_policy"]["auto_merge"])

    def test_auth_me_reports_authenticated_subject_with_mock_bearer(self):
        response = self.client.get(
            "/api/auth/me/?session_id=ses_auth_me",
            HTTP_X_GUEST_ID="gst_before_login",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["auth_state"], "authenticated")
        self.assertEqual(body["subject"]["subject_id"], "user:usr_mock")
        self.assertEqual(body["subject"]["guest_id"], "gst_before_login")
        self.assertEqual(body["subject"]["auth_session_id"], "auth_dev_mock")
        self.assertEqual(body["auth_session"]["verification"], "mock_bearer_shape_only")
        self.assertEqual(body["session_binding"]["session_id"], "ses_auth_me")

    def test_auth_me_can_report_guest_subject_without_bearer(self):
        response = Client().get("/api/auth/me/", HTTP_X_GUEST_ID="guest_header")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["auth_state"], "guest")
        self.assertEqual(body["guest"]["guest_id"], "gst_guest_header")
        self.assertEqual(body["subject"]["subject_type"], "guest")
        self.assertFalse(body["subject"]["is_authenticated"])

    def test_auth_me_reuses_auth_error_header_for_invalid_bearer(self):
        response = Client(HTTP_AUTHORIZATION="Bearer expired").get("/api/auth/me/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response["WWW-Authenticate"],
            'Bearer error="token_expired", error_description="expired_token"',
        )
        error = response.json()["error"]
        self.assertEqual(error["contract_version"], "auth_error.v1")
        self.assertEqual(error["code"], "token_expired")

    def test_history_endpoint_requires_authorization_header(self):
        response = Client().get("/api/history/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "auth_required")

    def test_mypage_summary_endpoint_requires_authorization_header(self):
        response = Client().get("/api/mypage/summary/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "auth_required")

    def test_mypage_summary_returns_empty_collection_for_session(self):
        response = self.client.get("/api/mypage/summary/?session_id=ses_empty_mycase")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["api_surface"], "canonical_mock")
        self.assertEqual(body["storage"]["backend"], "postgresql")
        self.assertIn("analysis_jobs", body["storage"]["tables"])
        self.assertEqual(body["active_cases"], 0)
        self.assertEqual(body["saved_reports"], 0)
        self.assertEqual(body["recent_analysis_count"], 0)
        self.assertEqual(body["cases"], [])

    def test_history_endpoint_returns_standard_light_session_events(self):
        raw_user_text = "이 고지서 원문은 history metadata에 저장되면 안 됩니다."
        response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_history_api",
                "auth_context": {
                    "auth_state": "guest",
                    "guest_id": "gst_history",
                    "session_id": "ses_history_api",
                },
                "user_text": raw_user_text,
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
            HTTP_X_GUEST_ID="gst_history",
        )
        self.assertEqual(response.status_code, 200)

        history_response = self.client.get("/api/history/?session_id=ses_history_api")

        self.assertEqual(history_response.status_code, 200)
        body = history_response.json()
        self.assertEqual(body["history_contract"], "history_event.v1")
        self.assertEqual(body["storage"]["policy"], "standard_light")
        events = body["events"]
        self.assertIn("chat_message_created", {event["event_type"] for event in events})
        chat_event = next(event for event in events if event["event_type"] == "chat_message_created")
        self.assertEqual(chat_event["actor"]["guest_id"], "gst_history")
        self.assertEqual(chat_event["subject"]["session_id"], "ses_history_api")
        self.assertFalse(chat_event["privacy"]["contains_user_text"])
        self.assertNotIn(raw_user_text, json.dumps(events, ensure_ascii=False))
        self.assertNotIn("user_text", json.dumps([event["metadata"] for event in events], ensure_ascii=False))

    def test_protected_mock_endpoint_rejects_invalid_mock_token(self):
        response = Client(HTTP_AUTHORIZATION="Bearer invalid").post(
            "/api/mock/chat/messages/",
            data={"session_id": "ses_invalid_auth", "user_text": "hello"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        error = response.json()["error"]
        self.assertEqual(error["code"], "token_invalid")
        self.assertEqual(error["auth"]["reason"], "invalid_token")

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
        self.assertFalse(
            ChatMessage.objects.filter(message_id=body["message_id"]).exists()
        )

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

        session = ChatSession.objects.get(session_id="ses_canonical_chat")
        message = ChatMessage.objects.get(message_id=body["message_id"])
        job = AnalysisJob.objects.get(message=message)
        event = job.events.get()
        self.assertEqual(message.session, session)
        self.assertEqual(message.role, MessageRole.USER)
        self.assertEqual(message.content, "이 고지서로 이의신청서를 만들 수 있을까요?")
        self.assertEqual(message.routing_intent, "objection_request")
        self.assertEqual(message.metadata["analysis_job_id"], job.job_id)
        self.assertEqual(message.metadata["source"], "canonical_chat_message")
        self.assertEqual(job.session, session)
        self.assertEqual(job.owner_id, "")
        self.assertEqual(job.routing_intent, "objection_request")
        self.assertEqual(job.mock_scenario, "fine_notice")
        self.assertEqual(job.status, AnalysisJobStatus.SUCCESS)
        self.assertEqual(job.analysis_plan_id, body["analysis_plan"]["plan_id"])
        self.assertEqual(job.metadata["analysis_plan"]["plan_id"], body["analysis_plan"]["plan_id"])
        self.assertEqual(job.metadata["assistant_message"], body["assistant_message"])
        self.assertEqual(event.status, AnalysisJobStatus.SUCCESS)
        self.assertEqual(event.metadata["source"], "canonical_chat_message")

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
        self.assertFalse(
            UploadedFile.objects.filter(attachment_id=attachment["attachment_id"]).exists()
        )

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
        self.assertEqual(attachment["persistence"]["backend"], "postgresql")
        self.assertEqual(attachment["persistence"]["table"], "uploaded_files")
        self.assertEqual(attachment["checks"]["metadata_repository"], "uploaded_files")

        uploaded_file = UploadedFile.objects.get(attachment_id=attachment["attachment_id"])
        self.assertEqual(uploaded_file.session.session_id, "ses_canonical_files")
        self.assertEqual(uploaded_file.purpose, "fine_notice")
        self.assertEqual(uploaded_file.file_type, "image")
        self.assertEqual(uploaded_file.content_type, "image/jpeg")
        self.assertEqual(uploaded_file.size_bytes, 2048)
        self.assertEqual(uploaded_file.status, UploadedFileStatus.UPLOADED)
        self.assertEqual(uploaded_file.metadata["mock_status"], "metadata_registered")

        detail = self.client.get(f"/api/files/{attachment['attachment_id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["api_surface"], "canonical_mock")
        self.assertEqual(
            detail.json()["attachment"]["persistence"]["table"],
            "uploaded_files",
        )

        list_response = self.client.get("/api/files/?session_id=ses_canonical_files")
        self.assertEqual(list_response.status_code, 200)
        self.assertIn(
            attachment["attachment_id"],
            {item["attachment_id"] for item in list_response.json()["attachments"]},
        )

    def test_canonical_file_detail_reads_uploaded_file_repository(self):
        session = ChatSession.objects.create(
            session_id="ses_db_file_detail",
            owner_id="usr_file_detail",
            status=ChatSessionStatus.ACTIVE,
        )
        uploaded_file = UploadedFile.objects.create(
            attachment_id="att_db_file_detail",
            owner_id="usr_file_detail",
            session=session,
            purpose="accident_statement",
            file_type="pdf",
            original_filename="statement.pdf",
            content_type="application/pdf",
            size_bytes=1204,
            storage_uri="mock://metadata/att_db_file_detail",
            status=UploadedFileStatus.READY,
            agent_handoff={
                "attachment_id": "att_db_file_detail",
                "purpose": "accident_statement",
                "type": "pdf",
            },
            metadata={
                "filename": "statement.pdf",
                "checks": {"extension": ".pdf"},
                "limitations": [],
            },
        )

        response = self.client.get(f"/api/files/{uploaded_file.attachment_id}/")

        self.assertEqual(response.status_code, 200)
        attachment = response.json()["attachment"]
        self.assertEqual(attachment["attachment_id"], uploaded_file.attachment_id)
        self.assertEqual(attachment["session_id"], session.session_id)
        self.assertEqual(attachment["status"], UploadedFileStatus.READY)
        self.assertEqual(attachment["persistence"]["table"], "uploaded_files")

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
        self.assertFalse(AnalysisJob.objects.filter(job_id=job["job_id"]).exists())

        detail = self.client.get(f"/api/mock/analysis/jobs/{job['job_id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["job"]["job_id"], job["job_id"])

        result_response = self.client.get(f"/api/mock/analysis/results/{job['job_id']}/")
        self.assertEqual(result_response.status_code, 200)
        result = result_response.json()["result"]
        self.assertEqual(result["job_id"], job["job_id"])
        self.assertIn("answer", result["assistant_message"])
        self.assertIn("progress", result)
        self.assertIn("cards", result)
        self.assertIn("agent_results", result)
        self.assertIn("evidence", result)
        self.assertNotIn("analysis_plan", result)
        self.assertNotIn("node_execution", result)
        self.assertNotIn("chat_response", result)
        self.assertFalse(AnalysisDisplayResult.objects.filter(display_result_id=f"disp_{job['job_id']}").exists())

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
            HTTP_X_GUEST_ID="gst_canonical_job",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        job = body["job"]
        self.assertEqual(body["api_surface"], "canonical_mock")
        self.assertEqual(body["execution_mode"], "mock")
        self.assertEqual(job["status"], "success")
        self.assertEqual(job["persistence"]["backend"], "postgresql")
        self.assertEqual(job["persistence"]["analysis_job_table"], "analysis_jobs")
        self.assertEqual(job["persistence"]["agent_results_table"], "agent_results")
        self.assertEqual(job["persistence"]["ai_session_table"], "ai_sessions")
        self.assertEqual(job["persistence"]["agent_invocations_table"], "agent_invocations")
        self.assertEqual(
            job["persistence"]["agent_results_saved"],
            len(job["node_execution"]["executions"]),
        )
        self.assertEqual(
            job["persistence"]["agent_invocations_saved"],
            len(job["node_execution"]["executions"]),
        )
        self.assertIn(
            "/api/reports",
            {link["endpoint"] for link in job["chat_response"]["report_links"]},
        )

        persisted_job = AnalysisJob.objects.get(job_id=job["job_id"])
        self.assertEqual(persisted_job.owner_id, "usr_mock")
        self.assertEqual(persisted_job.metadata["source"], "canonical_analysis_job")
        self.assertEqual(persisted_job.events.get().metadata["source"], "canonical_analysis_job")
        persisted_results = list(persisted_job.agent_results.order_by("created_at"))
        self.assertEqual(len(persisted_results), len(job["node_execution"]["executions"]))
        fine_notice_result = persisted_job.agent_results.get(node_code="fine_notice_analysis")
        self.assertEqual(fine_notice_result.status, AgentResultStatus.SUCCESS)
        self.assertIn("notice_fields", fine_notice_result.structured_result)
        self.assertEqual(fine_notice_result.raw_output["source"], "mock_node_execution")
        self.assertNotIn("agent_input", fine_notice_result.raw_output)
        ai_session = AiSession.objects.get(ai_session_id=job["persistence"]["ai_session_id"])
        self.assertEqual(ai_session.session, persisted_job.session)
        self.assertEqual(ai_session.user.user_id, "usr_mock")
        self.assertEqual(ai_session.guest.guest_id, "gst_canonical_job")
        self.assertEqual(ai_session.metadata["auth_session_id"], "auth_dev_mock")
        self.assertEqual(ai_session.metadata["chat_session_id"], "ses_canonical_job")
        self.assertEqual(ai_session.quota_key, "rate_limit:user:usr_mock:agent_run")
        persisted_invocations = list(persisted_job.agent_invocations.order_by("created_at"))
        self.assertEqual(len(persisted_invocations), len(job["node_execution"]["executions"]))
        self.assertTrue(all(invocation.ai_session == ai_session for invocation in persisted_invocations))
        self.assertTrue(all(invocation.agent_node is not None for invocation in persisted_invocations))
        self.assertEqual(
            persisted_invocations[0].metadata["agent_result_id"],
            persisted_results[0].result_id,
        )
        self.assertEqual(
            AgentNodeDefinition.objects.get(node_code="fine_notice_analysis").owner,
            "workzion2",
        )

        repeat_response = self.client.post(
            "/api/analysis/jobs/",
            data={
                "session_id": "ses_canonical_job",
                "user_text": "repeat same job",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
                "job_id": job["job_id"],
            },
            content_type="application/json",
            HTTP_X_GUEST_ID="gst_canonical_job",
        )
        self.assertEqual(repeat_response.status_code, 200)
        repeat_job = repeat_response.json()["job"]
        self.assertEqual(repeat_job["job_id"], job["job_id"])
        self.assertEqual(
            AgentResult.objects.filter(job__job_id=job["job_id"]).count(),
            repeat_job["persistence"]["agent_results_saved"],
        )
        self.assertEqual(
            AgentInvocation.objects.filter(job__job_id=job["job_id"]).count(),
            repeat_job["persistence"]["agent_invocations_saved"],
        )

        detail = self.client.get(f"/api/analysis/jobs/{job['job_id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["api_surface"], "canonical_mock")

        result_response = self.client.get(f"/api/analysis/results/{job['job_id']}/")
        self.assertEqual(result_response.status_code, 200)
        result_body = result_response.json()
        result = result_body["result"]
        self.assertEqual(result_body["api_surface"], "canonical_mock")
        self.assertEqual(result_body["execution_mode"], "mock")
        self.assertEqual(result["persistence"]["backend"], "postgresql")
        self.assertEqual(result["persistence"]["table"], "analysis_display_results")
        self.assertEqual(result["persistence"]["status"], "saved")
        self.assertIn(
            "/api/reports/",
            {link["endpoint"] for link in result["report_links"]},
        )
        self.assertTrue(
            all(
                not link["endpoint"].startswith("/api/mock/")
                for link in result["report_links"]
            )
        )
        display_result = AnalysisDisplayResult.objects.get(job=persisted_job)
        self.assertEqual(display_result.display_result_id, result["persistence"]["display_result_id"])
        self.assertEqual(display_result.assistant_message["answer"], result["assistant_message"]["answer"])
        self.assertEqual(display_result.progress[0]["node_code"], result["progress"][0]["node_code"])
        self.assertTrue(
            all(
                not link["endpoint"].startswith("/api/mock/")
                for link in display_result.report_links
            )
        )

    def test_canonical_api_smoke_covers_session_file_job_result_and_report(self):
        session_response = self.client.post(
            "/api/chat/sessions/",
            data={"user_id": "usr_canonical_smoke"},
            content_type="application/json",
        )
        self.assertEqual(session_response.status_code, 200)
        session_body = session_response.json()
        session_id = session_body["session_id"]
        self.assertEqual(session_body["api_surface"], "canonical_mock")

        file_response = self.client.post(
            "/api/files/",
            data={
                "session_id": session_id,
                "purpose": "fine_notice",
                "filename": "canonical-notice.jpg",
                "content_type": "image/jpeg",
                "size_bytes": 2048,
            },
            content_type="application/json",
        )
        self.assertEqual(file_response.status_code, 200)
        attachment = file_response.json()["attachment"]

        message_payload = {
            "session_id": session_id,
            "user_text": "과태료 고지서 이의신청 초안을 만들어줘",
            "attachments": [{"attachment_id": attachment["attachment_id"]}],
            "mock_scenario": "fine_notice",
            "mock_status": "success",
        }
        message_response = self.client.post(
            "/api/chat/messages/",
            data=message_payload,
            content_type="application/json",
        )
        self.assertEqual(message_response.status_code, 200)
        message_body = message_response.json()
        self.assertEqual(message_body["api_surface"], "canonical_mock")
        self.assertEqual(
            message_body["analysis_plan"]["input_summary"]["attachment_purposes"],
            ["fine_notice"],
        )
        self.assertTrue(
            all(
                not link["endpoint"].startswith("/api/mock/")
                for link in message_body["report_links"]
            )
        )

        job_response = self.client.post(
            "/api/analysis/jobs/",
            data=message_payload,
            content_type="application/json",
        )
        self.assertEqual(job_response.status_code, 200)
        job_body = job_response.json()
        job = job_body["job"]
        self.assertEqual(job_body["api_surface"], "canonical_mock")
        self.assertEqual(job["session_id"], session_id)
        self.assertEqual(job["status"], "success")

        detail_response = self.client.get(f"/api/analysis/jobs/{job['job_id']}/")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["job"]["job_id"], job["job_id"])

        result_response = self.client.get(f"/api/analysis/results/{job['job_id']}/")
        self.assertEqual(result_response.status_code, 200)
        result_body = result_response.json()
        result = result_body["result"]
        self.assertEqual(result_body["api_surface"], "canonical_mock")
        self.assertEqual(result["status"], "success")
        self.assertIn("agent_results", result)
        self.assertNotIn("analysis_plan", result)
        self.assertTrue(
            all(
                not link["endpoint"].startswith("/api/mock/")
                for link in result["report_links"]
            )
        )

        report_response = self.client.post(
            "/api/reports/",
            data={
                "action": "download",
                "report_id": "rep_canonical_smoke",
                "job_id": job["job_id"],
            },
            content_type="application/json",
        )
        self.assertEqual(report_response.status_code, 200)
        report_body = report_response.json()
        self.assertEqual(report_body["api_surface"], "canonical_mock")
        self.assertEqual(report_body["persistence"]["backend"], "postgresql")
        self.assertEqual(report_body["persistence"]["table"], "reports")
        self.assertEqual(report_body["persistence"]["status"], "metadata_saved")
        self.assertEqual(report_body["persistence"]["object_storage"], "mock_placeholder")
        self.assertTrue(report_body["download_url"].startswith("/api/reports/"))
        report = Report.objects.get(report_id=report_body["report_id"])
        self.assertEqual(report.job.job_id, job["job_id"])
        self.assertEqual(report.session.session_id, session_id)
        self.assertEqual(report.display_result.display_result_id, result["persistence"]["display_result_id"])
        self.assertEqual(report.status, ReportStatus.READY)
        self.assertEqual(report.storage_uri, "mock://reports/rep_canonical_smoke")
        self.assertEqual(report.metadata["source"], "canonical_report_action")
        self.assertEqual(report.metadata["object_storage_status"], "mock_placeholder")
        self.assertEqual(report.content["download_url"], report_body["download_url"])

        download_response = self.client.get(
            f"/api/reports/{report_body['report_id']}/download/"
        )
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response["X-API-Surface"], "canonical_mock")
        self.assertEqual(download_response["X-Report-Persistence"], "postgresql")
        self.assertEqual(download_response["X-Report-Storage-Backend"], "mock_placeholder")
        self.assertEqual(download_response["X-Report-Storage-URI"], "mock://reports/rep_canonical_smoke")
        self.assertIn(
            "Report metadata download for rep_canonical_smoke",
            download_response.content.decode("utf-8"),
        )

        summary_response = self.client.get(f"/api/mypage/summary/?session_id={session_id}")
        self.assertEqual(summary_response.status_code, 200)
        summary_body = summary_response.json()
        self.assertEqual(summary_body["api_surface"], "canonical_mock")
        self.assertEqual(summary_body["execution_mode"], "mock")
        self.assertEqual(summary_body["storage"]["backend"], "postgresql")
        self.assertEqual(
            set(summary_body["storage"]["tables"]),
            {
                "chat_sessions",
                "chat_messages",
                "analysis_jobs",
                "analysis_job_events",
                "agent_results",
                "ai_sessions",
                "agent_invocations",
                "analysis_display_results",
                "reports",
            },
        )
        self.assertEqual(summary_body["active_cases"], 0)
        self.assertEqual(summary_body["due_soon_cases"], 0)
        self.assertEqual(summary_body["saved_reports"], 1)
        self.assertEqual(summary_body["recent_analysis_count"], len(summary_body["cases"]))
        self.assertGreaterEqual(summary_body["recent_analysis_count"], 1)
        case = next(item for item in summary_body["cases"] if item["job_id"] == job["job_id"])
        self.assertEqual(case["case_id"], job["job_id"])
        self.assertEqual(case["job_id"], job["job_id"])
        self.assertEqual(case["session_id"], session_id)
        self.assertEqual(case["case_status"], "success")
        self.assertEqual(case["routing_intent"], "objection_request")
        self.assertEqual(case["agent_result_count"], len(job["node_execution"]["executions"]))
        self.assertEqual(case["agent_invocation_count"], len(job["node_execution"]["executions"]))
        self.assertEqual(
            sum(case["agent_status_counts"].values()),
            case["agent_result_count"],
        )
        self.assertEqual(
            sum(case["agent_invocation_status_counts"].values()),
            case["agent_invocation_count"],
        )
        self.assertIn(f"ais_{job['job_id']}", case["ai_session_ids"])
        self.assertGreaterEqual(case["agent_status_counts"]["success"], 1)
        self.assertEqual(case["display_result_id"], result["persistence"]["display_result_id"])
        self.assertEqual(case["report_count"], 1)
        self.assertEqual(case["latest_report_id"], report_body["report_id"])
        self.assertEqual(case["latest_report_status"], ReportStatus.READY)
        self.assertTrue(case["next_actions"])
        self.assertTrue(case["limitations"])

    def test_analysis_result_endpoint_returns_404_for_missing_job(self):
        response = self.client.get("/api/mock/analysis/results/job_missing/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "analysis_result_not_found")

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

    def test_mock_report_action_stays_sidecar_only(self):
        response = self.client.post(
            "/api/mock/reports/",
            data={
                "action": "download",
                "report_id": "rep_mock_sidecar",
                "job_id": "job_mock_sidecar",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        report_body = response.json()
        self.assertTrue(report_body["download_url"].startswith("/api/mock/reports/"))
        self.assertFalse(Report.objects.filter(report_id="rep_mock_sidecar").exists())

    def test_report_download_returns_attachment(self):
        response = self.client.get("/api/mock/reports/rep_mock/download/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])

    def test_canonical_report_download_marks_canonical_mock_surface(self):
        response = self.client.get("/api/reports/rep_mock/download/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-API-Surface"], "canonical_mock")
        self.assertEqual(response["X-Execution-Mode"], "mock")
        self.assertNotIn("X-Report-Persistence", response)

