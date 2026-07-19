from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from chatbot.management.commands.smoke_non_dl_analysis_reporting_pipeline import (
    ANALYSIS_NODE_CODES,
    EXPECTED_ADAPTERS,
    _fine_notice_fixture,
    _smoke_payloads,
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
    def test_fine_notice_fixture_builds_trusted_s3_attachment_metadata(self) -> None:
        fixture = _fine_notice_fixture(
            "s3://clean-bucket/canonical/acceptance/fine-notice-smoke.PDF"
        )

        self.assertEqual(fixture["purpose"], "fine_notice")
        self.assertEqual(fixture["status"], "ready")
        self.assertEqual(fixture["content_type"], "application/pdf")
        self.assertEqual(
            fixture["metadata_source"],
            "operator_reviewed_acceptance_fixture",
        )
        self.assertEqual(fixture["object_storage"]["provider"], "s3")
        self.assertEqual(fixture["object_storage"]["bucket"], "clean-bucket")
        self.assertEqual(
            fixture["object_storage"]["key"],
            "canonical/acceptance/fine-notice-smoke.PDF",
        )

    def test_fine_notice_fixture_rejects_untrusted_storage_paths(self) -> None:
        invalid_uris = (
            "",
            "https://clean-bucket/canonical/acceptance/fine-notice.png",
            "s3://clean-bucket/quarantine/fine-notice.png",
            "s3://clean-bucket/canonical/acceptance/",
            "s3://clean-bucket/canonical/acceptance/../secret.png",
            "s3://clean-bucket/canonical/acceptance/%2e%2e/secret.png",
            "s3://clean-bucket/canonical/acceptance/fine-notice.png?versionId=1",
            "s3://clean-bucket/canonical/acceptance/fine-notice.png#fragment",
            "s3://clean-bucket/canonical/acceptance/fine-notice.txt",
        )

        for storage_uri in invalid_uris:
            with self.subTest(storage_uri=storage_uri), self.assertRaisesMessage(
                CommandError,
                "--fine-notice-fixture-s3-uri",
            ):
                _fine_notice_fixture(storage_uri)

    def test_smoke_payloads_keep_server_context_out_of_request_payload(self) -> None:
        fixture = _fine_notice_fixture(
            "s3://clean-bucket/canonical/acceptance/fine-notice-smoke.png"
        )
        payload, job_payload, server_context = _smoke_payloads(
            {
                "owner_id": "usr_smoke",
                "session_id": "ses_smoke",
                "message_id": "msg_smoke",
                "job_id": "job_smoke",
                "plan_id": "plan_smoke",
            },
            fine_notice_fixture=fixture,
        )

        self.assertNotIn("context", payload)
        self.assertEqual(payload["attachments"], [fixture])
        self.assertNotIn("attachments", job_payload)
        self.assertEqual(server_context["query"]["search_query"], payload["user_text"])
        self.assertEqual(server_context["temporal_basis"], {"mode": "current"})
        self.assertEqual(server_context["scope"], {"jurisdiction": "KR"})

    def test_smoke_contract_covers_every_non_dl_sync_adapter(self) -> None:
        self.assertEqual(
            ANALYSIS_NODE_CODES,
            (
                "fine_notice_analysis",
                "law_ground_search",
                "text_ml_case_search",
                "appeal_decision_flow",
            ),
        )
        self.assertEqual(
            EXPECTED_ADAPTERS,
            {
                "fine_notice_analysis": "ai.agents.fine_notice_analysis.graph",
                "law_ground_search": "ai.agents.law_ground_search.run_law_ground_search",
                "text_ml_case_search": "ai.agents.text_ml_case_search.run_text_ml_case_search",
                "appeal_decision_flow": "ai.agents.appeal_decision_flow.graph",
            },
        )

    def test_command_fails_before_enqueue_without_fine_notice_fixture(self) -> None:
        with (
            patch("chatbot.repositories.enqueue_analysis_job_work") as enqueue,
            patch("chatbot.repositories.process_agent_work_item") as process,
            self.assertRaisesMessage(
                CommandError,
                "--fine-notice-fixture-s3-uri",
            ),
        ):
            call_command(
                "smoke_non_dl_analysis_reporting_pipeline",
                allow_paid_provider_call=True,
                require_real_agent_results=True,
            )

        enqueue.assert_not_called()
        process.assert_not_called()

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
        from ai.agents.appeal_decision_flow import graph as appeal_graph
        from ai.agents.fine_notice_analysis import graph as fine_notice_graph

        fine_notice_calls = []
        law_calls = []
        text_calls = []
        appeal_calls = []

        def run_fine_notice(state):
            fine_notice_calls.append(state)
            return {
                "agent_results": {
                    "fine_notice_analysis": {
                        "status": "success",
                        "summary": "Production OCR parsed the sanitized acceptance notice.",
                        "structured_result": {
                            "ocr_status": "success",
                            "fine_type": "과태료",
                            "notice_stage": "사전통지",
                            "law_code": "도로교통법 제32조",
                            "violation_text": "Acceptance-only parking violation fixture.",
                            "opinion_deadline": "2026-12-31",
                            "issuing_authority": "Acceptance Traffic Authority",
                        },
                        "evidence": [
                            {
                                "source_type": "user_uploaded_file",
                                "source_reference": "acceptance-fixture:1",
                            }
                        ],
                        "next_actions": [],
                        "limitations": [],
                    }
                }
            }

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

        def run_appeal(state):
            appeal_calls.append(state)
            return {
                "agent_results": {
                    "appeal_judgment": {
                        "status": "success",
                        "summary": "Production appeal flow completed with verified law context.",
                        "structured_result": {
                            "judgment_status": "success",
                            "overall_possibility": "review_available",
                            "guide": {"summary": "Submit the verified supporting evidence."},
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
                }
            }

        stdout = StringIO()
        with (
            patch.object(fine_notice_graph, "invoke", side_effect=run_fine_notice),
            patch(
                "ai.agents.law_ground_search.run_law_ground_search",
                side_effect=run_law,
            ),
            patch(
                "ai.agents.text_ml_case_search.run_text_ml_case_search",
                side_effect=run_text,
            ),
            patch.object(appeal_graph, "invoke", side_effect=run_appeal),
            patch(
                "app.services.agent_node_service.read_object_bytes",
                return_value=b"operator-reviewed-fine-notice-fixture",
            ),
        ):
            call_command(
                "smoke_non_dl_analysis_reporting_pipeline",
                allow_paid_provider_call=True,
                require_real_agent_results=True,
                require_persisted_handoff=True,
                require_report=True,
                fine_notice_fixture_s3_uri=(
                    "s3://clean-bucket/canonical/acceptance/fine-notice-smoke.png"
                ),
                timeout_seconds=5,
                poll_interval_seconds=0,
                format="json",
                stdout=stdout,
            )

        result = json.loads(stdout.getvalue())
        self.assertEqual(result["status"], "pass")
        self.assertEqual(
            result["analysis_node_codes"],
            [
                "fine_notice_analysis",
                "law_ground_search",
                "text_ml_case_search",
                "appeal_decision_flow",
            ],
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
        self.assertEqual(len(fine_notice_calls), 1)
        self.assertEqual(len(appeal_calls), 1)

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
