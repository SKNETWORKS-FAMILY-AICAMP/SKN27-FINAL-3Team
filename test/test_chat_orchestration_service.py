from __future__ import annotations

from app.services.chat_orchestration_service import compose_agent_response, submit_message


def test_empty_message_requests_input_without_creating_an_agent_plan() -> None:
    response = submit_message({"session_id": "ses_1", "user_text": ""})

    assert response["status"] == "needs_input"
    assert response["pending_questions"]
    assert response["analysis_plan"]["steps"] == []
    assert "mock" not in str(response).lower()


def test_fine_notice_message_queues_only_supported_real_agents() -> None:
    response = submit_message(
        {
            "session_id": "ses_1",
            "user_text": "과태료 고지서를 받았고 의견제출 가능성을 확인하고 싶습니다.",
            "attachments": [{"attachment_id": "att_1", "purpose": "fine_notice", "status": "ready"}],
        }
    )

    assert response["status"] == "queued"
    assert response["routing_intent"] == "fine_notice_objection"
    assert [step["node_code"] for step in response["analysis_plan"]["steps"]] == [
        "fine_notice_analysis",
        "law_ground_search",
        "objection_report_generation",
    ]
    assert response["assistant_message"] is None
    assert "vision_media_analysis" not in str(response)
    assert "mock" not in str(response).lower()


def test_fault_ratio_message_requires_case_and_does_not_enable_unsupported_media_analysis() -> None:
    response = submit_message(
        {"session_id": "ses_1", "user_text": "교차로에서 충돌했는데 과실비율이 궁금합니다."}
    )

    assert response["routing_intent"] == "fault_ratio_text"
    assert response["status"] == "needs_input"
    assert response["analysis_plan"]["steps"] == []
    assert response["consultation_state"]["v2"]["schema_version"] == "consultation_state.v2"
    assert "vision_media_analysis" not in str(response)


def test_agent_response_is_composed_from_execution_results() -> None:
    response = compose_agent_response(
        {
            "job_id": "job_1",
            "status_counts": {"success": 1, "partial": 1},
            "executions": [
                {
                    "node_code": "text_ml_case_search",
                    "agent_output": {
                        "status": "success",
                        "summary": "유사 심의사례 2건을 찾았습니다.",
                        "structured_result": {"ratio_range": "A 70 : B 30"},
                        "evidence": [{"source_reference": "review:1"}],
                        "limitations": [],
                    },
                },
                {
                    "node_code": "law_ground_search",
                    "agent_output": {
                        "status": "partial",
                        "summary": "관련 조문 후보를 확인했습니다.",
                        "structured_result": {"matched_laws": ["도로교통법"]},
                        "evidence": [{"source_reference": "law:1"}],
                        "limitations": ["사건별 적용 여부는 추가 확인이 필요합니다."],
                    },
                },
            ],
        }
    )

    assert response["status"] == "partial"
    assert response["assistant_message"]["answer"] == (
        "유사 심의사례 2건을 찾았습니다.\n\n관련 조문 후보를 확인했습니다."
    )
    assert response["structured_results"]["text_ml_case_search"]["ratio_range"] == "A 70 : B 30"
    assert [item["source_reference"] for item in response["evidence"]] == ["review:1", "law:1"]
    assert response["limitations"] == ["사건별 적용 여부는 추가 확인이 필요합니다."]

