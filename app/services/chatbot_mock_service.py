"""Mock chatbot service fixtures for the mid-demo MVP path."""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.security.chat_input_privacy import protect_chat_input_payload
from app.services.attachment_mock_service import resolve_attachment_references
from app.services.persona_catalog_service import (
    DEFAULT_PERSONA_ID,
    default_demo_persona,
    demo_persona_ids,
    get_demo_persona,
    list_demo_personas,
)
from app.services.supervisor_llm_service import (
    build_analysis_plan_with_optional_llm,
    build_supervisor_state_with_optional_llm,
)


SCENARIO_INTENTS = {
    "fine_notice": "objection_request",
    "fault_ratio": "fault_ratio",
    "law_question": "law_question",
    "report_redownload": "report_redownload",
    "general_consultation": "general_consultation",
}

DEMO_PERSONA_ID = DEFAULT_PERSONA_ID

DEMO_PERSONA_RUN: dict[str, Any] = default_demo_persona()


MOCK_SCENARIO_RESULTS: dict[str, dict[str, dict[str, Any]]] = {
    "fine_notice": {
        "success": {
            "assistant_message": "고지서 내용을 확인했고, 이의신청 초안까지 이어갈 수 있습니다.",
            "progress": {
                "status": "success",
                "active_node": "final_response_merge",
                "message": "과태료 고지서 mock 분석이 완료되었습니다.",
            },
            "case_status": "analysis_completed",
            "cards": [
                {
                    "card_type": "fine_notice",
                    "title": "고지서 분석",
                    "status": "success",
                    "summary": "과태료 고지서로 추정되며 의견제출 기한과 발급기관 확인이 필요합니다.",
                    "evidence_refs": ["att_0001"],
                },
                {
                    "card_type": "objection_report",
                    "title": "이의신청서 초안",
                    "status": "partial",
                    "summary": "사용자 사실관계 보완 후 제출용 초안 형태로 정리할 수 있습니다.",
                    "evidence_refs": ["att_0001"],
                },
            ],
            "report_links": [
                {
                    "action": "save",
                    "label": "리포트 저장",
                    "endpoint": "/api/mock/reports",
                },
                {
                    "action": "download",
                    "label": "리포트 다운로드",
                    "endpoint": "/api/mock/reports/download",
                },
            ],
            "limitations": [
                "중간발표용 mock 결과이며 실제 Agent, RAG, MCP 호출 결과가 아닙니다.",
                "법률 자문 또는 처분 취소 가능성 보장이 아닙니다.",
            ],
        },
        "partial": {
            "assistant_message": "고지서 흐름을 시작했지만 이의신청 사유가 더 필요합니다.",
            "progress": {
                "status": "partial",
                "active_node": "missing_input_question",
                "message": "필수 입력 보완이 필요합니다.",
            },
            "case_status": "needs_more_input",
            "cards": [
                {
                    "card_type": "fine_notice",
                    "title": "고지서 분석",
                    "status": "partial",
                    "summary": "고지서 이미지는 확인했지만 사용자 사실관계가 부족합니다.",
                    "evidence_refs": ["att_0001"],
                }
            ],
            "report_links": [],
            "pending_questions": [
                {
                    "field": "user_facts",
                    "question": "이의신청 사유와 당시 상황을 한두 문장으로 보완해 주세요.",
                }
            ],
            "limitations": ["필수 입력이 부족해 리포트 초안 생성은 보류되었습니다."],
        },
        "pending": {
            "assistant_message": "고지서 분석을 시작했습니다.",
            "progress": {
                "status": "pending",
                "active_node": "input_classification",
                "message": "입력 유형을 분류하는 중입니다.",
            },
            "case_status": "analysis_requested",
            "cards": [],
            "report_links": [],
            "limitations": ["mock pending 상태입니다."],
        },
        "failed": {
            "assistant_message": "현재 입력만으로는 고지서 분석 결과를 만들 수 없습니다.",
            "progress": {
                "status": "failed",
                "active_node": "input_classification",
                "message": "분석 가능한 고지서 입력을 찾지 못했습니다.",
            },
            "case_status": "failed",
            "cards": [],
            "report_links": [],
            "limitations": ["지원 형식의 고지서 이미지, PDF, 설명 텍스트를 다시 입력해 주세요."],
        },
    },
    "fault_ratio": {
        "success": {
            "assistant_message": "사고 설명을 바탕으로 과실비율 쟁점과 유사 사례 후보를 정리했습니다.",
            "progress": {
                "status": "success",
                "active_node": "text_ml_case_search",
                "message": "과실비율 mock 분석이 완료되었습니다.",
            },
            "case_status": "analysis_completed",
            "cards": [
                {
                    "card_type": "fault_ratio",
                    "title": "과실비율 쟁점",
                    "status": "success",
                    "summary": "신호 없는 교차로, 선진입 여부, 일시정지 여부가 핵심 쟁점입니다.",
                    "evidence_refs": ["case_mock_001", "att_0002"],
                },
                {
                    "card_type": "similar_case",
                    "title": "유사 사례 후보",
                    "status": "partial",
                    "summary": "유사 사례 2건이 있으나 실제 과실비율 확정 근거는 아닙니다.",
                    "evidence_refs": ["case_mock_001", "case_mock_002"],
                },
                {
                    "card_type": "recommended_evidence",
                    "title": "추가 제출 권장 자료",
                    "status": "success",
                    "summary": "블랙박스 원본, 현장 사진, 보험사 접수 내역을 추가하면 쟁점 정리가 좋아집니다.",
                    "evidence_refs": [],
                },
            ],
            "structured_result": {
                "normalized_description": "신호 없는 교차로에서 A차 직진, B차 우측 진입 중 접촉사고",
                "accident_type_candidates": ["intersection_no_signal", "side_entry_collision"],
                "issue_tags": ["선진입", "일시정지", "시야 제한"],
                "evidence_tags": ["blackbox", "scene_photo", "insurance_record"],
                "similar_cases": [
                    {
                        "case_id": "case_mock_001",
                        "title": "신호 없는 교차로 직진/우측 진입 사고",
                        "summary": "선진입과 일시정지 여부가 주요 판단 요소로 정리된 사례입니다.",
                        "reliability_score": 0.78,
                        "source_type": "review_case",
                        "source_ref": "case_chunk_mock_001",
                    },
                    {
                        "case_id": "case_mock_002",
                        "title": "교차로 시야 제한 접촉사고",
                        "summary": "시야 제한과 감속 여부를 함께 검토한 유사 사례입니다.",
                        "reliability_score": 0.64,
                        "source_type": "precedent",
                        "source_ref": "case_chunk_mock_002",
                    },
                ],
                "reliability_score": 0.71,
                "ratio_range_label": "과실비율 확정 전 쟁점 검토 필요",
                "recommended_evidence": ["블랙박스 원본", "현장 사진", "보험사 접수 내역"],
                "limitations": [
                    "과실비율을 수치로 확정하지 않습니다.",
                    "유사 사례는 참고 근거이며 실제 판단과 다를 수 있습니다.",
                ],
            },
            "report_links": [
                {
                    "action": "save",
                    "label": "분석 리포트 저장",
                    "endpoint": "/api/mock/reports",
                },
                {
                    "action": "download",
                    "label": "분석 리포트 다운로드",
                    "endpoint": "/api/mock/reports/download",
                },
            ],
            "limitations": [
                "중간발표용 mock 결과이며 실제 ML/RAG/판례 검색 결과가 아닙니다.",
                "과실비율 수치 확정 또는 법률 판단이 아닙니다.",
            ],
        },
        "partial": {
            "assistant_message": "사고 설명은 확인했지만 핵심 자료가 부족합니다.",
            "progress": {
                "status": "partial",
                "active_node": "missing_input_question",
                "message": "과실비율 쟁점 정리를 위해 추가 자료가 필요합니다.",
            },
            "case_status": "needs_more_input",
            "cards": [
                {
                    "card_type": "fault_ratio",
                    "title": "과실비율 쟁점",
                    "status": "partial",
                    "summary": "사고 유형 후보는 있으나 블랙박스나 현장 사진이 필요합니다.",
                    "evidence_refs": [],
                }
            ],
            "report_links": [],
            "pending_questions": [
                {
                    "field": "accident_context",
                    "question": "사고 장소, 진행 방향, 신호 여부, 블랙박스 보유 여부를 알려 주세요.",
                }
            ],
            "limitations": ["증거 자료 부족으로 유사 사례와 쟁점만 제한적으로 표시합니다."],
        },
        "pending": {
            "assistant_message": "과실비율 분석을 시작했습니다.",
            "progress": {
                "status": "pending",
                "active_node": "input_classification",
                "message": "사고 설명과 첨부 자료를 분류하는 중입니다.",
            },
            "case_status": "analysis_requested",
            "cards": [],
            "report_links": [],
            "limitations": ["mock pending 상태입니다."],
        },
        "failed": {
            "assistant_message": "현재 입력만으로는 과실비율 쟁점 분석을 시작할 수 없습니다.",
            "progress": {
                "status": "failed",
                "active_node": "input_classification",
                "message": "사고 설명 또는 첨부 자료가 필요합니다.",
            },
            "case_status": "failed",
            "cards": [],
            "report_links": [],
            "limitations": ["사고 경위 텍스트, 현장 사진, 블랙박스 설명 중 하나를 입력해 주세요."],
        },
    },
}


