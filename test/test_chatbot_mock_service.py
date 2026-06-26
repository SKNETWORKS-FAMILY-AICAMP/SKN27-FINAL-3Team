from app.services.chatbot_mock_service import (
    create_session,
    list_demo_scenarios,
    perform_report_action,
    submit_message,
)


def test_chatbot_mock_session_exposes_mid_demo_scenarios():
    session = create_session(user_id="usr_mock")

    assert session["status"] == "draft"
    assert {item["scenario"] for item in session["available_scenarios"]} == {
        "fine_notice",
        "fault_ratio",
    }
    assert {item["scenario"] for item in list_demo_scenarios()} == {"fine_notice", "fault_ratio"}


def test_chatbot_mock_fine_notice_success_flow_returns_cards_and_report_actions():
    session = create_session(user_id="usr_mock")

    response = submit_message(
        {
            "session_id": session["session_id"],
            "user_text": "이 고지서로 이의신청서를 만들 수 있을까요?",
            "attachments": [
                {
                    "attachment_id": "att_0001",
                    "type": "image",
                    "purpose": "fine_notice",
                }
            ],
            "mock_scenario": "fine_notice",
            "mock_status": "success",
        }
    )

    assert response["session_id"] == session["session_id"]
    assert response["mock_scenario"] == "fine_notice"
    assert response["status"] == "success"
    assert response["routing_intent"] == "objection_request"
    assert response["case_status"] == "analysis_completed"
    assert {card["card_type"] for card in response["cards"]} >= {
        "fine_notice",
        "objection_report",
    }
    assert {link["action"] for link in response["report_links"]} == {"save", "download"}
    assert response["limitations"]


def test_chatbot_mock_fault_ratio_success_flow_returns_schema_fields_without_ratio_assertion():
    response = submit_message(
        {
            "session_id": "ses_fault",
            "user_text": "신호 없는 교차로 사고 과실비율을 확인하고 싶어요.",
            "mock_scenario": "fault_ratio",
            "mock_status": "success",
        }
    )

    structured_result = response["structured_result"]

    assert response["mock_scenario"] == "fault_ratio"
    assert response["routing_intent"] == "fault_ratio"
    assert response["status"] == "success"
    assert {card["card_type"] for card in response["cards"]} >= {
        "fault_ratio",
        "similar_case",
        "recommended_evidence",
    }
    assert structured_result["accident_type_candidates"]
    assert structured_result["issue_tags"]
    assert structured_result["similar_cases"]
    assert structured_result["reliability_score"] > 0
    assert "확정" in structured_result["ratio_range_label"]
    assert any("수치로 확정하지 않습니다" in item for item in structured_result["limitations"])


def test_chatbot_mock_partial_flow_returns_pending_question():
    response = submit_message(
        {
            "session_id": "ses_partial",
            "user_text": "사고 과실비율을 봐줘",
            "needs_more_input": True,
            "mock_scenario": "fault_ratio",
            "mock_status": "partial",
        }
    )

    assert response["status"] == "partial"
    assert response["case_status"] == "needs_more_input"
    assert response["pending_questions"][0]["field"] == "accident_context"
    assert response["report_links"] == []


def test_chatbot_mock_report_download_action_returns_download_url():
    report = perform_report_action(
        {
            "session_id": "ses_report",
            "action": "download",
            "case_id": "case_mock",
        }
    )

    assert report["case_id"] == "case_mock"
    assert report["status"] == "downloaded"
    assert report["download_url"].endswith("/download")

