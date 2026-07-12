import json
import os
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.agent_node_service import execute_mock_node
from app.services.persona_catalog_service import list_demo_personas
from chatbot.models import (
    AgentFeedbackEvent,
    AgentInvocation,
    AgentInvocationStatus,
    AgentNodeDefinition,
    AgentResult,
    AgentResultStatus,
    AgentWorkItem,
    AgentWorkItemStatus,
    AnalysisDisplayResult,
    AnalysisJob,
    AnalysisJobEvent,
    AnalysisJobStatus,
    AuthEvent,
    AuthSession,
    AuthSessionStatus,
    ChatMessage,
    ChatSession,
    ChatSessionStatus,
    CodeGroup,
    CodeItem,
    GuestIdentity,
    GuestIdentityStatus,
    HistoryEvent,
    AiSession,
    MessageRole,
    OAuthConnection,
    RagChunk,
    RetrievalEvent,
    Report,
    ReportStatus,
    ReportType,
    SourceDocument,
    SocialAccount,
    Subscription,
    SubscriptionStatus,
    UsageEvent,
    UsageQuota,
    UserAccount,
    UserAccountStatus,
    UploadedFile,
    UploadedFileStatus,
)
from config.env_loader import load_django_env_file
from chatbot.readiness import build_production_readiness_report
from chatbot.repositories import (
    list_history_event_records,
    process_agent_work_item,
    process_agent_work_items,
    record_history_event_record,
)
from chatbot.progress_cache import read_analysis_job_progress, read_chat_session_state


def fixture_value(*parts):
    return "".join(parts)


def extract_pdf_text(content: bytes) -> str:
    try:
        import fitz
    except ModuleNotFoundError:
        return ""

    with fitz.open(stream=content, filetype="pdf") as document:
        return "\n".join(page.get_text() for page in document)


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
        self.assertEqual(SocialAccount._meta.db_table, "social_accounts")
        self.assertEqual(OAuthConnection._meta.db_table, "oauth_connections")
        self.assertEqual(GuestIdentity._meta.db_table, "guest_identities")
        self.assertEqual(AuthSession._meta.db_table, "auth_sessions")
        self.assertEqual(CodeGroup._meta.db_table, "code_groups")
        self.assertEqual(CodeItem._meta.db_table, "code_items")
        self.assertEqual(AgentNodeDefinition._meta.db_table, "agent_nodes")
        self.assertEqual(AiSession._meta.db_table, "ai_sessions")
        self.assertEqual(AgentInvocation._meta.db_table, "agent_invocations")
        self.assertEqual(SourceDocument._meta.db_table, "source_documents")
        self.assertEqual(RagChunk._meta.db_table, "rag_chunks")
        self.assertEqual(RetrievalEvent._meta.db_table, "retrieval_events")
        self.assertEqual(AgentWorkItem._meta.db_table, "agent_work_items")
        self.assertEqual(AgentFeedbackEvent._meta.db_table, "agent_feedback_events")
        self.assertEqual(Subscription._meta.db_table, "subscriptions")
        self.assertEqual(UsageQuota._meta.db_table, "usage_quotas")
        self.assertEqual(UsageEvent._meta.db_table, "usage_events")
        self.assertEqual(HistoryEvent._meta.db_table, "history_events")

    def test_knowledge_rag_tables_link_source_chunks_and_retrieval_events(self):
        source = SourceDocument.objects.create(
            source_document_id="src_road_traffic_act",
            source_type="law",
            source_name="Road Traffic Act",
            source_url="https://example.test/law",
            metadata={"source": "unit_test"},
        )
        chunk = RagChunk.objects.create(
            chunk_id="rag_road_traffic_act_article_32",
            source_document=source,
            source_id="road_traffic_act",
            source_type="law",
            chunk_type="article",
            title="Stopping and parking restriction",
            article_no="Article 32",
            content="Emergency stopping near a school zone may require supporting evidence.",
            normalized_text="school zone emergency stopping supporting evidence",
            domain_tags=["fine_notice", "school_zone"],
        )
        job = AnalysisJob.objects.create(
            job_id="job_rag_foundation",
            session=ChatSession.objects.create(session_id="ses_rag_foundation"),
            status=AnalysisJobStatus.RUNNING,
        )
        event = RetrievalEvent.objects.create(
            retrieval_event_id="retr_rag_foundation",
            job=job,
            query_text="school zone stopping fine",
            query_type="django_rag_tables",
            top_k=3,
            result_count=1,
            source_refs=[chunk.chunk_id],
        )

        self.assertEqual(chunk.source_document, source)
        self.assertEqual(event.source_refs, ["rag_road_traffic_act_article_32"])

    def test_law_ground_search_reads_django_rag_chunks_when_available(self):
        source = SourceDocument.objects.create(
            source_document_id="src_school_zone_rule",
            source_type="law",
            source_name="Road Traffic Act",
            source_url="https://example.test/school-zone",
        )
        RagChunk.objects.create(
            chunk_id="rag_school_zone_emergency_stop",
            source_document=source,
            source_id="road_traffic_act",
            source_type="law",
            chunk_type="article",
            title="School zone emergency stopping",
            article_no="Article 32",
            content="Emergency stopping in a school zone should be checked with evidence.",
            normalized_text="school zone emergency stopping evidence fine notice",
            domain_tags=["school_zone", "fine_notice"],
        )

        execution = execute_mock_node(
            {
                "node_code": "law_ground_search",
                "search_query": "school zone emergency stopping fine",
            }
        )
        structured_result = execution["agent_output"]["structured_result"]

        self.assertEqual(structured_result["retrieval_quality"], "django_rag_tables")
        self.assertEqual(
            structured_result["matched_laws"][0]["source_reference"],
            "rag_school_zone_emergency_stop",
        )
        self.assertEqual(structured_result["retrieval"]["status"], "ready")
        self.assertEqual(structured_result["retrieval"]["backend"], "django_rag_tables")
        self.assertEqual(
            structured_result["retrieval"]["attempted_backends"][0]["backend"],
            "postgres_pgvector",
        )
        self.assertEqual(
            structured_result["retrieval"]["attempted_backends"][0]["status"],
            "disabled",
        )

    def test_legal_rag_smoke_fixture_loads_searchable_chunks(self):
        output = StringIO()

        call_command(
            "load_legal_rag_smoke_fixture",
            "--replace",
            "--smoke-query",
            "school zone emergency stopping fine notice",
            "--format",
            "json",
            stdout=output,
        )

        body = json.loads(output.getvalue())
        self.assertEqual(body["contract_version"], "legal_rag_smoke_fixture.v1")
        self.assertEqual(body["status"], "loaded")
        self.assertEqual(body["loaded"]["rag_chunks"], 3)
        self.assertEqual(body["counts"]["rag_chunks"], 3)
        self.assertEqual(body["smoke"]["backend"], "django_rag_tables")
        self.assertEqual(body["smoke"]["status"], "ready")
        self.assertGreaterEqual(body["smoke"]["result_count"], 1)
        self.assertTrue(
            RagChunk.objects.filter(chunk_id="rag_smoke_school_zone_stop", is_searchable=True).exists()
        )

    def test_progress_cache_recovers_from_postgresql_on_cache_miss(self):
        cache.clear()
        session = ChatSession.objects.create(
            session_id="ses_progress_cache",
            owner_id="usr_progress_cache",
            status=ChatSessionStatus.ACTIVE,
        )
        AnalysisJob.objects.create(
            job_id="job_progress_cache",
            session=session,
            owner_id="usr_progress_cache",
            routing_intent="objection_request",
            status=AnalysisJobStatus.RUNNING,
            active_node="fine_notice_analysis",
            progress_message="analysis running",
            analysis_plan_id="plan_progress_cache",
            status_counts={"running": 1},
        )

        progress = read_analysis_job_progress("job_progress_cache")
        self.assertEqual(progress["status"], "miss_fallback")
        self.assertEqual(progress["backend"], "locmem")
        self.assertEqual(progress["fallback"], "postgresql")
        self.assertEqual(progress["ttl_seconds"], 300)
        self.assertEqual(progress["key"], "analysis_job_progress:job_progress_cache")
        self.assertEqual(progress["snapshot"]["status"], AnalysisJobStatus.RUNNING)
        self.assertEqual(progress["snapshot"]["source_tables"], ["analysis_jobs", "analysis_job_events"])

        cached_progress = read_analysis_job_progress("job_progress_cache")
        self.assertEqual(cached_progress["status"], "hit")
        self.assertEqual(cached_progress["snapshot"]["job_id"], "job_progress_cache")

        session_state = read_chat_session_state("ses_progress_cache")
        self.assertEqual(session_state["status"], "miss_fallback")
        self.assertEqual(session_state["key"], "chat_session_state:ses_progress_cache")
        self.assertEqual(session_state["snapshot"]["latest_job_id"], "job_progress_cache")
        self.assertEqual(session_state["snapshot"]["current_intent"], "objection_request")

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


