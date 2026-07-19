import json

from app.services import agent_node_service
from app.services.agent_adapter_contract import validate_agent_output_envelope
from app.services.agent_node_service import execute_agent_node, list_agent_nodes, list_public_agent_nodes
from app.services.attachment_mock_service import register_attachment
from app.services.chat_orchestration_service import submit_message
from app.services.supervisor_routing_service import plan_node_codes, route_supervisor_input
from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr import (
    agent as traffic_ocr_agent,
)


TRAFFIC_OCR_RESPONSE = {
    "document_name": "교통사고사실확인원",
    "detected_labels": ["발생일시", "발생장소", "사고유형", "사고원인"],
    "issuer_labels": ["경찰서", "발급번호"],
    "page_info": {"page_1_processed": True, "page_2_exists": False},
    "extracted_fields": {
        "receipt_number": "1234-5678",
        "issue_number": "2026-1234",
        "police_station": "서울노원경찰서",
        "accident_datetime": "2026-06-25 14:30",
        "accident_location": "서울시 노원구",
        "accident_type": {"value": "차대차", "raw_text": "차대차"},
        "accident_cause": "안전운전의무불이행",
        "damage": {"raw_text": "물적피해", "death_count": 0, "injury_count": 0},
        "usage": "보험사 제출용",
        "accident_description": "차량 12가3456이 충돌했고 연락처는 010-1234-5678입니다.",
    },
    "raw_text_redacted": "원문 OCR 텍스트 900101-1234567",
    "quality": {"ocr_confidence": 0.95, "image_quality": "readable", "warnings": []},
    "limitations": [],
}


def _scan_ready_attachment() -> dict:
    return {
        "attachment_id": "att_traffic_confirmation_001",
        "purpose": "traffic_accident_confirmation",
        "content_type": "image/jpeg",
        "filename": "traffic-confirmation.jpg",
        "storage_uri": "s3://skn27-demo-object-storage/canonical/traffic-confirmation.jpg",
        "status": "ready",
        "scan_status": "clean",
        "resolution_status": "scan_ready",
        "metadata_source": "canonical_scan_gate",
        "object_storage": {
            "resource_type": "uploaded_file",
            "status": "ready",
            "storage_uri": "s3://skn27-demo-object-storage/canonical/traffic-confirmation.jpg",
        },
    }


def test_traffic_accident_confirmation_ocr_is_a_public_sync_agent():
    registry_nodes = {node["node_code"]: node for node in list_agent_nodes()}
    public_nodes = {node["node_code"]: node for node in list_public_agent_nodes()}

    assert registry_nodes["traffic_accident_confirmation_ocr"]["adapter_modes"] == ["sync"]
    assert registry_nodes["traffic_accident_confirmation_ocr"]["adapter_contract"]["execution_modes"] == ["sync"]
    assert "traffic_accident_confirmation_ocr" in public_nodes


def test_traffic_accident_confirmation_attachment_routes_to_ocr_plan():
    attachments = [{"purpose": "traffic_accident_confirmation"}]

    intent = route_supervisor_input("교통사고 사실확인원을 확인해 주세요.", attachments)

    assert intent == "traffic_accident_confirmation_ocr"
    assert plan_node_codes(intent, report_requested=False) == (
        "input_context_validation",
        "traffic_accident_confirmation_ocr",
        "agent_result_validation",
        "final_response_merge",
    )


def test_chat_submission_builds_the_ocr_execution_plan_for_confirmation_attachment():
    response = submit_message(
        {
            "session_id": "ses_traffic_ocr_plan",
            "user_text": "사실확인원 내용을 확인해 주세요.",
            "attachments": [
                {
                    "attachment_id": "att_traffic_ocr_plan",
                    "purpose": "traffic_accident_confirmation",
                    "content_type": "image/jpeg",
                    "storage_uri": "s3://skn27-demo-object-storage/canonical/traffic-plan.jpg",
                }
            ],
        }
    )

    assert response["status"] == "queued"
    assert response["routing_intent"] == "traffic_accident_confirmation_ocr"
    assert [step["node_code"] for step in response["analysis_plan"]["steps"]] == [
        "input_context_validation",
        "traffic_accident_confirmation_ocr",
        "agent_result_validation",
        "final_response_merge",
    ]


