from __future__ import annotations

import json

from app.services.supervisor_execution_input_service import (
    bind_supervisor_plan_step_payload,
    build_trusted_worker_execution_payload,
    is_ready_supervisor_handoff,
    sanitize_public_supervisor_request,
)


def _server_supervisor_state(node_code: str = "law_ground_search") -> dict:
    slot_state = {
        "contract_version": "slot_filling_state.v1",
        "slots": {"query": {"value": "server value", "status": "filled"}},
    }
    return {
        "contract_version": "supervisor_conversation_state.v2",
        "stage": "agent_execution_ready",
        "slot_state": slot_state,
        "agent_input_packages": [
            {
                "schema_version": "agent_input_schema.v1",
                "node_code": node_code,
                "status": "ready",
                "required_inputs": ["user_text"],
                "payload": {
                    "user_text": "server approved question",
                    "attachments": [],
                    "slot_state": slot_state,
                },
            }
        ],
    }


def test_ready_handoff_accepts_fallback_and_llm_supervisor_contract_versions() -> None:
    for contract_version in (
        "supervisor_conversation.v1",
        "supervisor_conversation_state.v1",
        "supervisor_conversation_state.v2",
    ):
        assert is_ready_supervisor_handoff(
            {
                "contract_version": contract_version,
                "stage": "agent_execution_ready",
                "agent_input_packages": [],
            }
        )


def test_sanitize_public_request_removes_execution_controls_and_forged_handoffs() -> None:
    result = sanitize_public_supervisor_request(
        {
            "user_text": "check this law",
            "job_id": "job_client_requested",
            "agent_input": {"node_code": "objection_report_generation"},
            "node_code": "objection_report_generation",
            "slot_state": {"client": True},
            "upstream_results": {"law_ground_search": {"status": "success"}},
            "analysis_plan": {"steps": []},
            "execution_mode": "live",
            "reporting_payload": {"report_type": "client"},
            "_server_report_generation_requested": True,
            "search_query": "client search override",
            "violation_text": "client violation override",
            "context": {
                "locale": "ko-KR",
                "query": {"search_query": "client context query"},
                "retrieval_seed": {"client": True},
                "supervisor_handoff": {"client": True},
                "supervisor_reporting_handoff": {"client": True},
            },
        }
    )

    assert result["user_text"] == "check this law"
    assert result["job_id"] == "job_client_requested"
    assert result["search_query"] == "client search override"
    assert result["violation_text"] == "client violation override"
    assert result["context"] == {
        "locale": "ko-KR",
        "query": {"search_query": "client context query"},
        "retrieval_seed": {"client": True},
    }
    for field in (
        "agent_input",
        "node_code",
        "slot_state",
        "upstream_results",
        "analysis_plan",
        "execution_mode",
        "reporting_payload",
        "_server_report_generation_requested",
    ):
        assert field not in result


def test_build_trusted_worker_payload_uses_server_handoff_after_control_removal() -> None:
    supervisor_state = _server_supervisor_state()

    result = build_trusted_worker_execution_payload(
        {
            "user_text": "check this law",
            "agent_input": {"node_code": "objection_report_generation"},
            "execution_status": "blocked",
            "mock_status": "failed",
            "slot_state": {"client": True},
            "upstream_results": {"law_ground_search": {"status": "success"}},
            "search_query": "client search override",
            "violation_text": "client violation override",
            "context": {
                "locale": "ko-KR",
                "query": {"search_query": "client context query"},
                "retrieval_seed": {"client": True},
                "notice_image": "unscanned-base64",
                "notice_mime_type": "image/png",
                "vision_evidence": [{"source": "client"}],
                "case_evidence": {"recipient": "client controlled"},
                "fine_type": "client controlled appeal state",
                "supervisor_handoff": {"client": True},
            },
        },
        chat_response={
            "session_id": "ses_server",
            "message_id": "msg_server",
            "attachments": [{"attachment_id": "att_server"}],
            "supervisor_state": supervisor_state,
        },
        public_request=True,
    )

    assert result["session_id"] == "ses_server"
    assert result["message_id"] == "msg_server"
    assert result["attachments"] == [{"attachment_id": "att_server"}]
    assert result["execution_mode"] == "sync"
    assert result["upstream_results"] == {}
    assert result["context"]["supervisor_handoff"] == supervisor_state
    assert "agent_input" not in result
    assert "slot_state" not in result
    assert "search_query" not in result
    assert "violation_text" not in result
    assert "execution_status" not in result
    assert "mock_status" not in result
    assert result["requires_supervisor_handoff"] is True
    assert result["context"] == {"supervisor_handoff": supervisor_state}



def test_bind_step_uses_matching_server_package_and_runtime_upstream_results() -> None:
    result = bind_supervisor_plan_step_payload(
        {
            "user_text": "client text",
            "node_code": "law_ground_search",
            "agent_input": {
                "node_code": "objection_report_generation",
                "slot_state": {"client": True},
            },
            "slot_state": {"client": True},
            "context": {
                "locale": "ko-KR",
                "supervisor_handoff": _server_supervisor_state(),
            },
        },
        step={"node_code": "law_ground_search", "status": "ready"},
        upstream_results={"input_context_validation": {"status": "success"}},
    )

    assert result["node_code"] == "law_ground_search"
    assert result["user_text"] == "server approved question"
    assert result["slot_state"]["slots"]["query"]["value"] == "server value"
    assert result["upstream_results"] == {"input_context_validation": {"status": "success"}}
    assert result["context"]["supervisor_agent_package"]["node_code"] == "law_ground_search"
    assert "agent_input" not in result


