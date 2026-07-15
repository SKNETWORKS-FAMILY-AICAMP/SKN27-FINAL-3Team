"""Canonical chat planning and response composition without runtime fixtures."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.services.attachment_mock_service import resolve_attachment_references
from app.services.consultation_v2_service import build_consultation_state_v2
from app.services.supervisor_llm_service import build_supervisor_state_with_optional_llm


NODE_PLANS: dict[str, tuple[str, ...]] = {
    "fine_notice_objection": (
        "fine_notice_analysis",
        "law_ground_search",
        "appeal_decision_flow",
        "objection_report_generation",
    ),
    "fault_ratio_text": ("text_ml_case_search", "law_ground_search"),
    "traffic_law_search": ("law_ground_search",),
}

ROUTING_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("fine_notice_objection", ("과태료", "고지서", "범칙금", "의견제출", "이의신청")),
    (
        "fault_ratio_text",
        (
            "과실",
            "사고",
            "충돌",
            "접촉",
            "교차로",
            "보행자",
            "구급차",
            "다쳐",
            "accident",
            "collision",
            "fault",
        ),
    ),
    ("traffic_law_search", ("법령", "조문", "도로교통법", "근거")),
)


def create_session(user_id: str | None = None) -> dict[str, Any]:
    return {
        "contract_version": "chat_session.v1",
        "session_id": f"ses_{uuid4().hex[:12]}",
        "user_id": user_id,
        "status": "draft",
        "created_at": _now_iso(),
    }


def submit_message(payload: dict[str, Any]) -> dict[str, Any]:
    payload = resolve_attachment_references(payload)
    session_id = str(payload.get("session_id") or f"ses_{uuid4().hex[:12]}")
    message_id = f"msg_{uuid4().hex[:12]}"
    attachments = [item for item in payload.get("attachments", []) if isinstance(item, dict)]
    user_text = str(payload.get("user_text") or "").strip()

    if not user_text and not attachments:
        return _needs_input_response(session_id=session_id, message_id=message_id)

    routing_intent = _routing_intent(user_text, attachments)
    if routing_intent == "fault_ratio_text":
        consultation_state = build_consultation_state_v2(
            user_text=user_text,
            facts=dict(payload.get("facts") or {}) if isinstance(payload.get("facts"), dict) else {},
            sources=[
                dict(item)
                for item in payload.get("fact_sources") or []
                if isinstance(item, dict)
            ],
            conflicts=[
                dict(item)
                for item in payload.get("fact_conflicts") or []
                if isinstance(item, dict)
            ],
        )
        if consultation_state["risk_gate"]["level"] == "high_risk":
            return _consultation_hold_response(
                session_id=session_id,
                message_id=message_id,
                routing_intent=routing_intent,
                consultation_state=consultation_state,
                status="high_risk_handoff",
            )
        if not consultation_state["readiness"]["ready_for_fault_range"]:
            return _consultation_hold_response(
                session_id=session_id,
                message_id=message_id,
                routing_intent=routing_intent,
                consultation_state=consultation_state,
                status="needs_input",
            )
        return _consultation_hold_response(
            session_id=session_id,
            message_id=message_id,
            routing_intent=routing_intent,
            consultation_state=consultation_state,
            status="case_ready",
        )

    supervisor_state = build_supervisor_state_with_optional_llm(
        payload={**payload, "user_text": user_text, "attachments": attachments},
        scenario=routing_intent,
        fallback_builder=_fallback_supervisor_state,
    )
    analysis_plan = _analysis_plan(
        session_id=session_id,
        message_id=message_id,
        routing_intent=routing_intent,
        supervisor_state=supervisor_state,
    )

    response = {
        "contract_version": "chat_message_accepted.v2",
        "message_id": message_id,
        "session_id": session_id,
        "routing_intent": routing_intent,
        "status": "queued",
        "created_at": _now_iso(),
        "assistant_message": None,
        "progress": {
            "status": "queued",
            "active_node": analysis_plan["steps"][0]["node_code"],
            "message": "상담 분석 작업이 대기열에 등록될 준비가 되었습니다.",
        },
        "pending_questions": [],
        "cards": [],
        "report_links": [],
        "attachments": attachments,
        "blocked_attachments": list(payload.get("blocked_attachments") or []),
        "attachment_scan_policy": dict(payload.get("attachment_scan_policy") or {}),
        "scan_gate": dict(payload.get("scan_gate") or {}),
        "supervisor_state": supervisor_state,
        "reporting_payload": supervisor_state.get("reporting_payload"),
        "analysis_plan": analysis_plan,
        "limitations": [],
    }
    return response


def compose_agent_response(node_execution: dict[str, Any]) -> dict[str, Any]:
    executions = [item for item in node_execution.get("executions", []) if isinstance(item, dict)]
    summaries: list[str] = []
    structured_results: dict[str, dict[str, Any]] = {}
    evidence: list[dict[str, Any]] = []
    limitations: list[str] = []
    statuses: list[str] = []

    for execution in executions:
        output = execution.get("agent_output") if isinstance(execution.get("agent_output"), dict) else {}
        node_code = str(output.get("node_code") or execution.get("node_code") or "")
        status = str(output.get("status") or "failed")
        statuses.append(status)
        summary = str(output.get("summary") or "").strip()
        if summary:
            summaries.append(summary)
        if node_code:
            structured_results[node_code] = dict(output.get("structured_result") or {})
        evidence.extend(item for item in output.get("evidence", []) if isinstance(item, dict))
        limitations.extend(str(item) for item in output.get("limitations", []) if str(item).strip())

    status = _combined_status(statuses)
    answer = "\n\n".join(_dedupe(summaries))
    if not answer:
        answer = "분석 결과를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요."

    return {
        "contract_version": "analysis_result.v2",
        "job_id": node_execution.get("job_id"),
        "status": status,
        "assistant_message": {"answer": answer, "summary": answer},
        "structured_results": structured_results,
        "evidence": _dedupe_dicts(evidence, key="source_reference"),
        "limitations": _dedupe(limitations),
    }


def _needs_input_response(*, session_id: str, message_id: str) -> dict[str, Any]:
    question = "상담할 교통분쟁 내용이나 고지서 정보를 입력해 주세요."
    return {
        "contract_version": "chat_message_accepted.v2",
        "message_id": message_id,
        "session_id": session_id,
        "routing_intent": "needs_input",
        "status": "needs_input",
        "created_at": _now_iso(),
        "assistant_message": {"answer": question, "summary": question},
        "progress": {"status": "needs_input", "active_node": "", "message": question},
        "pending_questions": [{"field": "user_text", "question": question}],
        "cards": [],
        "report_links": [],
        "attachments": [],
        "blocked_attachments": [],
        "supervisor_state": {},
        "reporting_payload": None,
        "analysis_plan": {
            "contract_version": "analysis_plan.v2",
            "plan_id": f"plan_{uuid4().hex[:12]}",
            "session_id": session_id,
            "message_id": message_id,
            "routing_intent": "needs_input",
            "steps": [],
        },
        "limitations": [],
    }


def _consultation_hold_response(
    *,
    session_id: str,
    message_id: str,
    routing_intent: str,
    consultation_state: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    high_risk = status == "high_risk_handoff"
    pending_questions = list(consultation_state.get("next_questions") or [])
    if high_risk:
        answer = "인명 피해가 우려되는 사건입니다. 긴급 조치와 증거 보존을 우선하고 전문가 이관 자료를 준비합니다."
    elif status == "case_ready":
        answer = "핵심 사실이 준비되었습니다. 로그인 후 사건으로 저장하고 사실을 확정해 주세요."
    else:
        answer = pending_questions[0]["question"] if pending_questions else "사실관계를 추가로 확인해 주세요."
    return {
        "contract_version": "chat_message_accepted.v2",
        "message_id": message_id,
        "session_id": session_id,
        "routing_intent": routing_intent,
        "status": status,
        "created_at": _now_iso(),
        "assistant_message": {"answer": answer, "summary": answer},
        "progress": {"status": status, "active_node": "risk_gate", "message": answer},
        "pending_questions": pending_questions,
        "cards": list(consultation_state.get("fact_cards") or []),
        "report_links": [],
        "attachments": [],
        "blocked_attachments": [],
        "supervisor_state": {},
        "reporting_payload": None,
        "consultation_state": {"v2": consultation_state},
        "analysis_plan": {
            "contract_version": "analysis_plan.v2",
            "plan_id": f"plan_{uuid4().hex[:12]}",
            "session_id": session_id,
            "message_id": message_id,
            "routing_intent": routing_intent,
            "steps": [],
        },
        "limitations": list(consultation_state.get("limitations") or []),
    }


def _routing_intent(user_text: str, attachments: list[dict[str, Any]]) -> str:
    if any(item.get("purpose") == "fine_notice" for item in attachments):
        return "fine_notice_objection"
    normalized_text = user_text.lower()
    for intent, keywords in ROUTING_KEYWORDS:
        if any(keyword.lower() in normalized_text for keyword in keywords):
            return intent
    return "traffic_law_search"


def _fallback_supervisor_state(payload: dict[str, Any], routing_intent: str) -> dict[str, Any]:
    node_codes = NODE_PLANS[routing_intent]
    user_text = str(payload.get("user_text") or "").strip()
    return {
        "contract_version": "supervisor_conversation_state.v2",
        "scenario": routing_intent,
        "stage": "analysis_ready",
        "conversation_turn_count": len(payload.get("conversation_history") or []) + 1,
        "conversation_summary": user_text,
        "collected_facts": [{"field": "user_text", "value": user_text}] if user_text else [],
        "missing_fields": [],
        "next_questions": [],
        "agent_input_packages": [
            {
                "node_code": node_code,
                "required_inputs": ["user_text|attachments"],
                "payload": {"user_text": user_text, "attachments": payload.get("attachments", [])},
            }
            for node_code in node_codes
        ],
        "reporting_payload": {
            "contract_version": "reporting_payload.v2",
            "report_type": {
                "fine_notice_objection": "fine_notice_objection",
                "fault_ratio_text": "fault_ratio_analysis",
                "traffic_law_search": "general",
            }[routing_intent],
        },
    }


def _analysis_plan(
    *,
    session_id: str,
    message_id: str,
    routing_intent: str,
    supervisor_state: dict[str, Any],
) -> dict[str, Any]:
    steps = []
    previous_node: str | None = None
    for order, node_code in enumerate(NODE_PLANS[routing_intent], start=1):
        steps.append(
            {
                "order": order,
                "node_code": node_code,
                "status": "ready",
                "execution_mode": "sync",
                "depends_on": [previous_node] if previous_node else [],
                "required_inputs": ["user_text|attachments"],
            }
        )
        previous_node = node_code
    return {
        "contract_version": "analysis_plan.v2",
        "plan_id": f"plan_{uuid4().hex[:12]}",
        "session_id": session_id,
        "message_id": message_id,
        "routing_intent": routing_intent,
        "steps": steps,
        "supervisor_contract_version": supervisor_state.get("contract_version"),
    }


def _combined_status(statuses: list[str]) -> str:
    if statuses and all(status == "success" for status in statuses):
        return "success"
    if any(status in {"success", "partial"} for status in statuses):
        return "partial"
    return "failed"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _dedupe_dicts(values: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        identity = str(value.get(key) or value)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(value)
    return result


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