def list_demo_scenarios() -> list[dict[str, str]]:
    return [
        {"scenario": "fine_notice", "label": "과태료/이의신청 mock 흐름"},
        {"scenario": "fault_ratio", "label": "과실비율 mock 흐름"},
        {"scenario": "law_question", "label": "법령 근거 질문 mock 흐름"},
        {"scenario": "report_redownload", "label": "저장 리포트 재다운로드 mock 흐름"},
    ]


def create_session(user_id: str | None = None) -> dict[str, Any]:
    session_id = f"ses_{uuid4().hex[:12]}"
    return {
        "session_id": session_id,
        "user_id": user_id,
        "status": "draft",
        "created_at": _now_iso(),
        "available_scenarios": list_demo_scenarios(),
        "available_personas": list_demo_personas(),
    }


def submit_message(payload: dict[str, Any]) -> dict[str, Any]:
    payload = protect_chat_input_payload(payload)
    payload = resolve_attachment_references(payload)
    persona_run = _persona_run_for_payload(payload)
    scenario = payload.get("mock_scenario") or (
        persona_run.get("scenario") if persona_run else _infer_scenario(payload)
    )
    if persona_run:
        scenario = persona_run["scenario"]
    if scenario == "general_consultation" and not persona_run:
        return _general_consultation_response(payload)
    supervisor_state = build_supervisor_state_with_optional_llm(
        payload=payload,
        scenario=scenario,
        fallback_builder=_build_supervisor_conversation_state,
    )
    requested_status = payload.get("mock_status") or (
        "success"
        if persona_run
        else _infer_status(
            payload,
            scenario=scenario,
            supervisor_state=supervisor_state,
        )
    )
    scenario_fixtures = MOCK_SCENARIO_RESULTS.get(scenario, MOCK_SCENARIO_RESULTS["fine_notice"])
    fixture = deepcopy(scenario_fixtures.get(requested_status, scenario_fixtures["success"]))
    if persona_run:
        _apply_persona_run(fixture, persona_run)
    else:
        _apply_supervisor_conversation_state(
            fixture,
            supervisor_state=supervisor_state,
            scenario=scenario,
            requested_status=requested_status,
            use_dynamic_sequence=not bool(payload.get("mock_status")),
        )
    _append_attachment_resolution_limitations(fixture, payload)
    message_id = f"msg_{uuid4().hex[:12]}"
    session_id = payload.get("session_id") or f"ses_{uuid4().hex[:12]}"
    routing_intent = payload.get("routing_intent") or SCENARIO_INTENTS.get(scenario, "general")
    fixture.update(
        {
            "message_id": message_id,
            "session_id": session_id,
            "mock_scenario": scenario,
            "routing_intent": routing_intent,
            "status": fixture["progress"]["status"],
            "created_at": _now_iso(),
            "attachments": deepcopy(payload.get("attachments", [])),
            "blocked_attachments": deepcopy(payload.get("blocked_attachments", [])),
            "attachment_scan_policy": deepcopy(payload.get("attachment_scan_policy", {})),
            "attachment_resolution": deepcopy(payload.get("attachment_resolution", {})),
            "analysis_plan": build_analysis_plan(
                scenario=scenario,
                requested_status=requested_status,
                payload=payload,
                session_id=session_id,
                message_id=message_id,
                routing_intent=routing_intent,
                pending_questions=fixture.get("pending_questions", []),
                supervisor_state=fixture.get("supervisor_state") or supervisor_state,
                persona_run=persona_run,
            ),
        }
    )
    return fixture


