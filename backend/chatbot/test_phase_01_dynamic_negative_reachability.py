from __future__ import annotations

import json
import tempfile
from contextlib import ExitStack, contextmanager
from datetime import timedelta
from typing import Iterator
from unittest.mock import patch
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from chatbot.models import (
    AgentWorkItem,
    AgentResult,
    AnalysisJob,
    AuthSession,
    AuthSessionStatus,
    ChatSession,
    ChatSessionStatus,
    HistoryEvent,
    UploadedFile,
    UserAccount,
)
from chatbot.repositories import enqueue_analysis_job_work, process_agent_work_items


TEST_JWT_SIGNING_KEY = "phase-01-dynamic-isolation-signing-key-is-long-enough"
MOCK_MARKERS = (
    "mock_scenario",
    "mock_status",
    "canonical_mock",
    "mock://",
)
EXPLICIT_MOCK_TARGETS = (
    "app.mock_runtime.attachments.register_attachment",
    "app.mock_runtime.attachments.list_attachments",
    "app.mock_runtime.attachments.get_attachment",
    "app.mock_runtime.attachments.resolve_attachment_references",
    "app.mock_runtime.attachments._write_metadata",
    "app.mock_runtime.analysis_jobs.create_analysis_job",
    "app.mock_runtime.analysis_jobs._write_job",
    "app.mock_runtime.history.record_history_event",
    "app.mock_runtime.history._write_event",
    "app.mock_runtime.agent_execution.execute_mock_node",
    "app.mock_runtime.agent_execution.execute_mock_plan",
    "app.services.attachment_mock_service.register_attachment",
    "app.services.analysis_job_mock_service.create_analysis_job",
    "app.services.history_event_mock_service.record_history_event",
    "app.services.chatbot_mock_service.submit_message",
)


