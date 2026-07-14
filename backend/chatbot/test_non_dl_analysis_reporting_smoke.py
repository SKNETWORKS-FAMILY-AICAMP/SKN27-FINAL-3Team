from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from chatbot.management.commands.smoke_non_dl_analysis_reporting_pipeline import (
    _verification_result,
)
from chatbot.models import (
    AgentResult,
    AgentResultStatus,
    AgentWorkItem,
    AnalysisJob,
    AnalysisJobStatus,
    ChatSession,
    Report,
    ReportStatus,
)


class NonDlAnalysisReportingSmokeTests(TestCase):
    def test_command_fails_before_enqueue_without_explicit_paid_call_consent(self) -> None:
        with (
            patch("chatbot.repositories.enqueue_analysis_job_work") as enqueue,
            patch("chatbot.repositories.process_agent_work_item") as process,
            self.assertRaisesMessage(
                CommandError,
                "--allow-paid-provider-call",
            ),
        ):
            call_command("smoke_non_dl_analysis_reporting_pipeline")

        enqueue.assert_not_called()
        process.assert_not_called()
        self.assertFalse(AnalysisJob.objects.exists())
        self.assertFalse(ChatSession.objects.exists())

    def test_command_runs_canonical_non_dl_pipeline_and_checks_safe_retry(self) -> None:
        law_calls = []
        text_calls = []

        def run_law(agent_input, adapter_context):
            law_calls.append((agent_input, adapter_context))
            return {
                "status": "success",
                "summary": "Production law search returned one persisted provision.",
                "structured_result": {
                    "law_provisions": [
                        {
                            "source_ref": "law-smoke:1",
                            "source_name": "Road Traffic Act",
                            "article_no": "1",
                            "provision_text": "Smoke-test legal provision.",
                        }
                    ],
                    "matched_laws": [
                        {
                            "law_name": "Road Traffic Act",
                            "article": "Article 1",
                            "summary": "Smoke-test legal provision.",
                            "source_reference": "law-smoke:1",
                        }
                    ],
                },
                "evidence": [
                    {
                        "source_type": "law",
                        "source_reference": "law-smoke:1",
                    }
                ],
                "next_actions": [],
                "limitations": [],
            }

        def run_text(agent_input, adapter_context):
            text_calls.append((agent_input, adapter_context))
            return {
                "status": "success",
                "summary": "Production case search returned one persisted case.",
                "structured_result": {
                    "query_text": "intersection collision smoke facts",
                    "normalized_description": "ego straight, other vehicle left turn",
                    "similar_cases": [
                        {
                            "title": "Reviewed intersection case",
                            "summary": "Comparable reviewed case.",
                            "source_reference": "review-case-smoke:1",
                        }
                    ],
                    "top_cases": [],
                    "issue_tags": ["signal priority"],
                    "recommended_evidence": ["blackbox video"],
                    "retrieval": {
                        "adapter_source": "fault_ratio_knowledge_agent",
                        "source_type": "review_case",
                        "fallback_used": False,
                    },
                },
                "evidence": [
                    {
                        "source_type": "review_case",
                        "source_reference": "review-case-smoke:1",
                    }
                ],
                "next_actions": [],
                "limitations": [],
            }

        stdout = StringIO()
        with (
            patch(
                "ai.agents.law_ground_search.run_law_ground_search",
                side_effect=run_law,
            ),
            patch(
                "ai.agents.text_ml_case_search.run_text_ml_case_search",
                side_effect=run_text,
            ),
        ):
            call_command(
                "smoke_non_dl_analysis_reporting_pipeline",
                allow_paid_provider_call=True,
                require_real_agent_results=True,
                require_persisted_handoff=True,
                require_report=True,
                timeout_seconds=5,
                poll_interval_seconds=0,
                format="json",
                stdout=stdout,
            )

        result = json.loads(stdout.getvalue())
        self.assertEqual(result["status"], "pass")
        self.assertEqual(
            result["analysis_node_codes"],
            ["law_ground_search", "text_ml_case_search"],
        )
        self.assertNotIn("vision_media_analysis", result["all_node_codes"])
        self.assertTrue(result["checks"]["analysis_persisted_before_reporting"])
        self.assertTrue(result["checks"]["persisted_handoff_consumed"])
        self.assertTrue(result["checks"]["report_persisted"])
        self.assertTrue(result["checks"]["analysis_display_persisted"])
        self.assertTrue(result["checks"]["job_success"])
        self.assertTrue(result["checks"]["all_agent_results_success"])
        self.assertTrue(result["checks"]["report_ready"])
        self.assertTrue(result["checks"]["download_metadata_available"])
        self.assertTrue(result["checks"]["safe_retry_no_new_paid_invocation"])
        self.assertEqual(result["paid_phase_guard_count_before_retry"], 2)
        self.assertEqual(result["paid_phase_guard_count_after_retry"], 2)
        self.assertEqual(len(law_calls), 1)
        self.assertEqual(len(text_calls), 1)

        job = AnalysisJob.objects.get(job_id=result["job_id"])
        work_item = AgentWorkItem.objects.get(work_item_id=result["work_item_id"])
        job.status = AnalysisJobStatus.PARTIAL.value
        job.save(update_fields=["status", "updated_at"])
        report = Report.objects.get(job=job)
        report.status = ReportStatus.DRAFT.value
        report.save(update_fields=["status", "updated_at"])
        analysis_result = AgentResult.objects.filter(
            job=job,
            node_code="law_ground_search",
        ).get()
        analysis_result.status = AgentResultStatus.PARTIAL.value
        analysis_result.save(update_fields=["status"])

        degraded = _verification_result(
            job=job,
            work_item=work_item,
            worker_result={"status": "success"},
            safe_retry_result={"status": "skipped"},
            paid_guard_count_before_retry=2,
            paid_guard_count_after_retry=2,
            requirements={
                "real_agent_results": True,
                "persisted_handoff": True,
                "report": True,
            },
        )

        self.assertEqual(degraded["status"], "fail")
        for failed_check in (
            "job_success",
            "all_agent_results_success",
            "real_agent_results",
            "report_ready",
            "download_metadata_available",
        ):
            self.assertIn(failed_check, degraded["failed_checks"])