def _general_consultation_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Answer an eligibility/procedure question before any report work is requested."""
    session_id = payload.get("session_id") or f"ses_{uuid4().hex[:12]}"
    return {
        "message_id": f"msg_{uuid4().hex[:12]}",
        "session_id": session_id,
        "mock_scenario": "general_consultation",
        "routing_intent": "general_consultation",
        "status": "success",
        "created_at": _now_iso(),
        "assistant_message": (
            "지금 단계에서는 리포트를 만들기보다 이의신청 대상 여부와 절차부터 확인하는 게 맞습니다. "
            "말씀하신 자녀의 고열과 응급실 방문 사정은 부득이한 정차 사유로 검토될 수 있지만, "
            "현재 정보만으로 이의신청 가능 여부를 확정할 수는 없습니다.\n\n"
            "먼저 고지서의 발행기관과 제출 기한, 정차 시각·장소를 확인하고, "
            "응급실 진료기록·영수증·방문 시각 자료와 당시 정차가 불가피했다는 설명을 준비하세요. "
            "일반적으로는 고지서에 적힌 관할 기관의 의견제출 또는 이의신청 창구에 사건번호, 사유, 증빙을 함께 제출합니다. "
            "기한을 놓치지 않는 것이 가장 먼저입니다.\n\n"
            "원하시면 다음 메시지에서 고지서 발행기관, 제출 기한, 정차 시각, 응급실 방문 증빙 유무만 확인한 뒤 "
            "이의신청 대상 여부와 실제 제출 순서를 이어서 안내하겠습니다."
        ),
        "progress": {
            "status": "success",
            "active_node": "general_consultation",
            "message": "이의신청 대상 여부와 제출 방법을 일반 상담으로 안내했습니다.",
        },
        "case_status": "guidance_only",
        "cards": [],
        "report_links": [],
        "pending_questions": [],
        "reporting_payload": None,
        "supervisor_state": None,
        "structured_result": {
            "consultation_mode": "general_guidance",
            "report_ready": False,
            "next_step": "collect_notice_deadline_and_evidence",
        },
        "limitations": [
            "일반 상담 안내이며 실제 처분 취소나 이의신청 인용을 보장하지 않습니다.",
            "고지서 발행기관과 제출 기한을 확인한 뒤 구체적인 절차를 이어서 안내해야 합니다.",
        ],
        "attachments": deepcopy(payload.get("attachments", [])),
        "blocked_attachments": deepcopy(payload.get("blocked_attachments", [])),
        "attachment_scan_policy": deepcopy(payload.get("attachment_scan_policy", {})),
        "attachment_resolution": deepcopy(payload.get("attachment_resolution", {})),
    }


def _persona_run_for_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    persona_id = str(payload.get("persona_id") or "").strip()
    user_text = str(payload.get("user_text") or "")
    wants_persona = persona_id in demo_persona_ids() or any(
        keyword in user_text for keyword in ("페르소나", "데모", "샘플 상담", "끝까지 진행")
    )
    if not wants_persona:
        return None

    persona_run = get_demo_persona(persona_id) or default_demo_persona()
    persona_run["requested_by"] = {
        "user_text": user_text,
        "persona_id": persona_id or DEMO_PERSONA_ID,
    }
    return persona_run


def _apply_persona_run(fixture: dict[str, Any], persona_run: dict[str, Any]) -> None:
    persona = persona_run["persona"]
    snapshot = persona_run["case_snapshot"]
    fixture["assistant_message"] = (
        f"{persona['name']} 님 사례로 상담을 끝까지 시뮬레이션했습니다. "
        f"현재 단계는 {persona_run['progress_label']}"
    )
    fixture["case_status"] = f"persona_{persona_run['stage']}"
    fixture["persona_run"] = persona_run
    fixture["supervisor_state"] = _persona_supervisor_state(persona_run)
    fixture["reporting_payload"] = _persona_reporting_payload(persona_run)
    fixture.setdefault("structured_result", {})
    fixture["structured_result"].update(
        {
            "persona_id": persona["persona_id"],
            "persona_name": persona["name"],
            "case_type": persona["case_type"],
            "notice_type": snapshot.get("notice_type"),
            "scenario": persona_run["scenario"],
            "routing_intent": persona_run["routing_intent"],
            "expected_nodes": deepcopy(persona_run["expected_nodes"]),
            "report_action_ready": bool(persona_run.get("report_action_ready")),
            "case_snapshot": deepcopy(snapshot),
        }
    )
    fixture["cards"] = deepcopy(persona_run["cards"]) + fixture.get("cards", [])
    fixture["pending_questions"] = deepcopy(persona_run.get("pending_questions", []))
    if not persona_run.get("report_action_ready"):
        fixture["report_links"] = []
    fixture.setdefault("limitations", [])
    fixture["limitations"].append(
        "페르소나 상담은 실제 Agent 실행 전 화면/대화 흐름 검증용 시뮬레이션입니다."
    )


def _persona_supervisor_state(persona_run: dict[str, Any]) -> dict[str, Any]:
    snapshot = persona_run["case_snapshot"]
    packages = [
        _agent_input_package(
            node_code,
            _owner_for_persona_node(node_code),
            {
                "persona_id": persona_run["persona"]["persona_id"],
                "scenario": persona_run["scenario"],
                "case_snapshot": deepcopy(snapshot),
                "sample_user_text": persona_run["sample_user_text"],
            },
            [],
        )
        for node_code in persona_run["expected_nodes"]
    ]
    pending_questions = deepcopy(persona_run.get("pending_questions", []))
    return {
        "contract_version": "supervisor_conversation_state.v1",
        "scenario": persona_run["scenario"],
        "stage": persona_run["stage"],
        "conversation_turn_count": len(persona_run.get("turns", [])),
        "conversation_summary": persona_run["progress_label"],
        "collected_facts": _persona_collected_facts(snapshot),
        "missing_fields": [],
        "next_questions": pending_questions,
        "agent_input_packages": packages,
        "reporting_payload": _persona_reporting_payload(persona_run),
        "llm": {
            "status": "persona_fixture",
            "reason": "real_agents_not_connected",
            "provider": "mock_contract",
            "model": "persona_catalog",
        },
    }


def _persona_reporting_payload(persona_run: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "reporting_payload.v1",
        "scenario": persona_run["scenario"],
        "stage": persona_run["stage"],
        "title": f"{persona_run['persona']['case_type']} 리포트",
        "summary": persona_run["progress_label"],
        "sections": [
            {
                "title": "페르소나",
                "items": [
                    {
                        "field": "persona",
                        "label": persona_run["persona"]["name"],
                        "value": persona_run["persona"]["goal"],
                    }
                ],
            },
            {
                "title": "사건 스냅샷",
                "items": _persona_collected_facts(persona_run["case_snapshot"]),
            },
            {
                "title": "Agent 전달 입력",
                "items": [
                    {
                        "node_code": node_code,
                        "owner": _owner_for_persona_node(node_code),
                        "status": "ready",
                        "missing_fields": [],
                    }
                    for node_code in persona_run["expected_nodes"]
                ],
            },
        ],
    }


def _persona_collected_facts(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    labels = {
        "notice_type": "유형",
        "notice_amount": "금액",
        "notice_received_at": "고지 수령일",
        "incident_at": "일시",
        "location": "장소",
        "claimed_fact": "주장",
        "user_context": "사용자 맥락",
    }
    return [
        {"field": field, "label": labels.get(field, field), "value": str(value)}
        for field, value in snapshot.items()
        if value
    ]


def _owner_for_persona_node(node_code: str) -> str:
    return {
        "input_context_validation": "hi20260204-maker",
        "fine_notice_analysis": "workzion2",
        "law_ground_search": "techshin31",
        "objection_report_generation": "hi20260204-maker",
        "text_ml_case_search": "leejaegang27",
        "vision_media_analysis": "ohjuheecode",
        "agent_result_validation": "hi20260204-maker",
    }.get(node_code, "hi20260204-maker")


def _apply_supervisor_conversation_state(
    fixture: dict[str, Any],
    *,
    supervisor_state: dict[str, Any],
    scenario: str,
    requested_status: str,
    use_dynamic_sequence: bool,
) -> None:
    fixture["supervisor_state"] = supervisor_state
    expose_reporting_payload = _supervisor_report_ready(supervisor_state) or (
        requested_status == "success" and not use_dynamic_sequence
    )
    fixture["reporting_payload"] = supervisor_state["reporting_payload"] if expose_reporting_payload else None
    fixture.setdefault("structured_result", {})
    fixture["structured_result"].update(
        {
            "supervisor_stage": supervisor_state["stage"],
            "collected_facts": supervisor_state["collected_facts"],
            "missing_fields": supervisor_state["missing_fields"],
            "agent_input_packages": supervisor_state["agent_input_packages"],
        }
    )
    fixture["cards"] = _supervisor_cards(supervisor_state, scenario) + fixture.get("cards", [])

    if not use_dynamic_sequence:
        return

    if supervisor_state["stage"] == "need_more_input" and requested_status != "success":
        first_question = supervisor_state["next_questions"][0]["question"]
        fixture["assistant_message"] = (
            "지금까지 대화를 Supervisor가 Agent 입력 스키마 초안으로 정리했습니다. "
            f"다음 분석으로 넘기기 전에 확인이 필요합니다. {first_question}"
        )
        fixture["case_status"] = "needs_more_input"
        fixture["pending_questions"] = deepcopy(supervisor_state["next_questions"])
        fixture["report_links"] = []
        fixture["progress"] = {
            "status": "partial",
            "active_node": "missing_input_question",
            "message": "Supervisor가 부족 입력을 확인하고 역질문을 생성했습니다.",
        }
        return

    fixture["assistant_message"] = (
        "대화 내용을 Supervisor가 Agent 입력 스키마로 정리했고, "
        "각 Agent 결과 envelope를 리포팅 화면에 반영할 수 있는 형태로 병합했습니다."
    )
    fixture["case_status"] = "analysis_completed"
    fixture["pending_questions"] = deepcopy(supervisor_state["next_questions"])
    fixture["progress"] = {
        "status": fixture.get("progress", {}).get("status", "success"),
        "active_node": "final_response_merge",
        "message": "Supervisor handoff와 reporting payload가 준비되었습니다.",
    }


def _build_supervisor_conversation_state(
    payload: dict[str, Any],
    scenario: str,
) -> dict[str, Any]:
    turns = _conversation_turns(payload)
    conversation_text = _conversation_text_from_turns(turns)
    facts = _extract_supervisor_facts(conversation_text, payload, scenario)
    missing_fields = _missing_fields_for_conversation(scenario, facts)
    slot_state = _slot_state_for_facts(
        scenario=scenario,
        facts=facts,
        turns=turns,
        missing_fields=missing_fields,
    )
    next_questions = _next_questions_for_missing_fields(scenario, missing_fields)
    agent_input_packages = _agent_input_packages_for_scenario(
        scenario,
        facts=facts,
        payload=payload,
        missing_fields=missing_fields,
        slot_state=slot_state,
    )
    stage = "agent_execution_ready" if not missing_fields else "need_more_input"
    collected_facts = _collected_fact_items(facts, slot_state=slot_state)

    return {
        "contract_version": "supervisor_conversation.v1",
        "stage": stage,
        "conversation_turn_count": len(turns),
        "conversation_summary": _conversation_summary(conversation_text, scenario),
        "slot_state": slot_state,
        "collected_facts": collected_facts,
        "missing_fields": missing_fields,
        "next_questions": next_questions,
        "agent_input_packages": agent_input_packages,
        "reporting_payload": _reporting_payload(
            scenario=scenario,
            stage=stage,
            facts=facts,
            missing_fields=missing_fields,
            agent_input_packages=agent_input_packages,
            slot_state=slot_state,
        ),
    }


def _conversation_turns(payload: dict[str, Any]) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    raw_turns = payload.get("conversation_history")
    if isinstance(raw_turns, list):
        for item in raw_turns:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or item.get("message") or "").strip()
            if not content:
                continue
            role = str(item.get("role") or "user")
            turns.append({"role": role, "content": content})

    user_text = str(payload.get("user_text") or "").strip()
    if user_text and (not turns or turns[-1]["content"] != user_text):
        turns.append({"role": "user", "content": user_text})
    return turns


def _conversation_text(payload: dict[str, Any]) -> str:
    return _conversation_text_from_turns(_conversation_turns(payload))


def _conversation_text_from_turns(turns: list[dict[str, str]]) -> str:
    return "\n".join(turn["content"] for turn in turns if turn.get("content"))


def _extract_supervisor_facts(
    conversation_text: str,
    payload: dict[str, Any],
    scenario: str,
) -> dict[str, Any]:
    attachments = payload.get("attachments", [])
    facts: dict[str, Any] = {
        "scenario": scenario,
        "raw_conversation": conversation_text,
        "attachments": deepcopy(attachments),
        "attachment_count": len(attachments),
        "evidence_status": _evidence_status(conversation_text, attachments),
    }

    if scenario == "law_question":
        facts.update(
            {
                "law_query": _sentence_with_keywords(
                    conversation_text,
                    ("법령", "조문", "근거", "도로교통법", "시행령", "의견제출", "과태료"),
                ),
                "violation_text": _sentence_with_keywords(
                    conversation_text,
                    ("정차", "주차", "위반", "단속", "과태료", "범칙금", "사고"),
                ),
            }
        )
        return facts

    if scenario == "report_redownload":
        facts.update(
            {
                "report_request": _sentence_with_keywords(
                    conversation_text,
                    ("리포트", "보고서", "다운로드", "내려받", "저장", "내 사건"),
                ),
            }
        )
        return facts

    if scenario == "fault_ratio":
        facts.update(
            {
                "accident_context": _sentence_with_keywords(
                    conversation_text,
                    ("사고", "접촉", "충돌", "보험", "과실", "교차로", "차로"),
                ),
                "road_context": _sentence_with_keywords(
                    conversation_text,
                    ("교차로", "신호", "차로", "횡단보도", "주차장", "도로"),
                ),
                "movement_context": _sentence_with_keywords(
                    conversation_text,
                    ("직진", "좌회전", "우회전", "진입", "정차", "후진", "차선"),
                ),
            }
        )
        return facts

    facts.update(
        {
            "notice_or_disposition": _sentence_with_keywords(
                conversation_text,
                ("고지서", "과태료", "범칙금", "통지서", "납부", "위반"),
            ),
            "notice_amount": _extract_amount(conversation_text),
            "incident_at": _extract_datetime_hint(conversation_text),
            "location": _sentence_with_keywords(
                conversation_text,
                ("학교", "보호구역", "도로", "앞", "교차로", "차로", "구역"),
            ),
            "user_facts": _sentence_with_keywords(
                conversation_text,
                ("때문", "갑자기", "비상", "정차", "구토", "아파", "억울", "사유"),
            ),
        }
    )
    return facts


def _missing_fields_for_conversation(
    scenario: str,
    facts: dict[str, Any],
) -> list[dict[str, str]]:
    if scenario == "law_question":
        checks = [
            ("law_query", "법령 질문"),
        ]
    elif scenario == "report_redownload":
        checks = [
            ("report_request", "리포트 재다운로드 요청"),
        ]
    elif scenario == "fault_ratio":
        checks = [
            ("accident_context", "사고 상황"),
            ("movement_context", "각 차량 진행 방향"),
            ("evidence_status", "블랙박스·사진·보험 접수 등 증빙 보유 여부"),
        ]
    else:
        checks = [
            ("notice_or_disposition", "고지서 또는 처분 내용"),
            ("user_facts", "이의제기 사유와 당시 상황"),
            ("evidence_status", "고지서·블랙박스·영수증 등 증빙 보유 여부"),
        ]

    return [
        {"field": field, "label": label}
        for field, label in checks
        if not facts.get(field)
    ]


def _next_questions_for_missing_fields(
    scenario: str,
    missing_fields: list[dict[str, str]],
) -> list[dict[str, str]]:
    fine_questions = {
        "notice_or_disposition": "고지서에 적힌 위반 일시, 장소, 금액 또는 처분명을 알려 주세요.",
        "user_facts": "이의제기를 하고 싶은 이유와 당시 상황을 한두 문장으로 알려 주세요.",
        "evidence_status": "고지서 사진, 블랙박스, 영수증, 통화기록처럼 갖고 있는 자료가 있나요?",
    }
    fault_questions = {
        "accident_context": "사고 장소와 어떤 상황에서 부딪혔는지 먼저 설명해 주세요.",
        "movement_context": "내 차와 상대 차가 각각 직진, 좌회전, 진입, 정차 중 무엇을 하고 있었나요?",
        "evidence_status": "블랙박스 원본, 현장 사진, 보험사 접수 내역 중 보유한 자료가 있나요?",
    }
    law_questions = {
        "law_query": "확인하려는 법령 근거나 위반 내용을 한 문장으로 알려 주세요.",
    }
    report_questions = {
        "report_request": "다시 내려받을 리포트나 사건을 식별할 수 있는 정보를 알려 주세요.",
    }
    if scenario == "fault_ratio":
        question_map = fault_questions
    elif scenario == "law_question":
        question_map = law_questions
    elif scenario == "report_redownload":
        question_map = report_questions
    else:
        question_map = fine_questions
    return [
        {
            "field": item["field"],
            "question": question_map.get(item["field"], f"{item['label']} 정보를 보완해 주세요."),
        }
        for item in missing_fields
    ]


def _agent_input_packages_for_scenario(
    scenario: str,
    *,
    facts: dict[str, Any],
    payload: dict[str, Any],
    missing_fields: list[dict[str, str]],
    slot_state: dict[str, Any],
) -> list[dict[str, Any]]:
    missing_codes = {item["field"] for item in missing_fields}
    common_payload = {
        "conversation_summary": _conversation_summary(facts.get("raw_conversation", ""), scenario),
        "collected_facts": _compact_facts(facts),
        "slot_state": deepcopy(slot_state),
        "slot_contract_version": slot_state.get("contract_version"),
        "attachments": deepcopy(payload.get("attachments", [])),
        "blocked_attachments": deepcopy(payload.get("blocked_attachments", [])),
        "attachment_scan_policy": deepcopy(payload.get("attachment_scan_policy", {})),
        "raw_user_text": payload.get("user_text"),
    }

    if scenario == "law_question":
        return [
            _agent_input_package(
                "input_context_validation",
                "hi20260204-maker",
                common_payload,
                [],
            ),
            _agent_input_package(
                "law_ground_search",
                "techshin31",
                {
                    **common_payload,
                    "search_query": facts.get("law_query"),
                    "violation_text": facts.get("violation_text") or facts.get("law_query"),
                },
                ["law_query"] if "law_query" in missing_codes else [],
            ),
            _agent_input_package(
                "agent_result_validation",
                "hi20260204-maker",
                {**common_payload, "expected_agent_results": ["law_ground_search"]},
                [],
            ),
        ]

    if scenario == "report_redownload":
        return [
            _agent_input_package(
                "input_context_validation",
                "hi20260204-maker",
                common_payload,
                [],
            ),
            _agent_input_package(
                "agent_result_validation",
                "hi20260204-maker",
                {
                    **common_payload,
                    "expected_agent_results": [],
                    "report_request": facts.get("report_request"),
                },
                ["report_request"] if "report_request" in missing_codes else [],
            ),
        ]

    if scenario == "fault_ratio":
        return [
            _agent_input_package(
                "input_context_validation",
                "hi20260204-maker",
                common_payload,
                [],
            ),
            _agent_input_package(
                "text_ml_case_search",
                "leejaegang27",
                {
                    **common_payload,
                    "query_text": facts.get("raw_conversation"),
                    "accident_context": facts.get("accident_context"),
                    "road_context": facts.get("road_context"),
                    "movement_context": facts.get("movement_context"),
                    "evidence_status": facts.get("evidence_status"),
                },
                [field for field in ("accident_context", "movement_context") if field in missing_codes],
            ),
            _agent_input_package(
                "law_ground_search",
                "techshin31",
                {
                    **common_payload,
                    "search_query": "교통사고 과실비율 판단 기준",
                    "violation_text": facts.get("accident_context"),
                },
                ["accident_context"] if "accident_context" in missing_codes else [],
            ),
            _agent_input_package(
                "objection_report_generation",
                "hi20260204-maker",
                {
                    **common_payload,
                    "draft_goal": "교통사고 이의신청서 초안",
                    "text_ml_case_result_ref": "text_ml_case_search",
                    "law_ground_result_ref": "law_ground_search",
                    "user_facts": _fault_ratio_user_facts(facts),
                    "evidence_status": facts.get("evidence_status"),
                },
                [
                    field
                    for field in ("accident_context", "movement_context", "evidence_status")
                    if field in missing_codes
                ],
            ),
            _agent_input_package(
                "agent_result_validation",
                "hi20260204-maker",
                {
                    **common_payload,
                    "expected_agent_results": [
                        "text_ml_case_search",
                        "law_ground_search",
                        "objection_report_generation",
                    ],
                },
                [],
            ),
        ]

    return [
        _agent_input_package(
            "input_context_validation",
            "hi20260204-maker",
            common_payload,
            [],
        ),
        _agent_input_package(
            "fine_notice_analysis",
            "workzion2",
            {
                **common_payload,
                "notice_text": facts.get("notice_or_disposition"),
                "notice_amount": facts.get("notice_amount"),
                "incident_at": facts.get("incident_at"),
                "location": facts.get("location"),
                "user_facts": facts.get("user_facts"),
                "evidence_status": facts.get("evidence_status"),
            },
            [field for field in ("notice_or_disposition", "evidence_status") if field in missing_codes],
        ),
        _agent_input_package(
            "law_ground_search",
            "techshin31",
            {
                **common_payload,
                "search_query": _law_search_query_for_fine_notice(facts),
                "violation_text": facts.get("notice_or_disposition"),
                "location_context": facts.get("location"),
            },
            ["notice_or_disposition"] if "notice_or_disposition" in missing_codes else [],
        ),
        _agent_input_package(
            "objection_report_generation",
            "hi20260204-maker",
            {
                **common_payload,
                "draft_goal": "의견제출서 또는 이의신청서 초안",
                "notice_analysis_result_ref": "fine_notice_analysis",
                "law_ground_result_ref": "law_ground_search",
                "user_facts": facts.get("user_facts"),
                "evidence_status": facts.get("evidence_status"),
            },
            [field for field in ("user_facts", "evidence_status") if field in missing_codes],
        ),
        _agent_input_package(
            "agent_result_validation",
            "hi20260204-maker",
            {
                **common_payload,
                "expected_agent_results": [
                    "fine_notice_analysis",
                    "law_ground_search",
                    "objection_report_generation",
                ],
            },
            [],
        ),
    ]


def _agent_input_package(
    node_code: str,
    owner: str,
    payload: dict[str, Any],
    missing_fields: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "agent_input_schema.v1",
        "node_code": node_code,
        "owner": owner,
        "status": "waiting_for_fields" if missing_fields else "ready",
        "missing_fields": missing_fields,
        "payload": payload,
    }


def _reporting_payload(
    *,
    scenario: str,
    stage: str,
    facts: dict[str, Any],
    missing_fields: list[dict[str, str]],
    agent_input_packages: list[dict[str, Any]],
    slot_state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract_version": "reporting_payload.v1",
        "scenario": scenario,
        "report_type": _report_type_for_scenario(scenario),
        "screen_id": _report_screen_id_for_scenario(scenario),
        "stage": stage,
        "title": _report_title_for_scenario(scenario),
        "summary": _conversation_summary(facts.get("raw_conversation", ""), scenario),
        "quality": _report_quality(stage=stage, missing_fields=missing_fields),
        "sections": _report_sections(
            scenario=scenario,
            facts=facts,
            missing_fields=missing_fields,
            agent_input_packages=agent_input_packages,
            slot_state=slot_state,
        ),
    }


def _report_type_for_scenario(scenario: str) -> str:
    if scenario == "fine_notice":
        return "fine_notice_objection"
    if scenario == "fault_ratio":
        return "fault_ratio_analysis"
    return "generic_supervisor"


def _report_screen_id_for_scenario(scenario: str) -> str:
    if scenario == "fine_notice":
        return "UI-REPORT-FINE-001"
    if scenario == "fault_ratio":
        return "UI-REPORT-FAULT-001"
    return "UI-REPORT-GENERIC-001"


def _report_quality(
    *,
    stage: str,
    missing_fields: list[dict[str, str]],
) -> dict[str, Any]:
    partial_report = bool(missing_fields) or stage not in {"agent_execution_ready", "success"}
    return {
        "partial_report": partial_report,
        "review_required": True,
        "confidence_label": "추가 자료 필요" if partial_report else "검토 가능",
    }


def _report_title_for_scenario(scenario: str) -> str:
    if scenario == "fine_notice":
        return "과태료·범칙금 대응 리포트"
    if scenario == "fault_ratio":
        return "사고 과실비율 분석 리포트"
    if scenario == "law_question":
        return "교통 법령 근거 리포트"
    return "Supervisor 상담 분석 리포트"


def _report_sections(
    *,
    scenario: str,
    facts: dict[str, Any],
    missing_fields: list[dict[str, str]],
    agent_input_packages: list[dict[str, Any]],
    slot_state: dict[str, Any],
) -> list[dict[str, Any]]:
    if scenario == "fine_notice":
        return _fine_notice_report_sections(
            facts=facts,
            missing_fields=missing_fields,
            agent_input_packages=agent_input_packages,
            slot_state=slot_state,
        )
    if scenario == "fault_ratio":
        return _fault_ratio_report_sections(
            facts=facts,
            missing_fields=missing_fields,
            agent_input_packages=agent_input_packages,
            slot_state=slot_state,
        )
    return _generic_report_sections(
        facts=facts,
        missing_fields=missing_fields,
        agent_input_packages=agent_input_packages,
        slot_state=slot_state,
    )


def _generic_report_sections(
    *,
    facts: dict[str, Any],
    missing_fields: list[dict[str, str]],
    agent_input_packages: list[dict[str, Any]],
    slot_state: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "title": "수집된 사실관계",
            "items": _collected_fact_items(facts, slot_state=slot_state),
        },
        {
            "title": "Slot filling 상태",
            "items": _slot_state_items(slot_state),
        },
        {
            "title": "역질문 필요 항목",
            "items": missing_fields,
        },
        {
            "title": "Agent 전달 입력",
            "items": [
                {
                    "node_code": package["node_code"],
                    "owner": package["owner"],
                    "status": package["status"],
                    "missing_fields": package["missing_fields"],
                }
                for package in agent_input_packages
            ],
        },
    ]


def _fault_ratio_report_sections(
    *,
    facts: dict[str, Any],
    missing_fields: list[dict[str, str]],
    agent_input_packages: list[dict[str, Any]],
    slot_state: dict[str, Any],
) -> list[dict[str, Any]]:
    _ = slot_state
    accident_context = (
        facts.get("accident_context")
        or facts.get("raw_conversation")
        or "사고 일시, 장소, 진행 방향 확인 필요"
    )
    road_context = facts.get("road_context") or "신호, 차선, 도로 구조 확인 필요"
    movement_context = facts.get("movement_context") or "차량 A/B 진행 방향과 충돌 지점 확인 필요"
    evidence = facts.get("evidence_status") or "블랙박스, 현장 사진, 보험 접수 자료 확인 필요"
    missing_labels = [item["label"] for item in missing_fields if item.get("label")]
    missing_text = ", ".join(missing_labels) if missing_labels else "핵심 입력은 1차 충족"
    ready_nodes = [
        package["node_code"]
        for package in agent_input_packages
        if package.get("status") == "ready"
    ]
    text_ml_package = next(
        (
            package
            for package in agent_input_packages
            if package.get("node_code") == "text_ml_case_search"
        ),
        {},
    )
    text_ml_status = text_ml_package.get("status") or "waiting_for_fields"

    return [
        {
            "title": "사고 개요",
            "items": [
                _report_item("사고 상황", accident_context, "accident_context"),
                _report_item("도로/신호 맥락", road_context, "road_context"),
                _report_item("차량 진행 방향", movement_context, "movement_context"),
                _report_item("보완 필요", missing_text),
            ],
        },
        {
            "title": "제출 자료",
            "items": [
                _report_item("현재 자료", evidence, "evidence_status"),
                _report_item("권장 자료", "블랙박스 원본, 현장 사진, 보험 접수 내역, 상대 차량 진술"),
                _report_item("자료 상태", "자료가 부족하면 partial_report로 표시하고 추가 제출 항목을 먼저 안내"),
            ],
        },
        {
            "title": "AI 분석 결과",
            "items": [
                _report_item("예상 과실비율 후보", "확정 수치가 아닌 예상 범위와 쟁점으로만 표시"),
                _report_item("책임 방향", "신호, 일시정지, 진로 변경, 시야 제한 여부를 기준으로 검토"),
                _report_item("주의 문구", "본 결과는 법적 확정 판단이 아니라 상담용 분석 초안"),
            ],
        },
        {
            "title": "판단 근거",
            "items": [
                _report_item("Agent 상태", text_ml_status),
                _report_item("준비된 노드", ", ".join(ready_nodes) or "Agent 입력 대기"),
                _report_item("적용 한계", "유사 사례와 보험 기준은 참고 근거이며 실제 판단과 다를 수 있음"),
            ],
        },
        {
            "title": "핵심 쟁점",
            "items": [
                _report_item("신호/우선권", "신호 유무, 선진입, 우선 통행권 확인"),
                _report_item("차선/진로", "차선 변경, 교차로 진입 방향, 충돌 위치 확인"),
                _report_item("속도/회피 가능성", "감속, 제동, 시야 제한, 회피 가능성 확인"),
                _report_item("증거 부족 지점", missing_text),
            ],
        },
        {
            "title": "유사 사례·판례",
            "items": [
                _report_item("유사 사례 후보", "text_ml_case_search 결과와 RAG 근거를 연결해 표시"),
                _report_item("표시 원칙", "유사 사례는 참고 근거로만 표시하고 법적 확정 판단처럼 표현하지 않음"),
                _report_item("검증 필요", "최신 판례, 보험 기준, 사실관계 차이는 별도 확인 필요"),
            ],
        },
        {
            "title": "후속 조치",
            "items": [
                _report_item("추가 자료 요청", "블랙박스 원본, 사고 직후 사진, 보험사 접수 내역을 보완"),
                _report_item("리포트 활용", "보험사 상담 또는 이의 제기 전 사실관계 검토용으로 사용"),
                _report_item("다운로드 조건", "저장된 리포트 payload에 본 섹션들이 포함된 상태로 다운로드"),
            ],
        },
    ]


def _fine_notice_report_sections(
    *,
    facts: dict[str, Any],
    missing_fields: list[dict[str, str]],
    agent_input_packages: list[dict[str, Any]],
    slot_state: dict[str, Any],
) -> list[dict[str, Any]]:
    notice_text = facts.get("notice_or_disposition") or "고지서 원본 OCR 또는 처분 문구 확인 필요"
    amount = facts.get("notice_amount") or "금액 OCR/고지서 확인 필요"
    incident_at = facts.get("incident_at") or "위반 일시 확인 필요"
    location = facts.get("location") or "위반 장소 확인 필요"
    user_facts = facts.get("user_facts") or "이의제기 사유와 당시 상황 보완 필요"
    evidence = facts.get("evidence_status") or "고지서 원본, 현장 사진, 블랙박스 등 증빙 확인 필요"
    missing_labels = [item["label"] for item in missing_fields if item.get("label")]
    objection_status = "검토 가능" if not missing_labels else "추가 자료 필요"
    missing_text = ", ".join(missing_labels) if missing_labels else "필수 입력은 충족된 상태"
    ready_nodes = [
        package["node_code"]
        for package in agent_input_packages
        if package.get("status") == "ready"
    ]

    return [
        {
            "title": "고지서 OCR 결과",
            "items": [
                _report_item("처분 내용", notice_text, "notice_or_disposition"),
                _report_item("위반 일시", incident_at, "incident_at"),
                _report_item("위반 장소", location, "location"),
                _report_item("고지 금액", amount, "notice_amount"),
            ],
        },
        {
            "title": "처분 결과",
            "items": [
                _report_item("처분 유형", "과태료·범칙금 고지서 분석 흐름"),
                _report_item("현재 상태", "의견제출 또는 이의신청 검토 단계"),
                _report_item("의견제출 기한", "고지서 납부·의견제출 기한을 원본에서 재확인 필요"),
            ],
        },
        {
            "title": "이의제기 가능성",
            "items": [
                _report_item("판단", objection_status),
                _report_item("주요 사유", user_facts, "user_facts"),
                _report_item("보완 필요", missing_text),
            ],
        },
        {
            "title": "필요 증거",
            "items": [
                _report_item("현재 증빙", evidence, "evidence_status"),
                _report_item("현장 자료", "표지판, 노면 표시, 차량 위치, 정차 시간이 함께 보이는 사진"),
                _report_item("운전자 진술", "정차 사유, 정차 시간, 긴급성 또는 불가피성을 시간 순서로 정리"),
                _report_item("고지서 원본", "처분 기관, 고지 번호, 금액, 기한이 보이는 원본"),
            ],
        },
        {
            "title": "관련 법령·판례 근거",
            "items": [
                _report_item("검색 쿼리", _law_search_query_for_fine_notice(facts)),
                _report_item("적용 한계", "실제 법령·판례 RAG 결과 연결 전에는 최신성 확인이 필요"),
                _report_item("Agent 상태", ", ".join(ready_nodes) or "Agent 입력 대기"),
            ],
        },
        {
            "title": "예상 결과와 유의사항",
            "items": [
                _report_item("수용 가능성", "입증 자료가 충분하면 처분 전 의견제출 또는 감경 검토 가능"),
                _report_item("기각 리스크", "표지·위반 사실이 명확하거나 긴급성이 부족하면 기각될 수 있음"),
                _report_item("주의", "확정 판단이 아니라 제출 전 검토용 분석입니다."),
            ],
        },
        {
            "title": "이의신청서 초안",
            "items": [
                _report_item("제목", "과태료 부과 처분 의견제출서 또는 이의신청서 초안"),
                _report_item("제출 대상", "고지서에 표시된 처분 기관"),
                _report_item("사실관계", f"{incident_at} {location}에서 {user_facts}"),
                _report_item("신청 취지", "고지 내용과 실제 정차 사유를 재확인해 처분 취소 또는 감경을 요청합니다."),
                _report_item("첨부 자료", evidence),
                _report_item("검토 안내", "본 문서는 제출 전 사용자가 사실관계와 관할 기관 요구 양식을 확인해야 하는 초안입니다."),
            ],
        },
        {
            "title": "제출 가이드라인",
            "items": [
                _report_item("1단계", "고지서 원본의 기관, 기한, 고지 번호를 확인합니다."),
                _report_item("2단계", "현장 사진과 블랙박스 원본 등 첨부 자료명을 초안에 맞춥니다."),
                _report_item("3단계", "주장 문구는 감정 표현보다 시간, 장소, 사유 중심으로 정리합니다."),
                _report_item("4단계", "제출 전 관할 기관 양식과 접수 방법을 다시 확인합니다."),
            ],
        },
    ]


def _report_item(label: str, value: Any, field: str | None = None) -> dict[str, Any]:
    item = {
        "label": label,
        "value": value,
    }
    if field:
        item["field"] = field
    return item


def _supervisor_cards(
    supervisor_state: dict[str, Any],
    scenario: str,
) -> list[dict[str, Any]]:
    ready_count = sum(
        1 for item in supervisor_state["agent_input_packages"] if item["status"] == "ready"
    )
    total_count = len(supervisor_state["agent_input_packages"])
    cards = [
        {
            "card_type": "supervisor_summary",
            "title": "Supervisor 대화 분석",
            "status": "success" if supervisor_state["stage"] == "agent_execution_ready" else "partial",
            "summary": supervisor_state["conversation_summary"],
            "evidence_refs": [],
        },
        {
            "card_type": "agent_input_schema",
            "title": "Agent 입력 스키마",
            "status": "success" if ready_count == total_count else "partial",
            "summary": f"{total_count}개 노드 중 {ready_count}개 입력 패키지가 바로 실행 가능한 상태입니다.",
            "evidence_refs": [],
        },
    ]
    if _supervisor_report_ready(supervisor_state):
        cards.append({
            "card_type": "reporting_preview",
            "title": "프론트 리포팅 반영",
            "status": "success" if not supervisor_state["missing_fields"] else "partial",
            "summary": (
                "리포팅 화면에 Supervisor 요약, Agent 입력, 결과 상태를 표시할 payload를 생성했습니다."
                if scenario
                else "리포팅 payload를 생성했습니다."
            ),
            "evidence_refs": [],
        })
    return cards


def _supervisor_report_ready(supervisor_state: dict[str, Any]) -> bool:
    return (
        supervisor_state.get("stage") == "agent_execution_ready"
        and not supervisor_state.get("missing_fields")
        and not supervisor_state.get("next_questions")
    )


def build_analysis_plan(
    *,
    scenario: str,
    requested_status: str,
    payload: dict[str, Any],
    session_id: str,
    message_id: str,
    routing_intent: str,
    pending_questions: list[dict[str, Any]],
    supervisor_state: dict[str, Any] | None = None,
    persona_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the Supervisor call plan that precedes mock Agent execution."""

    steps = (
        _plan_steps_for_persona(persona_run, requested_status)
        if persona_run
        else _plan_steps_for_scenario(scenario, requested_status)
    )
    blocked_reason = _plan_blocked_reason(requested_status, pending_questions)
    supervisor_state = supervisor_state or {}
    missing_fields = deepcopy(supervisor_state.get("missing_fields", []))
    agent_input_packages = deepcopy(supervisor_state.get("agent_input_packages", []))
    fallback_plan = {
        "plan_id": f"plan_{uuid4().hex[:12]}",
        "session_id": session_id,
        "message_id": message_id,
        "routing_intent": routing_intent,
        "input_summary": {
            "has_user_command": bool(payload.get("user_text")),
            "modalities": _input_modalities(payload),
            "attachment_purposes": _attachment_purposes(payload),
            "conversation_turn_count": supervisor_state.get("conversation_turn_count", 0),
            "collected_fact_count": len(supervisor_state.get("collected_facts", [])),
            "missing_fields": missing_fields,
        },
        "required_inputs": _required_inputs_for_scenario(scenario),
        "persona_id": persona_run["persona"]["persona_id"] if persona_run else None,
        "pending_questions": deepcopy(pending_questions),
        "agent_input_packages": agent_input_packages,
        "steps": steps,
        "blocked_reason": blocked_reason,
        "limitations": [
            "중간발표용 mock analysis_plan이며 실제 LangGraph 실행 계획은 아닙니다."
        ],
    }
    return build_analysis_plan_with_optional_llm(
        payload=payload,
        scenario=scenario,
        requested_status=requested_status,
        fallback_plan=fallback_plan,
        supervisor_state=supervisor_state,
    )


