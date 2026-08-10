from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

import pytest

from app.services.agent_node_service import execute_agent_node, execute_agent_plan


@patch("ai.agents.appeal_decision_flow.graph.graph.invoke")
def test_appeal_decision_flow_uses_real_graph_and_upstream_notice_result(invoke) -> None:
    invoke.return_value = {
        "agent_results": {
            "appeal_judgment": {
                "status": "success",
                "summary": "appeal decision completed",
                "structured_result": {"judgment_status": "success"},
                "evidence": [],
                "next_actions": [],
                "limitations": [],
            }
        }
    }

    execution = execute_agent_node(
        {
            "node_code": "appeal_decision_flow",
            "session_id": "ses_appeal",
            "message_id": "msg_appeal",
            "user_text": "The cited violation did not occur and I want to object.",
            "context": {"notice_received_date": "2026-07-01"},
            "upstream_results": {
                "fine_notice_analysis": {
                    "status": "success",
                    "structured_result": {
                        "fine_type": "과태료",
                        "notice_stage": "사전통지",
                        "violation_text": "signal violation",
                        "opinion_deadline": "2026-07-31",
                        "issuing_authority": "Seoul",
                        "law_code": "ROAD_TRAFFIC_ACT",
                    },
                }
            },
        }
    )

    state = invoke.call_args.args[0]
    assert execution["execution_mode"] == "sync"
    assert execution["agent_output"]["status"] == "success"
    assert execution["agent_output"]["node_code"] == "appeal_decision_flow"
    assert state["fine_type"] == "과태료"
    assert state["notice_stage"] == "사전통지"
    assert state["user_appeal_reason"].startswith("The cited violation")
    assert state["notice_received_date"] == "2026-07-01"


@patch("app.services.agent_node_service._run_sync_adapter")
def test_production_plan_executes_registered_sync_adapter_without_fixture_fallback(run_adapter) -> None:
    run_adapter.return_value = {
        "status": "success",
        "summary": "실제 검색 결과",
        "structured_result": {"matched_laws": ["도로교통법"]},
        "evidence": [{"source_reference": "law:1"}],
        "next_actions": [],
        "limitations": [],
    }
    result = execute_agent_plan(
        {
            "plan_id": "plan_1",
            "session_id": "ses_1",
            "message_id": "msg_1",
            "steps": [
                {
                    "order": 1,
                    "node_code": "law_ground_search",
                    "status": "ready",
                    "execution_mode": "sync",
                    "required_inputs": ["search_query"],
                    "depends_on": [],
                }
            ],
        },
        {"job_id": "job_1", "user_text": "도로교통법 근거", "execution_mode": "sync"},
    )

    assert result["execution_mode"] == "sync"
    assert result["status_counts"] == {"success": 1, "partial": 0, "failed": 0}
    assert result["executions"][0]["agent_output"]["summary"] == "실제 검색 결과"
    assert "mock" not in str(result).lower()


@patch("app.services.agent_node_service._run_sync_adapter")
def test_supervisor_plan_ignores_client_node_slot_and_upstream_overrides(run_adapter) -> None:
    run_adapter.return_value = {
        "status": "success",
        "summary": "server plan completed",
        "structured_result": {"matched_laws": ["law:server"]},
        "evidence": [],
        "next_actions": [],
        "limitations": [],
    }
    server_slot_state = {
        "contract_version": "slot_filling_state.v1",
        "slots": {
            "query": {
                "value": "server approved query",
                "source": {"type": "supervisor", "reference": "msg_server"},
                "confidence": 1.0,
                "editable": False,
            }
        },
    }
    result = execute_agent_plan(
        {
            "plan_id": "plan_server_authoritative",
            "session_id": "ses_server",
            "message_id": "msg_server",
            "steps": [
                {
                    "order": 1,
                    "node_code": "law_ground_search",
                    "status": "ready",
                    "depends_on": [],
                    "required_inputs": ["user_text"],
                }
            ],
        },
        {
            "job_id": "job_server_authoritative",
            "user_text": "client supplied question",
            "agent_input": {
                "node_code": "objection_report_generation",
                "slot_state": {"client": True},
            },
            "slot_state": {"client": True},
            "upstream_results": {"law_ground_search": {"status": "success"}},
            "context": {
                "supervisor_handoff": {
                    "contract_version": "supervisor_conversation_state.v2",
                    "stage": "agent_execution_ready",
                    "agent_input_packages": [
                        {
                            "schema_version": "agent_input_schema.v1",
                            "node_code": "law_ground_search",
                            "status": "ready",
                            "required_inputs": ["user_text"],
                            "payload": {
                                "user_text": "server approved question",
                                "attachments": [],
                                "slot_state": server_slot_state,
                            },
                        }
                    ]
                }
            },
        },
    )

    assert [execution["node_code"] for execution in result["executions"]] == ["law_ground_search"]
    adapter_input = run_adapter.call_args.args[0]
    assert adapter_input["node_code"] == "law_ground_search"
    assert adapter_input["user_text"] == "server approved question"
    assert adapter_input["slot_state"] == server_slot_state
    assert adapter_input["upstream_results"] == {}


