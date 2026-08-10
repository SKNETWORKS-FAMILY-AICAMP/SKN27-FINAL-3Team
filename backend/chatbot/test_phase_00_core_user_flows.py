"""Phase 0 characterization tests for canonical queue/worker boundaries.

These tests do not use Explicit Mock Runtime.  They protect real PostgreSQL/ORM
contracts under Django's test database and use the provider-free Supervisor
internal node so no Google, OCR, RAG, Vision, or Agent provider is contacted.
"""

from __future__ import annotations

from datetime import timedelta
import json
import os
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from chatbot.models import AgentResult, AgentWorkItem, AnalysisJob, ChatSession, ChatSessionStatus
from chatbot.repositories import enqueue_analysis_job_work, process_agent_work_items


INTERNAL_NODE = "input_context_validation"


class _GoogleResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class Phase00CoreUserFlowTests(TestCase):
    @override_settings(
        APP_JWT_SECRET="[MASKED]",
        GOOGLE_CLIENT_ID="phase00.apps.googleusercontent.com",
        GOOGLE_CLIENT_SECRET="[MASKED]",
        GOOGLE_POPUP_REDIRECT_URI="https://app.example.test",
        GOOGLE_TOKEN_ENDPOINT="https://oauth2.googleapis.com/token",
        GOOGLE_USERINFO_ENDPOINT="https://openidconnect.googleapis.com/v1/userinfo",
    )
    def test_phase_00_guest_login_promotes_only_its_session(self) -> None:
        """Phase 0 A: canonical guest → Google login → resume; only Google HTTP is a test double, never Explicit Mock Runtime."""

        initial = Client().post("/api/auth/guest-session/", data={}, content_type="application/json")
        self.assertEqual(initial.status_code, 200, initial.content)
        guest_id = initial.json()["guest"]["guest_id"]
        credential = initial.json()["guest_credential"]
        session_id = f"ses_phase00_guest_{uuid4().hex}"
        guest_session = Client(HTTP_X_GUEST_CREDENTIAL=credential).post(
            "/api/auth/guest-session/",
            data={"guest_id": guest_id, "session_id": session_id},
            content_type="application/json",
        )
        self.assertEqual(guest_session.status_code, 200, guest_session.content)
        credential = guest_session.json()["guest_credential"]

        def google_http(request, timeout=0):
            self.assertEqual(timeout, 10)
            if request.full_url.endswith("/token"):
                return _GoogleResponse({"access_token": "phase00-google-token", "expires_in": 3600, "scope": "openid email profile", "token_type": "Bearer"})
            self.assertEqual(request.headers["Authorization"], "Bearer phase00-google-token")
            return _GoogleResponse({"sub": "phase00-google-subject", "email": "phase00@example.test", "email_verified": True, "name": "Phase 0 User"})

        with patch("app.services.google_auth_service.urllib_request.urlopen", side_effect=google_http):
            login = Client().post(
                "/api/auth/google/code/",
                data={
                    "provider": "google",
                    "code": "phase00-code",
                    "purpose": "LOGIN",
                    "scope": "openid email profile",
                    "client_id": "phase00.apps.googleusercontent.com",
                    "redirect_uri": "https://app.example.test",
                    "guest_id": guest_id,
                    "session_id": session_id,
                },
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XmlHttpRequest",
                HTTP_ORIGIN="https://app.example.test",
                HTTP_X_GUEST_CREDENTIAL=credential,
            )
        self.assertEqual(login.status_code, 200, login.content)
        access_token = login.json()["access_token"]
        owner_id = login.json()["subject"]["user_id"]
        session = ChatSession.objects.get(session_id=session_id)
        self.assertEqual(session.owner_id, owner_id)
        self.assertEqual(session.metadata["auth_context"]["guest_id"], guest_id)
        resume = Client(HTTP_AUTHORIZATION=f"Bearer {access_token}").get("/api/auth/resume/")
        self.assertEqual(resume.status_code, 200, resume.content)
        self.assertEqual(resume.json()["session"]["session_id"], session_id)

    def _enqueue_internal_work(self) -> tuple[str, str]:
        """Create the smallest existing provider-free production worker plan."""

        suffix = uuid4().hex
        owner_id = f"usr_phase00_{suffix}"
        session_id = f"ses_phase00_{suffix}"
        message_id = f"msg_phase00_{suffix}"
        job_id = f"job_phase00_{suffix}"
        plan_id = f"plan_phase00_{suffix}"
        ChatSession.objects.create(
            session_id=session_id,
            owner_id=owner_id,
            status=ChatSessionStatus.ACTIVE.value,
        )
        queued = enqueue_analysis_job_work(
            {
                "owner_id": owner_id,
                "user_id": owner_id,
                "session_id": session_id,
                "message_id": message_id,
                "user_text": "phase zero deterministic internal worker input",
            },
            {
                "job_id": job_id,
                "session_id": session_id,
                "message_id": message_id,
                "routing_intent": "phase_00_internal_probe",
                "status": "queued",
                "active_node": INTERNAL_NODE,
                "progress_message": "Phase 0 internal work queued.",
                "analysis_plan_id": plan_id,
                "analysis_plan": {
                    "contract_version": "analysis_plan.v2",
                    "plan_id": plan_id,
                    "session_id": session_id,
                    "message_id": message_id,
                    "routing_intent": "phase_00_internal_probe",
                    "steps": [
                        {
                            "order": 1,
                            "node_code": INTERNAL_NODE,
                            "status": "ready",
                            "depends_on": [],
                        }
                    ],
                },
                "chat_response": {},
                "node_execution": {},
            },
        )
        return queued["job_id"], queued["work_item_id"]

    def test_phase_00_internal_worker_plan_persists_once(self) -> None:
        """Phase 0 E: production queue → worker → AgentResult persistence; no external double or Explicit Mock Runtime."""

        job_id, work_item_id = self._enqueue_internal_work()

        processed = process_agent_work_items(limit=1)

        job = AnalysisJob.objects.get(job_id=job_id)
        work_item = AgentWorkItem.objects.get(work_item_id=work_item_id)
        result = AgentResult.objects.get(job=job, node_code=INTERNAL_NODE)
        self.assertEqual(processed["processed"], 1)
        self.assertEqual(work_item.status, "success")
        self.assertGreaterEqual(work_item.attempt_no, 1)
        self.assertIsNotNone(work_item.started_at)
        self.assertIsNotNone(work_item.completed_at)
        self.assertEqual(job.status, "success")
        self.assertEqual(result.node_code, INTERNAL_NODE)
        self.assertEqual(AgentResult.objects.filter(job=job, node_code=INTERNAL_NODE).count(), 1)

    def test_phase_00_stale_internal_work_is_reclaimed_once(self) -> None:
        """Phase 0 F: a stale production lease is reclaimed without duplicate AgentResult; no external double or Explicit Mock Runtime."""

        job_id, work_item_id = self._enqueue_internal_work()
        work_item = AgentWorkItem.objects.get(work_item_id=work_item_id)
        work_item.status = "running"
        work_item.attempt_no = 1
        work_item.started_at = timezone.now() - timedelta(minutes=5)
        work_item.locked_at = timezone.now() - timedelta(minutes=5)
        work_item.save(update_fields=["status", "attempt_no", "started_at", "locked_at"])

        processed = process_agent_work_items(limit=1, stale_after_seconds=1)

        job = AnalysisJob.objects.get(job_id=job_id)
        work_item.refresh_from_db()
        self.assertEqual(processed["stale_requeued"], 1)
        self.assertEqual(work_item.status, "success")
        self.assertGreaterEqual(work_item.attempt_no, 2)
        self.assertEqual(job.status, "success")
        self.assertEqual(AgentResult.objects.filter(job=job, node_code=INTERNAL_NODE).count(), 1)
