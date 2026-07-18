"""Canonical chat planning and response composition without runtime fixtures."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.security.chat_input_privacy import protect_chat_input_payload
from app.services.attachment_mock_service import resolve_attachment_references
from app.services.case_evidence_service import build_case_evidence
from app.services.consultation_v2_service import CORE_FACT_QUESTIONS, build_consultation_state_v2
from app.services.law_ground_contract import normalize_law_evidence
from app.services.service_scope_policy_service import evaluate_service_scope
from app.services.supervisor_control_service import (
    evaluate_case_promotion,
    reduce_consultation_fact_state,
)
from app.services.supervisor_llm_service import build_supervisor_state_with_optional_llm
from app.services.supervisor_routing_service import (
    BASE_NODE_PLANS,
    PUBLIC_AGENT_NODE_CODES,
    plan_node_codes,
    report_generation_requested,
    route_supervisor_input,
)


# Compatibility export for callers that inspect the declarative policy.
NODE_PLANS = BASE_NODE_PLANS


def create_session(user_id: str | None = None) -> dict[str, Any]:
    return {
        "contract_version": "chat_session.v1",
        "session_id": f"ses_{uuid4().hex[:12]}",
        "user_id": user_id,
        "status": "draft",
        "created_at": _now_iso(),
    }


def build_scope_guidance_response(
    *,
    session_id: str,
    message_id: str,
    user_text: str,
    attachments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return a non-executable response when the declared service boundary applies."""

    if not user_text and not attachments:
        return None
    routing_intent = route_supervisor_input(user_text, attachments)
    service_scope = evaluate_service_scope(
        user_text=user_text,
        attachments=attachments,
        routing_intent=routing_intent,
    )
    if service_scope["decision"] == "proceed":
        return None
    return _scope_guidance_response(
        session_id=session_id,
        message_id=message_id,
        routing_intent=routing_intent,
        attachments=attachments,
        service_scope=service_scope,
    )


