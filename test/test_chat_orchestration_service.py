from __future__ import annotations

import json
from unittest.mock import patch

from app.services.attachment_mock_service import CANONICAL_SCAN_GATE_MARKER
from app.services.agent_node_service import execute_agent_plan
from app.services.chat_orchestration_service import compose_agent_response, submit_message
from app.services.supervisor_llm_service import validate_slot_filling_state
from app.services.supervisor_routing_service import DEFAULT_POLICY_PATH, routing_policy_metadata


def test_supervisor_routing_uses_a_versioned_external_policy() -> None:
    metadata = routing_policy_metadata()

    assert metadata["contract_version"] == "supervisor_routing_policy.v1"
    assert metadata["source"].endswith("supervisor_routing_policy.v1.json")


def test_report_routing_policy_has_no_obsolete_pre_merge_placement_rule() -> None:
    policy = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))

    assert "insert_before" not in policy["report_policy"]


def test_empty_message_requests_input_without_creating_an_agent_plan() -> None:
    response = submit_message({"session_id": "ses_1", "user_text": ""})

    assert response["status"] == "needs_input"
    assert response["pending_questions"]
    assert response["analysis_plan"]["steps"] == []
    assert "mock" not in str(response).lower()


def test_out_of_scope_accident_does_not_create_a_supervisor_plan() -> None:
    response = submit_message(
        {
            "session_id": "ses_scope_boundary",
            "user_text": "차가 보행자와 충돌한 사고의 과실을 확정해 주세요.",
        }
    )

    assert response["status"] == "scope_guidance"
    assert response["service_scope"]["decision"] == "expert_handoff"
    assert response["analysis_plan"]["steps"] == []
    assert response["reporting_payload"] is None


def test_criminal_scope_guidance_does_not_create_execution_or_report() -> None:
    response = submit_message(
        {
            "session_id": "ses_criminal",
            "user_text": "형사처벌과 고발 가능성을 판정해 주세요.",
        }
    )

    assert response["status"] == "scope_guidance"
    assert response["service_scope"]["scope_code"] == "criminal_review"
    assert response["next_actions"] == response["service_scope"]["next_actions"]
    assert response["analysis_plan"]["status"] == "blocked"
    assert response["analysis_plan"]["steps"] == []
    assert response["reporting_payload"] is None


def test_fine_notice_message_queues_supervisor_boundaries_and_supported_real_agents() -> None:
    response = submit_message(
        {
            "session_id": "ses_1",
            "user_text": "과태료 고지서를 받았고 의견제출 가능성을 확인하고 싶습니다.",
            "attachments": [{"attachment_id": "att_1", "purpose": "fine_notice", "status": "ready"}],
        }
    )

    assert response["status"] == "queued"
    assert response["routing_intent"] == "fine_notice_analysis"
    assert [step["node_code"] for step in response["analysis_plan"]["steps"]] == [
        "input_context_validation",
        "fine_notice_analysis",
        "agent_result_validation",
        "final_response_merge",
    ]
    assert response["assistant_message"] is None
    assert "vision_media_analysis" not in str(response)
    assert "mock" not in str(response).lower()


def test_canonical_scan_ready_image_or_pdf_queues_document_classification_before_declared_purpose() -> None:
    storage_uri = "s3://clean-bucket/canonical/uploads/usr/ses_document/att_document/notice.pdf"
    response = submit_message(
        {
            "session_id": "ses_document_classification",
            "user_text": "첨부 자료를 확인해 주세요.",
            "attachments": [
                {
                    "_canonical_scan_gate": CANONICAL_SCAN_GATE_MARKER,
                    "attachment_id": "att_document",
                    "purpose": "fine_notice",
                    "type": "pdf",
                    "content_type": "application/pdf",
                    "status": "ready",
                    "scan_status": "clean",
                    "resolution_status": "scan_ready",
                    "storage_uri": storage_uri,
                    "object_storage": {
                        "resource_type": "uploaded_file",
                        "status": "ready",
                        "storage_uri": storage_uri,
                    },
                }
            ],
        }
    )

    assert response["routing_intent"] == "attachment_document_classification"
    assert [step["node_code"] for step in response["analysis_plan"]["steps"]] == [
        "input_context_validation",
        "attachment_document_classification",
        "agent_result_validation",
        "final_response_merge",
    ]