def test_attachment_registry_keeps_traffic_confirmation_purpose():
    attachment = register_attachment(
        {
            "attachment_id": "att_traffic_confirmation_purpose",
            "filename": "traffic_confirmation.jpg",
            "content_type": "image/jpeg",
            "purpose": "traffic_accident_confirmation",
        }
    )

    assert attachment["purpose"] == "traffic_accident_confirmation"


def test_sync_runtime_reaches_actual_ocr_graph_and_excludes_raw_text(monkeypatch):
    monkeypatch.setattr(
        agent_node_service,
        "_attachment_object_storage_bytes",
        lambda _attachment, _storage_uri: b"image-bytes",
    )
    monkeypatch.setattr(traffic_ocr_agent, "_call_gpt_vision", lambda *_args: TRAFFIC_OCR_RESPONSE)
    monkeypatch.setattr(traffic_ocr_agent, "save_ocr_output", lambda *_args, **_kwargs: "safe-output.json")

    execution = execute_agent_node(
        {
            "node_code": "traffic_accident_confirmation_ocr",
            "analysis_plan_id": "plan_traffic_ocr",
            "job_id": "job_traffic_ocr",
            "session_id": "ses_traffic_ocr",
            "message_id": "msg_traffic_ocr",
            "attachments": [_scan_ready_attachment()],
        }
    )

    output = execution["agent_output"]
    serialized = json.dumps(output, ensure_ascii=False)

    assert execution["execution_mode"] == "sync"
    assert output["node_code"] == "traffic_accident_confirmation_ocr"
    assert output["status"] == "success"
    assert output["structured_result"]["ocr_evidence"] == [
        {
            "attachment_id": "att_traffic_confirmation_001",
            "storage_uri": "s3://skn27-demo-object-storage/canonical/traffic-confirmation.jpg",
            "content_type": "image/jpeg",
        }
    ]
    assert "raw_text_redacted" not in output["structured_result"]
    assert "900101-1234567" not in serialized
    assert "010-1234-5678" not in serialized
    assert output["structured_result"]["adapter_trace"]["adapter"].endswith(
        "traffic_accident_confirmation_ocr.graph"
    )
    assert validate_agent_output_envelope(
        output,
        expected_node_code="traffic_accident_confirmation_ocr",
    )["valid"]


def test_sync_runtime_rejects_inline_or_unscanned_attachment_before_ocr(monkeypatch):
    invoked = []
    monkeypatch.setattr(traffic_ocr_agent, "_call_gpt_vision", lambda *_args: invoked.append(True))

    execution = execute_agent_node(
        {
            "node_code": "traffic_accident_confirmation_ocr",
            "session_id": "ses_unsafe_traffic_ocr",
            "attachments": [
                {
                    "attachment_id": "att_unscanned_traffic_confirmation",
                    "purpose": "traffic_accident_confirmation",
                    "content_type": "image/jpeg",
                    "content_base64": "aGVsbG8=",
                    "status": "uploaded",
                    "scan_status": "not_started",
                }
            ],
        }
    )

    output = execution["agent_output"]

    assert output["status"] == "partial"
    assert output["execution_status"] == "input_required"
    assert output["structured_result"]["missing_fields"] == [
        "attachments[purpose=traffic_accident_confirmation, scan_ready]"
    ]
    assert invoked == []
    assert validate_agent_output_envelope(
        output,
        expected_node_code="traffic_accident_confirmation_ocr",
    )["valid"]


def test_sync_runtime_returns_failed_envelope_for_unsupported_scan_ready_file(monkeypatch):
    monkeypatch.setattr(
        agent_node_service,
        "_attachment_object_storage_bytes",
        lambda _attachment, _storage_uri: b"not-a-supported-image",
    )
    attachment = _scan_ready_attachment()
    attachment["content_type"] = "application/pdf"

    execution = execute_agent_node(
        {
            "node_code": "traffic_accident_confirmation_ocr",
            "session_id": "ses_unsupported_traffic_ocr",
            "attachments": [attachment],
        }
    )

    output = execution["agent_output"]

    assert output["status"] == "failed"
    assert output["execution_status"] == "failed"
    assert output["structured_result"]["ocr_evidence"][0]["attachment_id"] == (
        "att_traffic_confirmation_001"
    )
    assert validate_agent_output_envelope(
        output,
        expected_node_code="traffic_accident_confirmation_ocr",
    )["valid"]