def perform_report_action(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "save").lower()
    if action == "download":
        status = "downloaded"
    elif action in {"preview", "prepare"}:
        status = "preview_ready"
    else:
        status = "report_saved"
    report_id = payload.get("report_id") or f"rep_{uuid4().hex[:12]}"
    return {
        "report_id": report_id,
        "case_id": payload.get("case_id") or f"case_{uuid4().hex[:12]}",
        "status": status,
        "download_url": f"/api/mock/reports/{report_id}/download" if action == "download" else None,
        "created_at": _now_iso(),
        "limitations": ["mock report action 결과입니다."],
    }


def _infer_status(
    payload: dict[str, Any],
    *,
    scenario: str | None = None,
    supervisor_state: dict[str, Any] | None = None,
) -> str:
    if not payload.get("user_text") and not payload.get("attachments") and not payload.get("conversation_history"):
        return "failed"
    if payload.get("needs_more_input"):
        return "partial"
    if supervisor_state and supervisor_state.get("missing_fields"):
        return "partial"
    return "success"


def _infer_scenario(payload: dict[str, Any]) -> str:
    text = _conversation_text(payload)
    if "리포트" in text or "다운로드" in text or "내려받" in text or "내 사건" in text:
        return "report_redownload"
    if _is_general_guidance_request(text):
        return "general_consultation"
    if (
        "과실비율" in text
        or "과실" in text
        or "판례" in text
        or "유사 사례" in text
        or "유사사례" in text
        or "심의사례" in text
        or "사고" in text
        or "접촉" in text
        or "충돌" in text
    ):
        return "fault_ratio"
    if "법령" in text or "조문" in text or "근거" in text or "도로교통법" in text:
        return "law_question"
    if "고지서" in text or "과태료" in text or "범칙금" in text or "이의" in text:
        return "fine_notice"
    return "fine_notice"


