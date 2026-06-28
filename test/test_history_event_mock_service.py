from app.services.history_event_mock_service import (
    actor_from_payload,
    list_history_events,
    record_agent_execution_events,
    record_history_event,
)


def test_record_history_event_sanitizes_sensitive_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_HISTORY_EVENT_ROOT", str(tmp_path / "history"))

    event = record_history_event(
        event_type="chat_message_created",
        status="success",
        summary="채팅 메시지를 mock 분석 응답으로 처리했습니다.",
        actor={"guest_id": "gst_demo", "auth_state": "guest"},
        subject={"session_id": "ses_demo", "message_id": "msg_demo"},
        source={"api_path": "/api/chat/messages/", "execution_mode": "canonical_mock"},
        metadata={
            "routing_intent": "objection_request",
            "user_text": "원문은 저장되면 안 됩니다.",
            "nested": {"ocr_text": "OCR 원문도 저장되면 안 됩니다.", "card_count": 2},
        },
        privacy={"risk_level": "medium"},
    )

    events = list_history_events(session_id="ses_demo")

    assert events == [event]
    assert events[0]["event_version"] == "history_event.v1"
    assert events[0]["metadata"]["routing_intent"] == "objection_request"
    assert "user_text" not in events[0]["metadata"]
    assert "ocr_text" not in events[0]["metadata"]["nested"]
    assert events[0]["privacy"]["contains_user_text"] is False


def test_actor_from_payload_separates_guest_auth_and_chat_session():
    actor = actor_from_payload(
        {
            "auth_context": {
                "auth_state": "authenticated",
                "guest_id": "gst_before_login",
                "auth_session_id": "auth_dev_mock",
                "session_id": "ses_chat",
            }
        },
        authorization_header="Bearer dev-mock-token",
    )

    assert actor == {
        "user_id": None,
        "guest_id": "gst_before_login",
        "auth_session_id": "auth_dev_mock",
        "auth_state": "authenticated",
    }


def test_record_agent_execution_events_store_summary_not_reasoning(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_HISTORY_EVENT_ROOT", str(tmp_path / "history"))

    record_agent_execution_events(
        [
            {
                "execution_id": "exec_demo",
                "execution_status": "failed",
                "agent_output": {
                    "job_id": "job_demo",
                    "node_code": "law_ground_search",
                    "node_name": "법률 근거 검색 노드",
                    "status": "failed",
                    "summary": "필수 입력이 부족합니다.",
                    "structured_result": {
                        "missing_fields": ["law_code"],
                        "reasoning": "내부 reasoning은 저장되면 안 됩니다.",
                    },
                    "evidence": [],
                    "limitations": ["mock failure"],
                },
            }
        ],
        actor={"guest_id": "gst_demo", "auth_state": "guest"},
        subject={"session_id": "ses_demo", "job_id": "job_demo"},
        source={"api_path": "/api/agents/nodes/run/", "execution_mode": "canonical_mock"},
    )

    events = list_history_events(job_id="job_demo")

    assert len(events) == 1
    assert events[0]["event_type"] == "agent_call_failed"
    assert events[0]["metadata"]["missing_fields"] == ["law_code"]
    assert "reasoning" not in events[0]["metadata"]
