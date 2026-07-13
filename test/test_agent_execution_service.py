from __future__ import annotations

from unittest.mock import patch

from app.services.agent_node_service import execute_agent_plan


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


def test_production_plan_rejects_unregistered_agent_instead_of_generating_a_fixture() -> None:
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

    output = result["executions"][0]["agent_output"]
    assert output["status"] == "failed"
    assert output["structured_result"]["error_code"] == "sync_adapter_unregistered"
    assert "mock" not in str(result).lower()


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