def test_confirmed_accident_photo_routes_to_search_without_video_analysis() -> None:
    storage_uri = "s3://clean-bucket/canonical/uploads/usr/ses_photo/att_photo/scene.png"
    response = submit_message(
        {
            "session_id": "ses_confirmed_accident_photo",
            "user_text": "교차로 사고 사진과 설명을 기준으로 관련 사례와 법령을 찾아 주세요.",
            "attachments": [
                {
                    "_canonical_scan_gate": CANONICAL_SCAN_GATE_MARKER,
                    "attachment_id": "att_photo",
                    "purpose": "accident_scene",
                    "type": "image",
                    "content_type": "image/png",
                    "status": "ready",
                    "scan_status": "clean",
                    "resolution_status": "scan_ready",
                    "storage_uri": storage_uri,
                    "object_storage": {
                        "resource_type": "uploaded_file",
                        "status": "ready",
                        "storage_uri": storage_uri,
                    },
                }
            ],
        },
        routing_intent_override="accident_photo_evidence_analysis",
    )

    assert response["routing_intent"] == "accident_photo_evidence_analysis"
    node_codes = [step["node_code"] for step in response["analysis_plan"]["steps"]]
    assert node_codes == [
        "input_context_validation",
        "text_ml_case_search",
        "law_ground_search",
        "agent_result_validation",
        "final_response_merge",
    ]
    assert "attachment_document_classification" not in node_codes
    assert "vision_media_analysis" not in node_codes


def test_traffic_accident_confirmation_keeps_its_specialized_ocr_route() -> None:
    response = submit_message(
        {
            "session_id": "ses_specialized_ocr",
            "user_text": "사실확인서를 읽어 주세요.",
            "attachments": [
                {
                    "attachment_id": "att_confirmation",
                    "purpose": "traffic_accident_confirmation",
                    "type": "image",
                    "content_type": "image/png",
                    "status": "ready",
                    "scan_status": "clean",
                }
            ],
        }
    )

    assert response["routing_intent"] == "traffic_accident_confirmation_ocr"


def test_confirmed_ocr_fields_enable_law_and_appeal_only_after_first_pass() -> None:
    response = submit_message(
        {
            "session_id": "ses_ocr_confirmed",
            "user_text": "OCR 내용을 확인했고 후속 절차를 진행해 주세요.",
            "ocr_confirmation": {
                "confirmed": True,
                "fields": {
                    "fine_type": "과태료",
                    "notice_stage": "사전통지",
                    "unexpected": "must_not_be_forwarded",
                },
            },
            "attachments": [{"attachment_id": "att_notice", "purpose": "fine_notice", "status": "ready"}],
        }
    )

    assert [step["node_code"] for step in response["analysis_plan"]["steps"]] == [
        "input_context_validation",
        "fine_notice_analysis",
        "law_ground_search",
        "appeal_decision_flow",
        "agent_result_validation",
        "final_response_merge",
    ]
    fine_step = next(
        step for step in response["analysis_plan"]["steps"] if step["node_code"] == "fine_notice_analysis"
    )
    assert fine_step["context"]["ocr_confirmation"] == {
        "confirmed": True,
        "fields": {"fine_type": "과태료", "notice_stage": "사전통지"},
    }


def test_incomplete_ocr_confirmation_keeps_follow_up_nodes_out_of_the_plan() -> None:
    response = submit_message(
        {
            "session_id": "ses_ocr_incomplete",
            "user_text": "OCR 내용을 확인했습니다.",
            "ocr_confirmation": {"confirmed": True, "fields": {"fine_type": "과태료"}},
            "attachments": [{"attachment_id": "att_notice", "purpose": "fine_notice", "status": "ready"}],
        }
    )

    node_codes = [step["node_code"] for step in response["analysis_plan"]["steps"]]
    assert node_codes == [
        "input_context_validation",
        "fine_notice_analysis",
        "agent_result_validation",
        "final_response_merge",
    ]
    assert "law_ground_search" not in node_codes
    assert "appeal_decision_flow" not in node_codes


