from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from chatbot.models import (
    AgentWorkItem,
    AgentWorkItemStatus,
    AnalysisJob,
    AnalysisJobStatus,
    ChatSession,
    ChatSessionStatus,
    UploadedFile,
    UploadedFileStatus,
)


SENSITIVE_MARKERS = (
    "Kim Hye-rim",
    "010-1234-5678",
    "900101-1234567",
    "123 Test-ro",
    "12A3456",
    "fine-notice.png",
    "C:\\private\\fine-notice.png",
    "s3://private-bucket/fine-notice.png",
    "sk-private-token",
)


def _private_exception() -> RuntimeError:
    return RuntimeError(" | ".join(SENSITIVE_MARKERS))


class OperationalLogPrivacyTests(TestCase):
    def assert_no_raw_markers(self, value: object) -> None:
        serialized = repr(value)
        for marker in SENSITIVE_MARKERS:
            self.assertNotIn(marker, serialized)

    def _uploaded_file_for_scan(self) -> UploadedFile:
        session = ChatSession.objects.create(
            session_id="ses_operational_scan",
            owner_id="usr_operational_scan",
            status=ChatSessionStatus.ACTIVE.value,
        )
        return UploadedFile.objects.create(
            attachment_id="att_operational_scan",
            owner_id=session.owner_id,
            session=session,
            purpose="fine_notice",
            file_type="image",
            original_filename=SENSITIVE_MARKERS[5],
            content_type="image/png",
            size_bytes=1,
            storage_uri=SENSITIVE_MARKERS[7],
            privacy_risk=False,
            status=UploadedFileStatus.UPLOADED.value,
            scan_status="not_started",
        )

    def test_analysis_job_reservation_failure_logs_only_error_type(self) -> None:
        from chatbot import views

        request = RequestFactory().post(
            "/api/analysis/jobs/",
            data=json.dumps({"session_id": "ses_log", "job_id": "job_log"}),
            content_type="application/json",
        )
        with (
            patch("chatbot.views._is_canonical_mock_request", return_value=True),
            patch("chatbot.views.reserve_analysis_job_request", side_effect=_private_exception()),
            self.assertLogs("chatbot.views", level="WARNING") as captured,
        ):
            response = views.analysis_jobs(request)

        self.assertEqual(response.status_code, 503)
        self.assertIn("analysis job reservation failed error_type=RuntimeError", captured.output[0])
        self.assert_no_raw_markers(captured.output)

    def test_file_scan_failure_log_excludes_uploaded_file_identifiers(self) -> None:
        from chatbot import file_scan_service

        uploaded_file = self._uploaded_file_for_scan()
        with (
            patch("chatbot.file_scan_service._source_snapshot_for_scan", return_value=b""),
            patch("chatbot.file_scan_service.build_file_scan_result", side_effect=_private_exception()),
            self.assertLogs("chatbot.file_scan_service", level="WARNING") as captured,
        ):
            file_scan_service.scan_uploaded_file(uploaded_file)

        self.assertIn("file scan failed error_type=RuntimeError", captured.output[0])
        self.assert_no_raw_markers(captured.output)

    def test_objection_draft_provider_failure_log_excludes_prompt_and_exception_text(self) -> None:
        from ai.agents.objection_report_generation import agent

        failing_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_kwargs: (_ for _ in ()).throw(_private_exception())
                )
            )
        )
        with (
            patch.object(agent, "_openai_client", return_value=failing_client),
            self.assertLogs("ai.agents.objection_report_generation.agent", level="WARNING") as captured,
        ):
            result = agent._draft_petition_text(
                disposition_details={"violation_text": SENSITIVE_MARKERS[0]},
                legal_grounds=[],
                user_facts=" ".join(SENSITIVE_MARKERS),
                missing_fields=[],
                appeal_decision={},
            )

        self.assertIsNone(result)
        self.assertIn("objection petition drafting failed; error_class=RuntimeError", captured.output[0])
        self.assert_no_raw_markers(captured.output)

    def test_worker_failure_persists_only_fixed_operational_values(self) -> None:
        from chatbot import repositories

        session = ChatSession.objects.create(
            session_id="ses_worker_log",
            owner_id="usr_worker_log",
            status=ChatSessionStatus.ACTIVE.value,
        )
        job = AnalysisJob.objects.create(
            job_id="job_worker_log",
            session=session,
            owner_id=session.owner_id,
            status=AnalysisJobStatus.RUNNING.value,
        )
        work_item = AgentWorkItem.objects.create(
            work_item_id="work_worker_log",
            job=job,
            status=AgentWorkItemStatus.RUNNING.value,
            attempt_no=1,
            max_attempts=1,
        )
        with (
            patch("chatbot.repositories.write_analysis_job_progress", return_value={}),
            patch("chatbot.repositories.write_chat_session_state", return_value=None),
        ):
            result = repositories._fail_agent_work_item(
                work_item.work_item_id,
                _private_exception(),
                expected_attempt_no=1,
            )

        work_item.refresh_from_db()
        job.refresh_from_db()
        event = job.events.latest("created_at")
        self.assertEqual(result["error_code"], "RuntimeError")
        self.assertEqual(work_item.result["message"], "Agent worker execution failed.")
        self.assertEqual(job.progress_message, "Agent worker item failed.")
        self.assert_no_raw_markers(
            {
                "result": result,
                "work_item": work_item.result,
                "job": job.progress_message,
                "event": event.metadata,
            }
        )
