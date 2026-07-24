import json
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from chatbot.models import (
    AgentInvocation,
    AgentInvocationStatus,
    AnalysisJob,
    AnalysisJobStatus,
    ChatSession,
    RetrievalEvent,
)
from chatbot.repositories import get_analysis_job_provenance


class AnalysisJobProvenanceTests(TestCase):
    def setUp(self):
        session = ChatSession.objects.create(session_id="ses_provenance")
        self.job = AnalysisJob.objects.create(
            job_id="job_provenance",
            session=session,
            status=AnalysisJobStatus.PARTIAL,
            analysis_plan_id="plan_provenance",
            metadata={
                "supervisor_state": {
                    "llm": {
                        "provider": "openai",
                        "model": "gpt-test",
                        "status": "used",
                        "prompt_version": "supervisor_conversation_prompt.v1",
                        "prompt_sha256": "sha256:conversation",
                    }
                },
                "analysis_plan": {
                    "llm_planner": {
                        "provider": "openai",
                        "model": "gpt-test",
                        "status": "used",
                        "prompt_version": "supervisor_analysis_plan_prompt.v1",
                        "prompt_sha256": "sha256:planner",
                    }
                },
            },
        )
        invocation = AgentInvocation.objects.create(
            invocation_id="ainv_provenance",
            job=self.job,
            node_code="law_ground_search",
            status=AgentInvocationStatus.PARTIAL,
            error_code="provider_timeout",
            metadata={
                "execution_id": "exec_provenance",
                "provenance": {
                    "contract_version": "agent_execution_provenance.v1",
                    "release_version": "release-test-001",
                    "agent_runtime_version": "agent_runtime.v1",
                    "agent_version": "agent_adapter.v1",
                    "adapter_contract_version": "agent_adapter.v1",
                },
            },
        )
        RetrievalEvent.objects.create(
            retrieval_event_id="retr_provenance",
            job=self.job,
            invocation=invocation,
            query_text="secret user query must not be returned",
            query_type="postgres_pgvector",
            result_count=1,
            source_refs=["law_chunk_001"],
            metadata={
                "retrieval_status": "partial",
                "retrieval_backend": "postgres_pgvector",
                "execution_id": "exec_provenance",
                "embedding": {
                    "provider": "openai",
                    "model": "text-embedding-3-large",
                    "dimensions": 1024,
                },
                "data_provenance": {
                    "contract_version": "legal_dataset_provenance.v1",
                    "dataset_version": "sha256:verified-dataset",
                    "verified_at": "2026-07-23T10:00:00+00:00",
                    "effective_at": "2026-07-23",
                    "retrieved_at": "2026-07-23T11:00:00+00:00",
                },
            },
        )

    def test_operator_query_links_job_execution_and_retrieval_without_raw_query(self):
        result = get_analysis_job_provenance(self.job.job_id)

        self.assertEqual(result["contract_version"], "analysis_job_provenance.v1")
        self.assertEqual(result["job_id"], self.job.job_id)
        self.assertEqual(result["supervisor"]["conversation"]["model"], "gpt-test")
        self.assertEqual(
            result["supervisor"]["planner"]["prompt_version"],
            "supervisor_analysis_plan_prompt.v1",
        )
        self.assertEqual(result["executions"][0]["execution_id"], "exec_provenance")
        self.assertEqual(result["executions"][0]["error_code"], "provider_timeout")
        self.assertEqual(
            result["retrievals"][0]["data_provenance"]["dataset_version"],
            "sha256:verified-dataset",
        )
        self.assertEqual(
            result["retrievals"][0]["embedding"]["model"],
            "text-embedding-3-large",
        )
        self.assertEqual(result["retrievals"][0]["source_refs"], ["law_chunk_001"])
        self.assertNotIn("query_text", result["retrievals"][0])
        self.assertNotIn("secret user query", json.dumps(result))

    def test_management_command_emits_json_operator_evidence(self):
        output = StringIO()

        call_command(
            "show_analysis_job_provenance",
            "--job-id",
            self.job.job_id,
            "--format",
            "json",
            stdout=output,
        )

        body = json.loads(output.getvalue())
        self.assertEqual(body["job_id"], self.job.job_id)
        self.assertEqual(body["executions"][0]["execution_id"], "exec_provenance")
