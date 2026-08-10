"""Phase 0 characterization for the OCR-confirmed law-search lifecycle.

C/G characterization keeps HTTP, routing, planning, queue, worker,
persistence, authorization, confirmation, rendering, and download boundaries
real. Classification and retrieval dependencies are deterministic
service/pipeline-level doubles whose internal contracts are protected by a
separate blocking service-contract selector. OCR is doubled at its
provider-call boundary, not asserted to be a provider leaf.
"""

from __future__ import annotations

from datetime import timedelta
import json
import os
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from chatbot.file_scan_service import process_uploaded_file_scans
from chatbot.models import (
    AgentResult,
    AgentWorkItem,
    AgentWorkItemStatus,
    AnalysisJob,
    AuthSession,
    AuthSessionStatus,
    ChatMessage,
    ChatSession,
    RetrievalEvent,
    UploadedFile,
    UserAccount,
)
from chatbot.repositories import process_agent_work_item


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


def _ocr_provider_result(_image_blocks: list[dict]) -> dict:
    return {
        "document_title": "과태료 고지서",
        "notice_stage": "사전통지",
        "law_code": "도로교통법 제32조",
        "violation_text": "소화전 주변 정차 위반",
        "fine_amount": 50000,
        "opinion_deadline": "2026-08-31",
        "issuing_authority": "서울특별시",
        "charge_number": "CHG-PHASE00-001",
        "vehicle_number": "12가3456",
    }


