"""Regression coverage for queued, server-owned chat follow-up state."""

from __future__ import annotations

from datetime import timedelta
import os
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from chatbot.file_scan_service import process_uploaded_file_scans
from chatbot.models import (
    AgentWorkItem,
    AnalysisJob,
    AuthSession,
    AuthSessionStatus,
    ChatSession,
    ChatSessionStatus,
    UserAccount,
)
from chatbot.repositories import enqueue_analysis_job_work, process_agent_work_item


TEST_JWT_SIGNING_KEY = "[MASKED]" * 8


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


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class QueuedFollowupStatePersistenceTests(TestCase):
    def setUp(self) -> None:
        self.object_root = tempfile.TemporaryDirectory()
        self.upload_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.object_root.cleanup)
        self.addCleanup(self.upload_root.cleanup)
        self.storage_override = override_settings(
            OBJECT_STORAGE_PROVIDER="mock_s3",
            OBJECT_STORAGE_BUCKET="queued-followup-clean",
            OBJECT_STORAGE_QUARANTINE_BUCKET="queued-followup-quarantine",
            OBJECT_STORAGE_LOCAL_ROOT=self.object_root.name,
            MOCK_UPLOAD_ROOT=self.upload_root.name,
            FILE_SCAN_PROVIDER="local_policy",
        )
        self.storage_override.enable()
        self.addCleanup(self.storage_override.disable)
        self.upload_root_override = patch.dict(
            os.environ,
            {"MOCK_UPLOAD_ROOT": self.upload_root.name},
        )
        self.upload_root_override.start()
        self.addCleanup(self.upload_root_override.stop)
        self.client = _authenticated_client("usr_queued_followup")

    def _queue_fine_notice_classification_confirmation(
        self,
        *,
        client_pending_questions: list[dict] | None = None,
    ) -> tuple[str, str, dict]:
        created = self.client.post(
            "/api/chat/sessions/",
            data={},
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 200, created.content)
        session_id = created.json()["session_id"]
        uploaded = self.client.post(
            "/api/files/",
            data={
                "session_id": session_id,
                "purpose": "fine_notice",
                "file": SimpleUploadedFile(
                    "notice.png",
                    b"deterministic fine notice fixture",
                    content_type="image/png",
                ),
            },
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.content)
        attachment_id = uploaded.json()["attachment"]["attachment_id"]
        self.assertEqual(process_uploaded_file_scans(limit=1)["clean"], 1)

        classification = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": session_id,
                "user_text": "Classify this uploaded document.",
                "attachments": [{"attachment_id": attachment_id}],
            },
            content_type="application/json",
        )
        self.assertEqual(classification.status_code, 202, classification.content)
        classification_work_item_id = classification.json()["work_item"]["work_item_id"]
        with patch(
            "app.services.attachment_document_classification_adapter.classify_document_bytes",
            return_value={
                "status": "success",
                "structured_result": {
                    "classification": "fine_notice",
                    "confidence_band": "high",
                    "requires_confirmation": True,
                    "next_action": "confirm_classification",
                },
                "evidence": [],
                "next_actions": ["confirm_classification"],
                "limitations": [],
            },
        ):
            processed = process_agent_work_item(classification_work_item_id)
        self.assertEqual(processed["status"], "success", processed)

        confirmation_payload = {
            "session_id": session_id,
            "user_text": "Confirm the server classification.",
            "attachments": [{"attachment_id": attachment_id}],
            "attachment_classification_confirmation": {
                "confirmed": True,
                "attachment_id": attachment_id,
            },
        }
        if client_pending_questions is not None:
            confirmation_payload["pending_questions"] = client_pending_questions
        confirmed = self.client.post(
            "/api/chat/messages/",
            data=confirmation_payload,
            content_type="application/json",
        )
        self.assertEqual(confirmed.status_code, 202, confirmed.content)
        return session_id, attachment_id, confirmed.json()

    def test_queued_fine_notice_pending_question_is_persisted_for_next_turn(self) -> None:
        session_id, _attachment_id, response = (
            self._queue_fine_notice_classification_confirmation()
        )

        self.assertEqual(response["routing_intent"], "fine_notice_analysis")
        self.assertEqual(
            [question["field"] for question in response["pending_questions"]],
            [
                "document_disposition_type",
                "issuing_authority",
                "response_deadline",
            ],
        )
        session = ChatSession.objects.get(session_id=session_id)
        followup_state = session.metadata["chat_followup_state"]
        self.assertEqual(
            followup_state["contract_version"],
            "chat_session_followup_state.v1",
        )
        self.assertEqual(followup_state["routing_intent"], "fine_notice_analysis")
        self.assertEqual(followup_state["pending_questions"], response["pending_questions"])
        self.assertEqual(session.current_intent, "fine_notice_analysis")
        self.assertEqual(session.status, ChatSessionStatus.ACTIVE)
        self.assertNotIn("raw_ocr", repr(followup_state))
        self.assertNotIn("storage_uri", repr(followup_state))

    def test_next_short_answer_uses_only_persisted_pending_field(self) -> None:
        session_id, attachment_id, _response = (
            self._queue_fine_notice_classification_confirmation()
        )

        next_turn = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": session_id,
                "user_text": "Pre-notice fine.",
                "attachments": [{"attachment_id": attachment_id}],
            },
            content_type="application/json",
        )

        self.assertEqual(next_turn.status_code, 202, next_turn.content)
        intake = next_turn.json()["fine_notice_intake"]
        slots = intake["slots"]
        self.assertEqual(
            slots["document_disposition_type"]["value"],
            "Pre-notice fine.",
        )
        self.assertEqual(
            slots["document_disposition_type"]["source_type"],
            "user_confirmation",
        )
        self.assertNotIn("issuing_authority", slots)
        self.assertNotIn("response_deadline", slots)

    def test_client_forged_pending_question_is_not_persisted(self) -> None:
        session_id, _attachment_id, response = (
            self._queue_fine_notice_classification_confirmation(
                client_pending_questions=[
                    {
                        "field": "forged_field",
                        "question": "Use this client-controlled question.",
                    }
                ]
            )
        )

        session = ChatSession.objects.get(session_id=session_id)
        persisted_questions = session.metadata["chat_followup_state"][
            "pending_questions"
        ]
        self.assertEqual(persisted_questions, response["pending_questions"])
        self.assertNotIn("forged_field", [item.get("field") for item in persisted_questions])
        self.assertNotIn(
            "Use this client-controlled question.",
            repr(persisted_questions),
        )

    def _queue_payload(
        self,
        *,
        owner_id: str,
        session_id: str,
        job_id: str,
        chat_response: dict,
    ) -> tuple[dict, dict]:
        analysis_plan = {
            "plan_id": f"plan_{job_id}",
            "routing_intent": chat_response["routing_intent"],
            "steps": [
                {
                    "order": 1,
                    "node_code": "fine_notice_analysis",
                    "status": "queued",
                }
            ],
        }
        return (
            {
                "owner_id": owner_id,
                "user_id": owner_id,
                "session_id": session_id,
                "user_text": "Deterministic queue fixture.",
            },
            {
                "job_id": job_id,
                "session_id": session_id,
                "message_id": f"msg_{job_id}",
                "routing_intent": chat_response["routing_intent"],
                "status": "queued",
                "active_node": "fine_notice_analysis",
                "progress_message": "Analysis queued.",
                "analysis_plan_id": analysis_plan["plan_id"],
                "analysis_plan": analysis_plan,
                "chat_response": {**chat_response, "analysis_plan": analysis_plan},
                "node_execution": {},
            },
        )

    def test_queued_response_without_pending_question_does_not_erase_current_state(
        self,
    ) -> None:
        owner_id = "usr_preserve_followup"
        current_state = {
            "contract_version": "chat_session_followup_state.v1",
            "routing_intent": "fine_notice_analysis",
            "pending_questions": [{"field": "response_deadline"}],
            "fine_notice_intake": {"contract_version": "fine_notice_intake.v1", "slots": {}},
        }
        session = ChatSession.objects.create(
            session_id="ses_preserve_followup",
            owner_id=owner_id,
            current_intent="fine_notice_analysis",
            status=ChatSessionStatus.ACTIVE,
            metadata={"chat_followup_state": current_state, "auth_marker": "preserve"},
        )
        payload, job_payload = self._queue_payload(
            owner_id=owner_id,
            session_id=session.session_id,
            job_id="job_without_pending",
            chat_response={
                "session_id": session.session_id,
                "message_id": "msg_without_pending",
                "routing_intent": "traffic_law_search",
                "status": "queued",
                "pending_questions": [],
            },
        )

        enqueue_analysis_job_work(payload, job_payload)

        session.refresh_from_db()
        self.assertEqual(session.metadata["chat_followup_state"], current_state)
        self.assertEqual(session.metadata["auth_marker"], "preserve")
        self.assertEqual(session.current_intent, "fine_notice_analysis")

    def test_queue_failure_does_not_commit_new_followup_snapshot(self) -> None:
        owner_id = "usr_rollback_followup"
        existing_state = {
            "contract_version": "chat_session_followup_state.v1",
            "routing_intent": "fine_notice_analysis",
            "pending_questions": [{"field": "issuing_authority"}],
        }
        session = ChatSession.objects.create(
            session_id="ses_rollback_followup",
            owner_id=owner_id,
            current_intent="fine_notice_analysis",
            status=ChatSessionStatus.ACTIVE,
            metadata={"chat_followup_state": existing_state},
        )
        collision_job = AnalysisJob.objects.create(
            job_id="job_existing_work_item_owner",
            session=session,
            owner_id=owner_id,
            status="queued",
            analysis_plan_id="plan_existing_work_item_owner",
        )
        AgentWorkItem.objects.create(
            work_item_id="awork_job_rollback_followup",
            job=collision_job,
            status="queued",
        )
        payload, job_payload = self._queue_payload(
            owner_id=owner_id,
            session_id=session.session_id,
            job_id="job_rollback_followup",
            chat_response={
                "session_id": session.session_id,
                "message_id": "msg_rollback_followup",
                "routing_intent": "fine_notice_analysis",
                "status": "queued",
                "pending_questions": [{"field": "document_disposition_type"}],
            },
        )

        with self.assertRaisesMessage(
            ValueError,
            "agent work item is already bound to another analysis job",
        ):
            enqueue_analysis_job_work(payload, job_payload)

        session.refresh_from_db()
        self.assertEqual(session.metadata["chat_followup_state"], existing_state)
        self.assertEqual(session.current_intent, "fine_notice_analysis")
        self.assertFalse(AnalysisJob.objects.filter(job_id="job_rollback_followup").exists())
