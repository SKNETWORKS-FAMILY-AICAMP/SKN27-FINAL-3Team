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
                {"role": "assistant", "content": "가진 자료를 먼저 알려 주세요."},
                {"role": "user", "content": "가진 자료는 블랙박스입니다."},
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
                {"role": "user", "content": "사고 과실을 상담하고 싶어요."},
                {"role": "assistant", "content": "도로 형태를 알려 주세요."},
            ],
        },
    )

    assert merged["facts"]["road_layout"]["value"] == "신호등 없는 교차로"
    assert merged["conversation_history"] == [
        {"role": "user", "content": "사고 과실을 상담하고 싶어요."},
        {"role": "assistant", "content": "도로 형태를 알려 주세요."},
    ]


def test_merge_appends_current_answer_after_saved_pending_question() -> None:
    merged = merge_chat_followup_payload(
        {"user_text": "신호등 없는 교차로입니다."},
        {
            "contract_version": "chat_session_followup_state.v1",
            "pending_questions": [
                {"field": "road_layout", "question": "사고 장소의 도로 형태를 알려 주세요."}
            ],
        },
    )

    assert merged["conversation_history"] == [
        {"role": "assistant", "content": "사고 장소의 도로 형태를 알려 주세요."},
        {"role": "user", "content": "신호등 없는 교차로입니다."},
    ]


def test_snapshot_does_not_duplicate_current_user_turn_already_in_merged_history() -> None:
    snapshot = build_chat_followup_snapshot(
        {
            "user_text": "신호등 없는 교차로입니다.",
            "conversation_history": [
                {"role": "assistant", "content": "사고 장소의 도로 형태를 알려 주세요."},
                {"role": "user", "content": "신호등 없는 교차로입니다."},
            ],
        },
        {
            "status": "needs_input",
            "assistant_message": {"answer": "상대 차량의 진행 방향을 알려 주세요."},
        },
    )

    assert snapshot["conversation_history"] == [
        {"role": "assistant", "content": "사고 장소의 도로 형태를 알려 주세요."},
        {"role": "user", "content": "신호등 없는 교차로입니다."},
        {"role": "assistant", "content": "상대 차량의 진행 방향을 알려 주세요."},
    ]


def test_snapshot_preserves_case_memory_summary_and_evidence_refs() -> None:
    snapshot = build_chat_followup_snapshot(
        {
            "user_text": "블랙박스는 있고 상대 차량이 끼어들었습니다.",
        },
        {
            "status": "needs_input",
            "assistant_message": {"answer": "신호 우선 상황을 알려 주세요."},
            "consultation_state": {
                "case_memory": {
                    "schema_version": "case_memory.v1",
                    "conversation_summary": "교차로 사고이며 블랙박스 보유 사실을 확인했습니다.",
                    "evidence_refs": ["att_blackbox_1"],
                    "deadlines": [],
                }
            },
        },
    )

    assert snapshot["case_memory"]["schema_version"] == "case_memory.v1"
    assert snapshot["case_memory"]["evidence_refs"] == ["att_blackbox_1"]
    assert "블랙박스 보유 사실" in snapshot["case_memory"]["conversation_summary"]


def test_merge_restores_server_case_memory_when_client_omits_it() -> None:
    merged = merge_chat_followup_payload(
        {"user_text": "상대 차량은 좌회전이었습니다."},
        {
            "contract_version": "chat_session_followup_state.v1",
            "case_memory": {
                "schema_version": "case_memory.v1",
                "conversation_summary": "이전 대화에서 교차로와 블랙박스를 확인했습니다.",
                "evidence_refs": ["att_blackbox_1"],
            },
        },
    )

    assert merged["case_memory"]["schema_version"] == "case_memory.v1"
    assert merged["case_memory"]["evidence_refs"] == ["att_blackbox_1"]