@patch("app.services.agent_node_service._run_sync_adapter")
def test_supervisor_plan_rejects_public_agent_without_matching_ready_package(run_adapter) -> None:
    with pytest.raises(RuntimeError, match="Supervisor Agent input package"):
        execute_agent_plan(
            {
                "plan_id": "plan_missing_package",
                "steps": [
                    {
                        "order": 1,
                        "node_code": "law_ground_search",
                        "status": "ready",
                        "depends_on": [],
                    }
                ],
            },
            {
                "job_id": "job_missing_package",
                "user_text": "client fallback must not execute",
                "context": {
                    "supervisor_handoff": {
                        "contract_version": "supervisor_conversation_state.v2",
                        "stage": "agent_execution_ready",
                        "agent_input_packages": [],
                    }
                },
            },
        )

    run_adapter.assert_not_called()


@patch("app.services.agent_node_service._run_sync_adapter")
def test_supervisor_plan_rejects_malformed_ready_package_without_client_fallback(run_adapter) -> None:
    with pytest.raises(RuntimeError, match="Supervisor Agent input package"):
        execute_agent_plan(
            {
                "plan_id": "plan_malformed_package",
                "steps": [
                    {
                        "order": 1,
                        "node_code": "law_ground_search",
                        "status": "ready",
                        "depends_on": [],
                    }
                ],
            },
            {
                "job_id": "job_malformed_package",
                "user_text": "client fallback must not execute",
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
        )

    run_adapter.assert_not_called()


@patch("app.services.agent_node_service._run_sync_adapter")
def test_non_supervisor_plan_preserves_server_checkpoint_upstream_results(run_adapter) -> None:
    result = execute_agent_plan(
        {
            "plan_id": "plan_legacy_checkpoint",
            "steps": [
                {
                    "order": 1,
                    "node_code": "law_ground_search",
                    "status": "ready",
                    "depends_on": [],
                }
            ],
        },
        {
            "job_id": "job_legacy_checkpoint",
            "upstream_results": {"law_ground_search": {"status": "success"}},
        },
    )

    assert result["executions"] == []
    run_adapter.assert_not_called()


def test_production_plan_runs_vision_through_the_sync_adapter() -> None:
    result = execute_agent_plan(
        {
            "plan_id": "plan_1",
            "steps": [
                {
                    "order": 1,
                    "node_code": "vision_media_analysis",
                    "status": "ready",
                    "execution_mode": "sync",
                    "required_inputs": ["attachments"],
                    "depends_on": [],
                }
            ],
        },
        {"job_id": "job_1", "execution_mode": "sync"},
    )

    execution = result["executions"][0]
    assert result["execution_mode"] == "sync"
    assert execution["node_code"] == "vision_media_analysis"
    assert execution["execution_mode"] == "sync"
    assert execution["agent_output"]["status"] == "partial"
    assert execution["agent_output"]["structured_result"]["error_code"] == "attachment_not_scan_ready"


@patch("app.services.agent_node_service._run_sync_adapter")
def test_agent_input_contract_is_validated_before_adapter_execution(run_adapter) -> None:
    execution = execute_agent_node(
        {
            "node_code": "law_ground_search",
            "session_id": "ses_invalid_input",
            "message_id": "msg_invalid_input",
            "user_text": "도로교통법",
            "attachments": "not-a-list",
        }
    )

    run_adapter.assert_not_called()
    assert execution["agent_output"]["status"] == "failed"
    assert execution["agent_output"]["structured_result"]["error_code"] == (
        "agent_input_contract_invalid"
    )


@patch("app.services.agent_node_service._run_sync_adapter")
def test_agent_output_contract_is_validated_before_supervisor_handoff(run_adapter) -> None:
    run_adapter.return_value = {
        "status": "success",
        "summary": "invalid collection output",
        "structured_result": {},
        "evidence": {"source_reference": "law:1"},
        "next_actions": [],
        "limitations": [],
    }

    execution = execute_agent_node(
        {
            "node_code": "law_ground_search",
            "session_id": "ses_invalid_output",
            "message_id": "msg_invalid_output",
            "user_text": "도로교통법",
            "attachments": [],
        }
    )

    assert run_adapter.call_count == 1
    assert execution["agent_output"]["status"] == "failed"
    assert execution["agent_output"]["structured_result"]["error_code"] == (
        "agent_output_contract_invalid"
    )


@patch("app.services.agent_node_service._run_sync_adapter")
def test_canonical_agent_entrypoint_runs_real_adapter(run_adapter) -> None:
    run_adapter.return_value = {
        "status": "success",
        "summary": "real law result",
        "structured_result": {"matched_laws": ["Road Traffic Act"]},
        "evidence": [],
        "next_actions": [],
        "limitations": [],
    }

    execution = execute_agent_node(
        {
            "node_code": "law_ground_search",
            "job_id": "job_real_only",
            "user_text": "find the applicable law",
        }
    )

    assert execution["execution_mode"] == "sync"
    assert execution["agent_output"]["summary"] == "real law result"
    assert "mock" not in str(execution).lower()


@patch("app.services.agent_node_service._run_sync_adapter")
def test_supervisor_collects_analysis_results_before_reporting(run_adapter) -> None:
    calls: list[dict] = []

    def execute(agent_input, _adapter_context):
        calls.append(deepcopy(agent_input))
        node_code = agent_input["node_code"]
        if node_code == "fine_notice_analysis":
            structured_result = {"notice_fields": {"issuing_authority": "Seoul"}}
        elif node_code == "law_ground_search":
            structured_result = {
                "matched_laws": [
                    {
                        "law_name": "Road Traffic Act",
                        "article": "Article 5",
                        "summary": "Signal compliance",
                    }
                ]
            }
        elif node_code == "appeal_decision_flow":
            structured_result = {
                "judgment_status": "success",
                "overall_possibility": "review_recommended",
            }
        else:
            structured_result = {
                "document_type": "objection_form",
                "document_title": "Objection draft",
                "form_sections": [{"title": "Facts", "body": "Verified facts"}],
                "report_actions": [{"type": "download_report"}],
                "missing_fields": [],
            }
        return {
            "status": "success",
            "summary": f"{node_code} completed",
            "structured_result": structured_result,
            "evidence": [{"source_reference": f"source:{node_code}"}],
            "next_actions": [],
            "limitations": [],
        }

    run_adapter.side_effect = execute
    result = execute_agent_plan(
        {
            "plan_id": "plan_supervisor_reporting",
            "session_id": "ses_supervisor_reporting",
            "message_id": "msg_supervisor_reporting",
            "steps": [
                {"order": 1, "node_code": "fine_notice_analysis", "status": "ready", "depends_on": []},
                {
                    "order": 2,
                    "node_code": "law_ground_search",
                    "status": "ready",
                    "depends_on": ["fine_notice_analysis"],
                },
                {
                    "order": 3,
                    "node_code": "appeal_decision_flow",
                    "status": "ready",
                    "depends_on": ["law_ground_search"],
                },
                {
                    "order": 4,
                    "node_code": "agent_result_validation",
                    "status": "ready",
                    "depends_on": ["appeal_decision_flow"],
                    "context": {
                        "routing_intent": "fine_notice_analysis",
                        "expected_node_codes": [
                            "fine_notice_analysis",
                            "law_ground_search",
                            "appeal_decision_flow",
                        ],
                        "report_requested": True,
                    },
                },
                {
                    "order": 5,
                    "node_code": "objection_report_generation",
                    "status": "ready",
                    "depends_on": ["agent_result_validation"],
                },
            ],
        },
        {
            "job_id": "job_supervisor_reporting",
            "user_text": "prepare an objection report",
            "reporting_payload": {
                "contract_version": "reporting_payload.v2",
                "report_type": "fine_notice_objection",
            },
        },
    )

    report_call = next(call for call in calls if call["node_code"] == "objection_report_generation")
    assert set(report_call["upstream_results"]) == {
        "fine_notice_analysis",
        "law_ground_search",
        "appeal_decision_flow",
        "agent_result_validation",
    }
    assert report_call["context"]["supervisor_handoff"]["source_node_codes"] == [
        "fine_notice_analysis",
        "law_ground_search",
        "appeal_decision_flow",
    ]
    assert result["supervisor_handoff"]["ready_for_reporting"] is True
    assert result["reporting_payload"]["source"] == "supervisor_agent_result_aggregation"
    assert result["reporting_payload"]["generated_from_node_codes"] == [
        "fine_notice_analysis",
        "law_ground_search",
        "appeal_decision_flow",
    ]
    assert result["reporting_payload"]["sections"] == [
        {"title": "Facts", "body": "Verified facts"}
    ]


@patch("app.services.agent_node_service._run_sync_adapter")
def test_production_plan_does_not_execute_waiting_or_approval_steps(run_adapter) -> None:
    result = execute_agent_plan(
        {
            "plan_id": "plan_waiting",
            "steps": [
                {
                    "order": 1,
                    "node_code": "law_ground_search",
                    "status": "waiting",
                    "depends_on": [],
                },
                {
                    "order": 2,
                    "node_code": "agent_result_validation",
                    "status": "approval_required",
                    "depends_on": [],
                },
            ],
        },
        {"job_id": "job_waiting"},
    )

    assert result["executions"] == []
    run_adapter.assert_not_called()


@patch("app.services.agent_node_service._run_sync_adapter")
def test_production_plan_does_not_execute_step_with_blocked_dependency(run_adapter) -> None:
    result = execute_agent_plan(
        {
            "plan_id": "plan_blocked_dependency",
            "steps": [
                {
                    "order": 1,
                    "node_code": "input_context_validation",
                    "status": "blocked",
                    "depends_on": [],
                },
                {
                    "order": 2,
                    "node_code": "law_ground_search",
                    "status": "ready",
                    "depends_on": ["input_context_validation"],
                },
            ],
        },
        {"job_id": "job_blocked_dependency"},
    )

    assert result["executions"] == []
    run_adapter.assert_not_called()