def test_bind_step_preserves_server_normalized_slots_over_public_values() -> None:
    supervisor_state = _server_supervisor_state()
    server_slots = {
        "fine_type": {"value": "fine"},
        "notice_stage": {"value": "first_notice"},
        "requested_action": {"value": "objection"},
        "legal_issue_terms": {"value": "signal_violation"},
    }
    supervisor_state["slot_state"]["slots"] = server_slots
    supervisor_state["agent_input_packages"][0]["payload"]["slot_state"] = (
        supervisor_state["slot_state"]
    )

    result = bind_supervisor_plan_step_payload(
        {
            "user_text": "client text",
            "slot_state": {
                "slots": {
                    field: {"value": "client override"} for field in server_slots
                }
            },
            "context": {"supervisor_handoff": supervisor_state},
        },
        step={"node_code": "law_ground_search", "status": "ready"},
        upstream_results={},
    )

    assert result["slot_state"]["slots"] == server_slots


def test_bind_step_accepts_llm_handoff_with_legacy_raw_user_text() -> None:
    supervisor_state = _server_supervisor_state()
    supervisor_state["contract_version"] = "supervisor_conversation.v1"
    package_payload = supervisor_state["agent_input_packages"][0]["payload"]
    package_payload["raw_user_text"] = package_payload.pop("user_text")

    result = bind_supervisor_plan_step_payload(
        {
            "user_text": "client text must be replaced",
            "attachments": [{"attachment_id": "client"}],
            "slot_state": {"client": True},
            "context": {"supervisor_handoff": supervisor_state},
        },
        step={"node_code": "law_ground_search", "status": "ready"},
        upstream_results={},
    )

    assert result["user_text"] == "server approved question"
    assert result["attachments"] == []
    assert result["slot_state"] == supervisor_state["slot_state"]


def test_bind_step_removes_raw_attachment_metadata_from_execution_context() -> None:
    supervisor_state = _server_supervisor_state()
    package_payload = supervisor_state["agent_input_packages"][0]["payload"]
    package_payload["attachments"] = [{"attachment_id": "att_clean"}]
    supervisor_state["agent_input_packages"][0]["attachments"] = [
        {
            "attachment_id": "att_clean",
            "content_base64": "untrusted-raw-content",
            "storage_uri": "untrusted://attachment",
        }
    ]
    supervisor_state["agent_input_packages"].append(
        {
            "schema_version": "agent_input_schema.v1",
            "node_code": "text_ml_case_search",
            "status": "ready",
            "required_inputs": ["user_text"],
            "payload": {
                "user_text": "unselected package",
                "attachments": [
                    {
                        "attachment_id": "att_unselected",
                        "content_base64": "untrusted-unselected-content",
                        "storage_uri": "untrusted://unselected",
                    }
                ],
                "slot_state": package_payload["slot_state"],
            },
        }
    )

    result = bind_supervisor_plan_step_payload(
        {
            "user_text": "client fallback must not survive",
            "attachments": [
                {
                    "attachment_id": "att_clean",
                    "storage_uri": "server://approved/attachment",
                    "scan_status": "clean",
                }
            ],
            "slot_state": {"client": True},
            "context": {"supervisor_handoff": supervisor_state},
        },
        step={"node_code": "law_ground_search", "status": "ready"},
        upstream_results={},
    )

    serialized_context = json.dumps(result["context"], ensure_ascii=False)
    assert "untrusted-raw-content" not in serialized_context
    assert "untrusted://attachment" not in serialized_context
    assert "untrusted-unselected-content" not in serialized_context
    assert "untrusted://unselected" not in serialized_context
    assert "server://approved/attachment" not in serialized_context
    assert result["attachments"] == [
        {
            "attachment_id": "att_clean",
            "storage_uri": "server://approved/attachment",
            "scan_status": "clean",
        }
    ]
    assert result["context"]["supervisor_agent_package"]["payload"]["attachments"] == [
        {"attachment_id": "att_clean"}
    ]


def test_bind_step_does_not_retain_public_input_for_a_malformed_ready_package() -> None:
    result = bind_supervisor_plan_step_payload(
        {
            "user_text": "client fallback must not survive",
            "attachments": [{"attachment_id": "client"}],
            "slot_state": {"client": True},
            "context": {
                "supervisor_handoff": {
                    "contract_version": "supervisor_conversation_state.v2",
                    "stage": "agent_execution_ready",
                    "agent_input_packages": [
                        {
                            "schema_version": "agent_input_schema.v1",
                            "node_code": "law_ground_search",
                            "status": "ready",
                            "payload": {},
                        }
                    ],
                }
            },
        },
        step={"node_code": "law_ground_search", "status": "ready"},
        upstream_results={},
    )

    assert "user_text" not in result
    assert "attachments" not in result
    assert "slot_state" not in result
    assert "supervisor_agent_package" not in result["context"]
