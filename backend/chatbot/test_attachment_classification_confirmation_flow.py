"""API regression coverage for server-owned attachment classification confirmation."""

from __future__ import annotations

from datetime import timedelta
import os
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from chatbot.attachment_classification_service import (
    persist_attachment_document_classification,
    resolve_confirmed_attachment_classification,
)
from chatbot.file_scan_service import process_uploaded_file_scans
from chatbot.models import AuthSession, AuthSessionStatus, UploadedFile, UserAccount
from chatbot.repositories import process_agent_work_item


TEST_JWT_SIGNING_KEY = "classification-confirmation-test-signing-key-is-long-enough"


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
class AttachmentClassificationConfirmationFlowTests(TestCase):
    def setUp(self) -> None:
        self.object_root = tempfile.TemporaryDirectory()
        self.upload_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.object_root.cleanup)
        self.addCleanup(self.upload_root.cleanup)
        self.storage_override = override_settings(
            OBJECT_STORAGE_PROVIDER="mock_s3",
            OBJECT_STORAGE_BUCKET="classification-clean",
            OBJECT_STORAGE_QUARANTINE_BUCKET="classification-quarantine",
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
        self.client = _authenticated_client("usr_classification_owner")

    def _upload_clean_photo(self) -> tuple[str, str]:
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
                "purpose": "accident_scene",
                "file": SimpleUploadedFile(
                    "scene.png",
                    b"fixture accident scene",
                    content_type="image/png",
                ),
            },
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.content)
        attachment_id = uploaded.json()["attachment"]["attachment_id"]
        self.assertEqual(process_uploaded_file_scans(limit=1)["clean"], 1)
        return session_id, attachment_id

    def test_confirmation_uses_server_classification_to_route_photo_search(self) -> None:
        session_id, attachment_id = self._upload_clean_photo()
        uploaded_file = UploadedFile.objects.get(attachment_id=attachment_id)
        persist_attachment_document_classification(
            attachment_id=attachment_id,
            storage_uri=uploaded_file.storage_uri,
            execution_id="exec_classification",
            structured_result={
                "classification": "accident_evidence",
                "confidence_band": "high",
                "requires_confirmation": True,
            },
        )
        captured: dict = {}

        def submit_fixture(
            payload: dict,
            *,
            routing_intent_override: str = "",
            **_kwargs,
        ) -> dict:
            captured["payload"] = payload
            captured["routing_intent_override"] = routing_intent_override
            return {
                "contract_version": "chat_message_accepted.v2",
                "session_id": session_id,
                "message_id": "msg_classification_confirmed",
                "routing_intent": routing_intent_override,
                "status": "scope_guidance",
                "analysis_plan": {"contract_version": "analysis_plan.v2", "steps": []},
            }

        with patch("chatbot.views.submit_message", side_effect=submit_fixture):
            response = self.client.post(
                "/api/chat/messages/",
                data={
                    "session_id": session_id,
                    "user_text": "사고 자료 분류를 확인했습니다.",
                    "attachments": [{"attachment_id": attachment_id}],
                    "attachment_classification_confirmation": {
                        "confirmed": True,
                        "attachment_id": attachment_id,
                    },
                    "attachment_classification": {
                        "classification": "fine_notice",
                        "status": "success",
                    },
                    "attachment_workflows": [
                        {
                            "attachment_id": attachment_id,
                            "state": "analysis_ready",
                        }
                    ],
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            captured["routing_intent_override"],
            "accident_photo_evidence_analysis",
        )
        confirmed_attachment = next(
            item
            for item in captured["payload"]["attachments"]
            if item["attachment_id"] == attachment_id
        )
        self.assertNotIn("attachment_classification", captured["payload"])
        self.assertNotIn("attachment_workflows", captured["payload"])
        self.assertEqual(confirmed_attachment["purpose"], "accident_scene")
        uploaded_file.refresh_from_db()
        record = uploaded_file.metadata["attachment_document_classification"]
        self.assertIsNotNone(record["confirmed_at"])

    def test_clean_attachment_worker_persists_public_classification_boundary(self) -> None:
        session_id, attachment_id = self._upload_clean_photo()

        queued = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": session_id,
                "user_text": "첨부한 자료를 확인해 주세요.",
                "attachments": [{"attachment_id": attachment_id}],
            },
            content_type="application/json",
        )
        self.assertEqual(queued.status_code, 202, queued.content)
        work_item = queued.json()["work_item"]

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
            processed = process_agent_work_item(work_item["work_item_id"])

        self.assertEqual(processed["status"], "success", processed)
        result_response = self.client.get(
            f"/api/analysis/results/{work_item['job_id']}/"
        )
        self.assertEqual(result_response.status_code, 200, result_response.content)
        result = result_response.json()["result"]
        self.assertEqual(
            result["attachment_workflows"][0]["state"],
            "classified_waiting_confirmation",
        )
        self.assertEqual(
            result["attachment_processing"][0]["classification"],
            "completed",
        )
        self.assertEqual(
            result["attachment_processing"][0]["confirmation"],
            "required",
        )
        self.assertNotIn("storage_uri", repr(result["attachment_processing"]))

    def test_confirmed_classification_is_rehydrated_for_later_ocr_confirmation(
        self,
    ) -> None:
        session_id, attachment_id = self._upload_clean_photo()
        uploaded_file = UploadedFile.objects.get(attachment_id=attachment_id)
        persist_attachment_document_classification(
            attachment_id=attachment_id,
            storage_uri=uploaded_file.storage_uri,
            execution_id="exec_fine_notice_rehydration",
            structured_result={
                "classification": "fine_notice",
                "confidence_band": "high",
                "requires_confirmation": True,
            },
        )
        resolve_confirmed_attachment_classification(
            session_id=session_id,
            attachment_id=attachment_id,
        )
        captured: dict = {}

        def submit_fixture(
            payload: dict,
            *,
            routing_intent_override: str = "",
            **_kwargs,
        ) -> dict:
            captured["payload"] = payload
            captured["routing_intent_override"] = routing_intent_override
            return {
                "contract_version": "chat_message_accepted.v2",
                "session_id": session_id,
                "message_id": "msg_ocr_confirmation_followup",
                "routing_intent": "fine_notice_analysis",
                "status": "scope_guidance",
                "analysis_plan": {"contract_version": "analysis_plan.v2", "steps": []},
            }

        with patch("chatbot.views.submit_message", side_effect=submit_fixture):
            response = self.client.post(
                "/api/chat/messages/",
                data={
                    "session_id": session_id,
                    "user_text": "OCR 추출값을 확인했습니다. 후속 절차를 진행해 주세요.",
                    "attachments": [{"attachment_id": attachment_id}],
                    "ocr_confirmation": {
                        "confirmed": True,
                        "fields": {
                            "fine_type": "과태료",
                            "notice_stage": "사전통지",
                        },
                    },
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content)
        confirmed_attachment = next(
            item
            for item in captured["payload"]["attachments"]
            if item["attachment_id"] == attachment_id
        )
        self.assertEqual(
            confirmed_attachment["classification_confirmation"],
            {
                "source": "server_record",
                "classification": "fine_notice",
                "confidence_band": "high",
            },
        )
        self.assertNotIn("scan_snapshot_sha256", repr(confirmed_attachment))
        self.assertNotIn("execution_id", repr(confirmed_attachment))

    def test_stale_confirmation_fails_closed_before_planning(self) -> None:
        session_id, attachment_id = self._upload_clean_photo()

        with patch("chatbot.views.submit_message") as submit_mock:
            response = self.client.post(
                "/api/chat/messages/",
                data={
                    "session_id": session_id,
                    "user_text": "사고 자료 분류를 확인했습니다.",
                    "attachments": [{"attachment_id": attachment_id}],
                    "attachment_classification_confirmation": {
                        "confirmed": True,
                        "attachment_id": attachment_id,
                    },
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(
            response.json()["error_code"],
            "classification_stale_or_unavailable",
        )
        self.assertEqual(
            response.json()["status"],
            "classification_confirmation_required",
        )
        self.assertEqual(
            response.json()["attachment_workflows"],
            [
                {
                    "contract_version": "attachment_workflow.v1",
                    "attachment_id": attachment_id,
                    "state": "failed",
                    "next_action": "rerun_attachment_classification",
                    "retryable": True,
                    "missing_fields": [],
                    "limitations": [
                        "현재 파일과 일치하는 분류 확인 기록이 없습니다."
                    ],
                }
            ],
        )
        submit_mock.assert_not_called()

    def test_fine_notice_confirmation_queues_ocr_without_later_nodes(self) -> None:
        session_id, attachment_id = self._upload_clean_photo()
        uploaded_file = UploadedFile.objects.get(attachment_id=attachment_id)
        persist_attachment_document_classification(
            attachment_id=attachment_id,
            storage_uri=uploaded_file.storage_uri,
            execution_id="exec_fine_notice_classification",
            structured_result={
                "classification": "fine_notice",
                "confidence_band": "high",
                "requires_confirmation": True,
            },
        )

        response = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": session_id,
                "user_text": "고지서 분류를 확인했습니다. 내용을 분석해 주세요.",
                "attachments": [{"attachment_id": attachment_id}],
                "attachment_classification_confirmation": {
                    "confirmed": True,
                    "attachment_id": attachment_id,
                },
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 202, response.content)
        body = response.json()
        self.assertEqual(body["routing_intent"], "fine_notice_analysis")
        node_codes = [
            step["node_code"] for step in body["analysis_plan"]["steps"]
        ]
        self.assertEqual(
            node_codes,
            [
                "input_context_validation",
                "fine_notice_analysis",
                "agent_result_validation",
                "final_response_merge",
            ],
        )
        self.assertNotIn("law_ground_search", node_codes)
        self.assertNotIn("appeal_decision_flow", node_codes)
        self.assertNotIn("objection_report_generation", node_codes)
        self.assertEqual(
            body["attachment_workflows"][0]["state"],
            "ocr_running",
        )

    def test_confirmation_cannot_target_an_attachment_omitted_from_request(self) -> None:
        session_id, attachment_id = self._upload_clean_photo()
        uploaded_file = UploadedFile.objects.get(attachment_id=attachment_id)
        persist_attachment_document_classification(
            attachment_id=attachment_id,
            storage_uri=uploaded_file.storage_uri,
            execution_id="exec_omitted_attachment",
            structured_result={
                "classification": "accident_evidence",
                "confidence_band": "high",
                "requires_confirmation": True,
            },
        )

        with patch("chatbot.views.submit_message") as submit_mock:
            response = self.client.post(
                "/api/chat/messages/",
                data={
                    "session_id": session_id,
                    "user_text": "현재 요청에 없는 자료를 확인하려고 합니다.",
                    "attachments": [],
                    "attachment_classification_confirmation": {
                        "confirmed": True,
                        "attachment_id": attachment_id,
                    },
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 409, response.content)
        submit_mock.assert_not_called()
        uploaded_file.refresh_from_db()
        record = uploaded_file.metadata["attachment_document_classification"]
        self.assertIsNone(record["confirmed_at"])
