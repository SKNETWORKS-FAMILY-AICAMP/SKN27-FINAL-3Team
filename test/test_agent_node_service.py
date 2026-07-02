from app.services.agent_adapter_contract import (
    ADAPTER_CONTRACT_VERSION,
    build_agent_adapter_input,
    validate_adapter_context_envelope,
    validate_agent_input_envelope,
    validate_agent_output_envelope,
)
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

    assert contract["signature_version"] == ADAPTER_CONTRACT_VERSION
    assert contract["adapter_key"] == "law_ground_search"
    assert contract["function_name"] == "run_law_ground_search"
    assert (
        contract["call_signature"]
        == "run_law_ground_search(agent_input: AgentAdapterInput, context: AgentAdapterContext) -> AgentAdapterOutput"
    )
    assert "upstream_results" in contract["required_input_fields"]
    assert "structured_result" in contract["required_output_fields"]
    assert contract["allowed_statuses"] == ["success", "partial", "failed"]
    assert contract["call_style"] == "sync_callable"
    assert contract["idempotency_scope"] == "job_id:node_code:analysis_plan_id"


def test_agent_adapter_input_and_context_envelopes_validate_signature_v1():
    law_node = next(
        node for node in list_agent_nodes() if node["node_code"] == "law_ground_search"
    )
    agent_input = build_agent_adapter_input(
        analysis_plan_id="plan_contract",
        job_id="job_contract",
        session_id="ses_contract",
        message_id="msg_contract",
        node=law_node,
        user_text="법률 근거를 확인해줘",
        attachments=[{"attachment_id": "att_contract", "purpose": "fine_notice"}],
        context={"locale": "ko-KR"},
        required_inputs=["law_code"],
        depends_on=["fine_notice_analysis"],
        upstream_results={"fine_notice_analysis": {"status": "success"}},
    )

    input_validation = validate_agent_input_envelope(
        agent_input,
        expected_node_code="law_ground_search",
    )
    execution = execute_mock_node(
        {
            "node_code": "law_ground_search",
            "analysis_plan_id": "plan_contract",
            "job_id": "job_contract",
            "session_id": "ses_contract",
            "message_id": "msg_contract",
            "user_text": "법률 근거를 확인해줘",
            "context": {"locale": "ko-KR"},
        }
    )
    context_validation = validate_adapter_context_envelope(
        execution["adapter_context"],
        expected_execution_mode="mock",
    )

    assert input_validation["valid"]
    assert agent_input["node_code"] == "law_ground_search"
    assert agent_input["upstream_results"]["fine_notice_analysis"]["status"] == "success"
    assert context_validation["valid"]
    assert execution["adapter_context"]["signature_version"] == ADAPTER_CONTRACT_VERSION


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


def test_hi_owned_agent_output_sample_validates_without_touching_other_agents():
    output = {
        "session_id": "ses_hi_contract",
        "message_id": "msg_hi_contract",
        "job_id": "job_hi_contract",
        "node_name": "Objection report generation",
        "node_code": "objection_report_generation",
        "node_type": "agent",
        "owner": "hi20260204-maker",
        "status": "partial",
        "summary": "Draft report structure is ready, but final user facts still need confirmation.",
        "structured_result": {
            "recipient_agency": "mock agency",
            "document_title": "Objection draft",
            "case_summary": "User facts and notice analysis are merged into a draft report.",
            "grounds": ["User-provided facts require final confirmation."],
            "attachment_list": ["fine_notice_image", "user_evidence"],
            "disclaimer": "This draft does not guarantee submission acceptance or disposition change.",
        },
        "evidence": [
            {
                "source_type": "user_uploaded_file",
                "title": "Fine notice attachment",
                "source_reference": "att_hi_contract",
                "metadata": {"purpose": "fine_notice"},
                "confidence": None,
            }
        ],
        "next_actions": ["confirm_user_facts", "review_report_draft"],
        "limitations": ["Final legal review and user confirmation are still required."],
        "created_at": "2026-07-01T00:00:00+00:00",
    }

    validation = validate_agent_output_envelope(
        output,
        expected_node_code="objection_report_generation",
    )

    assert validation["valid"]
    assert output["owner"] == "hi20260204-maker"


def test_hi_owned_supervisor_validation_sample_validates_as_internal_boundary():
    output = {
        "session_id": "ses_hi_supervisor",
        "message_id": "msg_hi_supervisor",
        "job_id": "job_hi_supervisor",
        "node_name": "Agent result validation",
        "node_code": "agent_result_validation",
        "node_type": "supervisor_internal",
        "owner": "hi20260204-maker",
        "status": "success",
        "summary": "Agent envelopes were checked before display DTO merge.",
        "structured_result": {
            "checked_contract_fields": [
                "node_code",
                "status",
                "summary",
                "structured_result",
                "evidence",
                "limitations",
            ],
            "rejected_results": [],
            "merge_ready": True,
        },
        "evidence": [],
        "next_actions": ["merge_display_dto"],
        "limitations": [],
        "created_at": "2026-07-01T00:00:00+00:00",
    }

    validation = validate_agent_output_envelope(
        output,
        expected_node_code="agent_result_validation",
    )

    assert validation["valid"]
    assert output["node_type"] == "supervisor_internal"
    assert output["owner"] == "hi20260204-maker"


def test_agent_contract_validators_report_malformed_collections():
    input_validation = validate_agent_input_envelope(
        {
            "analysis_plan_id": "plan_bad",
            "job_id": "job_bad",
            "session_id": "ses_bad",
            "message_id": "msg_bad",
            "node_code": "law_ground_search",
            "user_text": "법률 근거",
            "attachments": "att_bad",
            "context": {},
            "required_inputs": [],
            "depends_on": [],
            "upstream_results": {},
        }
    )
    output_validation = validate_agent_output_envelope(
        {
            "session_id": "ses_bad",
            "message_id": "msg_bad",
            "job_id": "job_bad",
            "node_name": "Law",
            "node_code": "law_ground_search",
            "node_type": "agent",
            "owner": "techshin31",
            "status": "success",
            "summary": "ok",
            "structured_result": [],
            "evidence": [],
            "next_actions": [],
            "limitations": [],
            "created_at": "2026-06-28T00:00:00+00:00",
        }
    )

    assert not input_validation["valid"]
    assert input_validation["invalid_collection_fields"] == ["attachments"]
    assert not output_validation["valid"]
    assert output_validation["invalid_collection_fields"] == ["structured_result"]


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