def _is_general_guidance_request(text: str) -> bool:
    normalized = str(text or "").replace(" ", "")
    if not ("이의신청" in normalized or "의견제출" in normalized or "이의" in normalized):
        return False
    guidance_markers = (
        "가능한지",
        "가능사항",
        "대상인지",
        "해당하는지",
        "할수있는지",
        "어떻게이의신청",
        "이의신청방법",
        "제출방법",
        "절차",
        "문의",
        "모르겠",
    )
    report_markers = (
        "리포트",
        "보고서",
        "초안작성",
        "작성해줘",
        "제출서작성",
        "다운로드",
        "정리해줘",
    )
    return any(marker in normalized for marker in guidance_markers) and not any(
        marker in normalized for marker in report_markers
    )


def _slot_labels() -> dict[str, str]:
    return {
        "notice_or_disposition": "고지/처분 내용",
        "notice_amount": "금액",
        "incident_at": "일시",
        "location": "장소",
        "user_facts": "사용자 주장",
        "accident_context": "사고 상황",
        "road_context": "도로/신호 맥락",
        "movement_context": "차량 진행 방향",
        "evidence_status": "증빙 보유 여부",
        "law_query": "법령 질문",
        "violation_text": "위반/사건 내용",
        "report_request": "리포트 요청",
    }