def test_first_pass_ocr_result_surfaces_an_editable_confirmation_requirement(monkeypatch) -> None:
    import importlib

    fine_notice_graph_module = importlib.import_module("ai.agents.fine_notice_analysis.graph")
    monkeypatch.setattr(
        fine_notice_graph_module.graph,
        "invoke",
        lambda _state: {
            "agent_results": {
                "fine_notice_analysis": {
                    "status": "success",
                    "summary": "OCR completed",
                    "structured_result": {
                        "fine_type": "과태료",
                        "notice_stage": "사전통지",
                    },
                    "evidence": [
                        {
                            "source_type": "user_uploaded_file",
                            "title": "uploaded fine notice",
                            "source_reference": "att_notice",
                            "metadata": {},
                            "confidence": 0.9,
                        }
                    ],
                    "next_actions": [],
                    "limitations": [],
                }
            }
        },
    )
    request = {
        "session_id": "ses_ocr_first_pass",
        "user_text": "첨부한 고지서를 확인해 주세요.",
        "attachments": [{"attachment_id": "att_notice", "purpose": "fine_notice", "status": "ready"}],
    }
    receipt = submit_message(request)

    execution = execute_agent_plan(
        receipt["analysis_plan"],
        {
            **request,
            "context": {"supervisor_handoff": receipt["supervisor_state"]},
        },
    )
    result = compose_agent_response(execution)

    assert result["structured_results"]["fine_notice_analysis"]["requires_confirmation"] is True
    assert result["structured_results"]["fine_notice_analysis"]["error_code"] == "ocr_confirmation_required"


def test_conflicting_ocr_confirmation_blocks_law_and_appeal_invocation(monkeypatch) -> None:
    import importlib

    fine_notice_graph_module = importlib.import_module("ai.agents.fine_notice_analysis.graph")
    monkeypatch.setattr(
        fine_notice_graph_module.graph,
        "invoke",
        lambda _state: {
            "agent_results": {
                "fine_notice_analysis": {
                    "status": "success",
                    "summary": "OCR completed",
                    "structured_result": {"fine_type": "범칙금", "notice_stage": "사전통지"},
                    "evidence": [
                        {
                            "source_type": "user_uploaded_file",
                            "title": "uploaded fine notice",
                            "source_reference": "att_notice_conflict",
                            "metadata": {},
                            "confidence": 0.9,
                        }
                    ],
                    "next_actions": [],
                    "limitations": [],
                }
            }
        },
    )
    request = {
        "session_id": "ses_ocr_conflict",
        "user_text": "OCR 내용을 확인했고 후속 절차를 진행해 주세요.",
        "ocr_confirmation": {
            "confirmed": True,
            "fields": {"fine_type": "과태료", "notice_stage": "사전통지"},
        },
        "attachments": [
            {"attachment_id": "att_notice_conflict", "purpose": "fine_notice", "status": "ready"}
        ],
    }
    receipt = submit_message(request)

    execution = execute_agent_plan(
        receipt["analysis_plan"],
        {
            **request,
            "context": {"supervisor_handoff": receipt["supervisor_state"]},
        },
    )
    executions = {item["node_code"]: item["agent_output"] for item in execution["executions"]}

    assert executions["fine_notice_analysis"]["structured_result"]["error_code"] == "purpose_result_conflict"
    assert executions["law_ground_search"]["execution_status"] == "blocked"
    assert executions["appeal_decision_flow"]["execution_status"] == "blocked"


def test_blackbox_video_uses_partial_evidence_plan_without_a_report() -> None:
    response = submit_message(
        {
            "session_id": "ses_video_1",
            "user_text": "블랙박스 영상의 관련 법령과 사례를 확인해 주세요.",
            "attachments": [
                {
                    "attachment_id": "att_video_1",
                    "purpose": "blackbox_video",
                    "status": "ready",
                }
            ],
        }
    )

    assert response["routing_intent"] == "accident_evidence_analysis"
    assert [step["node_code"] for step in response["analysis_plan"]["steps"]] == [
        "input_context_validation",
        "vision_media_analysis",
        "text_ml_case_search",
        "law_ground_search",
        "agent_result_validation",
        "final_response_merge",
    ]
    assert response["reporting_payload"] is None
    assert response["analysis_plan"]["steps"][-2]["context"]["evidence_only"] is True


def test_text_only_accident_still_waits_for_fact_confirmation() -> None:
    response = submit_message(
        {"session_id": "ses_text_only", "user_text": "교차로 충돌 사고입니다."}
    )

    assert response["routing_intent"] == "accident_initial_consultation"
    assert response["status"] == "needs_input"
    assert response["analysis_plan"]["steps"] == []


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


