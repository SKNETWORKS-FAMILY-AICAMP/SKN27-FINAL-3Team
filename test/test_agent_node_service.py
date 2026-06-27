from app.services.agent_adapter_contract import validate_agent_output_envelope
from app.services.agent_node_service import (
    execute_mock_node,
    execute_mock_plan,
    list_agent_nodes,
)
from app.services.attachment_mock_service import register_attachment
from app.services.chatbot_mock_service import build_analysis_plan


def test_agent_node_registry_lists_all_integration_nodes():
    nodes = list_agent_nodes()
    node_codes = {node["node_code"] for node in nodes}

    assert {
        "input_context_validation",
        "fine_notice_analysis",
        "law_ground_search",
        "text_ml_case_search",
        "vision_media_analysis",
        "objection_report_generation",
        "agent_result_validation",
    } <= node_codes
    assert {node["node_type"] for node in nodes} >= {"agent", "supervisor_internal"}


def test_agent_node_registry_exposes_real_adapter_contract():
    nodes = list_agent_nodes()
    law_node = next(node for node in nodes if node["node_code"] == "law_ground_search")
    contract = law_node["adapter_contract"]

    assert contract["adapter_key"] == "law_ground_search"
    assert contract["function_name"] == "run_law_ground_search"
    assert (
        contract["call_signature"]
        == "run_law_ground_search(agent_input: AgentAdapterInput, context: AgentAdapterContext) -> AgentAdapterOutput"
    )
    assert "upstream_results" in contract["required_input_fields"]
    assert "structured_result" in contract["required_output_fields"]
    assert contract["allowed_statuses"] == ["success", "partial", "failed"]


def test_execute_mock_node_returns_common_agent_output_envelope():
    execution = execute_mock_node(
        {
            "node_code": "law_ground_search",
            "user_text": "고지서 법률 근거를 확인해줘",
            "mock_status": "success",
        }
    )

    output = execution["agent_output"]

    assert execution["execution_mode"] == "mock"
    assert output["node_code"] == "law_ground_search"
    assert output["status"] == "success"
    assert output["structured_result"]["matched_laws"]
    assert output["evidence"][0]["source_type"] == "law"
    assert execution["adapter_context"]["execution_id"] == execution["execution_id"]
    assert execution["adapter_context"]["node"]["adapter_contract"]["adapter_key"] == "law_ground_search"
    assert "upstream_results" in execution["agent_input"]
    assert {
        "node_name",
        "node_code",
        "status",
        "summary",
        "structured_result",
        "evidence",
        "next_actions",
        "limitations",
    } <= set(output)
    assert validate_agent_output_envelope(output, expected_node_code="law_ground_search")["valid"]


def test_agent_output_validator_reports_adapter_contract_errors():
    validation = validate_agent_output_envelope(
        {"node_code": "fine_notice_analysis", "status": "pending"},
        expected_node_code="law_ground_search",
    )

    assert not validation["valid"]
    assert validation["invalid_status"]
    assert validation["node_code_mismatch"]
    assert "summary" in validation["missing_fields"]


def test_execute_mock_plan_maps_analysis_steps_to_node_executions():
    plan = build_analysis_plan(
        scenario="fine_notice",
        requested_status="success",
        payload={"user_text": "고지서 이의신청서 만들어줘"},
        session_id="ses_plan",
        message_id="msg_plan",
        routing_intent="objection_request",
        pending_questions=[],
    )

    execution = execute_mock_plan(plan, {"user_text": "고지서 이의신청서 만들어줘"})

    assert execution["plan_id"] == plan["plan_id"]
    assert len(execution["executions"]) == len(plan["steps"])
    assert execution["status_counts"]["success"] >= 3
    assert execution["status_counts"]["partial"] >= 1
    assert "fine_notice_analysis" in {
        item["agent_output"]["node_code"] for item in execution["executions"]
    }
    dependent_execution = next(
        item for item in execution["executions"] if item["agent_input"]["depends_on"]
    )
    assert dependent_execution["agent_input"]["upstream_results"]


def test_execute_mock_node_resolves_attachment_id_for_agent_input(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_UPLOAD_ROOT", str(tmp_path))
    attachment = register_attachment(
        {
            "session_id": "ses_agent_attachment",
            "filename": "accident_statement.pdf",
            "content_type": "application/pdf",
            "purpose": "accident_statement",
            "size_bytes": 1204,
        }
    )

    execution = execute_mock_node(
        {
            "node_code": "text_ml_case_search",
            "session_id": "ses_agent_attachment",
            "attachments": [{"attachment_id": attachment["attachment_id"]}],
        }
    )

    resolved_attachment = execution["agent_input"]["attachments"][0]
    assert resolved_attachment["purpose"] == "accident_statement"
    assert resolved_attachment["type"] == "pdf"
    assert resolved_attachment["storage_uri"] == attachment["storage_uri"]