def _collected_fact_items(
    facts: dict[str, Any],
    *,
    slot_state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    labels = _slot_labels()
    slots = slot_state.get("slots", {}) if isinstance(slot_state, dict) else {}
    items = []
    for field, label in labels.items():
        value = facts.get(field)
        if value:
            item: dict[str, Any] = {"field": field, "label": label, "value": str(value)}
            slot = slots.get(field) if isinstance(slots, dict) else None
            if isinstance(slot, dict):
                item["confidence"] = slot.get("confidence")
                item["source"] = slot.get("source")
                item["editable"] = slot.get("editable")
            items.append(item)
    if facts.get("attachment_count"):
        items.append(
            {
                "field": "attachment_count",
                "label": "첨부 수",
                "value": str(facts["attachment_count"]),
            }
        )
    return items


def _slot_state_for_facts(
    *,
    scenario: str,
    facts: dict[str, Any],
    turns: list[dict[str, str]],
    missing_fields: list[dict[str, str]],
) -> dict[str, Any]:
    missing_codes = {item["field"] for item in missing_fields}
    labels = _slot_labels()
    slots: dict[str, dict[str, Any]] = {}

    for field in _slot_fields_for_scenario(scenario):
        value = facts.get(field) or ""
        source = _slot_source_for_field(field, value, facts, turns)
        filled = bool(value) and field not in missing_codes
        slots[field] = {
            "field": field,
            "label": labels.get(field, field),
            "value": value or None,
            "status": "filled" if filled else "missing",
            "required": field in _required_slot_fields_for_scenario(scenario),
            "confidence": _slot_confidence(value, source),
            "source": source,
            "editable": True,
            "update_policy": "latest_user_turn_overrides_previous_value",
        }

    return {
        "contract_version": "slot_filling_state.v1",
        "scenario": scenario,
        "turn_count": len(turns),
        "filled_fields": [field for field, slot in slots.items() if slot["status"] == "filled"],
        "missing_fields": [field for field, slot in slots.items() if slot["status"] == "missing" and slot["required"]],
        "slots": slots,
        "policy": {
            "source_required": True,
            "confidence_required": True,
            "user_correction_supported": True,
            "attachments_joined_by_attachment_id": True,
        },
    }


def _slot_fields_for_scenario(scenario: str) -> list[str]:
    if scenario == "law_question":
        return ["law_query", "violation_text", "evidence_status"]
    if scenario == "report_redownload":
        return ["report_request", "evidence_status"]
    if scenario == "fault_ratio":
        return ["accident_context", "road_context", "movement_context", "evidence_status"]
    return [
        "notice_or_disposition",
        "notice_amount",
        "incident_at",
        "location",
        "user_facts",
        "evidence_status",
    ]


def _required_slot_fields_for_scenario(scenario: str) -> set[str]:
    if scenario == "law_question":
        return {"law_query"}
    if scenario == "report_redownload":
        return {"report_request"}
    if scenario == "fault_ratio":
        return {"accident_context", "movement_context", "evidence_status"}
    return {"notice_or_disposition", "user_facts", "evidence_status"}


def _slot_source_for_field(
    field: str,
    value: Any,
    facts: dict[str, Any],
    turns: list[dict[str, str]],
) -> dict[str, Any]:
    attachments = facts.get("attachments") if isinstance(facts.get("attachments"), list) else []
    if field == "evidence_status" and attachments:
        return {
            "type": "attachment",
            "attachment_ids": [
                str(item.get("attachment_id"))
                for item in attachments
                if isinstance(item, dict) and item.get("attachment_id")
            ],
        }

    value_text = str(value or "").strip()
    keywords = _slot_source_keywords(field, value_text)
    for index, turn in enumerate(turns):
        content = str(turn.get("content") or "")
        if not content:
            continue
        if value_text and value_text in content:
            return {
                "type": "conversation_turn",
                "turn_index": index,
                "role": turn.get("role") or "user",
                "text": content[:240],
            }
        if keywords and any(keyword and keyword in content for keyword in keywords):
            return {
                "type": "conversation_turn",
                "turn_index": index,
                "role": turn.get("role") or "user",
                "text": content[:240],
            }

    return {"type": "missing"}


def _slot_source_keywords(field: str, value_text: str) -> tuple[str, ...]:
    if field == "notice_amount":
        return ("만원", "원")
    if field == "incident_at":
        return ("월", "일", "오전", "오후", "시")
    if field == "evidence_status":
        return ("블랙박스", "사진", "영상", "영수증", "고지서", "통화기록", "보험", "접수")
    if value_text:
        return tuple(part for part in re.split(r"\s+", value_text) if len(part) >= 2)[:5]
    return ()


def _slot_confidence(value: Any, source: dict[str, Any]) -> float:
    if not value:
        return 0.0
    source_type = source.get("type")
    if source_type == "attachment":
        return 0.9
    if source_type == "conversation_turn":
        return 0.82
    return 0.68


def _slot_state_items(slot_state: dict[str, Any]) -> list[dict[str, Any]]:
    slots = slot_state.get("slots") if isinstance(slot_state, dict) else {}
    if not isinstance(slots, dict):
        return []
    return [
        {
            "field": field,
            "label": slot.get("label"),
            "status": slot.get("status"),
            "confidence": slot.get("confidence"),
            "source_type": (slot.get("source") or {}).get("type"),
            "editable": slot.get("editable"),
        }
        for field, slot in slots.items()
        if isinstance(slot, dict)
    ]


def _compact_facts(facts: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in facts.items()
        if key not in {"raw_conversation", "attachments"} and value
    }


def _conversation_summary(conversation_text: str, scenario: str) -> str:
    scenario_label = {
        "fault_ratio": "과실비율",
        "law_question": "법령 근거",
        "report_redownload": "리포트 재다운로드",
    }.get(scenario, "과태료/이의신청")
    cleaned = " ".join(conversation_text.split())
    if not cleaned:
        return f"{scenario_label} 상담 입력이 아직 부족합니다."
    return f"{scenario_label} 상담으로 분류했습니다. 핵심 입력: {cleaned[:160]}"


def _evidence_status(conversation_text: str, attachments: list[dict[str, Any]]) -> str:
    if attachments:
        return f"첨부 {len(attachments)}건"
    keywords = ("블랙박스", "사진", "영상", "영수증", "고지서", "통화기록", "보험", "접수")
    found = [keyword for keyword in keywords if keyword in conversation_text]
    return ", ".join(found)


def _sentence_with_keywords(conversation_text: str, keywords: tuple[str, ...]) -> str:
    if not conversation_text:
        return ""
    parts = re.split(r"(?<=[.!?。]|요|다)\s+|\n+", conversation_text)
    for part in parts:
        stripped = part.strip()
        if stripped and any(keyword in stripped for keyword in keywords):
            return stripped[:240]
    return ""


def _extract_amount(conversation_text: str) -> str:
    match = re.search(r"(\d{1,3}(?:,\d{3})*|\d+)\s*(만원|원)", conversation_text)
    if not match:
        return ""
    return f"{match.group(1)}{match.group(2)}"


def _extract_datetime_hint(conversation_text: str) -> str:
    patterns = [
        r"\d{4}[-./]\d{1,2}[-./]\d{1,2}(?:\s*\d{1,2}:\d{2})?",
        r"\d{1,2}월\s*\d{1,2}일(?:\s*(?:오전|오후)?\s*\d{1,2}시(?:\s*\d{1,2}분)?)?",
        r"(?:오전|오후)\s*\d{1,2}시(?:\s*\d{1,2}분)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, conversation_text)
        if match:
            return match.group(0)
    return ""


def _law_search_query_for_fine_notice(facts: dict[str, Any]) -> str:
    base = facts.get("notice_or_disposition") or "교통 과태료 의견제출 이의신청"
    location = facts.get("location")
    if location and "보호구역" in location:
        return f"{base} 어린이보호구역 정차 예외 긴급상황"
    return f"{base} 의견제출 근거"


def _fault_ratio_user_facts(facts: dict[str, Any]) -> str:
    def _normalize(value: Any) -> str:
        return str(value).strip() if value is not None else ""

    parts = [
        _normalize(facts.get("accident_context")),
        _normalize(facts.get("movement_context")),
        _normalize(facts.get("road_context")),
    ]
    merged = " / ".join(part for part in parts if part)
    if merged:
        return merged
    return _normalize(facts.get("raw_conversation"))


def _plan_steps_for_persona(persona_run: dict[str, Any], requested_status: str) -> list[dict[str, Any]]:
    expected_nodes = ["input_context_validation"] + [
        node_code
        for node_code in persona_run.get("expected_nodes", [])
        if node_code != "input_context_validation"
    ]
    steps = []
    previous_node: str | None = None
    for index, node_code in enumerate(expected_nodes, start=1):
        steps.append(
            _step(
                index,
                node_code,
                [previous_node] if previous_node else [],
                _persona_fallback_for_node(node_code),
            )
        )
        previous_node = node_code

    if requested_status == "failed":
        statuses = ["failed"] + ["skipped"] * (len(steps) - 1)
    elif requested_status in {"partial", "pending"}:
        statuses = ["success"] + ["partial"] + ["blocked"] * max(len(steps) - 2, 0)
    else:
        statuses = [
            "success"
            if step["node_code"] not in {"objection_report_generation", "law_ground_search", "vision_media_analysis"}
            else "partial"
            for step in steps
        ]
        if steps:
            statuses[-1] = "success"

    for step, status in zip(steps, statuses, strict=False):
        step["status"] = status
    return steps


def _persona_fallback_for_node(node_code: str) -> str:
    return {
        "vision_media_analysis": "mock_key_frame_or_scene_summary",
        "law_ground_search": "mock_legal_evidence_or_limitations",
        "objection_report_generation": "mock_report_draft_or_pending_questions",
        "text_ml_case_search": "mock_similar_case_search",
        "agent_result_validation": "limitations",
    }.get(node_code, "missing_input_question")


def _plan_steps_for_scenario(scenario: str, requested_status: str) -> list[dict[str, Any]]:
    if scenario == "law_question":
        base_steps = [
            _step(1, "input_context_validation", [], "missing_input_question"),
            _step(2, "law_ground_search", ["input_context_validation"], "semantic_search_or_limitations"),
            _step(3, "agent_result_validation", ["law_ground_search"], "limitations"),
        ]
    elif scenario == "report_redownload":
        base_steps = [
            _step(1, "input_context_validation", [], "missing_input_question"),
            _step(2, "agent_result_validation", ["input_context_validation"], "limitations"),
        ]
    elif scenario == "fault_ratio":
        base_steps = [
            _step(1, "input_context_validation", [], "missing_input_question"),
            _step(2, "text_ml_case_search", ["input_context_validation"], "pending_questions"),
            _step(3, "law_ground_search", ["text_ml_case_search"], "limitations"),
            _step(
                4,
                "objection_report_generation",
                ["text_ml_case_search", "law_ground_search"],
                "pending_questions",
            ),
            _step(5, "agent_result_validation", ["objection_report_generation"], "limitations"),
        ]
    else:
        base_steps = [
            _step(1, "input_context_validation", [], "missing_input_question"),
            _step(2, "fine_notice_analysis", ["input_context_validation"], "missing_input_question"),
            _step(3, "law_ground_search", ["fine_notice_analysis"], "semantic_search_or_limitations"),
            _step(
                4,
                "objection_report_generation",
                ["fine_notice_analysis", "law_ground_search"],
                "pending_questions",
            ),
            _step(5, "agent_result_validation", ["objection_report_generation"], "limitations"),
        ]

    status_patterns = {
        "success": ["success", "success", "success", "partial", "success"],
        "partial": ["success", "partial", "blocked", "blocked", "blocked"],
        "pending": ["running", "blocked", "blocked", "blocked", "blocked"],
        "failed": ["failed", "skipped", "skipped", "skipped", "skipped"],
    }
    if scenario == "fault_ratio":
        status_patterns = {
            "success": ["success", "success", "partial", "partial", "success"],
            "partial": ["success", "partial", "blocked", "blocked", "blocked"],
            "pending": ["running", "blocked", "blocked", "blocked", "blocked"],
            "failed": ["failed", "skipped", "skipped", "skipped", "skipped"],
        }
    elif scenario == "law_question":
        status_patterns = {
            "success": ["success", "partial", "success"],
            "partial": ["success", "blocked", "blocked"],
            "pending": ["running", "blocked", "blocked"],
            "failed": ["failed", "skipped", "skipped"],
        }
    elif scenario == "report_redownload":
        status_patterns = {
            "success": ["success", "success"],
            "partial": ["success", "blocked"],
            "pending": ["running", "blocked"],
            "failed": ["failed", "skipped"],
        }

    statuses = status_patterns.get(requested_status, status_patterns["success"])
    for step, status in zip(base_steps, statuses, strict=False):
        step["status"] = status
    return base_steps


def _step(
    order: int,
    node_code: str,
    depends_on: list[str],
    fallback: str,
) -> dict[str, Any]:
    return {
        "order": order,
        "node_code": node_code,
        "status": "ready",
        "required_inputs": _required_inputs_for_node(node_code),
        "depends_on": depends_on,
        "fallback": fallback,
    }


def _required_inputs_for_node(node_code: str) -> list[str]:
    return {
        "input_context_validation": ["user_text|attachments"],
        "fine_notice_analysis": ["attachments[purpose=fine_notice]|user_text"],
        "law_ground_search": ["law_code|violation_text|search_query"],
        "objection_report_generation": [
            "notice_analysis_result|text_ml_case_result",
            "law_ground_result",
            "user_facts|query_text",
        ],
        "text_ml_case_search": ["query_text|accident_context"],
        "vision_media_analysis": ["attachments[purpose=accident_scene|blackbox_video|evidence]"],
        "agent_result_validation": ["agent_results"],
    }.get(node_code, [])


def _required_inputs_for_scenario(scenario: str) -> list[str]:
    if scenario == "law_question":
        return ["law_code|violation_text|search_query"]
    if scenario == "report_redownload":
        return ["report_id|session_id|owner_identity"]
    if scenario == "fault_ratio":
        return ["accident_context", "query_text"]
    return ["fine_notice_image_or_text", "user_facts"]


def _plan_blocked_reason(
    requested_status: str,
    pending_questions: list[dict[str, Any]],
) -> str | None:
    if requested_status == "failed":
        return "분석 가능한 명령문 또는 첨부자료가 없습니다."
    if pending_questions:
        return "필수 입력이 부족해 일부 Agent 호출을 보류합니다."
    return None


def _input_modalities(payload: dict[str, Any]) -> list[str]:
    modalities = ["text"] if payload.get("user_text") else []
    for attachment in payload.get("attachments", []):
        attachment_type = _modality_for_attachment_type(attachment.get("type"))
        if attachment_type and attachment_type not in modalities:
            modalities.append(attachment_type)
    return modalities


def _attachment_purposes(payload: dict[str, Any]) -> list[str]:
    purposes = []
    for attachment in payload.get("attachments", []):
        purpose = attachment.get("purpose") or "unknown"
        if purpose not in purposes:
            purposes.append(purpose)
    return purposes


def _append_attachment_resolution_limitations(
    fixture: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    resolution = payload.get("attachment_resolution", {})
    unresolved_ids = resolution.get("unresolved_attachment_ids") or []
    metadata_missing_ids = resolution.get("metadata_missing_attachment_ids") or []
    if not unresolved_ids and not metadata_missing_ids:
        return

    fixture.setdefault("limitations", [])
    if unresolved_ids:
        fixture["limitations"].append(
            f"attachment metadata를 찾지 못한 ID가 있습니다: {', '.join(unresolved_ids)}"
        )
    if metadata_missing_ids:
        fixture["limitations"].append(
            f"registry metadata는 없지만 요청 inline metadata로 처리한 첨부가 있습니다: {', '.join(metadata_missing_ids)}"
        )


def _modality_for_attachment_type(attachment_type: Any) -> str | None:
    if attachment_type in {"pdf", "document", "file", "text"}:
        return "document"
    return str(attachment_type) if attachment_type else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