@contextmanager
def explicit_mock_usage_forbidden() -> Iterator[None]:
    """Make every supported Explicit Mock entry fail if canonical code reaches it."""

    # Load import-time aliases before patching their source functions so the
    # spy cannot leak into a later Explicit Mock URL test in this process.
    import app.mock_runtime.agent_execution  # noqa: F401
    import app.mock_runtime.analysis_jobs  # noqa: F401
    import app.mock_runtime.attachments  # noqa: F401
    import app.mock_runtime.history  # noqa: F401
    import app.services.analysis_job_mock_service  # noqa: F401
    import app.services.attachment_mock_service  # noqa: F401
    import app.services.chatbot_mock_service  # noqa: F401
    import app.services.history_event_mock_service  # noqa: F401

    with ExitStack() as stack:
        for target in EXPLICIT_MOCK_TARGETS:
            stack.enter_context(
                patch(
                    target,
                    side_effect=AssertionError(f"Canonical runtime called Explicit Mock entry: {target}"),
                )
            )
        yield


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class DynamicCanonicalNegativeReachabilityTests(TestCase):
    def setUp(self) -> None:
        self.object_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.object_root.cleanup)
        self.settings_override = override_settings(
            OBJECT_STORAGE_PROVIDER="mock_s3",
            OBJECT_STORAGE_BUCKET="phase-01-clean",
            OBJECT_STORAGE_QUARANTINE_BUCKET="phase-01-quarantine",
            OBJECT_STORAGE_LOCAL_ROOT=self.object_root.name,
            FILE_SCAN_PROVIDER="local_policy",
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

        suffix = uuid4().hex
        self.user_id = f"usr_phase_01_dynamic_{suffix}"
        self.session_id = f"ses_phase_01_dynamic_{suffix}"
        self.client = _authenticated_client(self.user_id)
        ChatSession.objects.create(
            session_id=self.session_id,
            owner_id=self.user_id,
            status=ChatSessionStatus.ACTIVE,
        )

    def test_canonical_file_and_history_http_never_calls_explicit_mock_or_publishes_markers(self) -> None:
        with explicit_mock_usage_forbidden():
            file_response = self.client.post(
                "/api/files/",
                data={
                    "session_id": self.session_id,
                    "purpose": "evidence",
                    "file": SimpleUploadedFile(
                        "phase-01-evidence.png",
                        b"harmless phase 01 file payload",
                        content_type="image/png",
                    ),
                },
            )
            history_response = self.client.get(f"/api/history/?session_id={self.session_id}")

        self.assertEqual(file_response.status_code, 200, file_response.content)
        self.assertEqual(history_response.status_code, 200, history_response.content)
        attachment_id = file_response.json()["attachment"]["attachment_id"]
        uploaded_file = UploadedFile.objects.get(attachment_id=attachment_id)
        persisted = json.dumps(uploaded_file.metadata, ensure_ascii=False)
        public = json.dumps(history_response.json(), ensure_ascii=False)
        for marker in MOCK_MARKERS:
            self.assertNotIn(marker, persisted)
            self.assertNotIn(marker, public)
        self.assertNotIn("mock://", uploaded_file.storage_uri)

    def test_canonical_analysis_worker_never_dispatches_explicit_mock_or_persists_markers(self) -> None:
        job_id, work_item_id = self._enqueue_provider_free_canonical_work()

        with explicit_mock_usage_forbidden():
            processed = process_agent_work_items(limit=1)

        job = AnalysisJob.objects.get(job_id=job_id)
        work_item = AgentWorkItem.objects.get(work_item_id=work_item_id)
        agent_result = AgentResult.objects.get(job=job, node_code="input_context_validation")
        persisted = json.dumps(
            {
                "job_metadata": job.metadata,
                "agent_output": agent_result.raw_output,
                "history": list(HistoryEvent.objects.values_list("metadata", flat=True)),
            },
            ensure_ascii=False,
        )
        self.assertEqual(processed["processed"], 1)
        self.assertEqual(work_item.status, "success")
        self.assertEqual(job.mock_scenario, "")
        for marker in MOCK_MARKERS:
            self.assertNotIn(marker, persisted)

    def _enqueue_provider_free_canonical_work(self) -> tuple[str, str]:
        suffix = uuid4().hex
        job_id = f"job_phase_01_dynamic_{suffix}"
        plan_id = f"plan_phase_01_dynamic_{suffix}"
        queued = enqueue_analysis_job_work(
            {
                "owner_id": self.user_id,
                "user_id": self.user_id,
                "session_id": self.session_id,
                "message_id": f"msg_phase_01_dynamic_{suffix}",
                "user_text": "provider-free canonical worker isolation probe",
            },
            {
                "job_id": job_id,
                "session_id": self.session_id,
                "message_id": f"msg_phase_01_dynamic_{suffix}",
                "routing_intent": "phase_01_dynamic_isolation",
                "status": "queued",
                "active_node": "input_context_validation",
                "progress_message": "Phase 1 dynamic isolation work queued.",
                "analysis_plan_id": plan_id,
                "analysis_plan": {
                    "contract_version": "analysis_plan.v2",
                    "plan_id": plan_id,
                    "session_id": self.session_id,
                    "message_id": f"msg_phase_01_dynamic_{suffix}",
                    "routing_intent": "phase_01_dynamic_isolation",
                    "steps": [
                        {
                            "order": 1,
                            "node_code": "input_context_validation",
                            "status": "ready",
                            "depends_on": [],
                        }
                    ],
                },
                "chat_response": {},
                "node_execution": {},
            },
        )
        return job_id, queued["work_item_id"]


def _authenticated_client(user_id: str) -> Client:
    issued_at = timezone.now()
    expires_at = issued_at + timedelta(hours=1)
    auth_session_id = f"auth_{user_id}"
    token, _claims = issue_access_token(
        user_id=user_id,
        auth_session_id=auth_session_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    user = UserAccount.objects.create(user_id=user_id)
    AuthSession.objects.create(
        auth_session_id=auth_session_id,
        user=user,
        subject_type="user",
        subject_id=f"user:{user_id}",
        status=AuthSessionStatus.ACTIVE,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    return Client(HTTP_AUTHORIZATION=f"Bearer {token}")
