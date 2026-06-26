from app.services.chatbot_mock_service import create_session, perform_report_action, submit_message


def test_chatbot_mock_success_flow_returns_cards_and_report_actions():
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
            "mock_status": "success",
        }
    )

    assert response["session_id"] == session["session_id"]
    assert response["status"] == "success"
    assert response["routing_intent"] == "objection_request"
    assert response["cards"]
    assert {card["card_type"] for card in response["cards"]} >= {
        "fine_notice",
        "law_ground",
        "objection_report",
    }
    assert {link["action"] for link in response["report_links"]} == {"save", "download"}
    assert response["limitations"]


def test_chatbot_mock_partial_flow_returns_pending_question():
    response = submit_message(
        {
            "session_id": "ses_partial",
            "user_text": "법령 근거만 알려줘",
            "needs_more_input": True,
            "mock_status": "partial",
        }
    )

    assert response["status"] == "partial"
    assert response["pending_questions"][0]["field"] == "user_facts"
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

