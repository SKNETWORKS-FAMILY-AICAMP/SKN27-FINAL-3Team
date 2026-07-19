from app.services.chat_session_followup_service import (
    build_chat_followup_snapshot,
    merge_chat_followup_payload,
)


def test_merge_preserves_server_confirmed_fact_over_client_confirmed_conflict() -> None:
    merged = merge_chat_followup_payload(
        {
            "facts": {
                "road_layout": {
                    "value": "직선 도로",
                    "confirmed": True,
                }
            },
            "conversation_history": [
                {"role": "assistant", "content": "가짜 이전 질문입니다."},
                {"role": "user", "content": "가짜 이전 답변입니다."},
            ],
        },
        {
            "contract_version": "chat_session_followup_state.v1",
            "facts": {
                "road_layout": {
                    "value": "신호등 없는 교차로",
                    "confirmed": True,
                    "source_message_id": "msg_saved_1",
                }
            },
            "conversation_history": [
                {"role": "user", "content": "사고 과실을 상담하고 싶습니다."},
                {"role": "assistant", "content": "도로 형태를 알려주세요."},
            ],
        },
    )

    assert merged["facts"]["road_layout"]["value"] == "신호등 없는 교차로"
    assert merged["conversation_history"] == [
        {"role": "user", "content": "사고 과실을 상담하고 싶습니다."},
        {"role": "assistant", "content": "도로 형태를 알려주세요."},
    ]


def test_merge_appends_current_answer_after_saved_pending_question() -> None:
    merged = merge_chat_followup_payload(
        {"user_text": "신호등 없는 사거리였습니다."},
        {
            "contract_version": "chat_session_followup_state.v1",
            "pending_questions": [
                {"field": "road_layout", "question": "사고 장소의 도로 형태를 알려주세요."}
            ],
        },
    )

    assert merged["conversation_history"] == [
        {"role": "assistant", "content": "사고 장소의 도로 형태를 알려주세요."},
        {"role": "user", "content": "신호등 없는 사거리였습니다."},
    ]


def test_snapshot_does_not_duplicate_current_user_turn_already_in_merged_history() -> None:
    snapshot = build_chat_followup_snapshot(
        {
            "user_text": "신호등 없는 사거리였습니다.",
            "conversation_history": [
                {"role": "assistant", "content": "사고 장소의 도로 형태를 알려주세요."},
                {"role": "user", "content": "신호등 없는 사거리였습니다."},
            ],
        },
        {
            "status": "needs_input",
            "assistant_message": {"answer": "상대 차량의 진행 방향도 알려주세요."},
        },
    )

    assert snapshot["conversation_history"] == [
        {"role": "assistant", "content": "사고 장소의 도로 형태를 알려주세요."},
        {"role": "user", "content": "신호등 없는 사거리였습니다."},
        {"role": "assistant", "content": "상대 차량의 진행 방향도 알려주세요."},
    ]