def test_enabled_supervisor_cannot_override_server_ready_stage(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_LLM_ENABLED", "1")
    monkeypatch.setenv("SUPERVISOR_LLM_API_KEY", "sk-test")
    monkeypatch.setattr(
        "app.services.supervisor_llm_service._request_supervisor_json",
        lambda *_args: {
            "conversation_summary": "A law reference is still required.",
            "collected_facts": [],
            "missing_fields": [
                {"field": "law_question", "reason": "model_requested"}
            ],
            "next_questions": [
                {"field": "law_question", "question": "Which law should be reviewed?"}
            ],
            "agent_input_packages": [
                {
                    "node_code": "law_ground_search",
                    "payload": {},
                }
            ],
        },
    )

    response = submit_message(
        {"session_id": "ses_need_more_input", "user_text": "help"}
    )

    assert response["status"] == "queued"
    assert response["progress"]["status"] == "queued"
    assert response["pending_questions"] == []
    assert response["analysis_plan"]["steps"]
    assert response["reporting_payload"] is None
    assert response["report_links"] == []
    assert response["supervisor_state"]["stage"] == "agent_execution_ready"
    assert response["supervisor_state"]["missing_fields"] == []


def test_fine_notice_procedure_question_does_not_run_ocr_appeal_or_report() -> None:
    response = submit_message(
        {
            "session_id": "ses_procedure",
            "user_text": "과태료 이의신청 절차와 제출 기한이 궁금합니다.",
            "attachments": [],
        }
    )

    assert response["routing_intent"] == "fine_notice_procedure"
    assert [step["node_code"] for step in response["analysis_plan"]["steps"]] == [
        "input_context_validation",
        "law_ground_search",
        "agent_result_validation",
        "final_response_merge",
    ]


def test_enforcement_eligibility_question_routes_to_fine_notice_procedure() -> None:
    response = submit_message(
        {
            "session_id": "ses_enforcement_eligibility",
            "user_text": "어린이보호구역에서 응급상황 때문에 잠깐 정차한 경우도 단속 대상이야?",
            "attachments": [],
        }
    )

    assert response["routing_intent"] == "fine_notice_procedure"


def test_emergency_stop_quick_question_routes_to_fine_notice_procedure() -> None:
    response = submit_message(
        {
            "session_id": "ses_emergency_stop_quick_question",
            "user_text": "6월 24일 오후 3시 초등학교 앞에서 아이가 아파 잠깐 정차했어",
            "attachments": [],
        }
    )

    assert response["routing_intent"] == "fine_notice_procedure"


def test_accident_context_with_burden_phrase_stays_in_accident_consultation() -> None:
    response = submit_message(
        {
            "session_id": "ses_accident_burden_phrase",
            "user_text": "고속도로에서 벌금 걱정이 되는데 사고가 나서 과실비율이 어떻게 되는지 궁금합니다.",
            "attachments": [],
        }
    )

    assert response["routing_intent"] == "accident_initial_consultation"
    assert response["status"] == "needs_input"
    assert response["analysis_plan"]["steps"] == []


def test_rear_end_quick_question_routes_to_accident_consultation() -> None:
    response = submit_message(
        {
            "session_id": "ses_rear_end_quick_question",
            "user_text": "앞차가 갑자기 급정거해서 추돌했는데 뒤차가 항상 100% 책임이야?",
            "attachments": [],
        }
    )

    assert response["routing_intent"] == "accident_initial_consultation"
    assert response["status"] == "needs_input"
    assert response["pending_questions"]


def test_illegal_parking_accident_quick_question_stays_in_accident_consultation() -> None:
    response = submit_message(
        {
            "session_id": "ses_illegal_parking_accident_quick_question",
            "user_text": "불법 주정차 차량 때문에 시야가 가려져 사고가 나면 그 차량에도 책임이 있어?",
            "attachments": [],
        }
    )

    assert response["routing_intent"] == "accident_initial_consultation"
    assert response["status"] == "needs_input"


def test_report_node_is_planned_only_when_document_generation_is_explicitly_requested() -> None:
    response = submit_message(
        {
            "session_id": "ses_report",
            "user_text": "첨부한 고지서를 분석하고 이의신청서 초안을 작성해 주세요.",
            "ocr_confirmation": {
                "confirmed": True,
                "fields": {"fine_type": "과태료", "notice_stage": "사전통지"},
            },
            "attachments": [{"attachment_id": "att_1", "purpose": "fine_notice", "status": "ready"}],
        }
    )

    assert [step["node_code"] for step in response["analysis_plan"]["steps"]] == [
        "input_context_validation",
        "fine_notice_analysis",
        "law_ground_search",
        "appeal_decision_flow",
        "agent_result_validation",
        "final_response_merge",
        "objection_report_generation",
    ]
    assert response["analysis_plan"]["steps"][-1]["depends_on"] == [
        "final_response_merge"
    ]


def test_supervisor_fallback_builds_valid_slot_state_for_reporting_handoff() -> None:
    response = submit_message(
        {
            "session_id": "ses_slot_state",
            "user_text": "prepare an objection report",
            "attachments": [{"attachment_id": "att_1", "purpose": "fine_notice", "status": "ready"}],
        }
    )

    validation = validate_slot_filling_state(
        response["supervisor_state"],
        response["analysis_plan"],
    )
    packages = response["supervisor_state"]["agent_input_packages"]
    assert validation["valid"] is True
    assert packages
    assert all(package["status"] == "ready" for package in packages)
    assert all(
        package["payload"]["slot_state"]["contract_version"] == "slot_filling_state.v1"
        for package in packages
    )


def test_fault_ratio_message_requires_case_and_does_not_enable_unsupported_media_analysis() -> None:
    response = submit_message(
        {"session_id": "ses_1", "user_text": "교차로에서 충돌했는데 과실비율이 궁금합니다."}
    )

    assert response["routing_intent"] == "accident_initial_consultation"
    assert response["status"] == "needs_input"
    assert response["analysis_plan"]["steps"] == []
    assert response["consultation_state"]["v2"]["schema_version"] == "consultation_state.v2"
    assert "vision_media_analysis" not in str(response)


def test_fault_ratio_followup_answer_is_accumulated_before_next_question() -> None:
    response = submit_message(
        {
            "session_id": "ses_followup",
            "user_text": "신호등이 있는 사거리 교차로입니다.",
            "conversation_history": [
                {"role": "user", "content": "사고 과실을 상담하고 싶어요."},
                {"role": "assistant", "content": "사고 장소의 도로 형태를 알려주세요."},
                {"role": "user", "content": "신호등이 있는 사거리 교차로입니다."},
            ],
        }
    )

    reduced = response["consultation_state"]["fact_state"]
    assert reduced["facts"]["road_layout"]["value"] == "신호등이 있는 사거리 교차로입니다."
    assert response["pending_questions"][0]["field"] == "vehicle_actions"


@patch("app.services.chat_orchestration_service.build_supervisor_state_with_optional_llm")
def test_structured_fault_facts_do_not_repeat_core_questions(build_supervisor_state) -> None:
    build_supervisor_state.return_value = {
        "contract_version": "supervisor_conversation_state.v2",
        "stage": "need_fact_confirmation",
        "collected_facts": [],
        "missing_fields": [],
        "next_questions": [],
        "agent_input_packages": [],
        "reporting_payload": None,
    }

    response = submit_message(
        {
            "session_id": "ses_structured_facts",
            "user_text": "교차로 사고 과실을 상담하고 싶습니다.",
            "facts": {
                "road_layout": "신호등이 없는 같은 폭의 일반 교차로",
                "vehicle_actions": "저는 직진, 상대 차량은 우측 도로에서 진입",
                "signal_priority": "신호와 일시정지 표지가 없습니다.",
                "collision_location": "제 차량 우측 앞 범퍼와 상대 차량 좌측 앞 범퍼",
            },
        },
        routing_intent_override="accident_initial_consultation",
    )

    assert response["consultation_state"]["fact_state"]["missing_fields"] == []
    assert not {
        question["field"]
        for question in response["pending_questions"]
    } & {"road_layout", "vehicle_actions", "signal_priority", "collision_location"}


@patch("app.services.chat_orchestration_service.build_supervisor_state_with_optional_llm")
def test_accident_initial_message_uses_llm_only_for_fact_candidates(build_supervisor_state) -> None:
    build_supervisor_state.return_value = {
        "contract_version": "supervisor_conversation_state.v2",
        "stage": "need_fact_confirmation",
        "collected_facts": [
            {"field": "road_layout", "value": "사거리 교차로", "confidence": 0.9},
            {"field": "vehicle_actions", "value": "A 직진, B 좌회전", "confidence": 0.9},
            {"field": "signal_priority", "value": "A 녹색 신호", "confidence": 0.8},
            {"field": "collision_location", "value": "A 앞범퍼와 B 우측면", "confidence": 0.9},
        ],
        "missing_fields": [],
        "next_questions": [],
        "agent_input_packages": [],
        "reporting_payload": None,
    }

    response = submit_message(
        {
            "session_id": "ses_initial_facts",
            "message_id": "msg_initial_facts",
            "user_text": "사거리에서 저는 직진하고 상대는 좌회전하다 충돌했습니다. 제 신호는 녹색이었습니다.",
        }
    )

    fact_state = response["consultation_state"]["fact_state"]
    assert fact_state["missing_fields"] == []
    assert all(not record["confirmed"] for record in fact_state["facts"].values())
    case_evidence = response["consultation_state"]["v2"]["case_evidence"]
    assert case_evidence["schema_version"] == "case_evidence.v1"
    assert case_evidence["facts"] == {}
    assert set(case_evidence["claims"]) == {
        "road_layout",
        "vehicle_actions",
        "signal_priority",
        "collision_location",
    }
    assert response["supervisor_state"]["case_evidence"] == case_evidence
    assert response["pending_questions"][0]["field"] == "material_evidence"
    assert response["consultation_state"]["promotion_gate"]["requirements"][0] == "fact_confirmation"
    assert response["analysis_plan"]["steps"] == []


def test_accident_consultation_exposes_structured_case_memory() -> None:
    response = submit_message(
        {
            "session_id": "ses_case_memory",
            "message_id": "msg_case_memory",
            "user_text": "신호등 있는 교차로에서 직진 중이었는데 상대 차량이 좌회전으로 들어왔습니다.",
            "case_memory": {
                "schema_version": "case_memory.v1",
                "conversation_summary": "이전 대화에서 블랙박스 보유 여부를 확인했습니다.",
                "evidence_refs": ["att_blackbox_1"],
                "progress_steps": ["collect_missing_facts"],
            },
        }
    )

    case_memory = response["consultation_state"]["case_memory"]
    assert case_memory["schema_version"] == "case_memory.v1"
    assert case_memory["incident_types"] == ["accident_initial_consultation"]
    assert case_memory["evidence_refs"] == ["att_blackbox_1"]
    assert case_memory["progress_steps"][-1] in {"collect_missing_facts", "confirm_facts"}
    assert "블랙박스 보유 여부" in case_memory["conversation_summary"]
    assert "신호등 있는 교차로" in case_memory["conversation_summary"]


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
                        "evidence": [{"source_ref": "law:1", "source_type": "law"}],
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
    assert "source_ref" not in response["evidence"][1]
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



def test_composed_agent_response_preserves_deadline_guidance() -> None:
    response = compose_agent_response(
        {
            "job_id": "job_deadline",
            "executions": [
                {
                    "node_code": "final_response_merge",
                    "agent_output": {
                        "status": "partial",
                        "summary": "deadline guidance",
                        "structured_result": {
                            "assistant_message": {
                                "answer": "deadline guidance",
                                "summary": "deadline guidance",
                            },
                            "deadline_guidance": {
                                "contract_version": "deadline_guidance.v1",
                                "status": "needs_confirmation",
                            },
                            "cards": [
                                {
                                    "card_type": "deadline_guidance",
                                    "title": "deadline confirmation",
                                }
                            ],
                            "evidence": [],
                            "limitations": [],
                            "pending_questions": [],
                            "report_links": [],
                        },
                    },
                }
            ],
        }
    )

    assert response["deadline_guidance"]["status"] == "needs_confirmation"
    assert response["cards"][0]["card_type"] == "deadline_guidance"


def test_composed_agent_response_preserves_final_next_actions() -> None:
    response = compose_agent_response(
        {
            "job_id": "job_next_actions",
            "executions": [
                {
                    "node_code": "final_response_merge",
                    "agent_output": {
                        "status": "partial",
                        "summary": "추가 근거 확인이 필요합니다.",
                        "structured_result": {
                            "assistant_message": {"answer": "추가 근거 확인이 필요합니다."},
                            "next_actions": ["고지서 원문을 확인해 주세요."],
                        },
                    },
                }
            ],
        }
    )

    assert response["next_actions"] == ["고지서 원문을 확인해 주세요."]