class ProductionReadinessTests(TestCase):
    def test_env_loader_reads_explicit_file_without_overriding_process_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env.production"
            env_path.write_text(
                "\n".join(
                    [
                        "SKN27_TEST_ENV_FILE_VALUE=from-file",
                        "SKN27_TEST_ENV_EXISTING=from-file",
                        "export SKN27_TEST_ENV_EXPORTED=from-export",
                        "SKN27_TEST_ENV_QUOTED='quoted value'",
                    ]
                ),
                encoding="utf-8",
            )
            previous_existing = os.environ.get("SKN27_TEST_ENV_EXISTING")
            previous_keys = {
                key: os.environ.get(key)
                for key in (
                    "SKN27_TEST_ENV_FILE_VALUE",
                    "SKN27_TEST_ENV_EXISTING",
                    "SKN27_TEST_ENV_EXPORTED",
                    "SKN27_TEST_ENV_QUOTED",
                )
            }
            try:
                os.environ["SKN27_TEST_ENV_EXISTING"] = "from-process"
                result = load_django_env_file(Path(temp_dir), env_file=env_path)

                self.assertTrue(result["loaded"])
                self.assertEqual(os.environ["SKN27_TEST_ENV_FILE_VALUE"], "from-file")
                self.assertEqual(os.environ["SKN27_TEST_ENV_EXISTING"], "from-process")
                self.assertEqual(os.environ["SKN27_TEST_ENV_EXPORTED"], "from-export")
                self.assertEqual(os.environ["SKN27_TEST_ENV_QUOTED"], "quoted value")
                self.assertNotIn("SKN27_TEST_ENV_EXISTING", result["loaded_keys"])
            finally:
                for key, previous_value in previous_keys.items():
                    if previous_value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = previous_value
                if previous_existing is None:
                    os.environ.pop("SKN27_TEST_ENV_EXISTING", None)
                else:
                    os.environ["SKN27_TEST_ENV_EXISTING"] = previous_existing

    def test_readiness_report_flags_default_development_settings(self):
        report = build_production_readiness_report(include_database=False)

        self.assertEqual(report["contract_version"], "production_readiness.v1")
        self.assertEqual(report["status"], "fail")
        failing_checks = {check["name"] for check in report["checks"] if check["status"] == "fail"}
        self.assertIn("django_security", failing_checks)
        self.assertIn("google_oauth", failing_checks)

    @override_settings(
        DEBUG=False,
        SECRET_KEY=("prod-secret-key-prod-secret-key-123456"),
        ALLOWED_HOSTS=["app.legaldrive.test"],
        DJANGO_DATABASE_ENGINE="postgres",
        GOOGLE_AUTH_ALLOW_MOCK=False,
        APP_AUTH_ALLOW_MOCK_BEARER=False,
        GOOGLE_CLIENT_ID="google-client-id",
        GOOGLE_CLIENT_SECRET=("google-client-secret"),
        GOOGLE_POPUP_REDIRECT_URI="https://app.legaldrive.test",
        APP_JWT_SECRET=("app-jwt-secret-app-jwt-secret-123456"),
        OAUTH_TOKEN_SECRET=("oauth-token-secret-oauth-token-123456"),
        REDIS_URL="redis://redis:6379/0",
        SUPERVISOR_LLM_ENABLED=False,
        LEGAL_RAG_VECTOR_ENABLED=False,
        OBJECT_STORAGE_PROVIDER="mock_s3",
        OBJECT_STORAGE_BUCKET="bucket",
    )
    def test_readiness_report_allows_non_blocking_warnings_for_optional_services(self):
        report = build_production_readiness_report(include_database=False)

        self.assertEqual(report["status"], "warn")
        self.assertEqual(report["summary"]["fail"], 0)
        warning_checks = {check["name"] for check in report["checks"] if check["status"] == "warn"}
        self.assertIn("supervisor_llm", warning_checks)
        self.assertIn("legal_rag", warning_checks)
        self.assertIn("law_ground_search_sync", warning_checks)
        self.assertIn("text_ml_case_search_rag", warning_checks)
        self.assertIn("object_storage", warning_checks)

    @override_settings(
        DEBUG=False,
        SECRET_KEY=("replace-with-django-secret-key-from-secret-manager"),
        ALLOWED_HOSTS=["app.example.com"],
        DJANGO_DATABASE_ENGINE="postgres",
        GOOGLE_AUTH_ALLOW_MOCK=False,
        APP_AUTH_ALLOW_MOCK_BEARER=False,
        GOOGLE_CLIENT_ID="replace-with-google-oauth-web-client-id",
        GOOGLE_CLIENT_SECRET=fixture_value("replace-with-google", "-oauth-client-secret"),
        GOOGLE_POPUP_REDIRECT_URI="https://app.example.com",
        APP_JWT_SECRET=("replace-with-app-jwt-secret-from-secret-manager"),
        OAUTH_TOKEN_SECRET=("replace-with-oauth-token-secret-from-secret-manager"),
        REDIS_URL="redis://redis:6379/0",
        SUPERVISOR_LLM_ENABLED=True,
        SUPERVISOR_LLM_API_KEY=fixture_value("replace-with-supervisor", "-llm-api-key"),
        LEGAL_RAG_VECTOR_ENABLED=False,
        FILE_SCAN_PROVIDER="clamav",
        FILE_SCAN_CLAMAV_HOST="clamav",
        OBJECT_STORAGE_PROVIDER="s3",
        OBJECT_STORAGE_BUCKET="bucket",
    )
    def test_readiness_report_rejects_template_placeholders(self):
        report = build_production_readiness_report(include_database=False)

        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(report["status"], "fail")
        self.assertEqual(checks["django_security"]["status"], "fail")
        self.assertEqual(checks["google_oauth"]["status"], "fail")
        self.assertEqual(checks["supervisor_llm"]["status"], "fail")
        self.assertTrue(
            any("placeholders" in detail["message"] for detail in checks["google_oauth"]["details"])
        )

    @override_settings(
        DEBUG=False,
        SECRET_KEY=("prod-secret-key-prod-secret-key-123456"),
        ALLOWED_HOSTS=["app.legaldrive.test"],
        DJANGO_DATABASE_ENGINE="postgres",
        GOOGLE_AUTH_ALLOW_MOCK=False,
        APP_AUTH_ALLOW_MOCK_BEARER=False,
        GOOGLE_CLIENT_ID="google-client-id.apps.googleusercontent.com",
        GOOGLE_CLIENT_SECRET=("google-client-secret-realistic-value"),
        GOOGLE_POPUP_REDIRECT_URI="https://app.legaldrive.test",
        APP_JWT_SECRET=("app-jwt-secret-app-jwt-secret-123456"),
        OAUTH_TOKEN_SECRET=("oauth-token-secret-oauth-token-123456"),
        REDIS_URL="redis://redis:6379/0",
        SUPERVISOR_LLM_ENABLED=True,
        SUPERVISOR_LLM_MODEL="gpt-5.4-mini",
        SUPERVISOR_LLM_API_KEY="",
        OPENAI_API_KEY=fixture_value("openai", "-api-key-realistic-value"),
        LEGAL_RAG_VECTOR_ENABLED=False,
        FILE_SCAN_PROVIDER="clamav",
        FILE_SCAN_CLAMAV_HOST="clamav",
        OBJECT_STORAGE_PROVIDER="s3",
        OBJECT_STORAGE_BUCKET="bucket",
        OBJECT_STORAGE_ACCESS_KEY_ID="access-key-realistic-value",
        OBJECT_STORAGE_SECRET_ACCESS_KEY=fixture_value("secret-key", "-realistic-value"),
    )
    def test_readiness_report_allows_openai_key_fallback_for_supervisor(self):
        report = build_production_readiness_report(include_database=False)

        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(checks["supervisor_llm"]["status"], "pass")

    @override_settings(
        OBJECT_STORAGE_PROVIDER="s3",
        OBJECT_STORAGE_BUCKET="bucket",
        OBJECT_STORAGE_PREFIX="canonical",
        FILE_SCAN_PROVIDER="clamav",
        FILE_SCAN_CLAMAV_HOST="clamav",
    )
    def test_readiness_report_requires_boto3_for_s3_provider(self):
        with patch("chatbot.readiness.importlib.util.find_spec", return_value=None):
            report = build_production_readiness_report(include_database=False)

        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(checks["object_storage"]["status"], "fail")
        self.assertTrue(
            any("boto3 package is required" in detail["message"] for detail in checks["object_storage"]["details"])
        )

    @override_settings(
        LEGAL_RAG_VECTOR_ENABLED=True,
        LEGAL_RAG_QUERY_EMBEDDING_PROVIDER="sentence-transformers",
        LEGAL_RAG_QUERY_EMBEDDING_MODEL="intfloat/multilingual-e5-large",
    )
    def test_readiness_report_requires_sentence_transformers_for_vector_rag(self):
        def fake_find_spec(name):
            if name == "sentence_transformers":
                return None
            return object()

        with patch("chatbot.readiness.importlib.util.find_spec", side_effect=fake_find_spec):
            report = build_production_readiness_report(include_database=False)

        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(checks["legal_rag"]["status"], "fail")
        self.assertTrue(
            any("sentence-transformers package is not installed" in detail["message"] for detail in checks["legal_rag"]["details"])
        )

    @override_settings(
        TEXT_ML_CASE_SEARCH_SYNC_USE_ES=True,
        TEXT_ML_CASE_SEARCH_ELASTICSEARCH_HOST="http://elasticsearch:9200",
        TEXT_ML_CASE_SEARCH_ELASTICSEARCH_USER="elastic",
        TEXT_ML_CASE_SEARCH_ELASTICSEARCH_PASSWORD=fixture_value("es-", "password-realistic-value"),
        REVIEW_CASE_ES_BM25_INDEX="review_case_chunks_bm25_nori_v1",
        FAULT_RATIO_PRECEDENT_ES_BM25_INDEX="precedent_fault_ratio_chunks_bm25_nori_v1",
    )
    def test_readiness_report_requires_elasticsearch_package_for_text_ml_rag(self):
        def fake_find_spec(name):
            if name == "elasticsearch":
                return None
            return object()

        with patch("chatbot.readiness.importlib.util.find_spec", side_effect=fake_find_spec):
            report = build_production_readiness_report(include_database=False)

        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(checks["text_ml_case_search_rag"]["status"], "fail")
        self.assertTrue(
            any("elasticsearch package is required" in detail["message"] for detail in checks["text_ml_case_search_rag"]["details"])
        )

    def test_readiness_management_command_outputs_json(self):
        output = StringIO()

        call_command(
            "check_production_readiness",
            "--skip-database",
            "--format",
            "json",
            stdout=output,
        )

        body = json.loads(output.getvalue())
        self.assertEqual(body["contract_version"], "production_readiness.v1")
        self.assertIn(body["status"], {"pass", "warn", "fail"})

    def test_text_ml_case_search_smoke_reports_safe_fallback_without_es(self):
        output = StringIO()

        with patch.dict(os.environ, {"TEXT_ML_CASE_SEARCH_SYNC_USE_ES": ""}):
            call_command(
                "smoke_text_ml_case_search",
                "--format",
                "json",
                stdout=output,
            )

        body = json.loads(output.getvalue())
        self.assertEqual(body["contract_version"], "text_ml_case_search_smoke.v1")
        self.assertEqual(body["status"], "pass")
        self.assertEqual(body["execution_mode"], "sync")
        self.assertEqual(body["adapter_execution_mode"], "sync")
        self.assertEqual(body["adapter_source"], "fault_ratio_knowledge_agent")
        self.assertFalse(body["es_rag_enabled"])
        self.assertTrue(body["es_rag_fallback"])

    def test_text_ml_case_search_smoke_require_es_fails_without_es(self):
        with patch.dict(os.environ, {"TEXT_ML_CASE_SEARCH_SYNC_USE_ES": ""}):
            with self.assertRaises(CommandError):
                call_command(
                    "smoke_text_ml_case_search",
                    "--require-es",
                    stdout=StringIO(),
                )

    def test_law_ground_search_smoke_reports_safe_partial_without_results(self):
        output = StringIO()

        with patch("ai.agents.law_ground_search.agent._get_neo4j_session", return_value=None):
            with patch("ai.agents.law_ground_search.agent.search_law_provisions", return_value=[]):
                call_command(
                    "smoke_law_ground_search",
                    "--format",
                    "json",
                    stdout=output,
                )

        body = json.loads(output.getvalue())
        self.assertEqual(body["contract_version"], "law_ground_search_smoke.v1")
        self.assertEqual(body["status"], "pass")
        self.assertEqual(body["execution_mode"], "sync")
        self.assertEqual(body["adapter_execution_mode"], "sync")
        self.assertEqual(body["agent_status"], "partial")
        self.assertEqual(body["execution_status"], "empty")
        self.assertEqual(body["law_provision_count"], 0)

    def test_law_ground_search_smoke_require_results_fails_without_results(self):
        with patch("ai.agents.law_ground_search.agent._get_neo4j_session", return_value=None):
            with patch("ai.agents.law_ground_search.agent.search_law_provisions", return_value=[]):
                with self.assertRaises(CommandError):
                    call_command(
                        "smoke_law_ground_search",
                        "--require-results",
                        stdout=StringIO(),
                    )

    @override_settings(
        DJANGO_DATABASE_ENGINE="postgres",
        LEGAL_RAG_VECTOR_ENABLED=True,
        LEGAL_RAG_QUERY_EMBEDDING_PROVIDER="sentence-transformers",
        LEGAL_RAG_QUERY_EMBEDDING_MODEL="intfloat/multilingual-e5-large",
        REDIS_URL="redis://redis:6379/0",
    )
    def test_readiness_report_handles_database_introspection_errors(self):
        class BrokenIntrospection:
            def table_names(self):
                raise RuntimeError("failed to resolve host postgres")

        class BrokenConnection:
            vendor = "postgresql"
            introspection = BrokenIntrospection()

        with patch("chatbot.readiness.connection", BrokenConnection()):
            report = build_production_readiness_report(include_database=True)

        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(report["status"], "fail")
        self.assertEqual(checks["database"]["status"], "fail")
        self.assertEqual(checks["legal_rag"]["status"], "fail")
        self.assertEqual(checks["worker_queue"]["status"], "fail")
        self.assertTrue(
            any("Database connection or introspection failed" in detail["message"] for detail in checks["database"]["details"])
        )
        self.assertTrue(
            any("database introspection failed" in detail["message"] for detail in checks["legal_rag"]["details"])
        )
        self.assertTrue(
            any("database introspection failed" in detail["message"] for detail in checks["worker_queue"]["details"])
        )

    @override_settings(SUPERVISOR_LLM_ENABLED=False)
    def test_supervisor_llm_smoke_command_outputs_sanitized_json(self):
        output = StringIO()

        call_command(
            "smoke_supervisor_llm",
            "--require-slot-state",
            "--format",
            "json",
            stdout=output,
        )

        body = json.loads(output.getvalue())
        self.assertEqual(body["contract_version"], "supervisor_llm_smoke.v1")
        self.assertEqual(body["status"], "pass")
        self.assertEqual(body["supervisor_llm"]["status"], "disabled")
        self.assertTrue(body["slot_state"]["valid"])
        self.assertEqual(body["slot_state"]["slot_contract_version"], "slot_filling_state.v1")
        self.assertNotIn("api_key", json.dumps(body))

    @override_settings(
        GOOGLE_AUTH_ALLOW_MOCK=False,
        GOOGLE_CLIENT_ID="google-client-id.apps.googleusercontent.com",
        GOOGLE_CLIENT_SECRET=("google-client-secret-realistic-value"),
        GOOGLE_POPUP_REDIRECT_URI="https://app.legaldrive.test",
    )
    def test_google_oauth_smoke_command_outputs_sanitized_config_json(self):
        output = StringIO()

        call_command(
            "smoke_google_oauth_code",
            "--format",
            "json",
            stdout=output,
        )

        body = json.loads(output.getvalue())
        self.assertEqual(body["contract_version"], "google_oauth_code_smoke.v1")
        self.assertEqual(body["status"], "pass")
        self.assertTrue(body["config"]["ready"])
        self.assertNotIn("google-client-secret", json.dumps(body))

    def test_object_storage_smoke_command_requires_binary_write(self):
        output = StringIO()

        with tempfile.TemporaryDirectory() as object_root, override_settings(
            OBJECT_STORAGE_PROVIDER="mock_s3",
            OBJECT_STORAGE_BUCKET="bucket",
            OBJECT_STORAGE_PREFIX="canonical",
            OBJECT_STORAGE_LOCAL_ROOT=object_root,
        ):
            call_command(
                "smoke_object_storage",
                "--require-binary",
                "--format",
                "json",
                stdout=output,
            )

        body = json.loads(output.getvalue())
        self.assertEqual(body["contract_version"], "object_storage_smoke.v1")
        self.assertEqual(body["status"], "pass")
        self.assertEqual(body["policy"]["provider"], "mock_s3")
        self.assertTrue(body["policy"]["writes_binary"])
        self.assertEqual(body["policy"]["persistence_state"], "binary_adapter")
        self.assertEqual(body["upload_write"]["status"], "written")
        self.assertEqual(body["report_write"]["status"], "written")

    def test_file_scan_smoke_command_requires_clean_scan(self):
        output = StringIO()

        call_command(
            "smoke_file_scan",
            "--require-clean",
            "--format",
            "json",
            stdout=output,
        )

        body = json.loads(output.getvalue())
        self.assertEqual(body["contract_version"], "file_scan_smoke.v1")
        self.assertEqual(body["status"], "pass")
        self.assertEqual(body["scan_status"], "clean")

    @override_settings(FILE_SCAN_PROVIDER="clamav", FILE_SCAN_CLAMAV_HOST="clamav")
    def test_file_scan_smoke_supports_clamav_provider_clean_scan(self):
        output = StringIO()

        with patch("chatbot.file_scan_service._clamav_scan_findings", return_value=[]):
            call_command(
                "smoke_file_scan",
                "--attachment-id",
                "att_file_scan_clamav_clean",
                "--require-clean",
                "--format",
                "json",
                stdout=output,
            )

        body = json.loads(output.getvalue())
        self.assertEqual(body["status"], "pass")
        self.assertEqual(body["scanner"], "clamav")
        self.assertEqual(body["scan_status"], "clean")

    @override_settings(FILE_SCAN_PROVIDER="clamav", FILE_SCAN_CLAMAV_HOST="clamav")
    def test_file_scan_smoke_fails_closed_when_provider_reports_unavailable(self):
        finding = {
            "category": "scanner",
            "code": "scanner_unavailable",
            "severity": "critical",
            "message": "Configured file scan provider could not scan the uploaded file.",
            "provider": "clamav",
            "reason": "connection_failed",
        }

        with patch("chatbot.file_scan_service._clamav_scan_findings", return_value=[finding]):
            with self.assertRaises(CommandError):
                call_command(
                    "smoke_file_scan",
                    "--attachment-id",
                    "att_file_scan_clamav_unavailable",
                    "--require-clean",
                    "--format",
                    "json",
                    stdout=StringIO(),
                )

        uploaded_file = UploadedFile.objects.get(attachment_id="att_file_scan_clamav_unavailable")
        self.assertEqual(uploaded_file.status, UploadedFileStatus.REJECTED)
        self.assertEqual(uploaded_file.scan_status, "rejected")
        self.assertEqual(uploaded_file.metadata["scan_result"]["findings"][0]["reason"], "connection_failed")

    def test_persona_catalog_smoke_command_covers_all_demo_personas(self):
        output = StringIO()

        call_command("smoke_persona_catalog", "--format", "json", stdout=output)

        body = json.loads(output.getvalue())
        self.assertEqual(body["status"], "pass")
        self.assertEqual(body["persona_count"], 5)
        self.assertEqual(
            {run["persona_id"] for run in body["runs"]},
            {
                "school_zone_fine_notice_parent",
                "accident_scene_photo_driver",
                "blackbox_video_fault_driver",
                "traffic_law_question_citizen",
                "saved_report_returning_user",
            },
        )


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
            {"fine_notice", "fault_ratio", "law_question", "report_redownload"},
        )
        self.assertIn(
            "school_zone_fine_notice_parent",
            {item["persona_id"] for item in body["available_personas"]},
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
        self.assertIn("X-Requested-With", response["Access-Control-Allow-Headers"])

    def test_public_mock_endpoints_do_not_require_authorization_header(self):
        public_client = Client()

        health_response = public_client.get("/api/health/")
        scenarios_response = public_client.get("/api/mock/chat/scenarios/")

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(scenarios_response.status_code, 200)
        self.assertIn("personas", scenarios_response.json())

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

    def test_guest_can_submit_canonical_chat_without_bearer_token(self):
        response = Client(HTTP_X_GUEST_ID="gst_chat_first").post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_guest_chat_first",
                "conversation_save_state": "pending",
                "user_text": "로그인 전에 상담부터 진행합니다.",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["persistence"]["conversation_save_state"], "pending")
        self.assertEqual(body["supervisor_execution"]["orchestration_mode"], "background_session")
        self.assertGreater(body["supervisor_execution"]["agent_invocations_saved"], 0)
        self.assertTrue(
            AgentInvocation.objects.filter(job__session__session_id="ses_guest_chat_first").exists()
        )

    def test_guest_persona_smoke_can_register_file_and_preview_report_without_bearer_token(self):
        guest_client = Client(HTTP_X_GUEST_ID="gst_persona_smoke")
        session_id = "ses_guest_persona_smoke"

        file_response = guest_client.post(
            "/api/files/",
            data={
                "session_id": session_id,
                "purpose": "accident_scene",
                "filename": "guest-scene.txt",
                "content_type": "text/plain",
                "size_bytes": 0,
            },
            content_type="application/json",
        )
        self.assertEqual(file_response.status_code, 200)
        attachment = file_response.json()["attachment"]
        call_command("process_uploaded_file_scans", "--limit", "1", stdout=StringIO())

        message_response = guest_client.post(
            "/api/chat/messages/",
            data={
                "session_id": session_id,
                "conversation_save_state": "pending",
                "user_text": "신호 없는 교차로 사고 사진이 있고 과실비율을 알고 싶습니다.",
                "persona_id": "accident_scene_photo_driver",
                "attachments": [{"attachment_id": attachment["attachment_id"]}],
            },
            content_type="application/json",
        )
        self.assertEqual(message_response.status_code, 200)
        message_body = message_response.json()
        job_id = message_body["supervisor_execution"]["job_id"]
        self.assertEqual(message_body["persona_run"]["persona"]["persona_id"], "accident_scene_photo_driver")

        report_response = guest_client.post(
            "/api/reports/",
            data={
                "action": "preview",
                "report_id": "rep_guest_persona_smoke",
                "job_id": job_id,
                "session_id": session_id,
                "report_type": "general",
                "title": "비회원 persona smoke 리포트",
            },
            content_type="application/json",
        )
        self.assertEqual(report_response.status_code, 200)
        report_body = report_response.json()
        self.assertEqual(report_body["status"], "preview_ready")
        self.assertEqual(report_body["persistence"]["table"], "reports")
        self.assertEqual(report_body["persistence"]["status"], "skipped")
        self.assertEqual(report_body["persistence"]["reason"], "preview_not_persisted")
        self.assertFalse(Report.objects.filter(report_id="rep_guest_persona_smoke").exists())

    def test_guest_report_save_and_download_actions_require_login(self):
        guest_client = Client(HTTP_X_GUEST_ID="gst_report_action_guard")

        for action in ("save", "download"):
            with self.subTest(action=action):
                response = guest_client.post(
                    "/api/reports/",
                    data={
                        "action": action,
                        "report_id": f"rep_guest_guard_{action}",
                        "session_id": "ses_guest_report_guard",
                    },
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 403)
                error = response.json()["error"]
                self.assertEqual(error["code"], "login_required")
                self.assertEqual(error["required_action"], "login")
                self.assertEqual(error["policy_version"], "report_action_policy.v1")
                self.assertEqual(error["subject"]["subject_type"], "guest")
                self.assertFalse(Report.objects.filter(report_id=f"rep_guest_guard_{action}").exists())

        download_response = guest_client.get("/api/reports/rep_guest_guard_download/download/")
        self.assertEqual(download_response.status_code, 403)
        download_error = download_response.json()["error"]
        self.assertEqual(download_error["code"], "login_required")
        self.assertEqual(download_error["action"], "report_download")

    def test_guest_cannot_promote_conversation_to_saved_state(self):
        guest_client = Client(HTTP_X_GUEST_ID="gst_save_state_guard")
        message_response = guest_client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_guest_save_state_guard",
                "conversation_save_state": "pending",
                "user_text": "로그인 전 상담은 저장 대기 상태입니다.",
            },
            content_type="application/json",
        )
        self.assertEqual(message_response.status_code, 200)

        save_response = guest_client.post(
            "/api/chat/save-state/",
            data={
                "session_id": "ses_guest_save_state_guard",
                "conversation_save_state": "saved",
            },
            content_type="application/json",
        )

        self.assertEqual(save_response.status_code, 403)
        error = save_response.json()["error"]
        self.assertEqual(error["code"], "login_required")
        self.assertEqual(error["action"], "conversation_save")
        self.assertEqual(error["policy_version"], "conversation_save_policy.v1")
        session = ChatSession.objects.get(session_id="ses_guest_save_state_guard")
        self.assertEqual(session.metadata["conversation_save_state"], "pending")

    def test_expired_guest_identity_is_rejected_before_guest_safe_state_changes(self):
        GuestIdentity.objects.create(
            guest_id="gst_expired_guard",
            status=GuestIdentityStatus.ACTIVE,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        guest_client = Client(HTTP_X_GUEST_ID="gst_expired_guard")

        cases = [
            (
                "chat_message",
                "post",
                "/api/chat/messages/",
                {
                    "session_id": "ses_expired_guest_guard",
                    "conversation_save_state": "pending",
                    "user_text": "만료된 guest는 새 상담으로 갱신해야 합니다.",
                },
            ),
            (
                "file_upload",
                "post",
                "/api/files/",
                {
                    "session_id": "ses_expired_guest_guard",
                    "purpose": "fine_notice",
                    "filename": "expired-guest.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 0,
                },
            ),
            (
                "file_list",
                "get",
                "/api/files/?session_id=ses_expired_guest_guard",
                None,
            ),
            (
                "report_preview",
                "post",
                "/api/reports/",
                {
                    "action": "preview",
                    "report_id": "rep_expired_guest_guard",
                    "session_id": "ses_expired_guest_guard",
                },
            ),
            (
                "save_state",
                "post",
                "/api/chat/save-state/",
                {
                    "session_id": "ses_expired_guest_guard",
                    "conversation_save_state": "pending",
                },
            ),
        ]

        for name, method, path, payload in cases:
            with self.subTest(name=name):
                if method == "get":
                    response = guest_client.get(path)
                else:
                    response = guest_client.post(path, data=payload, content_type="application/json")

                self.assertEqual(response.status_code, 401)
                error = response.json()["error"]
                self.assertEqual(error["code"], "guest_session_invalid")
                self.assertEqual(error["required_action"], "refresh_guest_session")
                self.assertEqual(error["reason"], "guest_expired")

        self.assertFalse(ChatSession.objects.filter(session_id="ses_expired_guest_guard").exists())
        self.assertFalse(UploadedFile.objects.filter(original_filename="expired-guest.pdf").exists())
        self.assertFalse(Report.objects.filter(report_id="rep_expired_guest_guard").exists())

    @override_settings(GOOGLE_AUTH_ALLOW_MOCK=False, APP_AUTH_ALLOW_MOCK_BEARER=False)
    def test_real_auth_mode_rejects_legacy_dev_mock_bearer(self):
        response = Client(HTTP_AUTHORIZATION="Bearer dev-mock-token").post(
            "/api/chat/messages/",
            data={"session_id": "ses_real_auth_only", "user_text": "hello"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        error = response.json()["error"]
        self.assertEqual(error["code"], "token_invalid")
        self.assertEqual(error["auth"]["reason"], "app_jwt_required")

    @override_settings(APP_AUTH_ALLOW_MOCK_BEARER=False)
    def test_real_auth_mode_accepts_backend_app_jwt(self):
        login_response = Client().post(
            "/api/auth/login/",
            data={
                "provider": "google",
                "google_sub": "google-sub-real-mode",
                "email": "real.mode@example.com",
                "display_name": "Real Mode",
                "session_id": "ses_real_app_jwt",
            },
            content_type="application/json",
        )
        token = login_response.json()["access_token"]

        response = Client(HTTP_AUTHORIZATION=f"Bearer {token}").post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_real_app_jwt",
                "user_text": "app JWT로 상담을 진행합니다.",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["supervisor_execution"]["orchestration_mode"], "background_session")

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
        self.assertEqual(body["persistence"]["backend"], "postgresql")
        self.assertEqual(body["persistence"]["guest_identity_table"], "guest_identities")
        self.assertEqual(body["persistence"]["auth_events_table"], "auth_events")

        guest = GuestIdentity.objects.get(guest_id="gst_existing")
        event = AuthEvent.objects.get(event_id=body["persistence"]["event_id"])
        session = ChatSession.objects.get(session_id="ses_guest_chat")
        self.assertEqual(guest.status, GuestIdentityStatus.ACTIVE)
        self.assertEqual(event.guest, guest)
        self.assertEqual(event.event_type, "guest_session_created")
        self.assertEqual(session.metadata["auth_context"]["guest_id"], "gst_existing")
        self.assertEqual(session.metadata["auth_context"]["subject_type"], "guest")

    def test_google_login_issues_app_jwt_and_persists_auth_session(self):
        response = Client().post(
            "/api/auth/login/",
            data={
                "provider": "google",
                "google_sub": "google-sub-123",
                "email": "driver@example.com",
                "display_name": "Driver User",
                "guest_id": "gst_before_google",
                "session_id": "ses_google_login",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["api_surface"], "canonical_mock")
        self.assertEqual(body["contract_version"], "google_auth.v1")
        self.assertEqual(body["provider"], "google")
        self.assertEqual(body["token_type"], "Bearer")
        self.assertTrue(body["access_token"])
        self.assertEqual(body["subject"]["subject_type"], "user")
        self.assertEqual(body["subject"]["guest_id"], "gst_before_google")
        self.assertEqual(body["auth_session"]["verification"], "mock_google_subject")
        self.assertEqual(body["persistence"]["auth_session_table"], "auth_sessions")

        user = UserAccount.objects.get(user_id=body["subject"]["user_id"])
        auth_session = AuthSession.objects.get(auth_session_id=body["subject"]["auth_session_id"])
        session = ChatSession.objects.get(session_id="ses_google_login")
        self.assertEqual(user.email, "driver@example.com")
        self.assertEqual(user.display_name, "Driver User")
        self.assertEqual(user.auth_provider, "google")
        self.assertEqual(user.provider_subject, "google-sub-123")
        self.assertEqual(auth_session.user, user)
        self.assertEqual(auth_session.metadata["verification"], "mock_google_subject")
        self.assertEqual(session.owner_id, user.user_id)

        auth_me_response = Client(
            HTTP_AUTHORIZATION=f"Bearer {body['access_token']}",
            HTTP_X_GUEST_ID="gst_before_google",
        ).get("/api/auth/me/?session_id=ses_google_login")
        self.assertEqual(auth_me_response.status_code, 200)
        auth_me = auth_me_response.json()
        self.assertEqual(auth_me["subject"]["user_id"], user.user_id)
        self.assertEqual(auth_me["subject"]["auth_session_id"], auth_session.auth_session_id)
        self.assertEqual(auth_me["auth_session"]["verification"], "app_jwt_hmac")

    def test_google_code_login_persists_social_account_and_oauth_connection(self):
        response = Client().post(
            "/api/auth/google/code/",
            data={
                "provider": "google",
                "code": "mock_google_code:code-login",
                "purpose": "LOGIN",
                "scope": "openid email profile",
                "email": "code.driver@example.com",
                "display_name": "Code Driver",
                "guest_id": "gst_google_code",
                "session_id": "ses_google_code",
            },
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XmlHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["contract_version"], "google_auth_code.v1")
        self.assertEqual(body["auth_mode"], "authorization_code_mock")
        self.assertEqual(body["google"]["connected"], True)
        self.assertEqual(body["google"]["oauth_connection"]["token_storage"], "backend_only")
        self.assertNotIn("_private_oauth_tokens", body)
        self.assertNotIn("mock_google_refresh", json.dumps(body["google"]))
        self.assertNotIn("refresh_token_encrypted", json.dumps(body["google"]))
        self.assertTrue(body["access_token"])
        self.assertEqual(body["persistence"]["social_account_table"], "social_accounts")
        self.assertEqual(body["persistence"]["oauth_connection_table"], "oauth_connections")

        user = UserAccount.objects.get(user_id=body["subject"]["user_id"])
        social_account = SocialAccount.objects.get(user=user, provider="google")
        oauth_connection = OAuthConnection.objects.get(user=user, provider="google")
        auth_session = AuthSession.objects.get(auth_session_id=body["subject"]["auth_session_id"])
        self.assertEqual(user.email, "code.driver@example.com")
        self.assertEqual(user.display_name, "Code Driver")
        self.assertEqual(social_account.provider_user_id, user.provider_subject)
        self.assertEqual(social_account.email, "code.driver@example.com")
        self.assertEqual(oauth_connection.granted_scopes, "openid email profile")
        self.assertTrue(oauth_connection.access_token_encrypted.startswith("v1."))
        self.assertTrue(oauth_connection.refresh_token_encrypted.startswith("v1."))
        self.assertNotIn("mock_google_refresh", oauth_connection.refresh_token_encrypted)
        self.assertEqual(auth_session.metadata["google"]["token_storage"], "backend_only")
        self.assertTrue(
            AuthEvent.objects.filter(
                event_type="auth_google_code_completed",
                auth_session=auth_session,
            ).exists()
        )

    def test_mvp_guest_chat_login_upload_scan_report_keeps_session_spine(self):
        session_id = "ses_mvp_auth_spine"
        guest_response = Client().post(
            "/api/auth/guest-session/",
            data={"session_id": session_id},
            content_type="application/json",
        )
        self.assertEqual(guest_response.status_code, 200)
        guest_id = guest_response.json()["guest"]["guest_id"]

        guest_client = Client(HTTP_X_GUEST_ID=guest_id)
        chat_response = guest_client.post(
            "/api/chat/messages/",
            data={
                "session_id": session_id,
                "conversation_save_state": "pending",
                "user_text": "어린이보호구역 과태료 고지서를 받았습니다.",
            },
            content_type="application/json",
        )
        self.assertEqual(chat_response.status_code, 200)
        chat_body = chat_response.json()
        self.assertEqual(chat_body["session_id"], session_id)
        job_id = (
            chat_body.get("persistence", {}).get("job_id")
            or chat_body.get("supervisor_execution", {}).get("job_id")
            or "job_mvp_auth_spine"
        )

        login_response = Client().post(
            "/api/auth/google/code/",
            data={
                "provider": "google",
                "code": "mock_google_code:mvp-spine",
                "purpose": "LOGIN",
                "scope": "openid email profile",
                "email": "mvp.spine@example.com",
                "display_name": "MVP Spine User",
                "guest_id": guest_id,
                "session_id": session_id,
            },
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XmlHttpRequest",
        )
        self.assertEqual(login_response.status_code, 200)
        login_body = login_response.json()
        user_id = login_body["subject"]["user_id"]
        auth_session_id = login_body["subject"]["auth_session_id"]
        auth_client = Client(
            HTTP_AUTHORIZATION=f"Bearer {login_body['access_token']}",
            HTTP_X_GUEST_ID=guest_id,
            HTTP_X_AUTH_SESSION_ID=auth_session_id,
        )

        save_response = auth_client.post(
            "/api/chat/save-state/",
            data={
                "session_id": session_id,
                "conversation_save_state": "saved",
                "conversation_save_source": "mvp_auth_spine_test",
            },
            content_type="application/json",
        )
        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(save_response.json()["conversation_save"]["conversation_save_state"], "saved")

        upload_response = auth_client.post(
            "/api/files/",
            data={
                "session_id": session_id,
                "purpose": "fine_notice",
                "filename": "notice.pdf",
                "content_type": "application/pdf",
                "size_bytes": 0,
            },
            content_type="application/json",
        )
        self.assertEqual(upload_response.status_code, 200)
        attachment = upload_response.json()["attachment"]
        self.assertEqual(attachment["session_id"], session_id)

        scan_response = auth_client.post(
            f"/api/files/{attachment['attachment_id']}/scan/",
            data={"session_id": session_id},
            content_type="application/json",
        )
        self.assertEqual(scan_response.status_code, 200)
        self.assertEqual(scan_response.json()["attachment"]["scan_status"], "clean")

        report_response = auth_client.post(
            "/api/reports/",
            data={
                "action": "save",
                "report_id": "rep_mvp_auth_spine",
                "job_id": job_id,
                "session_id": session_id,
                "report_type": "general",
                "title": "MVP auth spine report",
            },
            content_type="application/json",
        )
        self.assertEqual(report_response.status_code, 200)
        self.assertEqual(report_response.json()["persistence"]["status"], "metadata_saved")

        session = ChatSession.objects.get(session_id=session_id)
        uploaded_file = UploadedFile.objects.get(attachment_id=attachment["attachment_id"])
        report = Report.objects.get(report_id="rep_mvp_auth_spine")
        auth_session = AuthSession.objects.get(auth_session_id=auth_session_id)
        self.assertEqual(session.owner_id, user_id)
        self.assertEqual(session.metadata["auth_context"]["guest_id"], guest_id)
        self.assertEqual(uploaded_file.owner_id, user_id)
        self.assertEqual(uploaded_file.session, session)
        self.assertEqual(report.owner_id, user_id)
        self.assertEqual(report.session, session)
        self.assertEqual(auth_session.user.user_id, user_id)
        self.assertEqual(auth_session.guest.guest_id, guest_id)

    def test_mvp_e2e_demo_spine_upload_worker_report_history(self):
        session_id = "ses_mvp_e2e_demo"
        guest_response = Client().post(
            "/api/auth/guest-session/",
            data={"session_id": session_id},
            content_type="application/json",
        )
        self.assertEqual(guest_response.status_code, 200)
        guest_id = guest_response.json()["guest"]["guest_id"]

        login_response = Client().post(
            "/api/auth/google/code/",
            data={
                "provider": "google",
                "code": "mock_google_code:mvp-e2e-demo",
                "purpose": "LOGIN",
                "scope": "openid email profile",
                "email": "mvp.e2e@example.com",
                "display_name": "MVP E2E Demo User",
                "guest_id": guest_id,
                "session_id": session_id,
            },
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XmlHttpRequest",
        )
        self.assertEqual(login_response.status_code, 200)
        login_body = login_response.json()
        auth_session_id = login_body["subject"]["auth_session_id"]
        auth_client = Client(
            HTTP_AUTHORIZATION=f"Bearer {login_body['access_token']}",
            HTTP_X_GUEST_ID=guest_id,
            HTTP_X_AUTH_SESSION_ID=auth_session_id,
        )

        upload_response = auth_client.post(
            "/api/files/",
            data={
                "session_id": session_id,
                "purpose": "fine_notice",
                "filename": "demo-notice.pdf",
                "content_type": "application/pdf",
                "size_bytes": 0,
            },
            content_type="application/json",
        )
        self.assertEqual(upload_response.status_code, 200)
        attachment = upload_response.json()["attachment"]

        scan_response = auth_client.post(
            f"/api/files/{attachment['attachment_id']}/scan/",
            data={"session_id": session_id},
            content_type="application/json",
        )
        self.assertEqual(scan_response.status_code, 200)
        self.assertEqual(scan_response.json()["attachment"]["scan_status"], "clean")

        message_response = auth_client.post(
            "/api/chat/messages/",
            data={
                "session_id": session_id,
                "conversation_save_state": "saved",
                "user_text": "Prepare an MVP demo report from this uploaded fine notice.",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
                "execution_mode": "async_worker",
                "attachments": [{"attachment_id": attachment["attachment_id"]}],
            },
            content_type="application/json",
        )
        self.assertEqual(message_response.status_code, 200)
        message_body = message_response.json()
        self.assertEqual(message_body["execution_mode"], "async_worker")
        self.assertEqual(message_body["status"], "queued")
        self.assertEqual(message_body["persistence"]["progress_state"]["state"], "queued")
        self.assertEqual(message_body["attachments"][0]["scan_status"], "clean")
        self.assertNotIn("scan_gate", message_body)
        self.assertTrue(message_body["work_item"]["work_item_id"])

        worker_response = auth_client.post(
            "/api/agents/work-items/process/",
            data={"limit": 1},
            content_type="application/json",
        )
        self.assertEqual(worker_response.status_code, 200)
        worker_body = worker_response.json()
        self.assertEqual(worker_body["processed"], 1)
        self.assertEqual(worker_body["work_items"][0]["progress_state"]["state"], "success")
        job_id = message_body["work_item"]["job_id"]
        job = AnalysisJob.objects.get(job_id=job_id)
        self.assertIn(job.status, {AnalysisJobStatus.SUCCESS, AnalysisJobStatus.PARTIAL})
        self.assertGreater(job.agent_results.count(), 0)

        report_response = auth_client.post(
            "/api/reports/",
            data={
                "action": "save",
                "report_id": "rep_mvp_e2e_demo",
                "job_id": job_id,
                "session_id": session_id,
                "report_type": "general",
                "title": "MVP E2E demo report",
            },
            content_type="application/json",
        )
        self.assertEqual(report_response.status_code, 200)
        report_body = report_response.json()
        self.assertEqual(report_body["persistence"]["status"], "metadata_saved")
        self.assertEqual(report_body["persistence"]["report_quality"]["contract_version"], "report_quality.v1")
        self.assertEqual(report_body["persistence"]["report_quality"]["analysis_job_status"], job.status)

        download_response = auth_client.get("/api/reports/rep_mvp_e2e_demo/download/")
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response["Content-Type"], "application/pdf")
        self.assertIn('filename="rep_mvp_e2e_demo.pdf"', download_response["Content-Disposition"])
        self.assertTrue(download_response.content.startswith(b"%PDF"))
        download_body = extract_pdf_text(download_response.content)
        if download_body:
            self.assertIn("analysis_job_status:", download_body)
            self.assertIn("partial_report:", download_body)

        summary_response = auth_client.get(f"/api/mypage/summary/?session_id={session_id}")
        self.assertEqual(summary_response.status_code, 200)
        summary_body = summary_response.json()
        self.assertEqual(summary_body["saved_reports"], 1)
        self.assertTrue(any(item["job_id"] == job_id for item in summary_body["cases"]))

        session_history_response = auth_client.get(f"/api/history/?session_id={session_id}")
        self.assertEqual(session_history_response.status_code, 200)
        session_history_types = {event["event_type"] for event in session_history_response.json()["events"]}
        self.assertIn("chat_message_created", session_history_types)
        self.assertIn("report_saved", session_history_types)

        job_history_response = auth_client.get(f"/api/history/?session_id={session_id}&job_id={job_id}")
        self.assertEqual(job_history_response.status_code, 200)
        job_history_types = {event["event_type"] for event in job_history_response.json()["events"]}
        self.assertIn("report_saved", job_history_types)

    def test_google_code_login_requires_popup_csrf_header(self):
        response = Client().post(
            "/api/auth/google/code/",
            data={
                "provider": "google",
                "code": "mock_google_code:missing-header",
                "session_id": "ses_google_code_missing_header",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        error = response.json()["error"]
        self.assertEqual(error["code"], "forbidden")
        self.assertEqual(error["auth"]["reason"], "invalid_google_code_request_header")

    @override_settings(
        GOOGLE_AUTH_ALLOW_MOCK=False,
        GOOGLE_CLIENT_ID="real-google-client",
        GOOGLE_CLIENT_SECRET="x",
        GOOGLE_POPUP_REDIRECT_URI="http://127.0.0.1:5173",
    )
    def test_google_code_login_mock_off_uses_backend_token_exchange(self):
        class FakeGoogleResponse:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "access_token": "real_google_access_token",
                        "refresh_token": "real_google_refresh_token",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "scope": "openid email profile",
                        "profile": {
                            "sub": "real-google-sub",
                            "email": "real.driver@example.com",
                            "email_verified": True,
                            "display_name": "Real Driver",
                            "verification": "google_token_exchange_smoke",
                        },
                    }
                ).encode("utf-8")

        with patch("app.services.google_auth_service.urllib_request.urlopen", return_value=FakeGoogleResponse()):
            response = Client().post(
                "/api/auth/google/code/",
                data={
                    "provider": "google",
                    "code": "real-auth-code",
                    "purpose": "LOGIN",
                    "scope": "openid email profile",
                    "guest_id": "gst_real_google_code",
                    "session_id": "ses_real_google_code",
                    "redirect_uri": "http://127.0.0.1:5173",
                },
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["auth_mode"], "authorization_code")
        self.assertEqual(body["user"]["email"], "real.driver@example.com")
        self.assertNotIn("_private_oauth_tokens", body)
        self.assertNotIn("real_google_refresh_token", json.dumps(body))

        user = UserAccount.objects.get(user_id=body["subject"]["user_id"])
        oauth_connection = OAuthConnection.objects.get(user=user, provider="google")
        self.assertTrue(oauth_connection.access_token_encrypted.startswith("v1."))
        self.assertNotIn("real_google_access_token", oauth_connection.access_token_encrypted)
        self.assertNotIn("real_google_refresh_token", oauth_connection.refresh_token_encrypted)

    def test_auth_refresh_issues_app_jwt_and_keeps_auth_session_active(self):
        login_response = Client().post(
            "/api/auth/login/",
            data={
                "provider": "google",
                "google_sub": "google-sub-refresh",
                "email": "refresh.driver@example.com",
                "display_name": "Refresh Driver",
                "guest_id": "gst_refresh_before_login",
                "session_id": "ses_token_refresh",
            },
            content_type="application/json",
        )
        self.assertEqual(login_response.status_code, 200)
        login = login_response.json()

        response = Client(HTTP_AUTHORIZATION=f"Bearer {login['access_token']}").post(
            "/api/auth/refresh/",
            data={
                "guest_id": "gst_refresh_before_login",
                "session_id": "ses_token_refresh",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["contract_version"], "auth_token_refresh.v1")
        self.assertEqual(body["auth_state"], "authenticated")
        self.assertEqual(body["token_type"], "Bearer")
        self.assertTrue(body["access_token"])
        self.assertNotEqual(body["access_token"], login["access_token"])
        self.assertEqual(body["subject"]["auth_session_id"], login["subject"]["auth_session_id"])
        self.assertEqual(body["auth_session"]["status"], "active")
        self.assertEqual(body["auth_session"]["refresh_policy"], "valid_app_jwt_required")
        self.assertEqual(body["persistence"]["auth_session_status"], AuthSessionStatus.ACTIVE)

        auth_session = AuthSession.objects.get(auth_session_id=body["subject"]["auth_session_id"])
        self.assertEqual(auth_session.status, AuthSessionStatus.ACTIVE)
        self.assertIsNone(auth_session.revoked_at)
        self.assertIsNotNone(auth_session.issued_at)
        self.assertIsNotNone(auth_session.expires_at)
        self.assertEqual(auth_session.metadata["source"], "auth_refresh")
        self.assertTrue(
            AuthEvent.objects.filter(
                event_type="auth_token_refreshed",
                auth_session=auth_session,
            ).exists()
        )

        auth_me_response = Client(
            HTTP_AUTHORIZATION=f"Bearer {body['access_token']}",
            HTTP_X_GUEST_ID="gst_refresh_before_login",
        ).get("/api/auth/me/?session_id=ses_token_refresh")
        self.assertEqual(auth_me_response.status_code, 200)
        auth_me = auth_me_response.json()
        self.assertEqual(auth_me["subject"]["auth_session_id"], auth_session.auth_session_id)
        self.assertEqual(auth_me["subject"]["user_id"], body["subject"]["user_id"])

    def test_auth_refresh_rejects_non_app_jwt_bearer(self):
        response = Client(HTTP_AUTHORIZATION="Bearer dev-mock-token").post(
            "/api/auth/refresh/",
            data={"guest_id": "gst_refresh_invalid", "session_id": "ses_refresh_invalid"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response["WWW-Authenticate"],
            'Bearer error="token_invalid", error_description="app_jwt_required"',
        )
        error = response.json()["error"]
        self.assertEqual(error["contract_version"], "auth_error.v1")
        self.assertEqual(error["code"], "token_invalid")
        self.assertEqual(error["auth"]["reason"], "app_jwt_required")

    def test_auth_logout_revokes_auth_session_and_returns_client_action(self):
        login_response = Client().post(
            "/api/auth/login/",
            data={
                "provider": "google",
                "google_sub": "google-sub-logout",
                "email": "logout.driver@example.com",
                "display_name": "Logout Driver",
                "guest_id": "gst_logout_before_login",
                "session_id": "ses_token_logout",
            },
            content_type="application/json",
        )
        self.assertEqual(login_response.status_code, 200)
        login = login_response.json()

        response = Client(HTTP_AUTHORIZATION=f"Bearer {login['access_token']}").post(
            "/api/auth/logout/",
            data={
                "guest_id": "gst_logout_before_login",
                "session_id": "ses_token_logout",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["contract_version"], "auth_logout.v1")
        self.assertEqual(body["auth_state"], "anonymous")
        self.assertFalse(body["subject"]["is_authenticated"])
        self.assertEqual(body["auth_session"]["status"], "revoked")
        self.assertEqual(body["client_action"]["clear_access_token"], True)
        self.assertEqual(body["client_action"]["clear_google_profile"], True)
        self.assertEqual(body["client_action"]["next_auth_state"], "guest")
        self.assertEqual(body["persistence"]["auth_session_status"], AuthSessionStatus.REVOKED)

        auth_session = AuthSession.objects.get(auth_session_id=body["subject"]["auth_session_id"])
        self.assertEqual(auth_session.status, AuthSessionStatus.REVOKED)
        self.assertIsNotNone(auth_session.revoked_at)
        self.assertEqual(auth_session.metadata["source"], "auth_logout")
        self.assertTrue(auth_session.metadata["client_action"]["clear_access_token"])
        self.assertTrue(
            AuthEvent.objects.filter(
                event_type="auth_logout_completed",
                auth_session=auth_session,
            ).exists()
        )
        session = ChatSession.objects.get(session_id="ses_token_logout")
        self.assertEqual(session.metadata["auth_context"]["auth_state"], "guest")

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
        self.assertEqual(body["persistence"]["auth_session_table"], "auth_sessions")

        user = UserAccount.objects.get(user_id="usr_mock")
        guest = GuestIdentity.objects.get(guest_id="gst_before_login")
        auth_session = AuthSession.objects.get(auth_session_id="auth_dev_mock")
        session = ChatSession.objects.get(session_id="ses_auth_me")
        event = AuthEvent.objects.get(event_id=body["persistence"]["event_id"])
        self.assertEqual(auth_session.user, user)
        self.assertEqual(auth_session.guest, guest)
        self.assertEqual(auth_session.subject_id, "user:usr_mock")
        self.assertEqual(event.auth_session, auth_session)
        self.assertEqual(session.owner_id, "usr_mock")
        self.assertEqual(session.metadata["auth_context"]["auth_session_id"], "auth_dev_mock")

    def test_auth_me_can_report_guest_subject_without_bearer(self):
        response = Client().get("/api/auth/me/", HTTP_X_GUEST_ID="guest_header")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["auth_state"], "guest")
        self.assertEqual(body["guest"]["guest_id"], "gst_guest_header")
        self.assertEqual(body["subject"]["subject_type"], "guest")
        self.assertFalse(body["subject"]["is_authenticated"])
        self.assertEqual(body["persistence"]["guest_identity_table"], "guest_identities")
        self.assertTrue(GuestIdentity.objects.filter(guest_id="gst_guest_header").exists())
        self.assertTrue(
            AuthEvent.objects.filter(
                event_type="auth_me_checked",
                subject_id="guest:gst_guest_header",
            ).exists()
        )

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

    def test_canonical_chat_message_blocks_when_usage_quota_exceeded(self):
        UsageQuota.objects.create(
            quota_id="quota_user_usr_mock_chat_message",
            subject_id="user:usr_mock",
            scope="chat_message",
            limit_count=1,
            used_count=1,
        )

        response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_quota_blocked",
                "user_text": "한도 초과 확인",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 429)
        error = response.json()["error"]
        self.assertEqual(error["contract_version"], "rate_limit.v1")
        self.assertEqual(error["code"], "rate_limit_exceeded")
        self.assertEqual(error["usage"]["scope"], "chat_message")
        self.assertFalse(ChatMessage.objects.filter(session__session_id="ses_quota_blocked").exists())
        usage_event = UsageEvent.objects.get(scope="chat_message", subject_id="user:usr_mock")
        self.assertEqual(usage_event.amount, 0)
        self.assertEqual(usage_event.metadata["status"], "blocked")

    def test_usage_policy_seeds_free_subscription_and_code_items(self):
        response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_free_policy",
                "user_text": "무료 회원 quota 정책 확인",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        usage = response.json()["usage"]
        self.assertEqual(usage["plan_code"], "free")
        self.assertEqual(usage["limit_count"], 100)
        self.assertEqual(usage["policy_code_item"], "usage_quota_policy:free")
        self.assertTrue(Subscription.objects.filter(user__user_id="usr_mock", plan_code="free").exists())
        code_item = CodeItem.objects.get(group__group_code="usage_quota_policy", code="free")
        self.assertEqual(code_item.metadata["limits"]["chat_message"], 100)
        quota = UsageQuota.objects.get(subject_id="user:usr_mock", scope="chat_message")
        self.assertEqual(quota.metadata["plan_code"], "free")
        self.assertEqual(quota.metadata["policy_code_item"], "usage_quota_policy:free")

    def test_usage_policy_uses_paid_subscription_limit(self):
        user = UserAccount.objects.create(user_id="usr_paid", status=UserAccountStatus.ACTIVE)
        Subscription.objects.create(
            subscription_id="sub_paid_policy",
            user=user,
            plan_code="paid",
            status=SubscriptionStatus.ACTIVE,
        )
        paid_client = Client(HTTP_AUTHORIZATION="Bearer usr_paid:any")

        response = paid_client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_paid_policy",
                "user_text": "유료 회원 quota 정책 확인",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        usage = response.json()["usage"]
        self.assertEqual(usage["plan_code"], "paid")
        self.assertEqual(usage["subscription_id"], "sub_paid_policy")
        self.assertEqual(usage["limit_count"], 500)
        self.assertEqual(usage["policy_code_item"], "usage_quota_policy:paid")
        usage_event = UsageEvent.objects.get(subject_id="user:usr_paid", scope="chat_message")
        self.assertEqual(usage_event.metadata["plan_code"], "paid")
        self.assertEqual(usage_event.metadata["subscription_id"], "sub_paid_policy")

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

    def test_mypage_summary_denies_other_owner_query(self):
        other_client = Client(HTTP_AUTHORIZATION="Bearer usr_other:any")

        response = other_client.get("/api/mypage/summary/?owner_id=usr_mock")

        self.assertEqual(response.status_code, 403)
        error = response.json()["error"]
        self.assertEqual(error["contract_version"], "object_access.v1")
        self.assertEqual(error["code"], "object_access_denied")
        self.assertEqual(error["access"]["reason"], "owner_mismatch")
        self.assertEqual(error["access"]["resource"]["type"], "mypage")

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
        self.assertEqual(body["storage"]["backend"], "postgresql")
        self.assertEqual(body["storage"]["policy"], "standard_light")
        self.assertEqual(body["storage"]["table"], "history_events")
        self.assertEqual(body["history_policy"]["policy_version"], "history_operating_policy.v1")
        self.assertEqual(body["history_policy"]["retention"]["applied_subject_type"], "user")
        self.assertEqual(body["history_policy"]["retention"]["applied_days"], 365)
        self.assertTrue(body["after_service_summary"]["available"])
        self.assertTrue(body["after_service_summary"]["excludes_sensitive_payload"])
        events = body["events"]
        self.assertIn("chat_message_created", {event["event_type"] for event in events})
        chat_event = next(event for event in events if event["event_type"] == "chat_message_created")
        self.assertEqual(chat_event["actor"]["guest_id"], "gst_history")
        self.assertEqual(chat_event["subject"]["session_id"], "ses_history_api")
        self.assertFalse(chat_event["privacy"]["contains_user_text"])
        stored_event = HistoryEvent.objects.get(event_id=chat_event["event_id"])
        self.assertEqual(stored_event.event_type, "chat_message_created")
        self.assertEqual(stored_event.subject_session_id, "ses_history_api")
        self.assertEqual(stored_event.actor_guest_id, "gst_history")
        self.assertNotIn(raw_user_text, json.dumps(events, ensure_ascii=False))
        self.assertNotIn("user_text", json.dumps([event["metadata"] for event in events], ensure_ascii=False))

    def test_history_endpoint_applies_guest_retention_cutoff(self):
        old_event = HistoryEvent.objects.create(
            event_id="evt_old_guest_history",
            event_type="chat_message_created",
            event_version="history_event.v1",
            occurred_at=timezone.now() - timedelta(days=8),
            actor_guest_id="gst_old_history",
            actor_auth_state="guest",
            subject_session_id="ses_old_history",
            source_execution_mode="canonical_mock",
            status="success",
            summary="old guest event",
            actor={"guest_id": "gst_old_history", "auth_state": "guest"},
            subject={"session_id": "ses_old_history"},
            source={"execution_mode": "canonical_mock"},
            metadata={"routing_intent": "fine_notice"},
            privacy={"risk_level": "low", "retention_policy": "standard_light"},
        )
        self.assertTrue(HistoryEvent.objects.filter(event_id=old_event.event_id).exists())
        events = list_history_event_records(guest_id="gst_old_history", subject_type="guest")

        self.assertEqual(events, [])

    def test_history_metadata_uses_allowlist_and_sensitive_blocklist(self):
        event = record_history_event_record(
            event_type="chat_message_created",
            status="success",
            summary="metadata policy check",
            actor={"user_id": "usr_mock", "auth_state": "authenticated"},
            subject={"session_id": "ses_metadata_policy"},
            source={"execution_mode": "canonical_mock"},
            metadata={
                "routing_intent": "fine_notice",
                "user_text": "원문은 저장되면 안 됩니다.",
                "debug_blob": "internal detail",
                "merge_policy": {"prompt": "secret prompt", "mode": "manual"},
            },
        )

        metadata = event["metadata"]
        self.assertEqual(metadata["routing_intent"], "fine_notice")
        self.assertEqual(metadata["merge_policy"], {"mode": "manual"})
        self.assertNotIn("user_text", metadata)
        self.assertNotIn("debug_blob", metadata)
        self.assertIn("debug_blob", metadata["metadata_policy"]["dropped_keys"])
        self.assertIn("user_text", metadata["metadata_policy"]["dropped_keys"])

    def test_history_endpoint_denies_other_guest_query(self):
        other_guest_client = Client(
            HTTP_AUTHORIZATION="Bearer dev-mock-token",
            HTTP_X_GUEST_ID="gst_other",
        )

        response = other_guest_client.get("/api/history/?guest_id=gst_history_owner")

        self.assertEqual(response.status_code, 403)
        error = response.json()["error"]
        self.assertEqual(error["contract_version"], "object_access.v1")
        self.assertEqual(error["code"], "object_access_denied")
        self.assertEqual(error["access"]["reason"], "guest_mismatch")
        self.assertEqual(error["access"]["resource"]["type"], "history")

    def test_explicit_mock_history_endpoint_stays_sidecar_only(self):
        response = self.client.post(
            "/api/mock/chat/messages/",
            data={
                "session_id": "ses_mock_history",
                "user_text": "mock history only",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        history_response = self.client.get("/api/mock/history/?session_id=ses_mock_history")

        self.assertEqual(history_response.status_code, 200)
        body = history_response.json()
        self.assertEqual(body["storage"]["backend"], "mock_sidecar_json")
        self.assertIn("chat_message_created", {event["event_type"] for event in body["events"]})
        self.assertFalse(HistoryEvent.objects.filter(subject_session_id="ses_mock_history").exists())

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
        self.assertEqual(session.owner_id, "usr_mock")
        self.assertEqual(job.owner_id, "usr_mock")
        self.assertEqual(job.routing_intent, "objection_request")
        self.assertEqual(job.mock_scenario, "fine_notice")
        self.assertEqual(job.status, AnalysisJobStatus.SUCCESS)
        self.assertEqual(job.analysis_plan_id, body["analysis_plan"]["plan_id"])
        self.assertEqual(job.metadata["analysis_plan"]["plan_id"], body["analysis_plan"]["plan_id"])
        self.assertEqual(job.metadata["assistant_message"], body["assistant_message"])
        self.assertEqual(body["supervisor_execution"]["orchestration_mode"], "background_session")
        self.assertEqual(body["supervisor_execution"]["job_id"], job.job_id)
        self.assertEqual(
            body["supervisor_execution"]["agent_results_saved"],
            len(body["supervisor_execution"]["node_results"]),
        )
        self.assertEqual(
            body["supervisor_execution"]["agent_invocations_saved"],
            len(body["supervisor_execution"]["node_results"]),
        )
        self.assertEqual(job.agent_results.count(), len(body["analysis_plan"]["steps"]))
        self.assertEqual(job.agent_invocations.count(), len(body["analysis_plan"]["steps"]))
        self.assertTrue(AiSession.objects.filter(ai_session_id=body["supervisor_execution"]["ai_session_id"]).exists())
        self.assertIn("supervisor_execution", job.metadata)
        self.assertNotIn("agent_input", job.metadata["supervisor_execution"])
        self.assertEqual(event.status, AnalysisJobStatus.SUCCESS)
        self.assertEqual(event.metadata["source"], "canonical_chat_message")
        self.assertEqual(body["usage"]["scope"], "chat_message")
        self.assertEqual(body["usage"]["usage_event_table"], "usage_events")
        usage_event = UsageEvent.objects.get(subject_id="user:usr_mock", scope="chat_message")
        self.assertEqual(usage_event.metadata["status"], "allowed")

    def test_canonical_chat_sync_request_marks_fine_notice_adapter_mode(self):
        response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_canonical_sync_fine",
                "user_text": "과태료 고지서를 실제 fine notice adapter로 확인해줘.",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
                "execution_mode": "sync",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        execution = body["supervisor_execution"]
        node_results = {item["node_code"]: item for item in execution["node_results"]}
        fine_notice_result = node_results["fine_notice_analysis"]

        self.assertEqual(execution["execution_mode"], "hybrid")
        self.assertEqual(fine_notice_result["execution_mode"], "sync")
        self.assertEqual(fine_notice_result["adapter_execution_mode"], "sync")
        self.assertIn("sync", fine_notice_result["adapter_modes"])
        self.assertEqual(
            fine_notice_result["structured_result"]["adapter_trace"]["adapter"],
            "ai.agents.fine_notice_analysis.graph",
        )

        invocation = AgentInvocation.objects.get(
            job__job_id=execution["job_id"],
            node_code="fine_notice_analysis",
        )
        self.assertEqual(invocation.execution_mode, "sync")
        self.assertEqual(invocation.metadata["adapter_context"]["execution_mode"], "sync")

    def test_canonical_chat_message_can_queue_worker_progress_flow(self):
        response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_chat_worker_progress",
                "conversation_save_state": "pending",
                "user_text": "Queue this chat message through the worker progress flow.",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
                "execution_mode": "async_worker",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["execution_mode"], "async_worker")
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["node_execution"]["status"], "queued")
        self.assertEqual(body["supervisor_execution"]["execution_mode"], "async_worker")
        self.assertEqual(body["supervisor_execution"]["node_results"], [])
        self.assertEqual(body["supervisor_execution"]["work_item"]["status"], AgentWorkItemStatus.QUEUED)
        self.assertEqual(body["persistence"]["status"], AgentWorkItemStatus.QUEUED)
        self.assertEqual(body["persistence"]["progress_state"]["state"], "queued")
        self.assertEqual(body["work_item"]["status"], AgentWorkItemStatus.QUEUED)

        job = AnalysisJob.objects.get(job_id=body["work_item"]["job_id"])
        work_item = AgentWorkItem.objects.get(work_item_id=body["work_item"]["work_item_id"])
        self.assertEqual(job.status, AnalysisJobStatus.QUEUED)
        self.assertEqual(work_item.status, AgentWorkItemStatus.QUEUED)
        self.assertEqual(job.agent_results.count(), 0)
        self.assertEqual(read_analysis_job_progress(job.job_id)["snapshot"]["status"], AnalysisJobStatus.QUEUED)

        queued_detail_response = self.client.get(f"/api/analysis/jobs/{job.job_id}/")
        self.assertEqual(queued_detail_response.status_code, 200)
        queued_detail = queued_detail_response.json()["job"]
        self.assertEqual(queued_detail["backend"], "postgresql")
        self.assertEqual(queued_detail["contract_version"], "analysis_job_detail.v1")
        self.assertEqual(queued_detail["progress_state"]["state"], "queued")
        self.assertEqual(queued_detail["work_item"]["work_item_id"], work_item.work_item_id)

        result = process_agent_work_items(limit=1)

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["work_items"][0]["progress_state"]["state"], "success")
        job.refresh_from_db()
        work_item.refresh_from_db()
        self.assertEqual(work_item.status, AgentWorkItemStatus.SUCCESS)
        self.assertIn(job.status, {AnalysisJobStatus.SUCCESS, AnalysisJobStatus.PARTIAL})
        self.assertGreater(job.agent_results.count(), 0)
        self.assertEqual(read_analysis_job_progress(job.job_id)["snapshot"]["status"], job.status)

        completed_detail_response = self.client.get(f"/api/analysis/jobs/{job.job_id}/")
        self.assertEqual(completed_detail_response.status_code, 200)
        completed_detail = completed_detail_response.json()["job"]
        self.assertEqual(completed_detail["status"], job.status)
        self.assertEqual(completed_detail["progress_state"]["state"], "success")
        self.assertGreater(completed_detail["agent_result_count"], 0)

    def test_canonical_chat_sync_request_runs_ready_fault_ratio_adapter_only(self):
        response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_canonical_sync_fault_ratio_hybrid",
                "conversation_save_state": "pending",
                "user_text": "사고 사진과 블랙박스 상황으로 과실 비율을 검토해줘.",
                "persona_id": "accident_scene_photo_driver",
                "execution_mode": "sync",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        execution = body["supervisor_execution"]
        node_results = {item["node_code"]: item for item in execution["node_results"]}
        text_ml_result = node_results["text_ml_case_search"]
        vision_result = node_results["vision_media_analysis"]

        self.assertEqual(execution["execution_mode"], "hybrid")
        self.assertEqual(text_ml_result["execution_mode"], "sync")
        self.assertEqual(text_ml_result["adapter_execution_mode"], "sync")
        self.assertIn("sync", text_ml_result["adapter_modes"])
        self.assertEqual(vision_result["execution_mode"], "mock")
        self.assertEqual(vision_result["adapter_execution_mode"], "mock")
        self.assertEqual(vision_result["adapter_modes"], ["mock"])

        structured_result = text_ml_result["structured_result"]
        self.assertEqual(
            structured_result["retrieval"]["adapter_source"],
            "fault_ratio_knowledge_agent",
        )
        self.assertIn("similar_cases", structured_result)
        self.assertIn("top_cases", structured_result)
        self.assertIn("ratio_range_label", structured_result)
        self.assertIn("recommended_evidence", structured_result)
        self.assertTrue(
            any(
                "TEXT_ML_CASE_SEARCH_SYNC_USE_ES" in limitation
                for limitation in text_ml_result["limitations"]
            )
        )

        invocations = AgentInvocation.objects.filter(
            job__job_id=execution["job_id"],
            node_code__in=["vision_media_analysis", "text_ml_case_search"],
        )
        self.assertEqual(invocations.count(), 2)
        invocation_modes = {
            invocation.node_code: invocation.execution_mode
            for invocation in invocations
        }
        self.assertEqual(invocation_modes["text_ml_case_search"], "sync")
        self.assertEqual(invocation_modes["vision_media_analysis"], "mock")

    def test_canonical_chat_message_covers_all_demo_personas_before_real_agents(self):
        for persona in list_demo_personas():
            with self.subTest(persona_id=persona["persona_id"]):
                session_id = f"ses_persona_{persona['persona_id']}"
                response = self.client.post(
                    "/api/chat/messages/",
                    data={
                        "session_id": session_id,
                        "conversation_save_state": "pending",
                        "user_text": persona["sample_user_text"],
                        "persona_id": persona["persona_id"],
                    },
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 200)
                body = response.json()
                expected_nodes = set(persona["expected_nodes"])

                self.assertEqual(body["api_surface"], "canonical_mock")
                self.assertEqual(body["execution_mode"], "mock")
                self.assertEqual(body["status"], "success")
                self.assertEqual(body["mock_scenario"], persona["scenario"])
                self.assertEqual(body["routing_intent"], persona["routing_intent"])
                self.assertEqual(body["persona_run"]["persona"]["persona_id"], persona["persona_id"])
                self.assertEqual(body["analysis_plan"]["persona_id"], persona["persona_id"])
                self.assertGreaterEqual(
                    {step["node_code"] for step in body["analysis_plan"]["steps"]},
                    expected_nodes,
                )
                self.assertEqual(body["reporting_payload"]["contract_version"], "reporting_payload.v1")
                self.assertEqual(bool(body["report_links"]), persona["report_action_ready"])

                job = AnalysisJob.objects.get(job_id=body["persistence"]["job_id"])
                self.assertEqual(job.session.session_id, session_id)
                self.assertEqual(job.mock_scenario, persona["scenario"])
                self.assertGreaterEqual(
                    set(job.agent_results.values_list("node_code", flat=True)),
                    expected_nodes,
                )
                self.assertGreaterEqual(
                    set(job.agent_invocations.values_list("node_code", flat=True)),
                    expected_nodes,
                )

                if persona["report_action_ready"]:
                    report_response = self.client.post(
                        "/api/reports/",
                        data={
                            "action": "download",
                            "report_id": f"rep_{persona['persona_id']}",
                            "job_id": job.job_id,
                            "session_id": session_id,
                        },
                        content_type="application/json",
                    )
                    self.assertEqual(report_response.status_code, 200)
                    report_body = report_response.json()
                    self.assertEqual(report_body["persistence"]["status"], "metadata_saved")
                    self.assertEqual(report_body["persistence"]["table"], Report._meta.db_table)

    def test_pending_conversation_is_not_promoted_to_history_or_mypage(self):
        response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_pending_save",
                "conversation_save_state": "pending",
                "user_text": "로그인 전에 먼저 상담만 진행합니다.",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["persistence"]["conversation_save_state"], "pending")
        self.assertFalse(HistoryEvent.objects.filter(subject_session_id="ses_pending_save").exists())

        mypage_response = self.client.get("/api/mypage/summary/?session_id=ses_pending_save")
        self.assertEqual(mypage_response.status_code, 200)
        self.assertEqual(mypage_response.json()["cases"], [])

        history_response = self.client.get("/api/history/?session_id=ses_pending_save")
        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(history_response.json()["events"], [])

    def test_saved_conversation_state_promotes_pending_case_to_history_and_mypage(self):
        message_response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_save_after_login",
                "conversation_save_state": "pending",
                "user_text": "이 상담은 나중에 저장할 예정입니다.",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )
        self.assertEqual(message_response.status_code, 200)
        message_body = message_response.json()
        job_id = message_body["persistence"]["job_id"]

        save_response = self.client.post(
            "/api/chat/save-state/",
            data={
                "session_id": "ses_save_after_login",
                "conversation_save_state": "saved",
            },
            content_type="application/json",
        )

        self.assertEqual(save_response.status_code, 200)
        save_body = save_response.json()["conversation_save"]
        self.assertEqual(save_body["conversation_save_state"], "saved")
        self.assertGreaterEqual(save_body["analysis_jobs_updated"], 1)

        job = AnalysisJob.objects.get(job_id=job_id)
        self.assertEqual(job.metadata["conversation_save_state"], "saved")
        session = ChatSession.objects.get(session_id="ses_save_after_login")
        self.assertEqual(session.metadata["conversation_save_state"], "saved")

        mypage_response = self.client.get("/api/mypage/summary/?session_id=ses_save_after_login")
        self.assertEqual(mypage_response.status_code, 200)
        cases = mypage_response.json()["cases"]
        self.assertIn(job_id, {case["job_id"] for case in cases})

        history_response = self.client.get("/api/history/?session_id=ses_save_after_login")
        self.assertEqual(history_response.status_code, 200)
        self.assertIn(
            "conversation_saved",
            {event["event_type"] for event in history_response.json()["events"]},
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

    def test_canonical_agent_plan_can_queue_and_process_worker_item(self):
        queue_response = self.client.post(
            "/api/agents/plans/run/",
            data={
                "session_id": "ses_worker_queue",
                "user_text": "Queue this fine notice analysis for the worker.",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
                "execution_mode": "async_worker",
            },
            content_type="application/json",
        )

        self.assertEqual(queue_response.status_code, 200)
        queued = queue_response.json()
        self.assertEqual(queued["node_execution"]["status"], "queued")
        self.assertEqual(queued["persistence"]["status"], AgentWorkItemStatus.QUEUED)
        work_item_id = queued["work_item"]["work_item_id"]
        work_item = AgentWorkItem.objects.get(work_item_id=work_item_id)
        job = AnalysisJob.objects.get(job_id=queued["work_item"]["job_id"])
        self.assertEqual(work_item.status, AgentWorkItemStatus.QUEUED)
        self.assertEqual(job.status, AnalysisJobStatus.QUEUED)
        self.assertEqual(job.events.first().status, AnalysisJobStatus.QUEUED)
        self.assertEqual(read_analysis_job_progress(job.job_id)["snapshot"]["status"], AnalysisJobStatus.QUEUED)

        process_response = self.client.post(
            "/api/agents/work-items/process/",
            data={"limit": 1},
            content_type="application/json",
        )

        self.assertEqual(process_response.status_code, 200)
        processed = process_response.json()
        self.assertEqual(processed["processed"], 1)
        work_item.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(work_item.status, AgentWorkItemStatus.SUCCESS)
        self.assertIn(job.status, {AnalysisJobStatus.SUCCESS, AnalysisJobStatus.PARTIAL})
        self.assertGreater(job.agent_invocations.count(), 0)
        self.assertGreater(job.agent_results.count(), 0)
        event_statuses = list(job.events.values_list("status", flat=True))
        self.assertIn(AnalysisJobStatus.QUEUED, event_statuses)
        self.assertIn(AnalysisJobStatus.RUNNING, event_statuses)
        self.assertIn(job.status, event_statuses)
        progress = read_analysis_job_progress(job.job_id)
        self.assertEqual(progress["snapshot"]["status"], job.status)
        self.assertEqual(progress["snapshot"]["active_node"], job.active_node)

    def test_agent_worker_management_command_processes_queued_item(self):
        queue_response = self.client.post(
            "/api/agents/plans/run/",
            data={
                "session_id": "ses_worker_command",
                "user_text": "Queue this job for the management command.",
                "mock_scenario": "fault_ratio",
                "mock_status": "success",
                "execution_mode": "async_worker",
            },
            content_type="application/json",
        )
        self.assertEqual(queue_response.status_code, 200)
        work_item_id = queue_response.json()["work_item"]["work_item_id"]

        call_command("process_agent_work_items", "--limit", "1", stdout=StringIO())

        work_item = AgentWorkItem.objects.get(work_item_id=work_item_id)
        self.assertEqual(work_item.status, AgentWorkItemStatus.SUCCESS)
        self.assertIn(work_item.job.status, {AnalysisJobStatus.SUCCESS, AnalysisJobStatus.PARTIAL})

    @override_settings(AGENT_WORKER_RETRY_BACKOFF_SECONDS=7, AGENT_WORKER_RETRY_BACKOFF_MAX_SECONDS=30)
    def test_agent_worker_retries_failed_item_with_backoff(self):
        queue_response = self.client.post(
            "/api/agents/plans/run/",
            data={
                "session_id": "ses_worker_retry",
                "user_text": "Queue this job and force a worker failure.",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
                "execution_mode": "async_worker",
            },
            content_type="application/json",
        )
        self.assertEqual(queue_response.status_code, 200)
        work_item_id = queue_response.json()["work_item"]["work_item_id"]

        with patch("app.services.agent_node_service.execute_mock_plan", side_effect=RuntimeError("boom")):
            result = process_agent_work_items(limit=1)

        self.assertEqual(result["processed"], 1)
        work_item = AgentWorkItem.objects.get(work_item_id=work_item_id)
        self.assertEqual(work_item.status, AgentWorkItemStatus.RETRYING)
        self.assertEqual(work_item.attempt_no, 1)
        self.assertEqual(work_item.error_code, "RuntimeError")
        self.assertEqual(work_item.result["retry_after_seconds"], 7)
        self.assertEqual(result["work_items"][0]["progress_state"]["state"], "retry_waiting")
        self.assertEqual(result["work_items"][0]["progress_state"]["work_item_status"], AgentWorkItemStatus.RETRYING)
        self.assertIsNotNone(work_item.next_run_at)
        self.assertGreater(work_item.next_run_at, timezone.now())
        self.assertEqual(work_item.job.status, AnalysisJobStatus.RUNNING)
        self.assertEqual(work_item.job.metadata["work_queue"]["progress_state"]["state"], "retry_waiting")

        retry_result = process_agent_work_item(work_item.work_item_id)
        self.assertEqual(retry_result["status"], "skipped")
        self.assertEqual(retry_result["reason"], "work_item_not_ready")

    def test_agent_worker_reclaims_stale_running_item(self):
        queue_response = self.client.post(
            "/api/agents/plans/run/",
            data={
                "session_id": "ses_worker_stale",
                "user_text": "Queue this job and simulate worker death.",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
                "execution_mode": "async_worker",
            },
            content_type="application/json",
        )
        self.assertEqual(queue_response.status_code, 200)
        work_item_id = queue_response.json()["work_item"]["work_item_id"]
        work_item = AgentWorkItem.objects.get(work_item_id=work_item_id)
        work_item.status = AgentWorkItemStatus.RUNNING
        work_item.attempt_no = 1
        work_item.max_attempts = 1
        work_item.locked_at = timezone.now() - timedelta(seconds=120)
        work_item.save(update_fields=["status", "attempt_no", "max_attempts", "locked_at", "updated_at"])

        result = process_agent_work_items(limit=1, stale_after_seconds=30)

        self.assertEqual(result["stale_requeued"], 1)
        self.assertEqual(result["processed"], 0)
        work_item.refresh_from_db()
        self.assertEqual(work_item.status, AgentWorkItemStatus.FAILED)
        self.assertEqual(work_item.error_code, "worker_lock_timeout")
        self.assertIsNone(work_item.locked_at)
        self.assertIsNotNone(work_item.completed_at)
        self.assertEqual(work_item.job.status, AnalysisJobStatus.FAILED)

    def test_agent_worker_management_command_can_run_bounded_loop(self):
        output = StringIO()

        call_command(
            "process_agent_work_items",
            "--loop",
            "--max-loops",
            "1",
            "--sleep-seconds",
            "1",
            stdout=output,
        )

        body = json.loads(output.getvalue())
        self.assertEqual(body["loop_iteration"], 1)
        self.assertEqual(body["contract_version"], "agent_worker_queue.v1")

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
        self.assertEqual(attachment["object_storage"]["policy_version"], "object_storage_adapter.v1")
        self.assertEqual(attachment["object_storage"]["backend"], "object_storage")
        self.assertEqual(attachment["object_storage"]["resource_type"], "uploaded_file")
        self.assertTrue(attachment["storage_uri"].startswith("s3://"))
        self.assertEqual(attachment["scan_status"], "not_started")
        self.assertTrue(attachment["privacy_risk"])
        self.assertEqual(attachment["checks"]["metadata_repository"], "uploaded_files")

        uploaded_file = UploadedFile.objects.get(attachment_id=attachment["attachment_id"])
        self.assertEqual(uploaded_file.session.session_id, "ses_canonical_files")
        self.assertEqual(uploaded_file.purpose, "fine_notice")
        self.assertEqual(uploaded_file.file_type, "image")
        self.assertEqual(uploaded_file.content_type, "image/jpeg")
        self.assertEqual(uploaded_file.size_bytes, 2048)
        self.assertEqual(uploaded_file.status, UploadedFileStatus.UPLOADED)
        self.assertEqual(uploaded_file.scan_status, "not_started")
        self.assertTrue(uploaded_file.storage_uri.startswith("s3://"))
        self.assertEqual(uploaded_file.metadata["mock_status"], "metadata_registered")
        self.assertEqual(uploaded_file.metadata["object_storage"]["backend"], "object_storage")
        self.assertEqual(uploaded_file.metadata["source_storage_uri"], f"mock://metadata/{attachment['attachment_id']}")
        self.assertEqual(uploaded_file.agent_handoff["storage_uri"], uploaded_file.storage_uri)

        detail = self.client.get(f"/api/files/{attachment['attachment_id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["api_surface"], "canonical_mock")
        self.assertEqual(detail.json()["attachment"]["object_storage"]["backend"], "object_storage")
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

    def test_canonical_files_endpoint_accepts_multipart_file_upload(self):
        upload = SimpleUploadedFile(
            "dashcam.mp4",
            b"mock video bytes",
            content_type="video/mp4",
        )

        response = self.client.post(
            "/api/files/",
            data={
                "session_id": "ses_canonical_upload",
                "purpose": "blackbox_video",
                "file": upload,
            },
        )

        self.assertEqual(response.status_code, 200)
        attachment = response.json()["attachment"]
        self.assertEqual(attachment["status"], UploadedFileStatus.UPLOADED)
        self.assertEqual(attachment["purpose"], "blackbox_video")
        self.assertEqual(attachment["type"], "video")
        self.assertEqual(attachment["content_type"], "video/mp4")
        self.assertEqual(attachment["original_filename"], "dashcam.mp4")
        self.assertGreater(attachment["size_bytes"], 0)
        self.assertTrue(attachment["storage_uri"].startswith("s3://"))

        uploaded_file = UploadedFile.objects.get(attachment_id=attachment["attachment_id"])
        self.assertEqual(uploaded_file.session.session_id, "ses_canonical_upload")
        self.assertEqual(uploaded_file.status, UploadedFileStatus.UPLOADED)
        self.assertEqual(uploaded_file.scan_status, "not_started")
        self.assertEqual(uploaded_file.metadata["mock_status"], "uploaded")
        self.assertTrue(uploaded_file.metadata["source_storage_uri"].startswith("mock://uploads/"))

    def test_file_scan_command_marks_upload_ready_for_agent_handoff(self):
        response = self.client.post(
            "/api/files/",
            data={
                "session_id": "ses_scan_ready",
                "purpose": "fine_notice",
                "filename": "notice-clean.txt",
                "content_type": "text/plain",
                "size_bytes": 128,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        attachment_id = response.json()["attachment"]["attachment_id"]

        output = StringIO()
        call_command("process_uploaded_file_scans", "--limit", "1", "--format", "json", stdout=output)
        batch = json.loads(output.getvalue())
        self.assertEqual(batch["contract_version"], "file_scan_batch.v1")
        self.assertEqual(batch["processed"], 1)
        self.assertEqual(batch["clean"], 1)

        uploaded_file = UploadedFile.objects.get(attachment_id=attachment_id)
        self.assertEqual(uploaded_file.status, UploadedFileStatus.READY)
        self.assertEqual(uploaded_file.scan_status, "clean")
        self.assertEqual(uploaded_file.metadata["scan_result"]["contract_version"], "file_scan_result.v1")
        self.assertEqual(uploaded_file.agent_handoff["scan_status"], "clean")

    def test_file_scan_endpoint_marks_upload_ready_for_frontend_handoff(self):
        response = self.client.post(
            "/api/files/",
            data={
                "session_id": "ses_scan_endpoint",
                "purpose": "fine_notice",
                "file": SimpleUploadedFile(
                    "notice.txt",
                    b"frontend scan endpoint bytes",
                    content_type="text/plain",
                ),
            },
        )
        self.assertEqual(response.status_code, 200)
        attachment_id = response.json()["attachment"]["attachment_id"]

        scan_response = self.client.post(
            f"/api/files/{attachment_id}/scan/",
            data={"session_id": "ses_scan_endpoint"},
            content_type="application/json",
        )

        self.assertEqual(scan_response.status_code, 200)
        body = scan_response.json()
        self.assertEqual(body["contract_version"], "file_scan_endpoint.v1")
        self.assertEqual(body["file_scan"]["status"], "clean")
        self.assertEqual(body["attachment"]["scan_status"], "clean")
        self.assertEqual(body["attachment"]["status"], UploadedFileStatus.READY)

    def test_canonical_chat_sync_reads_ready_uploaded_fine_notice_attachment(self):
        with tempfile.TemporaryDirectory() as object_root, tempfile.TemporaryDirectory() as upload_root, override_settings(
            OBJECT_STORAGE_LOCAL_ROOT=object_root,
            MOCK_UPLOAD_ROOT=upload_root,
            FILE_SCAN_PROVIDER="local_policy",
        ):
            file_response = self.client.post(
                "/api/files/",
                data={
                    "session_id": "ses_sync_uploaded_notice",
                    "purpose": "fine_notice",
                    "file": SimpleUploadedFile(
                        "notice.txt",
                        b"canonical fine notice bytes",
                        content_type="text/plain",
                    ),
                },
            )
            self.assertEqual(file_response.status_code, 200)
            attachment = file_response.json()["attachment"]

            call_command("process_uploaded_file_scans", "--limit", "1", stdout=StringIO())
            uploaded_file = UploadedFile.objects.get(attachment_id=attachment["attachment_id"])
            self.assertEqual(uploaded_file.status, UploadedFileStatus.READY)
            self.assertEqual(uploaded_file.metadata["object_storage_write"]["status"], "written")

            message_response = self.client.post(
                "/api/chat/messages/",
                data={
                    "session_id": "ses_sync_uploaded_notice",
                    "user_text": "uploaded fine notice attachment sync bridge",
                    "mock_scenario": "fine_notice",
                    "mock_status": "success",
                    "execution_mode": "sync",
                    "attachments": [{"attachment_id": attachment["attachment_id"]}],
                },
                content_type="application/json",
            )

            self.assertEqual(message_response.status_code, 200)
            body = message_response.json()
            self.assertEqual(body["attachments"][0]["attachment_id"], attachment["attachment_id"])
            self.assertEqual(body["attachments"][0]["scan_status"], "clean")
            execution = body["supervisor_execution"]
            node_results = {item["node_code"]: item for item in execution["node_results"]}
            fine_notice_result = node_results["fine_notice_analysis"]
            self.assertEqual(execution["execution_mode"], "hybrid")
            self.assertEqual(fine_notice_result["execution_mode"], "sync")
            self.assertEqual(
                fine_notice_result["structured_result"]["adapter_trace"]["input_source"],
                "attachment",
            )

    def test_chat_message_blocks_unscanned_attachment_from_agent_payload(self):
        file_response = self.client.post(
            "/api/files/",
            data={
                "session_id": "ses_scan_blocked",
                "purpose": "fine_notice",
                "filename": "notice-waiting.txt",
                "content_type": "text/plain",
                "size_bytes": 128,
            },
            content_type="application/json",
        )
        attachment_id = file_response.json()["attachment"]["attachment_id"]

        message_response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_scan_blocked",
                "user_text": "이 첨부를 근거로 이의신청을 준비해줘.",
                "execution_mode": "async_worker",
                "attachments": [{"attachment_id": attachment_id}],
            },
            content_type="application/json",
        )

        self.assertEqual(message_response.status_code, 200)
        body = message_response.json()
        self.assertEqual(body["attachments"], [])
        self.assertEqual(body["blocked_attachments"][0]["attachment_id"], attachment_id)
        self.assertEqual(body["blocked_attachments"][0]["required_action"], "wait_for_file_scan")
        self.assertEqual(body["attachment_scan_policy"]["blocked_count"], 1)
        self.assertEqual(body["status"], "partial")
        self.assertEqual(body["execution_mode"], "async_worker")
        self.assertIsNone(body.get("work_item"))
        self.assertEqual(body["scan_gate"]["worker_action"], "not_queued")
        self.assertFalse(AgentWorkItem.objects.filter(job__session__session_id="ses_scan_blocked").exists())
        job = AnalysisJob.objects.get(session__session_id="ses_scan_blocked")
        self.assertEqual(job.status, AnalysisJobStatus.PARTIAL)
        self.assertEqual(job.metadata["scan_gate"]["status"], "blocked")
        self.assertEqual(job.metadata["blocked_attachments"][0]["attachment_id"], attachment_id)
        for package in body["analysis_plan"]["agent_input_packages"]:
            self.assertEqual(package["payload"]["attachments"], [])
            self.assertEqual(package["payload"]["blocked_attachments"][0]["attachment_id"], attachment_id)

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

        owner_client = Client(HTTP_AUTHORIZATION="Bearer usr_file_detail:any")
        response = owner_client.get(f"/api/files/{uploaded_file.attachment_id}/")

        self.assertEqual(response.status_code, 200)
        attachment = response.json()["attachment"]
        self.assertEqual(attachment["attachment_id"], uploaded_file.attachment_id)
        self.assertEqual(attachment["session_id"], session.session_id)
        self.assertEqual(attachment["status"], UploadedFileStatus.READY)
        self.assertEqual(attachment["persistence"]["table"], "uploaded_files")

    def test_canonical_file_detail_denies_other_owner(self):
        session = ChatSession.objects.create(
            session_id="ses_private_file",
            owner_id="usr_file_owner",
            status=ChatSessionStatus.ACTIVE,
        )
        UploadedFile.objects.create(
            attachment_id="att_private_file",
            owner_id="usr_file_owner",
            session=session,
            purpose="fine_notice",
            file_type="image",
            original_filename="notice.jpg",
            content_type="image/jpeg",
            size_bytes=2048,
            storage_uri="mock://metadata/att_private_file",
            status=UploadedFileStatus.READY,
            agent_handoff={},
            metadata={},
        )
        other_client = Client(HTTP_AUTHORIZATION="Bearer usr_other:any")

        response = other_client.get("/api/files/att_private_file/")

        self.assertEqual(response.status_code, 403)
        error = response.json()["error"]
        self.assertEqual(error["contract_version"], "object_access.v1")
        self.assertEqual(error["code"], "object_access_denied")
        self.assertEqual(error["access"]["reason"], "owner_mismatch")
        self.assertEqual(error["access"]["resource"]["attachment_id"], "att_private_file")

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
        self.assertEqual(job["persistence"]["progress_cache"]["status"], "cached")
        self.assertEqual(job["persistence"]["progress_cache"]["backend"], "locmem")
        self.assertEqual(
            job["persistence"]["progress_cache"]["key"],
            f"analysis_job_progress:{job['job_id']}",
        )
        self.assertEqual(
            job["persistence"]["session_cache"]["key"],
            "chat_session_state:ses_canonical_job",
        )
        self.assertEqual(job["usage"]["scope"], "agent_run")
        self.assertEqual(job["usage"]["usage_event_table"], "usage_events")
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
        usage_event = UsageEvent.objects.filter(
            subject_id="user:usr_mock",
            scope="agent_run",
        ).first()
        self.assertIsNotNone(usage_event)
        self.assertEqual(usage_event.metadata["status"], "allowed")
        persisted_invocations = list(persisted_job.agent_invocations.order_by("created_at"))
        self.assertEqual(len(persisted_invocations), len(job["node_execution"]["executions"]))
        self.assertTrue(all(invocation.ai_session == ai_session for invocation in persisted_invocations))
        self.assertTrue(all(invocation.agent_node is not None for invocation in persisted_invocations))
        self.assertTrue(
            all(
                invocation.metadata["status_timeline"][0]["status"] == AgentInvocationStatus.QUEUED
                for invocation in persisted_invocations
            )
        )
        self.assertTrue(
            all(
                AgentInvocationStatus.RUNNING
                in {item["status"] for item in invocation.metadata["status_timeline"]}
                for invocation in persisted_invocations
            )
        )
        self.assertEqual(
            persisted_invocations[0].metadata["agent_result_id"],
            persisted_results[0].result_id,
        )
        law_invocation = persisted_job.agent_invocations.get(node_code="law_ground_search")
        retrieval_event = RetrievalEvent.objects.get(invocation=law_invocation)
        self.assertEqual(retrieval_event.job, persisted_job)
        self.assertEqual(retrieval_event.filters["source_type"], "law")
        self.assertGreaterEqual(retrieval_event.result_count, 0)
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
        detail_body = detail.json()
        self.assertEqual(detail_body["api_surface"], "canonical_mock")
        self.assertEqual(detail_body["job"]["progress_cache"]["status"], "hit")
        self.assertEqual(detail_body["job"]["progress_cache"]["snapshot"]["job_id"], job["job_id"])

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
        call_command("process_uploaded_file_scans", "--limit", "1", stdout=StringIO())

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
        self.assertEqual(report_body["persistence"]["object_storage"]["backend"], "object_storage")
        self.assertEqual(report_body["persistence"]["report_quality"]["contract_version"], "report_quality.v1")
        self.assertFalse(report_body["persistence"]["report_quality"]["partial_report"])
        self.assertEqual(report_body["object_storage"]["policy_version"], "object_storage_adapter.v1")
        self.assertEqual(report_body["object_storage"]["resource_type"], "report")
        self.assertTrue(report_body["download_url"].startswith("/api/reports/"))
        report = Report.objects.get(report_id=report_body["report_id"])
        self.assertEqual(report.job.job_id, job["job_id"])
        self.assertEqual(report.session.session_id, session_id)
        self.assertEqual(report.display_result.display_result_id, result["persistence"]["display_result_id"])
        self.assertEqual(report.status, ReportStatus.READY)
        self.assertTrue(report.storage_uri.startswith("s3://skn27-demo-object-storage/"))
        self.assertEqual(report.metadata["source"], "canonical_report_action")
        self.assertEqual(report.metadata["object_storage_status"], "written")
        self.assertEqual(report.metadata["report_quality"]["analysis_job_status"], job["status"])
        self.assertTrue(report.metadata["object_storage_write"]["writes_binary"])
        self.assertEqual(report.metadata["object_storage"]["backend"], "object_storage")
        self.assertEqual(report.metadata["source_storage_uri"], "mock://reports/rep_canonical_smoke")
        self.assertEqual(report.content["download_url"], report_body["download_url"])
        self.assertEqual(report.content["object_storage"]["storage_uri"], report.storage_uri)

        download_response = self.client.get(
            f"/api/reports/{report_body['report_id']}/download/"
        )
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response["X-API-Surface"], "canonical_mock")
        self.assertEqual(download_response["X-Report-Persistence"], "postgresql")
        self.assertEqual(download_response["X-Report-Storage-Backend"], "object_storage")
        self.assertEqual(download_response["X-Report-Storage-URI"], report.storage_uri)
        self.assertEqual(download_response["X-Report-Object-Key"], report.metadata["object_storage"]["key"])
        self.assertEqual(download_response["X-Report-Object-Policy"], "object_storage_adapter.v1")
        self.assertEqual(download_response["X-Report-Access-Decision"], "owner_match")
        download_body = extract_pdf_text(download_response.content)
        self.assertIn(
            "Report metadata download for rep_canonical_smoke",
            download_body,
        )
        self.assertIn("object_storage_policy: object_storage_adapter.v1", download_body)

        summary_response = self.client.get(f"/api/mypage/summary/?session_id={session_id}")
        self.assertEqual(summary_response.status_code, 200)
        summary_body = summary_response.json()
        self.assertEqual(summary_body["api_surface"], "canonical_mock")
        self.assertEqual(summary_body["execution_mode"], "mock")
        self.assertEqual(summary_body["storage"]["backend"], "postgresql")
        self.assertEqual(summary_body["progress_cache"]["policy_version"], "progress_cache.v1")
        self.assertEqual(summary_body["progress_cache"]["fallback"], "postgresql")
        self.assertEqual(summary_body["object_storage"]["policy_version"], "object_storage_adapter.v1")
        self.assertEqual(summary_body["object_storage"]["backend"], "object_storage")
        self.assertEqual(
            summary_body["progress_cache"]["key_patterns"]["analysis_job_progress"],
            "analysis_job_progress:{job_id}",
        )
        self.assertEqual(summary_body["session_cache"]["status"], "hit")
        self.assertEqual(summary_body["session_cache"]["snapshot"]["session_id"], session_id)
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

    def test_canonical_report_marks_partial_analysis_quality(self):
        message_response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_partial_report_quality",
                "conversation_save_state": "saved",
                "user_text": "Need more info but prepare report preview.",
                "mock_scenario": "fine_notice",
                "mock_status": "partial",
            },
            content_type="application/json",
        )
        self.assertEqual(message_response.status_code, 200)
        job_id = message_response.json()["persistence"]["job_id"]

        report_response = self.client.post(
            "/api/reports/",
            data={
                "action": "save",
                "report_id": "rep_partial_report_quality",
                "job_id": job_id,
                "session_id": "ses_partial_report_quality",
            },
            content_type="application/json",
        )
        self.assertEqual(report_response.status_code, 200)
        quality = report_response.json()["persistence"]["report_quality"]
        self.assertEqual(quality["contract_version"], "report_quality.v1")
        self.assertEqual(quality["analysis_job_status"], AnalysisJobStatus.PARTIAL)
        self.assertTrue(quality["partial_report"])
        self.assertGreaterEqual(quality["limitation_count"], 1)

        report = Report.objects.get(report_id="rep_partial_report_quality")
        self.assertTrue(report.metadata["report_quality"]["partial_report"])

        download_response = self.client.get("/api/reports/rep_partial_report_quality/download/")
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response["Content-Type"], "application/pdf")
        self.assertIn('filename="rep_partial_report_quality.pdf"', download_response["Content-Disposition"])
        self.assertTrue(download_response.content.startswith(b"%PDF"))
        download_body = extract_pdf_text(download_response.content)
        if download_body:
            self.assertIn("partial_report: True", download_body)
            self.assertIn("limitation_1:", download_body)

    def test_canonical_report_download_includes_reporting_payload_sections(self):
        message_response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": "ses_report_payload_download",
                "conversation_save_state": "saved",
                "user_text": "어린이보호구역 과태료 이의신청서와 제출 가이드라인을 만들어주세요.",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )
        self.assertEqual(message_response.status_code, 200)
        message_body = message_response.json()
        job_id = message_body["persistence"]["job_id"]
        reporting_payload = message_body["reporting_payload"]
        section_titles = {section["title"] for section in reporting_payload["sections"]}
        self.assertIn("고지서 OCR 결과", section_titles)
        self.assertIn("이의신청서 초안", section_titles)
        self.assertIn("제출 가이드라인", section_titles)

        with tempfile.TemporaryDirectory() as object_root, override_settings(
            OBJECT_STORAGE_LOCAL_ROOT=object_root
        ):
            report_response = self.client.post(
                "/api/reports/",
                data={
                    "action": "download",
                    "report_id": "rep_report_payload_download",
                    "job_id": job_id,
                    "session_id": "ses_report_payload_download",
                    "title": reporting_payload["title"],
                    "reporting_payload": reporting_payload,
                },
                content_type="application/json",
            )
            self.assertEqual(report_response.status_code, 200)

            download_response = self.client.get("/api/reports/rep_report_payload_download/download/")
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response["Content-Type"], "application/pdf")
        self.assertIn('filename="rep_report_payload_download.pdf"', download_response["Content-Disposition"])
        self.assertTrue(download_response.content.startswith(b"%PDF"))
        download_body = extract_pdf_text(download_response.content)
        if download_body:
            self.assertIn("고지서 OCR 결과", download_body)
            self.assertIn("이의신청서 초안", download_body)
            self.assertIn("제출 가이드라인", download_body)

    def test_canonical_report_download_denies_other_owner(self):
        session = ChatSession.objects.create(session_id="ses_private_report", owner_id="usr_mock")
        Report.objects.create(
            report_id="rep_private_owner",
            owner_id="usr_mock",
            session=session,
            report_type=ReportType.OBJECTION_DRAFT,
            status=ReportStatus.READY,
            storage_uri="mock://reports/rep_private_owner",
            title="Private report",
        )
        other_client = Client(HTTP_AUTHORIZATION="Bearer usr_other:any")

        response = other_client.get("/api/reports/rep_private_owner/download/")

        self.assertEqual(response.status_code, 403)
        error = response.json()["error"]
        self.assertEqual(error["contract_version"], "object_access.v1")
        self.assertEqual(error["code"], "object_access_denied")
        self.assertFalse(error["access"]["allowed"])
        self.assertEqual(error["access"]["reason"], "owner_mismatch")
        self.assertEqual(error["access"]["resource"]["report_id"], "rep_private_owner")

    def test_report_download_returns_attachment(self):
        response = self.client.get("/api/mock/reports/rep_mock/download/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn('filename="rep_mock.pdf"', response["Content-Disposition"])
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_canonical_report_download_marks_canonical_mock_surface(self):
        response = self.client.get("/api/reports/rep_mock/download/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-API-Surface"], "canonical_mock")
        self.assertEqual(response["X-Execution-Mode"], "mock")
        self.assertNotIn("X-Report-Persistence", response)

