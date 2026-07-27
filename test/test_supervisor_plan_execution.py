from __future__ import annotations

from unittest.mock import patch

from app.services.agent_node_service import execute_agent_plan
from app.services.chat_orchestration_service import compose_agent_response, submit_message


@patch("app.services.agent_node_service._run_sync_adapter")
def test_canonical_plan_executes_supervisor_validation_and_final_merge(run_adapter) -> None:
    run_adapter.return_value = {
        "status": "success",
        "summary": "도로교통법 근거 후보를 확인했습니다.",
        "structured_result": {"matched_laws": [{"law_name": "도로교통법"}]},
        "evidence": [{"source_reference": "law:1"}],
        "next_actions": [],
        "limitations": ["사건별 적용 여부를 확인해야 합니다."],
    }
    chat = submit_message(
        {
            "session_id": "ses_supervisor_plan",
            "user_text": "도로교통법상 교차로 통행 기준이 궁금합니다.",
        }
    )

    execution = execute_agent_plan(
        chat["analysis_plan"],
        {
            "job_id": "job_supervisor_plan",
            "session_id": "ses_supervisor_plan",
            "user_text": "도로교통법상 교차로 통행 기준이 궁금합니다.",
        },
    )
    response = compose_agent_response(execution)

    assert [item["node_code"] for item in execution["executions"]] == [
        "input_context_validation",
        "law_ground_search",
        "agent_result_validation",
        "final_response_merge",
    ]
    assert response["assistant_message"]["answer"] == "도로교통법 근거 후보를 확인했습니다."
    assert response["evidence"] == [{"source_reference": "law:1"}]


@patch("app.services.agent_node_service._run_sync_adapter")
def test_video_plan_uses_the_sync_vision_adapter_and_preserves_partial_result(run_adapter) -> None:
    def adapter(agent_input, _adapter_context):
        if agent_input["node_code"] == "vision_media_analysis":
            return {
                "status": "partial",
                "summary": "Vision evidence was extracted for review.",
                "structured_result": {"analysis_kind": "accident_evidence"},
                "evidence": [],
                "next_actions": ["review_evidence_with_case_and_law_sources"],
                "limitations": ["Vision does not determine fault or legal responsibility."],
            }
        return {
            "status": "success",
            "summary": f"{agent_input['node_code']} result",
            "structured_result": {},
            "evidence": [],
            "next_actions": [],
            "limitations": [],
        }

    run_adapter.side_effect = adapter
    chat = submit_message(
        {
            "session_id": "ses_video_sync",
            "user_text": "Please analyze this dashcam video.",
            "attachments": [
                {"attachment_id": "att_video_sync", "purpose": "blackbox_video", "status": "ready"}
            ],
        }
    )

    execution = execute_agent_plan(chat["analysis_plan"], {"session_id": "ses_video_sync"})
    vision = next(item for item in execution["executions"] if item["node_code"] == "vision_media_analysis")

    assert execution["execution_mode"] == "sync"
    assert vision["execution_mode"] == "sync"
    assert vision["agent_output"]["status"] == "partial"
    assert vision["agent_output"]["structured_result"]["analysis_kind"] == "accident_evidence"


