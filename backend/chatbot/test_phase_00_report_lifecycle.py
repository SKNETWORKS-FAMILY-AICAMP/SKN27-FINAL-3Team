"""Phase 0 characterization for the confirmed-facts report lifecycle.

The public case, fact-confirmation, report-confirmation, and download APIs
remain live.  Only the pgvector-backed text/legal retrieval leaves are
deterministic so this test can run without an external database or paid
provider.  The worker, reporting handoff, report persistence, access checks,
and document rendering path are production implementations.
"""

from __future__ import annotations

from copy import deepcopy
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
    AnalysisDisplayResult,
    AnalysisJob,
    AuthSession,
    AuthSessionStatus,
    Case,
    ChatSession,
    ConfirmedFactVersion,
    Report,
    UploadedFile,
    UserAccount,
)
from chatbot.repositories import process_agent_work_item


TEST_JWT_SIGNING_KEY = "[MASKED]" * 8
REPORT_CONFIRMATION_PAYLOAD = {
    "facts_confirmed": True,
    "agency_confirmed": True,
    "deadline_confirmed": True,
    "attachments_confirmed": True,
}


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


def _legal_rag_provider_response(*_args: object, **_kwargs: object) -> dict:
    return {
        "contract_version": "legal_rag_search.v1",
        "status": "ready",
        "backend": "postgres_pgvector",
        "top_k": 5,
        "result_count": 1,
        "query": "교통사고 과실과 이의신청 근거",
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
                "title": "교차로 통행의 원칙",
                "summary": "교차로 진입과 통행 우선순위의 법적 기준",
                "provision_text": "운전자는 교통상황과 신호에 따라 안전하게 통행해야 한다.",
                "source_url": "https://www.law.go.kr/법령/도로교통법/제32조",
                "effective_date": "2020-01-01",
                "score": 0.91,
            }
        ],
    }


