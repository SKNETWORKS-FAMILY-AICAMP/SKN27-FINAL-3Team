from app.services.chatbot_mock_service import (
    build_analysis_plan,
    create_session,
    list_demo_scenarios,
    list_demo_personas,
    perform_report_action,
    submit_message,
)
from app.services.attachment_mock_service import register_attachment


def test_chatbot_mock_session_exposes_mid_demo_scenarios():
    session = create_session(user_id="usr_mock")

    assert session["status"] == "draft"
    assert {item["scenario"] for item in session["available_scenarios"]} >= {
        "fine_notice",
        "fault_ratio",
    }
    assert {item["scenario"] for item in list_demo_scenarios()} == {
        "fine_notice",
        "fault_ratio",
        "law_question",
        "report_redownload",
    }
    assert {item["persona_id"] for item in session["available_personas"]} == {
        item["persona_id"] for item in list_demo_personas()
    }


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
    assert response["analysis_plan"]["routing_intent"] == "objection_request"
    assert {step["node_code"] for step in response["analysis_plan"]["steps"]} >= {
        "fine_notice_analysis",
        "law_ground_search",
        "objection_report_generation",
    }
    assert {card["card_type"] for card in response["cards"]} >= {
        "fine_notice",
        "objection_report",
    }
    assert {link["action"] for link in response["report_links"]} == {"save", "download"}
    section_titles = {section["title"] for section in response["reporting_payload"]["sections"]}
    assert section_titles >= {
        "고지서 OCR 결과",
        "처분 결과",
        "이의제기 가능성",
        "필요 증거",
        "관련 법령·판례 근거",
        "예상 결과와 유의사항",
        "이의신청서 초안",
        "제출 가이드라인",
    }
    assert response["limitations"]


