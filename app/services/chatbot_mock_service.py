"""Mock chatbot service fixtures for the Django/React MVP path."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


MOCK_ANALYSIS_RESULTS: dict[str, dict[str, Any]] = {
    "success": {
        "assistant_message": "고지서 내용과 관련 법령 근거 후보를 확인했습니다.",
        "progress": {
            "status": "success",
            "active_node": "final_response_merge",
            "message": "분석 결과를 표시할 수 있습니다.",
        },
        "cards": [
            {
                "card_type": "fine_notice",
                "title": "고지서 분석",
                "status": "success",
                "summary": "과태료 고지서로 추정되며 의견제출 기한 확인이 필요합니다.",
                "evidence_refs": ["att_0001"],
            },
            {
                "card_type": "law_ground",
                "title": "법령 근거 후보",
                "status": "partial",
                "summary": "도로교통법 관련 조항 후보가 있으나 최신성 확인이 필요합니다.",
                "evidence_refs": ["law_chunk_mock_001"],
            },
            {
                "card_type": "objection_report",
                "title": "이의신청서 초안",
                "status": "partial",
                "summary": "사용자 사실관계 보완 후 초안 생성이 가능합니다.",
                "evidence_refs": ["law_chunk_mock_001", "att_0001"],
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
            "mock 결과이며 실제 Agent, RAG, 법령 API 호출 결과가 아닙니다.",
            "법률 자문 또는 처분 취소 가능성 보장이 아닙니다.",
        ],
    },
    "pending": {
        "assistant_message": "분석을 시작했습니다.",
        "progress": {
            "status": "pending",
            "active_node": "input_classification",
            "message": "입력 유형을 분류하는 중입니다.",
        },
        "cards": [],
        "report_links": [],
        "limitations": ["mock pending 상태입니다."],
    },
    "partial": {
        "assistant_message": "일부 결과만 확인되었습니다. 추가 정보가 필요합니다.",
        "progress": {
            "status": "partial",
            "active_node": "missing_input_question",
            "message": "필수 입력 보완이 필요합니다.",
        },
        "cards": [
            {
                "card_type": "law_ground",
                "title": "법령 근거 후보",
                "status": "partial",
                "summary": "위반 유형이 불명확해 semantic 검색 후보만 표시합니다.",
                "evidence_refs": ["law_chunk_mock_001"],
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
    "failed": {
        "assistant_message": "현재 입력만으로는 분석 결과를 만들 수 없습니다.",
        "progress": {
            "status": "failed",
            "active_node": "input_classification",
            "message": "분석 가능한 입력을 찾지 못했습니다.",
        },
        "cards": [],
        "report_links": [],
        "limitations": ["지원 형식의 고지서 이미지, PDF, 설명 텍스트를 다시 입력해 주세요."],
    },
}


def create_session(user_id: str | None = None) -> dict[str, Any]:
    session_id = f"ses_{uuid4().hex[:12]}"
    return {
        "session_id": session_id,
        "user_id": user_id,
        "status": "draft",
        "created_at": _now_iso(),
    }


def submit_message(payload: dict[str, Any]) -> dict[str, Any]:
    requested_status = payload.get("mock_status") or _infer_status(payload)
    fixture = deepcopy(MOCK_ANALYSIS_RESULTS.get(requested_status, MOCK_ANALYSIS_RESULTS["success"]))
    fixture.update(
        {
            "message_id": f"msg_{uuid4().hex[:12]}",
            "session_id": payload.get("session_id") or f"ses_{uuid4().hex[:12]}",
            "routing_intent": payload.get("routing_intent") or _infer_intent(payload),
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


def _infer_intent(payload: dict[str, Any]) -> str:
    text = str(payload.get("user_text") or "")
    if "이의" in text or "신청" in text:
        return "objection_request"
    if "법령" in text or "근거" in text:
        return "law_question"
    if payload.get("attachments"):
        return "fine_notice"
    return "general"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