def _text_rag_provider_response(*_args: object, **_kwargs: object) -> dict:
    evidence = {
        "source_type": "review_case",
        "title": "Signal intersection review case",
        "source_reference": "review_case_db:rc_001#chunk_001",
        "chunk_text": "This review case discusses a signal intersection entry conflict.",
        "metadata": {
            "case_id": "rc_001",
            "review_case_id": "rc_001",
            "review_no": "2019-000001",
            "chunk_id": "chunk_001",
            "chunk_type": "decision",
            "case_title": "Signal intersection review case",
            "reference_chart_key": "249",
            "decision_fault_ratio": "A 70 : B 30",
            "claimant_final_ratio": "70",
            "respondent_final_ratio": "30",
            "score": 13.5,
            "score_type": "cosine_similarity",
            "rank": 1,
            "highlight": {"chunk_text": ["<em>intersection</em> entry timing"]},
        },
    }
    return {
        "evidence": [evidence],
        "retriever": "unified_pgvector",
        "requested_search_variant": "schema_search_text",
        "search_variant": "schema_search_text",
        "top_k": 5,
        "final_top_k": 1,
        "active_sources": ["review_case"],
        "standby_sources": [],
        "excluded_sources": [],
        "source_results": {
            "review_case": {
                "retriever": "review_case_pgvector",
                "status": "ready",
                "error_code": None,
                "source_type": "review_case",
                "raw_hit_count": 1,
                "mapped_evidence_count": 1,
                "valid_evidence_count": 1,
                "validation_report": {},
            }
        },
        "merge_result": {
            "merge_strategy": "phase_00_deterministic",
            "review_case_quota": 1,
            "fault_ratio_precedent_quota": 0,
            "final_top_k": 1,
            "source_counts": {"review_case": 1},
            "input_counts": {"review_case": 1},
            "output_count": 1,
        },
        "source_summary": {"review_case": {"status": "ready", "count": 1}},
    }


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class Phase00ReportLifecycleTests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_phase_00_report_owner"
        self.client = _authenticated_client(self.owner_id)
        self.other_client = _authenticated_client("usr_phase_00_report_other")
        self.object_root = tempfile.TemporaryDirectory()
        self.upload_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.object_root.cleanup)
        self.addCleanup(self.upload_root.cleanup)
        self.storage_override = override_settings(
            OBJECT_STORAGE_PROVIDER="mock_s3",
            OBJECT_STORAGE_BUCKET="phase-00-report-clean",
            OBJECT_STORAGE_QUARANTINE_BUCKET="phase-00-report-quarantine",
            OBJECT_STORAGE_LOCAL_ROOT=self.object_root.name,
            MOCK_UPLOAD_ROOT=self.upload_root.name,
            FILE_SCAN_PROVIDER="local_policy",
        )
        self.storage_override.enable()
        self.addCleanup(self.storage_override.disable)
        self.upload_root_override = patch.dict(
            os.environ, {"MOCK_UPLOAD_ROOT": self.upload_root.name}
        )
        self.upload_root_override.start()
        self.addCleanup(self.upload_root_override.stop)

    def _create_completed_report(self) -> tuple[Report, Case, ConfirmedFactVersion, AnalysisJob, AgentWorkItem]:
        session_response = self.client.post(
            "/api/chat/sessions/", data={}, content_type="application/json"
        )
        self.assertEqual(session_response.status_code, 200, session_response.content)
        session_id = session_response.json()["session_id"]
        uploaded_response = self.client.post(
            "/api/files/",
            data={
                "session_id": session_id,
                "purpose": "supporting_evidence",
                "file": SimpleUploadedFile(
                    "phase-00-police-record.pdf",
                    b"phase-00 deterministic police record",
                    content_type="application/pdf",
                ),
            },
        )
        self.assertEqual(uploaded_response.status_code, 200, uploaded_response.content)
        attachment_id = uploaded_response.json()["attachment"]["attachment_id"]
        self.assertEqual(process_uploaded_file_scans(limit=1)["clean"], 1)
        session = ChatSession.objects.get(session_id=session_id)

        case_response = self.client.post(
            "/api/cases/",
            data={
                "session_id": session.session_id,
                "title": "Phase 0 report lifecycle traffic accident",
                "case_type": "accident_fault",
                "consultation_state": {"schema_version": "consultation_state.v2"},
            },
            content_type="application/json",
        )
        self.assertEqual(case_response.status_code, 201, case_response.content)
        case_id = case_response.json()["case"]["case_id"]
        case = Case.objects.get(case_id=case_id)

        attachment = UploadedFile.objects.get(attachment_id=attachment_id)
        self.assertEqual(attachment.status, "ready")
        self.assertEqual(attachment.scan_status, "clean")
        self.assertEqual(attachment.case_id, case.pk)
        facts_response = self.client.post(
            f"/api/cases/{case_id}/facts/confirm/",
            data={
                "facts": {
                    "road_layout": "four_way_intersection",
                    "vehicle_actions": "ego_straight_other_left_turn",
                    "signal_priority": "ego_green",
                    "collision_location": "front_left",
                },
                "sources": [
                    {
                        "source_type": "official_document",
                        "source_ref": attachment.attachment_id,
                    }
                ],
                "conflicts": [],
                "user_edit_history": [],
            },
            content_type="application/json",
        )
        self.assertEqual(facts_response.status_code, 201, facts_response.content)
        fact_version_id = facts_response.json()["fact_version"]["fact_version_id"]
        fact_version = ConfirmedFactVersion.objects.get(fact_version_id=fact_version_id)

        queued_response = self.client.post(
            f"/api/cases/{case_id}/analysis/jobs/",
            data={"fact_version_id": fact_version_id},
            content_type="application/json",
        )
        self.assertEqual(queued_response.status_code, 202, queued_response.content)
        queued = queued_response.json()
        self.assertEqual(
            queued["analysis_plan"]["node_codes"],
            ["text_ml_case_search", "law_ground_search", "objection_report_generation"],
        )

        with (
            patch(
                "etl.fault_cases.src.agents.text_ml_case_search.agent.run_unified_pgvector_pipeline",
                side_effect=_text_rag_provider_response,
            ),
            patch(
                "app.services.legal_rag_service.search_legal_rag",
                side_effect=_legal_rag_provider_response,
            ),
        ):
            processed = process_agent_work_item(queued["work_item"]["work_item_id"])
        self.assertEqual(processed["status"], "success", processed)

        job = AnalysisJob.objects.get(job_id=queued["job"]["job_id"])
        work_item = AgentWorkItem.objects.get(
            work_item_id=queued["work_item"]["work_item_id"]
        )
        report = Report.objects.get(job=job)
        return report, case, fact_version, job, work_item

    def _confirm(self, report: Report, *, client: Client | None = None):
        return (client or self.client).post(
            f"/api/reports/{report.report_id}/document-confirmation/",
            data=REPORT_CONFIRMATION_PAYLOAD,
            content_type="application/json",
        )

    def test_phase_00_worker_result_creates_versioned_report(self) -> None:
        report, case, fact_version, job, work_item = self._create_completed_report()
        report.refresh_from_db()
        case.refresh_from_db()

        self.assertEqual(job.case_id, case.pk)
        self.assertEqual(job.owner_id, self.owner_id)
        self.assertEqual(work_item.job_id, job.pk)
        self.assertEqual(work_item.status, AgentWorkItemStatus.SUCCESS)
        self.assertGreaterEqual(work_item.attempt_no, 1)
        self.assertEqual(
            set(AgentResult.objects.filter(job=job).values_list("node_code", flat=True)),
            {"text_ml_case_search", "law_ground_search", "objection_report_generation"},
        )
        self.assertEqual(AnalysisDisplayResult.objects.filter(job=job).count(), 1)
        self.assertEqual(report.owner_id, self.owner_id)
        self.assertEqual(report.session_id, job.session_id)
        self.assertEqual(report.case_id, case.pk)
        self.assertEqual(report.job_id, job.pk)
        self.assertEqual(report.source_fact_version_id, fact_version.pk)
        self.assertIsNotNone(report.display_result_id)
        self.assertEqual(report.version_no, 1)
        self.assertEqual(case.current_report_version, 1)
        self.assertEqual(report.status, "ready")
        self.assertEqual(Report.objects.filter(job=job).count(), 1)
        self.assertEqual(job.metadata["fact_version_id"], fact_version.fact_version_id)

        detail = self.client.get(f"/api/reports/{report.report_id}/")
        self.assertEqual(detail.status_code, 200, detail.content)
        public_json = json.dumps(detail.json())
        for private_marker in ("storage_uri", "raw_user_text", "Authorization", "token"):
            self.assertNotIn(private_marker, public_json)

    def test_phase_00_owner_confirms_current_report_document(self) -> None:
        report, _case, _fact_version, _job, _work_item = self._create_completed_report()
        foreign = self._confirm(report, client=self.other_client)
        self.assertEqual(foreign.status_code, 403, foreign.content)
        anonymous = Client().post(
            f"/api/reports/{report.report_id}/document-confirmation/",
            data=REPORT_CONFIRMATION_PAYLOAD,
            content_type="application/json",
        )
        self.assertEqual(anonymous.status_code, 401, anonymous.content)

        confirmed = self._confirm(report)
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        confirmation = confirmed.json()["document_confirmation"]
        self.assertTrue(confirmation["required"])
        self.assertTrue(confirmation["confirmed"])
        self.assertFalse(confirmation["stale"])
        self.assertNotIn("input_fingerprint", json.dumps(confirmed.json()))
        self.assertNotIn("storage_uri", json.dumps(confirmed.json()))

        report.refresh_from_db()
        stored = report.metadata["document_confirmation"]
        self.assertEqual(stored["schema_version"], "document_confirmation.v1")
        self.assertEqual(stored["document_type"], "objection_form")
        self.assertEqual(stored["confirmed_by_user_id"], self.owner_id)
        self.assertTrue(stored["input_fingerprint"])

    def test_phase_00_confirmed_report_download_is_owner_only(self) -> None:
        report, _case, _fact_version, _job, _work_item = self._create_completed_report()
        download_url = f"/api/reports/{report.report_id}/download/?document_type=objection_form"
        before_confirmation = self.client.get(download_url)
        self.assertEqual(before_confirmation.status_code, 409, before_confirmation.content)
        self.assertEqual(before_confirmation.json()["error"]["code"], "document_confirmation_required")

        self.assertEqual(self._confirm(report).status_code, 201)
        owner_download = self.client.get(download_url)
        self.assertEqual(owner_download.status_code, 200, owner_download.content)
        self.assertEqual(
            owner_download["Content-Type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertIn("attachment; filename=", owner_download["Content-Disposition"])
        self.assertEqual(owner_download["X-API-Surface"], "canonical")
        self.assertEqual(owner_download["X-Execution-Mode"], "async_worker")
        self.assertEqual(owner_download["X-Report-Document-Type"], "objection_form")
        self.assertTrue(owner_download.content)
        self.assertNotIn(b"mock://", owner_download.content)
        self.assertNotIn(b"storage_uri", owner_download.content)

        foreign = self.other_client.get(download_url)
        self.assertEqual(foreign.status_code, 403, foreign.content)
        anonymous = Client().get(download_url)
        self.assertEqual(anonymous.status_code, 401, anonymous.content)

    def test_phase_00_stale_or_foreign_confirmation_is_rejected(self) -> None:
        report, _case, _fact_version, _job, _work_item = self._create_completed_report()
        self.assertEqual(self._confirm(report).status_code, 201)
        self.assertEqual(self._confirm(report, client=self.other_client).status_code, 403)

        # A reporting provider can replace the persisted document inputs after
        # confirmation.  This test changes only that already-created record;
        # the stale decision itself is made by the public production download
        # boundary, without patching report/auth/download behavior.
        updated_content = deepcopy(report.content)
        updated_content["reporting_payload"]["form_data"]["specific_request"] = (
            "reviewed request after final confirmation"
        )
        report.content = updated_content
        report.save(update_fields=["content", "updated_at"])

        stale_download = self.client.get(
            f"/api/reports/{report.report_id}/download/?document_type=objection_form"
        )
        self.assertEqual(stale_download.status_code, 409, stale_download.content)
        self.assertEqual(stale_download.json()["error"]["code"], "document_confirmation_required")
        self.assertEqual(stale_download.json()["error"]["reason"], "document_confirmation_stale")