def test_chatbot_mock_resolves_uploaded_attachment_id_before_plan(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_UPLOAD_ROOT", str(tmp_path))
    attachment = register_attachment(
        {
            "session_id": "ses_resolved_chat",
            "filename": "fine_notice.jpg",
            "content_type": "image/jpeg",
            "purpose": "fine_notice",
            "size_bytes": 2048,
        }
    )

    response = submit_message(
        {
            "session_id": "ses_resolved_chat",
            "user_text": "이 고지서로 이의신청서를 만들 수 있을까요?",
            "attachments": [{"attachment_id": attachment["attachment_id"]}],
            "mock_scenario": "fine_notice",
            "mock_status": "success",
        }
    )

    assert response["attachments"][0]["purpose"] == "fine_notice"
    assert response["attachments"][0]["storage_uri"] == attachment["storage_uri"]
    assert response["attachment_resolution"]["resolved_attachment_ids"] == [
        attachment["attachment_id"]
    ]
    assert response["analysis_plan"]["input_summary"]["attachment_purposes"] == [
        "fine_notice"
    ]
    assert "image" in response["analysis_plan"]["input_summary"]["modalities"]


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
    assert response["analysis_plan"]["steps"][1]["node_code"] == "text_ml_case_search"
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


def test_chatbot_mock_infers_fault_ratio_before_law_or_fine_notice_terms():
    response = submit_message(
        {
            "session_id": "ses_fault_infer",
            "user_text": "교차로 접촉 사고의 과실비율과 유사 판례를 리포팅해줘",
            "mock_status": "success",
        }
    )

    assert response["mock_scenario"] == "fault_ratio"
    assert response["routing_intent"] == "fault_ratio"
    assert any(
        step["node_code"] == "text_ml_case_search"
        for step in response["analysis_plan"]["steps"]
    )


def test_chatbot_mock_routes_objection_eligibility_and_procedure_to_general_consultation():
    response = submit_message(
        {
            "session_id": "ses_general_guidance",
            "user_text": (
                "6월 25일 화요일에 딸 아이가 고열로 주정차 금지 구역에 정차를 하고 "
                "인근 병원 응급실을 다녀왔어요. 이의신청 가능 사항인지도 모르겠고 "
                "어떻게 이의신청해야 할지도 모르겠어요."
            ),
        }
    )

    assert response["mock_scenario"] == "general_consultation"
    assert response["routing_intent"] == "general_consultation"
    assert response["case_status"] == "guidance_only"
    assert response["cards"] == []
    assert response["report_links"] == []
    assert response["reporting_payload"] is None
    assert response["supervisor_state"] is None
    assert response["structured_result"]["report_ready"] is False
    assert "제출 기한" in response["assistant_message"]


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
    assert response["analysis_plan"]["blocked_reason"]
    assert any(step["status"] == "blocked" for step in response["analysis_plan"]["steps"])
    assert response["report_links"] == []


def test_chatbot_mock_demo_persona_runs_consultation_timeline():
    response = submit_message(
        {
            "session_id": "ses_persona",
            "user_text": "데모 페르소나로 상담을 끝까지 진행해줘",
            "persona_id": "school_zone_fine_notice_parent",
        }
    )

    persona_run = response["persona_run"]

    assert response["mock_scenario"] == "fine_notice"
    assert response["status"] == "success"
    assert "정민서" in response["assistant_message"]
    assert persona_run["persona"]["name"] == "정민서"
    assert persona_run["stage"] == "draft_ready"
    assert len(persona_run["turns"]) >= 5
    assert persona_run["turns"][0]["role"] == "persona_user"
    assert {card["card_type"] for card in response["cards"]} >= {
        "persona_case_summary",
        "persona_next_questions",
        "persona_draft_outline",
    }
    assert response["structured_result"]["persona_id"] == "school_zone_fine_notice_parent"
    assert response["pending_questions"]


def test_chatbot_mock_all_demo_personas_run_to_contract_boundary():
    personas = list_demo_personas()

    assert {item["persona_id"] for item in personas} == {
        "school_zone_fine_notice_parent",
        "accident_scene_photo_driver",
        "blackbox_video_fault_driver",
        "traffic_law_question_citizen",
        "saved_report_returning_user",
    }

    for persona in personas:
        response = submit_message(
            {
                "session_id": f"ses_{persona['persona_id']}",
                "user_text": persona["sample_user_text"],
                "persona_id": persona["persona_id"],
            }
        )
        node_codes = {step["node_code"] for step in response["analysis_plan"]["steps"]}

        assert response["status"] == "success"
        assert response["persona_run"]["persona"]["persona_id"] == persona["persona_id"]
        assert response["mock_scenario"] == persona["scenario"]
        assert response["routing_intent"] == persona["routing_intent"]
        assert response["reporting_payload"]["contract_version"] == "reporting_payload.v1"
        assert response["analysis_plan"]["persona_id"] == persona["persona_id"]
        assert node_codes >= set(persona["expected_nodes"])
        assert response["structured_result"]["expected_nodes"] == persona["expected_nodes"]
        assert bool(response["report_links"]) is persona["report_action_ready"]


def test_chatbot_mock_supervisor_conversation_sequence_asks_followup_then_builds_agent_inputs():
    first = submit_message(
        {
            "session_id": "ses_conversation",
            "user_text": "과태료 고지서를 받았는데 어떻게 해야 해?",
        }
    )

    assert first["status"] == "partial"
    assert first["supervisor_state"]["stage"] == "need_more_input"
    assert first["pending_questions"]
    assert first["analysis_plan"]["agent_input_packages"]
    assert any(
        item["status"] == "waiting_for_fields"
        for item in first["supervisor_state"]["agent_input_packages"]
    )

    conversation_history = [
        {"role": "user", "content": "과태료 고지서를 받았는데 어떻게 해야 해?"},
        {"role": "assistant", "content": first["assistant_message"]},
        {
            "role": "user",
            "content": (
                "6월 24일 오후 3시 초등학교 앞에서 아이가 갑자기 아파서 "
                "비상등을 켜고 정차했어. 과태료는 12만원이고 블랙박스와 약국 영수증이 있어."
            ),
        },
    ]
    second = submit_message(
        {
            "session_id": "ses_conversation",
            "user_text": "그럼 의견제출서 초안까지 갈 수 있는지 봐줘",
            "conversation_history": conversation_history,
        }
    )

    supervisor_state = second["supervisor_state"]

    assert second["status"] == "success"
    assert supervisor_state["stage"] == "agent_execution_ready"
    assert supervisor_state["missing_fields"] == []
    assert second["reporting_payload"]["contract_version"] == "reporting_payload.v1"
    assert {item["node_code"] for item in supervisor_state["agent_input_packages"]} >= {
        "fine_notice_analysis",
        "law_ground_search",
        "objection_report_generation",
    }
    fine_notice_input = next(
        item for item in supervisor_state["agent_input_packages"] if item["node_code"] == "fine_notice_analysis"
    )
    assert fine_notice_input["status"] == "ready"
    assert fine_notice_input["payload"]["notice_amount"] == "12만원"
    assert "초등학교" in fine_notice_input["payload"]["location"]
    slot_state = supervisor_state["slot_state"]
    assert slot_state["contract_version"] == "slot_filling_state.v1"
    assert slot_state["slots"]["notice_amount"]["value"] == "12만원"
    assert slot_state["slots"]["notice_amount"]["source"]["type"] == "conversation_turn"
    assert slot_state["slots"]["evidence_status"]["status"] == "filled"
    assert slot_state["slots"]["evidence_status"]["confidence"] > 0
    assert fine_notice_input["payload"]["slot_state"]["slots"]["location"]["editable"] is True
    assert second["analysis_plan"]["input_summary"]["missing_fields"] == []


def test_chatbot_mock_uploaded_attachment_fills_evidence_slot_state():
    response = submit_message(
        {
            "session_id": "ses_attachment_slot",
            "user_text": "과태료 고지서를 받았고 아이가 아파서 잠깐 정차했습니다.",
            "attachments": [
                {
                    "attachment_id": "att_uploaded_notice",
                    "purpose": "fine_notice",
                    "type": "image",
                    "storage_uri": "mock://uploads/att_uploaded_notice/fine_notice.jpg",
                }
            ],
        }
    )

    slot = response["supervisor_state"]["slot_state"]["slots"]["evidence_status"]
    fine_notice_input = next(
        item for item in response["supervisor_state"]["agent_input_packages"] if item["node_code"] == "fine_notice_analysis"
    )

    assert response["status"] == "success"
    assert slot["status"] == "filled"
    assert slot["source"]["type"] == "attachment"
    assert slot["source"]["attachment_ids"] == ["att_uploaded_notice"]
    assert fine_notice_input["payload"]["attachments"][0]["attachment_id"] == "att_uploaded_notice"


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


def test_chatbot_mock_analysis_plan_tracks_failed_input_before_agent_execution():
    plan = build_analysis_plan(
        scenario="fine_notice",
        requested_status="failed",
        payload={},
        session_id="ses_failed",
        message_id="msg_failed",
        routing_intent="objection_request",
        pending_questions=[],
    )

    assert plan["input_summary"]["has_user_command"] is False
    assert plan["blocked_reason"]
    assert plan["steps"][0]["node_code"] == "input_context_validation"
    assert plan["steps"][0]["status"] == "failed"
    assert {step["status"] for step in plan["steps"][1:]} == {"skipped"}

