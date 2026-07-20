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