def test_pdf_notice_e2e_executes_document_classification_adapter_boundary(monkeypatch) -> None:
    from app.services import agent_node_service
    from app.services import attachment_document_classification_adapter as classification_adapter
    from app.services.attachment_mock_service import CANONICAL_SCAN_GATE_MARKER

    storage_uri = "s3://clean-bucket/canonical/uploads/usr/ses_pdf/att_notice_pdf/notice.pdf"
    monkeypatch.setattr(
        agent_node_service,
        "_attachment_object_storage_bytes",
        lambda attachment, expected_uri: b"%PDF-1.7" if expected_uri == storage_uri else None,
    )
    monkeypatch.setattr(
        classification_adapter,
        "classify_document_bytes",
        lambda _bytes, _content_type: {
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
    )
    monkeypatch.setattr(
        agent_node_service,
        "_persist_attachment_document_classification",
        lambda **_kwargs: None,
        raising=False,
    )
    request = {
        "session_id": "ses_pdf_notice_e2e",
        "user_text": "첨부한 고지서가 어떤 문서인지 확인해 주세요.",
        "attachments": [
            {
                "_canonical_scan_gate": CANONICAL_SCAN_GATE_MARKER,
                "attachment_id": "att_notice_pdf",
                "purpose": "fine_notice",
                "type": "pdf",
                "content_type": "application/pdf",
                "status": "ready",
                "scan_status": "clean",
                "resolution_status": "scan_ready",
                "metadata_source": "canonical_scan_gate",
                "storage_uri": storage_uri,
                "object_storage": {
                    "resource_type": "uploaded_file",
                    "status": "ready",
                    "storage_uri": storage_uri,
                },
            }
        ],
    }

    chat = submit_message(request)
    execution = execute_agent_plan(
        chat["analysis_plan"],
        {**request, "context": {"supervisor_handoff": chat["supervisor_state"]}},
    )
    assert [item["node_code"] for item in execution["executions"]] == [
        "input_context_validation",
        "attachment_document_classification",
        "agent_result_validation",
        "final_response_merge",
    ]
    outputs = {item["node_code"]: item["agent_output"] for item in execution["executions"]}
    classification = outputs["attachment_document_classification"]["structured_result"]
    assert classification["classification"] == "fine_notice"
    assert classification["requires_confirmation"] is True
    assert classification["attachment_id"] == "att_notice_pdf"


def test_unknown_document_classification_e2e_requires_change_purpose(monkeypatch) -> None:
    from app.services import agent_node_service
    from app.services import attachment_document_classification_adapter as classification_adapter
    from app.services.attachment_mock_service import CANONICAL_SCAN_GATE_MARKER

    storage_uri = "s3://clean-bucket/canonical/uploads/usr/ses_unknown/att_unknown/scene.png"
    monkeypatch.setattr(
        agent_node_service,
        "_attachment_object_storage_bytes",
        lambda attachment, expected_uri: b"png-bytes" if expected_uri == storage_uri else None,
    )
    monkeypatch.setattr(
        classification_adapter,
        "classify_document_bytes",
        lambda _bytes, _content_type: {
            "status": "partial",
            "structured_result": {
                "classification": "unknown",
                "confidence_band": "low",
                "requires_confirmation": False,
                "next_action": "change_purpose",
            },
            "evidence": [],
            "next_actions": ["change_purpose"],
            "limitations": ["Document classification did not produce a confirmed category."],
        },
    )
    request = {
        "session_id": "ses_unknown_doc_e2e",
        "user_text": "이 첨부 자료의 종류를 확인해 주세요.",
        "attachments": [
            {
                "_canonical_scan_gate": CANONICAL_SCAN_GATE_MARKER,
                "attachment_id": "att_unknown",
                "purpose": "accident_scene",
                "type": "image",
                "content_type": "image/png",
                "status": "ready",
                "scan_status": "clean",
                "resolution_status": "scan_ready",
                "metadata_source": "canonical_scan_gate",
                "storage_uri": storage_uri,
                "object_storage": {
                    "resource_type": "uploaded_file",
                    "status": "ready",
                    "storage_uri": storage_uri,
                },
            }
        ],
    }

    chat = submit_message(request)
    execution = execute_agent_plan(
        chat["analysis_plan"],
        {**request, "context": {"supervisor_handoff": chat["supervisor_state"]}},
    )
    outputs = {item["node_code"]: item["agent_output"] for item in execution["executions"]}
    classification = outputs["attachment_document_classification"]["structured_result"]
    assert classification["classification"] == "unknown"
    assert classification["requires_confirmation"] is False
    assert classification["next_action"] == "change_purpose"
    assert (
        "Document classification did not produce a confirmed category."
        in outputs["attachment_document_classification"]["limitations"]
    )


def test_unsupported_document_classification_e2e_returns_safe_retry_upload(monkeypatch) -> None:
    from app.services import agent_node_service
    from app.services import attachment_document_classification_adapter as classification_adapter
    from app.services.attachment_mock_service import CANONICAL_SCAN_GATE_MARKER

    storage_uri = "s3://clean-bucket/canonical/uploads/usr/ses_unsupported/att_bad/file.png"
    monkeypatch.setattr(
        agent_node_service,
        "_attachment_object_storage_bytes",
        lambda attachment, expected_uri: b"bad-bytes" if expected_uri == storage_uri else None,
    )
    monkeypatch.setattr(
        classification_adapter,
        "classify_document_bytes",
        lambda _bytes, _content_type: {
            "status": "failed",
            "structured_result": {
                "classification": "unknown",
                "confidence_band": "low",
                "requires_confirmation": False,
                "next_action": "retry_upload",
                "error_code": "unsupported_document_classification_input",
            },
            "evidence": [],
            "next_actions": ["retry_upload"],
            "limitations": ["Document classification could not be completed safely."],
        },
    )
    request = {
        "session_id": "ses_unsupported_doc_e2e",
        "user_text": "첨부 파일을 확인해 주세요.",
        "attachments": [
            {
                "_canonical_scan_gate": CANONICAL_SCAN_GATE_MARKER,
                "attachment_id": "att_bad",
                "purpose": "fine_notice",
                "type": "image",
                "content_type": "image/png",
                "status": "ready",
                "scan_status": "clean",
                "resolution_status": "scan_ready",
                "metadata_source": "canonical_scan_gate",
                "storage_uri": storage_uri,
                "object_storage": {
                    "resource_type": "uploaded_file",
                    "status": "ready",
                    "storage_uri": storage_uri,
                },
            }
        ],
    }

    chat = submit_message(request)
    execution = execute_agent_plan(
        chat["analysis_plan"],
        {**request, "context": {"supervisor_handoff": chat["supervisor_state"]}},
    )
    outputs = {item["node_code"]: item["agent_output"] for item in execution["executions"]}
    classification = outputs["attachment_document_classification"]["structured_result"]
    assert classification["error_code"] == "unsupported_document_classification_input"
    assert classification["next_action"] == "retry_upload"
    assert (
        "Document classification did not produce a confirmed category."
        in outputs["attachment_document_classification"]["limitations"]
    )


def test_accident_scene_photo_e2e_executes_case_and_law_adapters_without_vision(monkeypatch) -> None:
    from ai.agents import law_ground_search as law_ground_package
    from ai.agents import text_ml_case_search as case_search_package
    from app.services.attachment_mock_service import CANONICAL_SCAN_GATE_MARKER

    monkeypatch.setattr(
        case_search_package,
        "run_text_ml_case_search",
        lambda _agent_input, _adapter_context: {
            "status": "success",
            "summary": "사고 사진 기반 사례 후보를 정리했습니다.",
            "structured_result": {
                "similar_cases": [{"case_id": "case-1", "summary": "intersection merge"}],
                "retrieval": {"status": "ready", "backend": "case_rag"},
            },
            "evidence": [{"source_reference": "case:1"}],
            "next_actions": [],
            "limitations": [],
        },
    )
    monkeypatch.setattr(
        law_ground_package,
        "run_law_ground_search",
        lambda _agent_input, _adapter_context, llm_extractor=None: {
            "status": "success",
            "summary": "관련 법령을 정리했습니다.",
            "structured_result": {
                "law_provisions": [
                    {
                        "source_ref": "law:road-traffic:32",
                        "source_name": "Road Traffic Act",
                        "article_no": "Article 32",
                        "provision_text": "Drivers must avoid unsafe lane encroachment.",
                    }
                ]
            },
            "evidence": [{"source_reference": "law:road-traffic:32"}],
            "next_actions": [],
            "limitations": [],
        },
    )
    request = {
        "session_id": "ses_accident_photo_e2e",
        "user_text": "사고 사진 기준으로 관련 사례와 법령을 보여 주세요.",
        "attachments": [
            {
                "_canonical_scan_gate": CANONICAL_SCAN_GATE_MARKER,
                "attachment_id": "att_photo_e2e",
                "purpose": "accident_scene",
                "type": "image",
                "content_type": "image/png",
                "status": "ready",
                "scan_status": "clean",
                "resolution_status": "scan_ready",
                "storage_uri": "s3://clean-bucket/canonical/uploads/usr/ses_photo/att_photo_e2e/scene.png",
                "object_storage": {
                    "resource_type": "uploaded_file",
                    "status": "ready",
                    "storage_uri": "s3://clean-bucket/canonical/uploads/usr/ses_photo/att_photo_e2e/scene.png",
                },
            }
        ],
    }

    chat = submit_message(request, routing_intent_override="accident_photo_evidence_analysis")
    execution = execute_agent_plan(
        chat["analysis_plan"],
        {**request, "context": {"supervisor_handoff": chat["supervisor_state"]}},
    )
    assert [item["node_code"] for item in execution["executions"]] == [
        "input_context_validation",
        "text_ml_case_search",
        "law_ground_search",
        "agent_result_validation",
        "final_response_merge",
    ]
    outputs = {item["node_code"]: item["agent_output"] for item in execution["executions"]}
    assert "vision_media_analysis" not in outputs
    assert outputs["text_ml_case_search"]["structured_result"]["similar_cases"][0]["case_id"] == "case-1"
    assert outputs["law_ground_search"]["structured_result"]["matched_laws"][0]["source_reference"] == (
        "law:road-traffic:32"
    )


def test_blackbox_video_e2e_executes_vision_case_and_law_adapter_boundaries(monkeypatch) -> None:
    from ai.agents import law_ground_search as law_ground_package
    from ai.agents import text_ml_case_search as case_search_package
    from app.services import vision_media_analysis_adapter

    monkeypatch.setattr(
        vision_media_analysis_adapter,
        "run_vision_media_analysis",
        lambda _agent_input, _adapter_context: {
            "status": "partial",
            "summary": "블랙박스 핵심 장면을 추렸습니다.",
            "structured_result": {"analysis_kind": "accident_evidence"},
            "evidence": [],
            "next_actions": ["review_evidence_with_case_and_law_sources"],
            "limitations": ["Vision does not determine fault or legal responsibility."],
        },
    )
    monkeypatch.setattr(
        case_search_package,
        "run_text_ml_case_search",
        lambda _agent_input, _adapter_context: {
            "status": "success",
            "summary": "관련 심의사례를 정리했습니다.",
            "structured_result": {
                "similar_cases": [{"case_id": "case-video-1"}],
                "retrieval": {"status": "ready", "backend": "case_rag"},
            },
            "evidence": [{"source_reference": "case:video:1"}],
            "next_actions": [],
            "limitations": [],
        },
    )
    monkeypatch.setattr(
        law_ground_package,
        "run_law_ground_search",
        lambda _agent_input, _adapter_context, llm_extractor=None: {
            "status": "success",
            "summary": "관련 법령을 찾았습니다.",
            "structured_result": {
                "law_provisions": [
                    {
                        "source_ref": "law:road-traffic:13",
                        "source_name": "Road Traffic Act",
                        "article_no": "Article 13",
                        "provision_text": "Drivers must maintain lane discipline.",
                    }
                ]
            },
            "evidence": [{"source_reference": "law:road-traffic:13"}],
            "next_actions": [],
            "limitations": [],
        },
    )
    request = {
        "session_id": "ses_blackbox_e2e",
        "user_text": "블랙박스 영상으로 관련 사례와 법령을 확인해 주세요.",
        "attachments": [
            {"attachment_id": "att_blackbox_e2e", "purpose": "blackbox_video", "status": "ready"}
        ],
    }

    chat = submit_message(request)
    execution = execute_agent_plan(
        chat["analysis_plan"],
        {**request, "context": {"supervisor_handoff": chat["supervisor_state"]}},
    )
    assert [item["node_code"] for item in execution["executions"]] == [
        "input_context_validation",
        "vision_media_analysis",
        "text_ml_case_search",
        "law_ground_search",
        "agent_result_validation",
        "final_response_merge",
    ]
    outputs = {item["node_code"]: item["agent_output"] for item in execution["executions"]}
    assert outputs["vision_media_analysis"]["structured_result"]["analysis_kind"] == "accident_evidence"
    assert outputs["text_ml_case_search"]["structured_result"]["similar_cases"][0]["case_id"] == (
        "case-video-1"
    )
    assert outputs["law_ground_search"]["structured_result"]["matched_laws"][0]["source_reference"] == (
        "law:road-traffic:13"
    )


@patch("app.services.agent_node_service._run_sync_adapter")
def test_report_agent_is_not_executed_when_validation_report_gate_is_closed(run_adapter) -> None:
    called_nodes: list[str] = []

    def adapter(agent_input, _adapter_context):
        called_nodes.append(agent_input["node_code"])
        return {
            "status": "success",
            "summary": f"{agent_input['node_code']} result",
            "structured_result": {},
            "evidence": [],
            "next_actions": [],
            "limitations": [],
        }

    run_adapter.side_effect = adapter
    plan = {
        "contract_version": "analysis_plan.v2",
        "plan_id": "plan_closed_report_gate",
        "session_id": "ses_closed_report_gate",
        "message_id": "msg_closed_report_gate",
        "routing_intent": "fine_notice_analysis",
        "steps": [
            {
                "order": 1,
                "node_code": "input_context_validation",
                "status": "ready",
                "depends_on": [],
                "context": {"routing_intent": "fine_notice_analysis"},
            },
            {
                "order": 2,
                "node_code": "fine_notice_analysis",
                "status": "ready",
                "depends_on": ["input_context_validation"],
            },
            {
                "order": 3,
                "node_code": "law_ground_search",
                "status": "ready",
                "depends_on": ["fine_notice_analysis"],
            },
            {
                "order": 4,
                "node_code": "appeal_decision_flow",
                "status": "ready",
                "depends_on": ["law_ground_search"],
            },
            {
                "order": 5,
                "node_code": "agent_result_validation",
                "status": "ready",
                "depends_on": ["appeal_decision_flow"],
                "context": {
                    "routing_intent": "fine_notice_analysis",
                    "expected_node_codes": [
                        "fine_notice_analysis",
                        "law_ground_search",
                        "appeal_decision_flow",
                        "objection_report_generation",
                    ],
                    "report_requested": True,
                },
            },
            {
                "order": 6,
                "node_code": "objection_report_generation",
                "status": "ready",
                "depends_on": ["agent_result_validation"],
            },
            {
                "order": 7,
                "node_code": "final_response_merge",
                "status": "ready",
                "depends_on": ["objection_report_generation"],
            },
        ],
    }

    execution = execute_agent_plan(
        plan,
        {
            "job_id": "job_closed_report_gate",
            "user_text": "이의신청서를 작성해 주세요.",
        },
    )

    assert "objection_report_generation" not in called_nodes
    assert "objection_report_generation" not in [
        item["node_code"] for item in execution["executions"]
    ]
    assert execution["executions"][-1]["node_code"] == "final_response_merge"
