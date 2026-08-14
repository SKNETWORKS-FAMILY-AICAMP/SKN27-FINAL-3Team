"""Public worker node isolation regressions for the canonical runtime."""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import types
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterator
from unittest.mock import Mock, patch
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from app.services.agent_node_service import list_public_agent_nodes
from chatbot.file_scan_service import scan_uploaded_file
from chatbot.models import AgentResult, AgentWorkItem, AnalysisJob, ChatSession, ChatSessionStatus
from chatbot.repositories import enqueue_analysis_job_work, process_agent_work_items
from chatbot.test_phase_01_dynamic_negative_reachability import (
    MOCK_MARKERS,
    TEST_JWT_SIGNING_KEY,
    _authenticated_client,
    explicit_mock_usage_forbidden,
)


PUBLIC_NODE_CODES = {
    "fine_notice_analysis",
    "attachment_document_classification",
    "law_ground_search",
    "text_ml_case_search",
    "traffic_accident_confirmation_ocr",
    "vision_media_analysis",
    "appeal_decision_flow",
    "objection_report_generation",
}


@contextmanager
def deterministic_provider_leaves() -> Iterator[dict[str, Mock]]:
    """Replace provider leaves only; the queue, worker, adapters, and ORM stay real."""

    from ai.agents.appeal_decision_flow import graph as appeal_graph
    from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.graph import graph as traffic_graph

    classification_module_name = "app.services.attachment_document_classification_adapter"
    try:
        classification_adapter = importlib.import_module(classification_module_name)
    except ImportError:
        classification_adapter = types.ModuleType(classification_module_name)
        classification_adapter.classify_document_bytes = Mock()
        sys.modules.pop(classification_module_name, None)
        classification_import_fallback = {classification_module_name: classification_adapter}
    else:
        classification_import_fallback = {}
    vision_adapter = importlib.import_module("app.services.vision_media_analysis_adapter")
    law_agent = importlib.import_module("ai.agents.law_ground_search")
    text_agent = importlib.import_module("ai.agents.text_ml_case_search")
    report_agent = importlib.import_module("ai.agents.objection_report_generation")

    fine_notice_module_name = "ai.agents.fine_notice_analysis.graph"
    fine_notice_package_name = "ai.agents.fine_notice_analysis"
    try:
        fine_notice_graph = importlib.import_module(fine_notice_module_name).graph
    except ImportError:
        fine_notice_graph = types.SimpleNamespace(invoke=Mock())
        fallback_module = types.ModuleType(fine_notice_module_name)
        fallback_module.graph = fine_notice_graph
        fallback_package = types.ModuleType(fine_notice_package_name)
        fallback_package.__path__ = []
        fallback_package.graph = fine_notice_graph
        sys.modules.pop(fine_notice_module_name, None)
        sys.modules.pop(fine_notice_package_name, None)
        fine_notice_import_fallback = {
            fine_notice_package_name: fallback_package,
            fine_notice_module_name: fallback_module,
        }
    else:
        fine_notice_import_fallback = {}
    def fine_notice_result(_state: dict) -> dict:
        return {
            "agent_results": {
                "fine_notice_analysis": {
                    "status": "success",
                    "summary": "Deterministic fine notice analysis.",
                    "structured_result": {
                        "ocr_status": "success",
                        "fine_type": "fine",
                        "notice_stage": "pre_notice",
                        "opinion_deadline": "2026-12-31",
                        "issuing_authority": "Deterministic Traffic Authority",
                    },
                    "evidence": [],
                    "next_actions": [],
                    "limitations": [],
                }
            }
        }

    def appeal_result(_state: dict) -> dict:
        return {
            "agent_results": {
                "appeal_judgment": {
                    "status": "success",
                    "summary": "Deterministic appeal decision.",
                    "structured_result": {
                        "judgment_status": "success",
                        "overall_possibility": "review_available",
                    },
                    "evidence": [],
                    "next_actions": [],
                    "limitations": [],
                }
            }
        }

    def traffic_result(_state: dict) -> dict:
        return {
            "agent_results": {
                "traffic_accident_confirmation_ocr": {
                    "status": "success",
                    "summary": "Deterministic traffic confirmation OCR.",
                    "structured_result": {
                        "document_check": {"status": "confirmed"},
                        "extracted_fields": {"accident_date": "2026-01-01"},
                    },
                    "evidence": [],
                    "next_actions": [],
                    "limitations": [],
                }
            }
        }

    def standard_output(summary: str, structured_result: dict | None = None) -> dict:
        return {
            "status": "success",
            "summary": summary,
            "structured_result": structured_result or {},
            "evidence": [],
            "next_actions": [],
            "limitations": [],
        }

    def report_result(agent_input: dict, _adapter_context: dict) -> dict:
        handoff = agent_input["context"]["supervisor_reporting_handoff"]
        source = handoff["source"]
        return standard_output(
            "Deterministic objection report.",
            {
                "document_type": "objection_form",
                "document_variant": "fine_notice",
                "document_title": "Deterministic objection form",
                "form_sections": [{"title": "Petition", "items": ["Review disposition."]}],
                "form_data": {"applicant_name": "Review required"},
                "petition_purpose": "Review disposition.",
                "petition_reason": "Review verified facts and legal grounds.",
                "appeal_gate": {"status": "ready"},
                "document_readiness": {"status": "review_required"},
                "report_actions": [{"action": "download_objection", "label": "Download form"}],
                "supervisor_handoff": {
                    "contract_version": handoff["contract_version"],
                    "handoff_id": handoff["handoff_id"],
                    "gate_status": handoff["gate"]["status"],
                    "source_fingerprint": source["fingerprint"],
                    "source_result_ids": source["result_ids"],
                },
            },
        )

    with ExitStack() as stack:
        if fine_notice_import_fallback:
            stack.enter_context(patch.dict(sys.modules, fine_notice_import_fallback))
        if classification_import_fallback:
            stack.enter_context(patch.dict(sys.modules, classification_import_fallback))
        leaves = {
            "fine_notice_analysis": stack.enter_context(
                patch.object(fine_notice_graph, "invoke", side_effect=fine_notice_result)
            ),
            "attachment_document_classification": stack.enter_context(
                patch.object(
                    classification_adapter,
                    "classify_document_bytes",
                    return_value=standard_output(
                        "Deterministic document classification.",
                        {
                            "classification": "fine_notice",
                            "confidence_band": "high",
                            "requires_confirmation": True,
                            "next_action": "confirm_classification",
                        },
                    ),
                )
            ),
            "law_ground_search": stack.enter_context(
                patch.object(
                    law_agent,
                    "run_law_ground_search",
                    side_effect=lambda *_args, **_kwargs: standard_output(
                        "Deterministic law search.",
                        {"law_provisions": [], "matched_laws": []},
                    ),
                )
            ),
            "text_ml_case_search": stack.enter_context(
                patch.object(
                    text_agent,
                    "run_text_ml_case_search",
                    side_effect=lambda *_args, **_kwargs: standard_output(
                        "Deterministic case search.",
                        {"similar_cases": [], "top_cases": [], "reliability_score": 0},
                    ),
                )
            ),
            "traffic_accident_confirmation_ocr": stack.enter_context(
                patch.object(traffic_graph, "invoke", side_effect=traffic_result)
            ),
            "vision_media_analysis": stack.enter_context(
                patch.object(
                    vision_adapter,
                    "run_vision_media_analysis",
                    side_effect=lambda *_args, **_kwargs: standard_output(
                        "Deterministic vision analysis.",
                        {"detected_object_summary": "No unsafe inference."},
                    ),
                )
            ),
            "appeal_decision_flow": stack.enter_context(
                patch.object(appeal_graph, "invoke", side_effect=appeal_result)
            ),
            "objection_report_generation": stack.enter_context(
                patch.object(
                    report_agent,
                    "run_objection_report_generation",
                    side_effect=report_result,
                )
            ),
        }
        yield leaves


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class PublicWorkerNodeIsolationTests(TestCase):
    def setUp(self) -> None:
        self.object_root = tempfile.TemporaryDirectory()
        self.staging_root = tempfile.TemporaryDirectory()
        self.mock_upload_root = tempfile.TemporaryDirectory()
        self.mock_job_root = tempfile.TemporaryDirectory()
        self.mock_history_root = tempfile.TemporaryDirectory()
        for resource in (
            self.object_root,
            self.staging_root,
            self.mock_upload_root,
            self.mock_job_root,
            self.mock_history_root,
        ):
            self.addCleanup(resource.cleanup)
        self.settings_override = override_settings(
            OBJECT_STORAGE_PROVIDER="mock_s3",
            OBJECT_STORAGE_BUCKET="phase-01-public-worker-clean",
            OBJECT_STORAGE_QUARANTINE_BUCKET="phase-01-public-worker-quarantine",
            OBJECT_STORAGE_LOCAL_ROOT=self.object_root.name,
            ATTACHMENT_STAGING_ROOT=self.staging_root.name,
            MOCK_UPLOAD_ROOT=self.mock_upload_root.name,
            FILE_SCAN_PROVIDER="local_policy",
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.environment_override = patch.dict(
            os.environ,
            {
                "MOCK_UPLOAD_ROOT": self.mock_upload_root.name,
                "MOCK_ANALYSIS_JOB_ROOT": self.mock_job_root.name,
                "MOCK_HISTORY_EVENT_ROOT": self.mock_history_root.name,
            },
        )
        self.environment_override.start()
        self.addCleanup(self.environment_override.stop)
        suffix = uuid4().hex
        self.owner_id = f"usr_{suffix[:8]}"
        self.session_id = f"ses_{suffix[:8]}"
        self.client = _authenticated_client(self.owner_id)
        ChatSession.objects.create(
            session_id=self.session_id,
            owner_id=self.owner_id,
            status=ChatSessionStatus.ACTIVE,
        )

    def _upload(self, *, purpose: str, filename: str, body: bytes, content_type: str) -> str:
        response = self.client.post(
            "/api/files/",
            data={
                "session_id": self.session_id,
                "purpose": purpose,
                "file": SimpleUploadedFile(filename, body, content_type=content_type),
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        attachment_id = response.json()["attachment"]["attachment_id"]
        uploaded = self.client.get(f"/api/files/{attachment_id}/?session_id={self.session_id}")
        self.assertEqual(uploaded.status_code, 200, uploaded.content)
        from chatbot.models import UploadedFile

        scan = scan_uploaded_file(UploadedFile.objects.get(attachment_id=attachment_id))
        self.assertEqual(scan["status"], "clean", scan)
        return attachment_id

    def _enqueue_full_public_plan(self, attachment_ids: list[str]) -> tuple[str, str]:
        suffix = uuid4().hex
        job_id = f"job_{suffix[:8]}"
        message_id = f"msg_{suffix[:8]}"
        plan_id = f"plan_{suffix[:8]}"
        ordered_node_codes = [
            node_code
            for node_code in sorted(PUBLIC_NODE_CODES)
            if node_code != "objection_report_generation"
        ]
        ordered_node_codes.append("objection_report_generation")
        steps = [
            {"order": order, "node_code": node_code, "status": "ready", "depends_on": []}
            for order, node_code in enumerate(ordered_node_codes, start=1)
        ]
        queued = enqueue_analysis_job_work(
            {
                "owner_id": self.owner_id,
                "user_id": self.owner_id,
                "session_id": self.session_id,
                "message_id": message_id,
                "user_text": "Execute every public canonical worker node.",
                "attachments": [{"attachment_id": attachment_id} for attachment_id in attachment_ids],
            },
            {
                "job_id": job_id,
                "session_id": self.session_id,
                "message_id": message_id,
                "routing_intent": "phase_01_public_worker_isolation",
                "status": "queued",
                "active_node": steps[0]["node_code"],
                "progress_message": "Phase 1 public worker isolation queued.",
                "analysis_plan_id": plan_id,
                "analysis_plan": {
                    "contract_version": "analysis_plan.v2",
                    "plan_id": plan_id,
                    "session_id": self.session_id,
                    "message_id": message_id,
                    "routing_intent": "phase_01_public_worker_isolation",
                    "steps": steps,
                },
                "attachments": [{"attachment_id": attachment_id} for attachment_id in attachment_ids],
                "chat_response": {},
                "node_execution": {},
            },
            server_execution_context={
                "ocr_confirmation": {
                    "confirmed": True,
                    "fields": {"fine_type": "fine", "notice_stage": "pre_notice"},
                }
            },
        )
        self.assertEqual(queued["status"], "queued", queued)
        return job_id, queued["work_item_id"]

    def test_every_public_node_runs_through_canonical_queue_without_explicit_mock_reachability(self) -> None:
        attachment_ids = [
            self._upload(
                purpose="fine_notice",
                filename="notice.png",
                body=b"deterministic fine notice image",
                content_type="image/png",
            ),
            self._upload(
                purpose="traffic_accident_confirmation",
                filename="confirmation.png",
                body=b"deterministic traffic confirmation image",
                content_type="image/png",
            ),
            self._upload(
                purpose="blackbox_video",
                filename="blackbox.mp4",
                body=b"deterministic blackbox video bytes",
                content_type="video/mp4",
            ),
        ]
        job_id, work_item_id = self._enqueue_full_public_plan(attachment_ids)

        with deterministic_provider_leaves() as provider_leaves:
            with explicit_mock_usage_forbidden() as explicit_mock_calls:
                processed = process_agent_work_items(limit=1)
                public_nodes_response = self.client.get("/api/agents/nodes/")

        for target, explicit_mock_call in explicit_mock_calls.items():
            self.assertEqual(explicit_mock_call.call_count, 0, target)
        self.assertEqual(processed["processed"], 1, processed)
        self.assertEqual(processed["work_items"][0]["status"], "success", processed)
        self.assertEqual(public_nodes_response.status_code, 200, public_nodes_response.content)
        expected_node_codes = {node["node_code"] for node in list_public_agent_nodes()}
        self.assertEqual(expected_node_codes, PUBLIC_NODE_CODES)
        self.assertEqual(
            {node["node_code"] for node in public_nodes_response.json()["nodes"]},
            expected_node_codes,
        )
        self.assertEqual(set(provider_leaves), expected_node_codes)
        for node_code, provider_leaf in provider_leaves.items():
            self.assertEqual(provider_leaf.call_count, 1, node_code)

        job = AnalysisJob.objects.get(job_id=job_id)
        work_item = AgentWorkItem.objects.get(work_item_id=work_item_id)
        agent_results = list(AgentResult.objects.filter(job=job).order_by("node_code"))
        self.assertEqual(job.status, "success")
        self.assertEqual(job.mock_scenario, "")
        self.assertEqual(work_item.status, "success")
        self.assertFalse(work_item.error_code)
        self.assertEqual({result.node_code for result in agent_results}, expected_node_codes)
        self.assertTrue(all(result.status == "success" for result in agent_results))

        persisted = json.dumps(
            {
                "job_metadata": job.metadata,
                "work_item_result": work_item.result,
                "agent_results": [
                    {"raw_output": result.raw_output, "structured_result": result.structured_result}
                    for result in agent_results
                ],
            },
            ensure_ascii=False,
        )
        public = json.dumps(public_nodes_response.json(), ensure_ascii=False)
        for marker in MOCK_MARKERS:
            self.assertNotIn(marker, persisted)
            self.assertNotIn(marker, public)
        self.assertNotIn("mock://", persisted)
        self.assertNotIn("mock://", public)
        for sidecar_root in (
            self.mock_upload_root.name,
            self.mock_job_root.name,
            self.mock_history_root.name,
        ):
            self.assertEqual(list(Path(sidecar_root).rglob("*")), [])