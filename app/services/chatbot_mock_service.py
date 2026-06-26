"""Mock chatbot service fixtures for the mid-demo MVP path."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


SCENARIO_INTENTS = {
    "fine_notice": "objection_request",
    "fault_ratio": "fault_ratio",
}


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
    ]


def create_session(user_id: str | None = None) -> dict[str, Any]:
    session_id = f"ses_{uuid4().hex[:12]}"
    return {
        "session_id": session_id,
        "user_id": user_id,
        "status": "draft",
        "created_at": _now_iso(),
        "available_scenarios": list_demo_scenarios(),
    }


def submit_message(payload: dict[str, Any]) -> dict[str, Any]:
    scenario = payload.get("mock_scenario") or _infer_scenario(payload)
    requested_status = payload.get("mock_status") or _infer_status(payload)
    scenario_fixtures = MOCK_SCENARIO_RESULTS.get(scenario, MOCK_SCENARIO_RESULTS["fine_notice"])
    fixture = deepcopy(scenario_fixtures.get(requested_status, scenario_fixtures["success"]))
    fixture.update(
        {
            "message_id": f"msg_{uuid4().hex[:12]}",
            "session_id": payload.get("session_id") or f"ses_{uuid4().hex[:12]}",
            "mock_scenario": scenario,
            "routing_intent": payload.get("routing_intent") or SCENARIO_INTENTS.get(scenario, "general"),
            "status": fixture["progress"]["status"],
            "created_at": _now_iso(),
        }
    )
    return fixture


def perform_report_action(payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("action", "save")
    status = "downloaded" if action == "download" else "report_saved"
    report_id = payload.get("report_id") or f"rep_{uuid4().hex[:12]}"
    return {
        "report_id": report_id,
        "case_id": payload.get("case_id") or f"case_{uuid4().hex[:12]}",
        "status": status,
        "download_url": f"/api/mock/reports/{report_id}/download" if action == "download" else None,
        "created_at": _now_iso(),
        "limitations": ["mock report action 결과입니다."],
    }


def _infer_status(payload: dict[str, Any]) -> str:
    if not payload.get("user_text") and not payload.get("attachments"):
        return "failed"
    if payload.get("needs_more_input"):
        return "partial"
    return "success"


def _infer_scenario(payload: dict[str, Any]) -> str:
    text = str(payload.get("user_text") or "")
    if "과실" in text or "사고" in text or "블랙박스" in text:
        return "fault_ratio"
    return "fine_notice"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

