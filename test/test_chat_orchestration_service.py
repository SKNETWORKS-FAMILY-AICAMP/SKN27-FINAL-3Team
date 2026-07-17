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
        "appeal_decision_flow",
        "objection_report_generation",
    ]
    assert response["assistant_message"] is None
    assert "vision_media_analysis" not in str(response)
    assert "mock" not in str(response).lower()


def test_enabled_supervisor_failure_blocks_analysis_plan_and_reporting(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_LLM_ENABLED", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SUPERVISOR_LLM_API_KEY", raising=False)

    response = submit_message(
        {
            "session_id": "ses_supervisor_blocked",
            "user_text": "도로교통법 신호위반 조문과 근거가 궁금합니다.",
        }
    )

    assert response["status"] == "supervisor_unavailable"
    assert response["progress"]["status"] == "blocked"
    assert response["analysis_plan"]["steps"] == []
    assert response["supervisor_state"]["llm"]["status"] == "failed"
    assert response["supervisor_state"]["llm"]["reason"] == "missing_config"
    assert response["reporting_payload"] is None


def test_enabled_supervisor_need_more_input_does_not_queue_or_report(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_LLM_ENABLED", "1")
    monkeypatch.setenv("SUPERVISOR_LLM_API_KEY", "sk-test")
    monkeypatch.setattr(
        "app.services.supervisor_llm_service._request_supervisor_json",
        lambda *_args: {
            "contract_version": "supervisor_conversation.v1",
            "stage": "need_more_input",
            "conversation_turn_count": 1,
            "conversation_summary": "A law reference is still required.",
            "collected_facts": [],
            "missing_fields": [{"field": "law_question"}],
            "next_questions": [
                {"field": "law_question", "question": "Which law should be reviewed?"}
            ],
            "agent_input_packages": [
                {
                    "schema_version": "agent_input_schema.v1",
                    "node_code": "law_ground_search",
                    "owner": "techshin31",
                    "status": "waiting_for_fields",
                    "missing_fields": ["law_question"],
                    "payload": {"user_text": "help", "attachments": []},
                }
            ],
            "reporting_payload": {
                "contract_version": "reporting_payload.v1",
                "scenario": "traffic_law_search",
                "stage": "need_more_input",
                "title": "Pending analysis",
                "summary": "More input is required.",
                "sections": [],
            },
        },
    )

    response = submit_message(
        {"session_id": "ses_need_more_input", "user_text": "help"}
    )

    assert response["status"] == "needs_input"
    assert response["progress"]["status"] == "needs_input"
    assert response["pending_questions"] == [
        {"field": "law_question", "question": "Which law should be reviewed?"}
    ]
    assert response["analysis_plan"]["steps"] == []
    assert response["reporting_payload"] is None
    assert response["report_links"] == []
    assert response["supervisor_state"]["stage"] == "need_more_input"


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
    assert response["assistant_message"]["follow_up"] is None


def test_empty_search_asks_only_for_the_categories_the_user_did_not_provide() -> None:
    response = compose_agent_response(
        {
            "job_id": "job_2",
            "status_counts": {"partial": 1},
            "executions": [
                {
                    "node_code": "law_ground_search",
                    "agent_output": {
                        "status": "partial",
                        "summary": "검색 조건에 맞는 유효한 조문이 없습니다.",
                        "structured_result": {"law_provisions": []},
                        "evidence": [],
                        "limitations": [],
                    },
                },
            ],
            "supervisor_state": {
                "collected_facts": [
                    {"field": "user_text", "value": "신호위반 관련 도로교통법 조문이 궁금해요"}
                ]
            },
            "attachments": [],
        }
    )

    answer = response["assistant_message"]["answer"]
    assert "발생 일시와 장소" in answer
    assert "받으신 고지서나 통지 내용" in answer
    assert "정확한 위반·분쟁 유형" not in answer

    follow_up = response["assistant_message"]["follow_up"]
    assert follow_up["items"] == [
        {"label": "발생 일시와 장소", "required": False},
        {"label": "받으신 고지서나 통지 내용", "required": False},
    ]
    assert response["assistant_message"]["core_answer"] == "검색 조건에 맞는 유효한 조문이 없습니다."


def test_low_confidence_search_with_evidence_still_asks_for_missing_info() -> None:
    # law_ground_search can find provisions (non-empty evidence) but still flag
    # low confidence via a non-success status. That must still prompt for more
    # info — the gate is "did any node succeed", not "is evidence non-empty".
    response = compose_agent_response(
        {
            "job_id": "job_4",
            "status_counts": {"partial": 1},
            "executions": [
                {
                    "node_code": "law_ground_search",
                    "agent_output": {
                        "status": "partial",
                        "summary": "조문 5건 검색됨. 다만 신뢰도가 낮아 추가 확인이 필요합니다.",
                        "structured_result": {"law_provisions": [{"article_no": "1"}]},
                        "evidence": [{"source_reference": "law:1"}],
                        "limitations": [],
                    },
                },
            ],
            "supervisor_state": {
                "collected_facts": [
                    {"field": "user_text", "value": "신호위반 관련 도로교통법 조문이 궁금해요"}
                ]
            },
            "attachments": [],
        }
    )

    follow_up = response["assistant_message"]["follow_up"]
    assert follow_up is not None
    assert follow_up["items"] == [
        {"label": "발생 일시와 장소", "required": False},
        {"label": "받으신 고지서나 통지 내용", "required": False},
    ]


def test_missing_violation_type_is_flagged_as_required() -> None:
    # No violation-type keyword at all, but date/location and notice content
    # are present -> only the required item should be missing.
    response = compose_agent_response(
        {
            "job_id": "job_5",
            "status_counts": {"partial": 1},
            "executions": [
                {
                    "node_code": "law_ground_search",
                    "agent_output": {
                        "status": "partial",
                        "summary": "검색 조건에 맞는 유효한 조문이 없습니다.",
                        "structured_result": {"law_provisions": []},
                        "evidence": [],
                        "limitations": [],
                    },
                },
            ],
            "supervisor_state": {
                "collected_facts": [
                    {
                        "field": "user_text",
                        "value": "어제 학교 앞에서 고지서를 받았어요. 어떻게 해야 하나요?",
                    }
                ]
            },
            "attachments": [],
        }
    )

    follow_up = response["assistant_message"]["follow_up"]
    assert follow_up["items"] == [{"label": "정확한 위반·분쟁 유형", "required": True}]

    answer = response["assistant_message"]["answer"]
    assert "꼭 필요해요: 정확한 위반·분쟁 유형." in answer
    assert "알려주시면 더 좋아요" not in answer


def test_empty_search_asks_user_to_rephrase_when_all_categories_are_already_given() -> None:
    response = compose_agent_response(
        {
            "job_id": "job_3",
            "status_counts": {"partial": 1},
            "executions": [
                {
                    "node_code": "law_ground_search",
                    "agent_output": {
                        "status": "partial",
                        "summary": "검색 조건에 맞는 유효한 조문이 없습니다.",
                        "structured_result": {"law_provisions": []},
                        "evidence": [],
                        "limitations": [],
                    },
                },
            ],
            "supervisor_state": {
                "collected_facts": [
                    {
                        "field": "user_text",
                        "value": (
                            "어제 학교 앞 교차로에서 신호위반 과태료 고지서를 받았어요"
                        ),
                    }
                ]
            },
            "attachments": [],
        }
    )

    answer = response["assistant_message"]["answer"]
    assert "표현을 조금 바꿔서" in answer
    assert "알려주시면 도움이 됩니다:" not in answer

    follow_up = response["assistant_message"]["follow_up"]
    assert follow_up["items"] == []