def submit_message(payload: dict[str, Any]) -> dict[str, Any]:
    payload = protect_chat_input_payload(payload)
    payload = resolve_attachment_references(payload)
    session_id = str(payload.get("session_id") or f"ses_{uuid4().hex[:12]}")
    message_id = f"msg_{uuid4().hex[:12]}"
    attachments = [item for item in payload.get("attachments", []) if isinstance(item, dict)]
    user_text = str(payload.get("user_text") or "").strip()

    if not user_text and not attachments:
        return _needs_input_response(session_id=session_id, message_id=message_id)

    scope_guidance = build_scope_guidance_response(
        session_id=session_id,
        message_id=message_id,
        user_text=user_text,
        attachments=attachments,
    )
    if scope_guidance is not None:
        return scope_guidance
    routing_intent = route_supervisor_input(user_text, attachments)
    report_requested = report_generation_requested(user_text)
    if routing_intent == "accident_initial_consultation":
        accident_supervisor_state = build_supervisor_state_with_optional_llm(
            payload={**payload, "user_text": user_text, "attachments": attachments},
            scenario=routing_intent,
            fallback_builder=_fallback_accident_supervisor_state,
        )
        source_message_id = str(payload.get("message_id") or message_id)
        fact_candidates = [
            {
                **dict(item),
                "source_message_id": item.get("source_message_id") or source_message_id,
                "confirmed": False,
            }
            for item in accident_supervisor_state.get("collected_facts") or []
            if isinstance(item, dict)
        ]
        fact_state = reduce_consultation_fact_state(
            {**payload, "fact_candidates": fact_candidates}
        )
        fact_sources = [
            dict(item)
            for item in payload.get("fact_sources") or []
            if isinstance(item, dict)
        ]
        consultation_state = build_consultation_state_v2(
            user_text=user_text,
            facts=fact_state["fact_values"],
            sources=fact_sources,
            conflicts=fact_state["conflicts"],
        )
        case_evidence = build_case_evidence(
            facts=fact_state["fact_values"],
            sources=fact_sources,
            conflicts=fact_state["conflicts"],
            material_source_refs=set(),
        )
        consultation_state = {
            **consultation_state,
            "case_evidence": case_evidence,
            "next_questions": [
                *list(consultation_state.get("next_questions") or []),
                *(
                    []
                    if consultation_state.get("next_questions")
                    else _case_evidence_questions(case_evidence)
                ),
            ],
        }
        accident_supervisor_state = {
            **accident_supervisor_state,
            "case_evidence": case_evidence,
        }
        auth_context = payload.get("auth_context") if isinstance(payload.get("auth_context"), dict) else {}
        promotion_gate = evaluate_case_promotion(
            consultation_state,
            analysis_requested=True,
            authenticated=str(auth_context.get("auth_state") or "") == "authenticated",
            storage_consent=bool(payload.get("case_storage_consent")),
            facts_confirmed=(
                bool(fact_state["facts"])
                and all(bool(record.get("confirmed")) for record in fact_state["facts"].values())
            ),
        )
        status_by_decision = {
            "expert_handoff": "high_risk_handoff",
            "ask_more": "needs_input",
            "ready_for_case": "case_ready",
            "stay_in_chat": "guidance_only",
        }
        return _consultation_hold_response(
            session_id=session_id,
            message_id=message_id,
            routing_intent=routing_intent,
            consultation_state=consultation_state,
            fact_state=fact_state,
            promotion_gate=promotion_gate,
            supervisor_state=accident_supervisor_state,
            status=status_by_decision[promotion_gate["decision"]],
        )

    supervisor_state = build_supervisor_state_with_optional_llm(
        payload={**payload, "user_text": user_text, "attachments": attachments},
        scenario=routing_intent,
        fallback_builder=_fallback_supervisor_state,
    )
    if (supervisor_state.get("llm") or {}).get("status") == "failed":
        return _supervisor_unavailable_response(
            session_id=session_id,
            message_id=message_id,
            routing_intent=routing_intent,
            attachments=attachments,
            supervisor_state=supervisor_state,
        )
    if supervisor_state.get("stage") == "need_more_input":
        return _supervisor_needs_input_response(
            session_id=session_id,
            message_id=message_id,
            routing_intent=routing_intent,
            attachments=attachments,
            supervisor_state=supervisor_state,
        )
    if supervisor_state.get("stage") != "agent_execution_ready":
        blocked_state = dict(supervisor_state)
        blocked_state["llm"] = {
            **(
                supervisor_state.get("llm")
                if isinstance(supervisor_state.get("llm"), dict)
                else {}
            ),
            "status": "failed",
            "reason": "invalid_contract",
        }
        blocked_state["agent_input_packages"] = []
        blocked_state["reporting_payload"] = None
        return _supervisor_unavailable_response(
            session_id=session_id,
            message_id=message_id,
            routing_intent=routing_intent,
            attachments=attachments,
            supervisor_state=blocked_state,
        )
    analysis_plan = _analysis_plan(
        session_id=session_id,
        message_id=message_id,
        routing_intent=routing_intent,
        supervisor_state=supervisor_state,
        report_requested=report_requested,
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
    final_execution = next(
        (
            item
            for item in reversed(executions)
            if str(item.get("node_code") or "") == "final_response_merge"
        ),
        None,
    )
    if final_execution:
        final_output = (
            final_execution.get("agent_output")
            if isinstance(final_execution.get("agent_output"), dict)
            else {}
        )
        merged = (
            final_output.get("structured_result")
            if isinstance(final_output.get("structured_result"), dict)
            else {}
        )
        assistant_message = (
            merged.get("assistant_message")
            if isinstance(merged.get("assistant_message"), dict)
            else {"answer": final_output.get("summary", ""), "summary": final_output.get("summary", "")}
        )
        return {
            "contract_version": "analysis_result.v2",
            "job_id": node_execution.get("job_id"),
            "status": str(final_output.get("status") or "partial"),
            "assistant_message": assistant_message,
            "structured_results": dict(merged.get("structured_results") or {}),
            "evidence": list(merged.get("evidence") or []),
            "limitations": list(merged.get("limitations") or []),
            "deadline_guidance": dict(merged.get("deadline_guidance") or {}),
            "pending_questions": list(merged.get("pending_questions") or []),
            "cards": list(merged.get("cards") or []),
            "report_links": list(merged.get("report_links") or []),
            "supervisor_handoff": dict(node_execution.get("supervisor_handoff") or {}),
            "reporting_payload": dict(node_execution.get("reporting_payload") or {}),
        }
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
        output_evidence = [item for item in output.get("evidence", []) if isinstance(item, dict)]
        if node_code == "law_ground_search":
            output_evidence = normalize_law_evidence(output_evidence)
        evidence.extend(output_evidence)
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
        "supervisor_handoff": dict(node_execution.get("supervisor_handoff") or {}),
        "reporting_payload": dict(node_execution.get("reporting_payload") or {}),
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


def _scope_guidance_response(
    *,
    session_id: str,
    message_id: str,
    routing_intent: str,
    attachments: list[dict[str, Any]],
    service_scope: dict[str, Any],
) -> dict[str, Any]:
    message = str(service_scope["reason"])
    return {
        "contract_version": "chat_message_accepted.v2",
        "message_id": message_id,
        "session_id": session_id,
        "routing_intent": routing_intent,
        "status": "scope_guidance",
        "created_at": _now_iso(),
        "assistant_message": {"answer": message, "summary": message},
        "progress": {"status": "scope_guidance", "active_node": "", "message": message},
        "pending_questions": [],
        "cards": [],
        "report_links": [],
        "attachments": attachments,
        "blocked_attachments": [],
        "supervisor_state": {},
        "reporting_payload": None,
        "service_scope": service_scope,
        "analysis_plan": {
            "contract_version": "analysis_plan.v2",
            "plan_id": f"plan_{uuid4().hex[:12]}",
            "session_id": session_id,
            "message_id": message_id,
            "routing_intent": routing_intent,
            "status": "blocked",
            "steps": [],
        },
        "limitations": list(service_scope["limitations"]),
    }


def _supervisor_unavailable_response(
    *,
    session_id: str,
    message_id: str,
    routing_intent: str,
    attachments: list[dict[str, Any]],
    supervisor_state: dict[str, Any],
) -> dict[str, Any]:
    message = "Supervisor planning is temporarily unavailable. Please retry shortly."
    return {
        "contract_version": "chat_message_accepted.v2",
        "message_id": message_id,
        "session_id": session_id,
        "routing_intent": routing_intent,
        "status": "supervisor_unavailable",
        "created_at": _now_iso(),
        "assistant_message": {"answer": message, "summary": message},
        "progress": {"status": "blocked", "active_node": "", "message": message},
        "pending_questions": [],
        "cards": [],
        "report_links": [],
        "attachments": attachments,
        "blocked_attachments": [],
        "supervisor_state": supervisor_state,
        "reporting_payload": None,
        "analysis_plan": {
            "contract_version": "analysis_plan.v2",
            "plan_id": f"plan_{uuid4().hex[:12]}",
            "session_id": session_id,
            "message_id": message_id,
            "routing_intent": routing_intent,
            "status": "blocked",
            "steps": [],
            "blocked_reason": (supervisor_state.get("llm") or {}).get("reason")
            or "provider_unavailable",
        },
        "limitations": ["Supervisor planning is temporarily unavailable."],
    }


def _supervisor_needs_input_response(
    *,
    session_id: str,
    message_id: str,
    routing_intent: str,
    attachments: list[dict[str, Any]],
    supervisor_state: dict[str, Any],
) -> dict[str, Any]:
    response = _needs_input_response(session_id=session_id, message_id=message_id)
    pending_questions = [
        dict(item)
        for item in supervisor_state.get("next_questions") or []
        if isinstance(item, dict)
    ]
    question = str(
        (pending_questions[0].get("question") if pending_questions else "")
        or response["assistant_message"]["answer"]
    )
    sanitized_state = dict(supervisor_state)
    sanitized_state["reporting_payload"] = None
    response.update(
        {
            "routing_intent": routing_intent,
            "assistant_message": {"answer": question, "summary": question},
            "progress": {
                "status": "needs_input",
                "active_node": "",
                "message": question,
            },
            "pending_questions": pending_questions,
            "attachments": attachments,
            "supervisor_state": sanitized_state,
            "reporting_payload": None,
        }
    )
    response["analysis_plan"].update(
        {
            "routing_intent": routing_intent,
            "status": "needs_input",
            "steps": [],
        }
    )
    return response


def _consultation_hold_response(
    *,
    session_id: str,
    message_id: str,
    routing_intent: str,
    consultation_state: dict[str, Any],
    fact_state: dict[str, Any],
    promotion_gate: dict[str, Any],
    supervisor_state: dict[str, Any],
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
        "progress": {"status": status, "active_node": "case_promotion_gate", "message": answer},
        "pending_questions": pending_questions,
        "cards": list(consultation_state.get("fact_cards") or []),
        "report_links": [],
        "attachments": [],
        "blocked_attachments": [],
        "supervisor_state": supervisor_state,
        "reporting_payload": None,
        "consultation_state": {
            "v2": consultation_state,
            "fact_state": fact_state,
            "promotion_gate": promotion_gate,
        },
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


def _case_evidence_questions(case_evidence: dict[str, Any]) -> list[dict[str, Any]]:
    claim_fields = sorted(
        field
        for field in (case_evidence.get("claims") or {})
        if str(field).strip()
    )
    conflict_fields = sorted(
        {
            str(item.get("field") or "").strip()
            for item in case_evidence.get("unknowns") or []
            if isinstance(item, dict) and item.get("reason") == "conflicting_claim"
        }
        - {""}
    )
    questions: list[dict[str, Any]] = []
    if claim_fields:
        questions.append(
            {
                "field": "material_evidence",
                "fields": claim_fields,
                "question": "현재 입력은 사용자 진술입니다. 과실·법령 판단 전에 해당 사실을 확인할 수 있는 자료를 첨부해 주세요.",
            }
        )
    if conflict_fields:
        questions.append(
            {
                "field": "resolve_conflict",
                "fields": conflict_fields,
                "question": "서로 다른 진술이 있어 판단을 보류했습니다. 정확한 사실과 이를 확인할 수 있는 자료를 알려 주세요.",
            }
        )
    return questions


def _fallback_supervisor_state(payload: dict[str, Any], routing_intent: str) -> dict[str, Any]:
    user_text = str(payload.get("user_text") or "").strip()
    report_requested = report_generation_requested(user_text)
    node_codes = plan_node_codes(routing_intent, report_requested=report_requested)
    public_node_codes = [code for code in node_codes if code in PUBLIC_AGENT_NODE_CODES]
    slot_state = {
        "contract_version": "slot_filling_state.v1",
        "slots": {
            "user_text": {
                "value": user_text,
                "source": {
                    "type": "user_message",
                    "reference": payload.get("message_id") or payload.get("session_id"),
                },
                "confidence": 1.0,
                "editable": True,
            }
        },
    }
    return {
        "contract_version": "supervisor_conversation_state.v2",
        "scenario": routing_intent,
        "stage": "agent_execution_ready",
        "conversation_turn_count": len(payload.get("conversation_history") or []) + 1,
        "conversation_summary": user_text,
        "collected_facts": [{"field": "user_text", "value": user_text}] if user_text else [],
        "missing_fields": [],
        "next_questions": [],
        "slot_state": slot_state,
        "agent_input_packages": [
            {
                "schema_version": "agent_input_schema.v1",
                "node_code": node_code,
                "status": "ready",
                "required_inputs": ["user_text|attachments"],
                "payload": {
                    "user_text": user_text,
                    "attachments": payload.get("attachments", []),
                    "slot_state": slot_state,
                },
            }
            for node_code in public_node_codes
        ],
        "reporting_payload": (
            {
                "contract_version": "reporting_payload.v2",
                "report_type": "fine_notice_objection",
            }
            if report_requested and routing_intent == "fine_notice_analysis"
            else None
        ),
    }


def _fallback_accident_supervisor_state(
    payload: dict[str, Any],
    routing_intent: str,
) -> dict[str, Any]:
    fact_state = reduce_consultation_fact_state(payload)
    collected_facts = [
        {
            "field": field,
            "value": record["value"],
            "confidence": record.get("confidence", 1.0),
            "source_message_id": record.get("source_message_id"),
        }
        for field, record in fact_state["facts"].items()
    ]
    missing_fields = [
        {"field": field, "reason": "required_for_accident_analysis"}
        for field in fact_state["missing_fields"]
    ]
    question_by_field = dict(CORE_FACT_QUESTIONS)
    return {
        "contract_version": "supervisor_conversation_state.v2",
        "scenario": routing_intent,
        "stage": "need_more_input" if missing_fields else "need_fact_confirmation",
        "conversation_turn_count": len(payload.get("conversation_history") or []) + 1,
        "conversation_summary": str(payload.get("user_text") or "").strip(),
        "collected_facts": collected_facts,
        "missing_fields": missing_fields,
        "next_questions": [
            {"field": item["field"], "question": question_by_field[item["field"]]}
            for item in missing_fields
        ],
        "slot_state": {
            "contract_version": "slot_filling_state.v1",
            "slots": {
                item["field"]: {
                    "value": item["value"],
                    "source": {
                        "type": "user_message",
                        "reference": item.get("source_message_id"),
                    },
                    "confidence": item.get("confidence", 1.0),
                    "editable": True,
                }
                for item in collected_facts
            },
        },
        "agent_input_packages": [],
        "reporting_payload": None,
    }
def _analysis_plan(
    *,
    session_id: str,
    message_id: str,
    routing_intent: str,
    supervisor_state: dict[str, Any],
    report_requested: bool,
) -> dict[str, Any]:
    node_codes = plan_node_codes(routing_intent, report_requested=report_requested)
    expected_node_codes = [code for code in node_codes if code in PUBLIC_AGENT_NODE_CODES]
    steps = []
    previous_node: str | None = None
    for order, node_code in enumerate(node_codes, start=1):
        context: dict[str, Any] = {"routing_intent": routing_intent}
        if node_code == "agent_result_validation":
            context.update(
                {
                    "expected_node_codes": expected_node_codes,
                    "report_requested": report_requested,
                }
            )
        elif node_code == "final_response_merge":
            context["pending_questions"] = list(supervisor_state.get("next_questions") or [])
        steps.append(
            {
                "order": order,
                "node_code": node_code,
                "status": "ready",
                "execution_mode": "sync",
                "depends_on": [previous_node] if previous_node else [],
                "required_inputs": ["user_text|attachments"],
                "context": context,
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