def _legal_rag_provider_response(*_args, **_kwargs) -> dict:
    return {
        "contract_version": "legal_rag_search.v1",
        "status": "ready",
        "backend": "postgres_pgvector",
        "top_k": 5,
        "result_count": 1,
        "query": "도로교통법 제32조 소화전 주변 정차 위반",
        "data_provenance": {
            "dataset_version": "phase-00-deterministic",
            "source": "official_law_fixture",
        },
        "embedding": {
            "provider": "deterministic_provider",
            "model": "deterministic-embedding-v1",
            "dimensions": 3,
        },
        "results": [
            {
                "source_reference": "law_chunk_road_traffic_32",
                "chunk_id": "law_chunk_road_traffic_32",
                "source_name": "도로교통법",
                "source_id": "law_road_traffic",
                "source_type": "law",
                "article": "제32조",
                "title": "정차 및 주차의 금지",
                "summary": "소화전 주변 정차 및 주차 제한",
                "provision_text": "소화전 주변에서는 정차 또는 주차하여서는 아니 된다.",
                "source_url": "https://www.law.go.kr/법령/도로교통법/제32조",
                "effective_date": "2020-01-01",
                "score": 0.91,
            }
        ],
    }


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class Phase00OcrLawFlowTests(TestCase):
    def setUp(self) -> None:
        self.object_root = tempfile.TemporaryDirectory()
        self.upload_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.object_root.cleanup)
        self.addCleanup(self.upload_root.cleanup)
        self.storage_override = override_settings(
            OBJECT_STORAGE_PROVIDER="mock_s3",
            OBJECT_STORAGE_BUCKET="phase-00-ocr-law-clean",
            OBJECT_STORAGE_QUARANTINE_BUCKET="phase-00-ocr-law-quarantine",
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
        self.owner_id = "usr_phase_00_ocr_owner"
        self.client = _authenticated_client(self.owner_id)

    def _create_classified_fine_notice(self) -> tuple[str, str, dict]:
        created = self.client.post(
            "/api/chat/sessions/", data={}, content_type="application/json"
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
                    b"phase-00 deterministic fine notice image",
                    content_type="image/png",
                ),
            },
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.content)
        attachment_id = uploaded.json()["attachment"]["attachment_id"]
        self.assertEqual(process_uploaded_file_scans(limit=1)["clean"], 1)

        classified = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": session_id,
                "user_text": "첨부한 고지서를 분류해 주세요.",
                "attachments": [{"attachment_id": attachment_id}],
            },
            content_type="application/json",
        )
        self.assertEqual(classified.status_code, 202, classified.content)
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
            processed = process_agent_work_item(
                classified.json()["work_item"]["work_item_id"]
            )
        self.assertEqual(processed["status"], "success", processed)

        confirmed = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": session_id,
                "user_text": "서버 분류를 확인합니다.",
                "attachments": [{"attachment_id": attachment_id}],
                "attachment_classification_confirmation": {
                    "confirmed": True,
                    "attachment_id": attachment_id,
                },
            },
            content_type="application/json",
        )
        self.assertEqual(confirmed.status_code, 202, confirmed.content)
        return session_id, attachment_id, confirmed.json()

    def _queue_confirmed_ocr_law_flow(self) -> tuple[str, str, dict]:
        session_id, attachment_id, ocr_queued = self._create_classified_fine_notice()
        with patch(
            "ai.agents.fine_notice_analysis.agent._call_gpt",
            side_effect=_ocr_provider_result,
        ):
            processed = process_agent_work_item(
                ocr_queued["work_item"]["work_item_id"]
            )
        self.assertIn(processed["status"], {"success", "partial"}, processed)

        session = ChatSession.objects.get(session_id=session_id)
        followup = session.metadata["chat_followup_state"]
        self.assertEqual(
            followup["contract_version"], "chat_session_followup_state.v1"
        )
        self.assertEqual(
            followup["pending_questions"][0]["field"],
            "document_disposition_type",
        )

        queued = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": session_id,
                "user_text": "사전통지 과태료입니다.",
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
        self.assertEqual(queued.status_code, 202, queued.content)
        queued_body = queued.json()
        slots = queued_body["fine_notice_intake"]["slots"]
        self.assertEqual(
            slots["document_disposition_type"]["value"],
            "과태료 사전통지",
        )
        self.assertNotIn("issuing_authority", slots)
        self.assertNotIn("response_deadline", slots)
        return session_id, attachment_id, queued_body

    def _run_confirmed_law_job(self) -> tuple[str, str, dict, dict]:
        session_id, attachment_id, queued = self._queue_confirmed_ocr_law_flow()
        with (
            patch(
                "ai.agents.fine_notice_analysis.agent._call_gpt",
                side_effect=_ocr_provider_result,
            ),
            patch(
                "app.services.legal_rag_service.search_legal_rag",
                side_effect=_legal_rag_provider_response,
            ),
        ):
            processed = process_agent_work_item(queued["work_item"]["work_item_id"])
        return session_id, attachment_id, queued, processed

    def test_phase_00_ocr_confirmation_is_attachment_scoped(self) -> None:
        session_id, attachment_id, queued = self._queue_confirmed_ocr_law_flow()
        session = ChatSession.objects.get(session_id=session_id)
        uploaded = UploadedFile.objects.get(attachment_id=attachment_id)
        state = session.metadata["chat_followup_state"]
        confirmation = state["ocr_confirmation"]

        self.assertEqual(uploaded.owner_id, self.owner_id)
        self.assertEqual(uploaded.session_id, session.pk)
        self.assertEqual(uploaded.scan_status, "clean")
        self.assertTrue(confirmation["confirmed"])
        self.assertEqual(confirmation["attachment_ids"], [attachment_id])
        self.assertEqual(
            set(confirmation["fields"]),
            {
                "fine_type",
                "notice_stage",
            },
        )
        self.assertNotIn("raw_ocr", json.dumps(state))
        self.assertNotIn("storage_uri", json.dumps(state))
        node_codes = [step["node_code"] for step in queued["analysis_plan"]["steps"]]
        self.assertIn("law_ground_search", node_codes)

    def test_phase_00_short_answer_routes_real_law_worker_and_persists_retrieval(self) -> None:
        session_id, attachment_id, queued, processed = self._run_confirmed_law_job()
        self.assertIn(processed["status"], {"success", "partial"}, processed)

        job = AnalysisJob.objects.get(job_id=queued["work_item"]["job_id"])
        work_item = AgentWorkItem.objects.get(
            work_item_id=queued["work_item"]["work_item_id"]
        )
        law_result = AgentResult.objects.get(job=job, node_code="law_ground_search")
        retrieval_event = RetrievalEvent.objects.get(job=job, invocation__node_code="law_ground_search")
        session = ChatSession.objects.get(session_id=session_id)

        self.assertEqual(job.session_id, session.pk)
        self.assertEqual(job.owner_id, self.owner_id)
        self.assertEqual(work_item.job_id, job.pk)
        self.assertGreaterEqual(work_item.attempt_no, 1)
        self.assertEqual(work_item.status, AgentWorkItemStatus.SUCCESS)
        self.assertEqual(law_result.node_code, "law_ground_search")
        self.assertIn(law_result.status, {"success", "partial"})
        self.assertEqual(retrieval_event.job_id, job.pk)
        self.assertTrue(retrieval_event.source_refs)
        self.assertEqual(retrieval_event.metadata["retrieval_backend"], "postgres_pgvector")
        self.assertEqual(
            retrieval_event.metadata["data_provenance"]["dataset_version"],
            "phase-00-deterministic",
        )
        self.assertEqual(
            attachment_id,
            session.metadata["chat_followup_state"]["ocr_confirmation"]["attachment_ids"][0],
        )

    def test_phase_00_replaced_attachment_does_not_reuse_stale_ocr_confirmation(self) -> None:
        session_id, attachment_a, _queued = self._queue_confirmed_ocr_law_flow()
        session = ChatSession.objects.get(session_id=session_id)
        self.assertEqual(
            session.metadata["chat_followup_state"]["ocr_confirmation"]["attachment_ids"],
            [attachment_a],
        )

        uploaded = self.client.post(
            "/api/files/",
            data={
                "session_id": session_id,
                "purpose": "fine_notice",
                "file": SimpleUploadedFile(
                    "replacement-notice.png",
                    b"phase-00 replacement fine notice image",
                    content_type="image/png",
                ),
            },
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.content)
        attachment_b = uploaded.json()["attachment"]["attachment_id"]
        self.assertEqual(process_uploaded_file_scans(limit=1)["clean"], 1)

        replaced = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": session_id,
                "user_text": "새 고지서 파일로 상담을 계속합니다.",
                "attachments": [{"attachment_id": attachment_b}],
            },
            content_type="application/json",
        )
        self.assertEqual(replaced.status_code, 202, replaced.content)
        replacement_body = replaced.json()
        replacement_job_id = replacement_body["work_item"]["job_id"]
        replacement_work_item_id = replacement_body["work_item"]["work_item_id"]
        replacement_plan = replacement_body["analysis_plan"]

        self.assertNotEqual(attachment_a, attachment_b)
        self.assertNotIn(
            "law_ground_search",
            [step["node_code"] for step in replacement_plan["steps"]],
        )
        self.assertEqual(
            replacement_body["routing_intent"], "attachment_document_classification"
        )
        self.assertIn(
            "attachment_document_classification",
            [step["node_code"] for step in replacement_plan["steps"]],
        )
        self.assertEqual(AnalysisJob.objects.filter(job_id=replacement_job_id).count(), 1)
        replacement_job = AnalysisJob.objects.get(job_id=replacement_job_id)
        self.assertEqual(
            AgentWorkItem.objects.filter(work_item_id=replacement_work_item_id).count(),
            1,
        )
        replacement_work_item = AgentWorkItem.objects.get(
            work_item_id=replacement_work_item_id
        )
        self.assertIsNotNone(replacement_job.message_id)
        self.assertEqual(
            ChatMessage.objects.filter(pk=replacement_job.message_id).count(),
            1,
        )
        replacement_message = ChatMessage.objects.get(pk=replacement_job.message_id)

        self.assertEqual(replacement_job.session_id, session.pk)
        self.assertEqual(replacement_job.message_id, replacement_message.pk)
        self.assertEqual(replacement_work_item.job_id, replacement_job.pk)
        self.assertEqual(
            replacement_message.metadata["analysis_job_id"], replacement_job.job_id
        )
        self.assertEqual(replacement_job.routing_intent, replacement_body["routing_intent"])
        self.assertEqual(replacement_message.routing_intent, replacement_job.routing_intent)
        self.assertEqual(replacement_job.metadata["analysis_plan"], replacement_plan)
        self.assertEqual(
            replacement_job.metadata["pending_questions"],
            replacement_body["pending_questions"],
        )
        self.assertEqual(replacement_work_item.payload["analysis_plan"], replacement_plan)
        self.assertEqual(
            replacement_work_item.payload["job_payload"]["routing_intent"],
            replacement_job.routing_intent,
        )
        self.assertFalse(
            AgentResult.objects.filter(
                job=replacement_job,
                node_code="law_ground_search",
            ).exists()
        )
        self.assertFalse(RetrievalEvent.objects.filter(job=replacement_job).exists())

        session.refresh_from_db()
        stored_confirmation = session.metadata["chat_followup_state"]["ocr_confirmation"]
        self.assertEqual(stored_confirmation["attachment_ids"], [attachment_a])
        self.assertIsNone(replacement_body["fine_notice_intake"])
        self.assertEqual(
            replacement_work_item.payload["execution_payload"]["attachments"][0]["attachment_id"],
            attachment_b,
        )
        attachment_a_record = UploadedFile.objects.get(attachment_id=attachment_a)
        replacement_json = json.dumps(replacement_body)
        self.assertNotIn(attachment_a, replacement_json)
        self.assertNotIn(attachment_a_record.storage_uri, replacement_json)
        for confirmed_value in stored_confirmation["fields"].values():
            self.assertNotIn(confirmed_value, replacement_json)
        self.assertNotIn("raw_ocr", replacement_json)

    def test_phase_00_foreign_ocr_and_stale_classification_confirmation_are_rejected(self) -> None:
        session_id, attachment_id, _queued = self._queue_confirmed_ocr_law_flow()
        foreign_client = _authenticated_client("usr_phase_00_ocr_foreign")
        foreign = foreign_client.post(
            "/api/chat/messages/",
            data={
                "session_id": session_id,
                "user_text": "다른 사용자의 OCR 확인을 재사용합니다.",
                "attachments": [{"attachment_id": attachment_id}],
                "ocr_confirmation": {
                    "confirmed": True,
                    "fields": {"fine_type": "과태료", "notice_stage": "사전통지"},
                },
            },
            content_type="application/json",
        )
        self.assertEqual(foreign.status_code, 403, foreign.content)

        stale = self.client.post(
            "/api/chat/messages/",
            data={
                "session_id": session_id,
                "user_text": "첨부하지 않은 파일의 분류 확인을 사용합니다.",
                "attachments": [],
                "attachment_classification_confirmation": {
                    "confirmed": True,
                    "attachment_id": attachment_id,
                },
            },
            content_type="application/json",
        )
        self.assertEqual(stale.status_code, 409, stale.content)
        self.assertEqual(stale.json()["error_code"], "classification_stale_or_unavailable")

    def test_phase_00_law_result_exposes_no_private_ocr_or_storage_data(self) -> None:
        _session_id, _attachment_id, queued, processed = self._run_confirmed_law_job()
        self.assertIn(processed["status"], {"success", "partial"}, processed)
        response = self.client.get(
            f"/api/analysis/results/{queued['work_item']['job_id']}/"
        )
        self.assertEqual(response.status_code, 200, response.content)
        public_json = json.dumps(response.json())
        for private_marker in ("storage_uri", "raw_ocr", "Authorization", "token"):
            self.assertNotIn(private_marker, public_json)
