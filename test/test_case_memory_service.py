from __future__ import annotations

from app.services.case_memory_service import compact_case_memory, update_case_memory


def test_case_memory_preserves_facts_claims_and_unknowns() -> None:
    memory = update_case_memory(
        {},
        user_text="교차로에서 직진 중이었고 상대 차량이 좌회전으로 들어왔습니다.",
        routing_intent="accident_initial_consultation",
        fact_state={
            "facts": {
                "road_layout": {
                    "field": "road_layout",
                    "value": "신호등 있는 교차로",
                    "source_message_id": "msg_1",
                    "confidence": 1.0,
                    "confirmed": True,
                }
            }
        },
        case_evidence={
            "claims": {
                "vehicle_actions": {
                    "value": "직진 차량과 좌회전 차량 충돌",
                    "evidence_source": {"source_type": "user_statement", "source_ref": "msg_1"},
                }
            },
            "unknowns": [
                {"field": "signal_priority", "reason": "missing_fact", "evidence_source": None}
            ],
        },
        attachments=[{"attachment_id": "att_scene_1", "purpose": "accident_scene"}],
        consultation_state={"next_action": "collect_missing_facts", "next_questions": []},
    )

    assert memory["schema_version"] == "case_memory.v1"
    assert memory["incident_types"] == ["accident_initial_consultation"]
    assert memory["time_place"] == ["신호등 있는 교차로"]
    assert memory["confirmed_facts"] == [
        {
            "field": "road_layout",
            "value": "신호등 있는 교차로",
            "source_message_id": "msg_1",
        }
    ]
    assert memory["user_claims"] == [
        {
            "field": "vehicle_actions",
            "value": "직진 차량과 좌회전 차량 충돌",
            "source_ref": "msg_1",
        }
    ]
    assert memory["attachments"] == [{"attachment_id": "att_scene_1", "purpose": "accident_scene"}]
    assert memory["unknowns"] == [{"field": "signal_priority", "reason": "missing_fact"}]


def test_compaction_keeps_deadlines_and_evidence_references() -> None:
    compacted = compact_case_memory(
        {
            "schema_version": "case_memory.v1",
            "deadlines": ["2026-07-30"],
            "evidence_refs": ["att_notice_1", "law:road-traffic-act-1"],
            "search_grounds": ["law:road-traffic-act-1"],
            "unknowns": [{"field": "signal_priority", "reason": "missing_fact"}],
            "conversation_summary": "기존 요약",
        },
        latest_user_text="상대 차량이 갑자기 끼어들었다는 점을 다시 확인합니다.",
    )

    assert compacted["deadlines"] == ["2026-07-30"]
    assert compacted["evidence_refs"] == ["att_notice_1", "law:road-traffic-act-1"]
    assert compacted["search_grounds"] == ["law:road-traffic-act-1"]
    assert compacted["unknowns"] == [{"field": "signal_priority", "reason": "missing_fact"}]
    assert "기존 요약" in compacted["conversation_summary"]
    assert "상대 차량이 갑자기 끼어들었다는 점" in compacted["conversation_summary"]


def test_case_memory_update_preserves_existing_summary_and_progress_steps() -> None:
    memory = update_case_memory(
        {
            "schema_version": "case_memory.v1",
            "conversation_summary": "이전 상담에서 교차로 사고와 블랙박스 보유 여부를 확인했습니다.",
            "progress_steps": ["collect_missing_facts"],
            "deadlines": ["2026-07-30"],
        },
        user_text="이제 상대 차량의 방향지시등 여부를 추가로 설명합니다.",
        routing_intent="accident_initial_consultation",
        fact_state={"facts": {}},
        case_evidence={"claims": {}, "unknowns": []},
        attachments=[],
        consultation_state={"next_action": "confirm_facts", "next_questions": []},
    )

    assert memory["progress_steps"] == ["collect_missing_facts", "confirm_facts"]
    assert memory["deadlines"] == ["2026-07-30"]
    assert "이전 상담에서 교차로 사고" in memory["conversation_summary"]
    assert "방향지시등 여부" in memory["conversation_summary"]
