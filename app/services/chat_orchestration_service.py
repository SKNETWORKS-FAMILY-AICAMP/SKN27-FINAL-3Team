"""Canonical chat planning and response composition without runtime fixtures."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from app.security.chat_input_privacy import protect_chat_input_payload
from app.services.attachment_mock_service import resolve_attachment_references
from app.services.attachment_workflow_service import build_attachment_workflows
from app.services.case_memory_service import update_case_memory
from app.services.case_evidence_service import build_case_evidence
from app.services.consultation_v2_service import CORE_FACT_QUESTIONS, build_consultation_state_v2
from app.services.fine_notice_intake_service import reduce_fine_notice_intake
from app.services.fact_conflict_service import (
    detect_same_message_fact_conflicts,
    normalize_fact_conflicts,
)
from app.services.input_understanding_service import evaluate_input_understanding
from app.services.law_ground_contract import normalize_law_evidence
from app.services.service_scope_policy_service import evaluate_service_scope
from app.services.supervisor_control_service import (
    evaluate_case_promotion,
    merge_final_response,
    reduce_consultation_fact_state,
)
from app.services.supervisor_llm_service import build_supervisor_state_with_optional_llm
from app.services.supervisor_llm_contract import enrich_agent_package
from app.services.supervisor_execution_input_service import canonical_attachment_selectors
from app.services.supervisor_input_normalization_service import (
    NORMALIZED_INPUT_CONTRACT_VERSION,
    POLICY_CONTRACT_VERSION as NORMALIZATION_POLICY_VERSION,
    normalize_supervisor_input,
)
from app.services.supervisor_input_projection_service import (
    accident_fact_candidates,
    accident_fact_sources,
    fine_notice_intake_slots,
    normalization_pending_questions,
    normalized_slot_state,
)
from app.services.supervisor_routing_service import (
    BASE_NODE_PLANS,
    PUBLIC_AGENT_NODE_CODES,
    plan_node_codes,
    report_generation_requested,
    route_supervisor_input,
)


# Compatibility export for callers that inspect the declarative policy.
NODE_PLANS = BASE_NODE_PLANS
logger = logging.getLogger(__name__)


NO_MATCH_REPHRASE_PROMPT = (
    "말씀해주신 내용으로 확인했지만 이번엔 일치하는 결과를 찾지 못했어요. "
    "표현을 조금 바꿔서 다시 설명해주시면 이어서 확인해드릴게요."
)

_VIOLATION_TYPE_KEYWORDS = (
    "신호위반", "속도위반", "과속", "불법유턴", "불법주정차", "불법주차", "무단횡단",
    "음주운전", "안전거리", "진로변경", "앞지르기", "정지선", "횡단보도", "중앙선",
    "보호구역", "과태료", "범칙금", "딱지", "사고", "충돌", "접촉", "과실",
)
_DATETIME_PATTERN = re.compile(r"\d+\s*(월|일|시|분)")
_RELATIVE_DATE_KEYWORDS = ("어제", "오늘", "그제", "지난주", "지난달", "방금", "아까")
_LOCATION_KEYWORDS = (
    "교차로", "사거리", "골목", "주차장", "학교", "근처", "구간", "앞", "도로변", "인근",
)
_NOTICE_KEYWORDS = ("고지서", "통지서", "위반고지", "과태료", "범칙금", "딱지", "통지")
OCR_CONFIRMATION_FIELDS = frozenset(
    {
        "fine_type",
        "notice_stage",
        "law_code",
        "violation_text",
        "opinion_deadline",
        "issuing_authority",
    }
)


def _has_datetime_or_location(user_text: str) -> bool:
    if _DATETIME_PATTERN.search(user_text):
        return True
    return any(
        keyword in user_text for keyword in _RELATIVE_DATE_KEYWORDS + _LOCATION_KEYWORDS
    )


def _normalized_ocr_confirmation(value: Any) -> dict[str, Any]:
    """Return the narrow user-confirmed OCR payload allowed into planning."""

    raw = value if isinstance(value, dict) else {}
    raw_fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
    fields = {
        key: str(raw_fields[key]).strip()
        for key in OCR_CONFIRMATION_FIELDS
        if str(raw_fields.get(key) or "").strip()
    }
    return {
        "confirmed": raw.get("confirmed") is True,
        "fields": fields,
    }


def _has_valid_ocr_confirmation(value: dict[str, Any]) -> bool:
    return value.get("confirmed") is True


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
    routing_intent: str = "",
    input_normalization: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a non-executable response when the declared service boundary applies."""

    if not user_text and not attachments:
        return None
    routing_intent = routing_intent or route_supervisor_input(user_text, attachments)
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
        input_normalization=input_normalization,
    )


def submit_message(
    payload: dict[str, Any],
    *,
    routing_intent_override: str = "",
    continuation_routing_intent: str = "",
    confirmed_report_user_facts: str = "",
) -> dict[str, Any]:
    payload = protect_chat_input_payload(payload)
    payload = resolve_attachment_references(payload)
    session_id = str(payload.get("session_id") or f"ses_{uuid4().hex[:12]}")
    message_id = f"msg_{uuid4().hex[:12]}"
    attachments = [item for item in payload.get("attachments", []) if isinstance(item, dict)]
    user_text = str(payload.get("user_text") or "").strip()

    if not user_text and not attachments:
        return _needs_input_response(session_id=session_id, message_id=message_id)

    input_understanding = evaluate_input_understanding(
        user_text=user_text,
        attachments=attachments,
    )
    if input_understanding["status"] in {
        "needs_clarification",
        "blocked_sensitive",
    }:
        return _input_clarification_response(
            session_id=session_id,
            message_id=message_id,
            input_understanding=input_understanding,
        )
    user_text = str(input_understanding["safe_user_text"] or user_text).strip()
    payload = {
        **payload,
        "message_id": message_id,
        "user_text": user_text,
        "safe_user_text": user_text,
        "input_understanding": input_understanding["public_metadata"],
    }
    input_normalization = _normalize_input_safely(
        user_text=user_text,
        message_id=message_id,
    )
    payload = {**payload, "input_normalization": input_normalization}
    detected_routing_intent = route_supervisor_input(
        user_text,
        attachments,
        normalized_input=input_normalization,
    )
    forced_routing_intent = str(routing_intent_override or "").strip()
    continuation_intent = str(continuation_routing_intent or "").strip()
    if forced_routing_intent not in {"", "general_consultation"}:
        routing_intent = forced_routing_intent
    elif detected_routing_intent != "general_consultation":
        routing_intent = detected_routing_intent
    elif continuation_intent:
        routing_intent = continuation_intent
    else:
        routing_intent = detected_routing_intent
    scope_guidance = build_scope_guidance_response(
        session_id=session_id,
        message_id=message_id,
        user_text=user_text,
        attachments=attachments,
        routing_intent=routing_intent,
        input_normalization=input_normalization,
    )
    if scope_guidance is not None:
        return scope_guidance
    normalization_questions = normalization_pending_questions(input_normalization)
    if (
        routing_intent != "attachment_document_classification"
        and normalization_questions
        and _normalization_requires_input_hold(input_normalization)
    ):
        return _normalization_needs_input_response(
            session_id=session_id,
            message_id=message_id,
            routing_intent=routing_intent,
            attachments=attachments,
            input_normalization=input_normalization,
            pending_questions=normalization_questions,
        )
    ocr_confirmation = _normalized_ocr_confirmation(payload.get("ocr_confirmation"))
    fine_notice_intake = (
        reduce_fine_notice_intake(
            {
                **payload,
                "user_text": user_text,
                "attachments": attachments,
                "ocr_confirmation": ocr_confirmation,
                "normalized_slots": fine_notice_intake_slots(
                    input_normalization
                ),
            }
        )
        if routing_intent in {"fine_notice_procedure", "fine_notice_analysis"}
        else None
    )
    report_requested = _report_requested_for_payload(
        payload,
        user_text=user_text,
        routing_intent=routing_intent,
        ocr_confirmation=ocr_confirmation,
    )
    if routing_intent == "accident_initial_consultation":
        accident_supervisor_state = build_supervisor_state_with_optional_llm(
            payload={**payload, "user_text": user_text, "attachments": attachments},
            scenario=routing_intent,
            fallback_builder=_fallback_accident_supervisor_state,
        )
        source_message_id = str(payload.get("message_id") or message_id)
        fact_conflicts = normalize_fact_conflicts(
            [
                *detect_same_message_fact_conflicts(
                    user_text,
                    source_message_id,
                ),
                *list(accident_supervisor_state.get("fact_conflicts") or []),
                *list(payload.get("fact_conflicts") or []),
            ],
            default_source_message_id=source_message_id,
        )
        conflict_fields = {item["field"] for item in fact_conflicts}
        fact_candidates = [
            {
                **dict(item),
                "source_message_id": item.get("source_message_id") or source_message_id,
                "confirmed": False,
            }
            for item in accident_supervisor_state.get("collected_facts") or []
            if isinstance(item, dict) and item.get("field") not in conflict_fields
        ]
        fact_state = reduce_consultation_fact_state(
            {
                **payload,
                "fact_candidates": fact_candidates,
                "fact_conflicts": fact_conflicts,
            }
        )
        fact_sources = [
            *[
                item
                for item in accident_fact_sources(
                    input_normalization,
                    source_message_id=source_message_id,
                )
                if item.get("field") not in _explicit_accident_fact_fields(payload)
            ],
            *[
                dict(item)
                for item in payload.get("fact_sources") or []
                if isinstance(item, dict)
            ],
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
        case_memory = update_case_memory(
            payload.get("case_memory") if isinstance(payload.get("case_memory"), dict) else {},
            user_text=user_text,
            routing_intent=routing_intent,
            fact_state=fact_state,
            case_evidence=case_evidence,
            attachments=attachments,
            consultation_state=consultation_state,
        )
        consultation_state = {
            **consultation_state,
            "case_evidence": case_evidence,
            "case_memory": case_memory,
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
            "fact_conflicts": fact_conflicts,
            "case_evidence": case_evidence,
            "case_memory": case_memory,
            "conversation_summary": case_memory.get("conversation_summary")
            or accident_supervisor_state.get("conversation_summary"),
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
            input_normalization=input_normalization,
        )

    supervisor_state = build_supervisor_state_with_optional_llm(
        payload={
            **payload,
            "user_text": user_text,
            "attachments": attachments,
            "ocr_confirmation": ocr_confirmation,
        },
        scenario=routing_intent,
        fallback_builder=_fallback_supervisor_state,
    )
    supervisor_state = _apply_ocr_confirmation_to_supervisor_state(
        supervisor_state,
        routing_intent=routing_intent,
        user_text=user_text,
        attachments=attachments,
        ocr_confirmation=ocr_confirmation,
    )
    if fine_notice_intake is not None:
        supervisor_state = {
            **supervisor_state,
            "fine_notice_intake": fine_notice_intake,
            "next_questions": _merge_fine_notice_questions(
                supervisor_state.get("next_questions"),
                fine_notice_intake,
            ),
        }
    if (supervisor_state.get("llm") or {}).get("status") == "failed":
        return _supervisor_unavailable_response(
            session_id=session_id,
            message_id=message_id,
            routing_intent=routing_intent,
            attachments=attachments,
            supervisor_state=supervisor_state,
            input_normalization=input_normalization,
        )
    if supervisor_state.get("stage") == "need_more_input":
        return _supervisor_needs_input_response(
            session_id=session_id,
            message_id=message_id,
            routing_intent=routing_intent,
            attachments=attachments,
            supervisor_state=supervisor_state,
            input_normalization=input_normalization,
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
            input_normalization=input_normalization,
        )
    analysis_plan = _analysis_plan(
        session_id=session_id,
        message_id=message_id,
        routing_intent=routing_intent,
        supervisor_state=supervisor_state,
        report_requested=report_requested,
        ocr_confirmation=ocr_confirmation,
    )
    active_workflow_node = next(
        (
            str(step["node_code"])
            for step in analysis_plan["steps"]
            if str(step.get("node_code") or "")
            not in {
                "input_context_validation",
                "agent_result_validation",
                "final_response_merge",
            }
        ),
        "",
    )
    attachment_workflows = build_attachment_workflows(
        attachments=attachments,
        active_node=active_workflow_node,
        overall_status="queued",
        ocr_confirmation=ocr_confirmation,
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
        "pending_questions": _merge_fine_notice_questions(
            supervisor_state.get("next_questions"),
            fine_notice_intake,
        ),
        "cards": [],
        "report_links": [],
        "attachments": attachments,
        "attachment_workflows": attachment_workflows,
        "blocked_attachments": list(payload.get("blocked_attachments") or []),
        "attachment_scan_policy": dict(payload.get("attachment_scan_policy") or {}),
        "scan_gate": dict(payload.get("scan_gate") or {}),
        "supervisor_state": supervisor_state,
        "fine_notice_intake": fine_notice_intake,
        "input_normalization": input_normalization,
        "reporting_payload": supervisor_state.get("reporting_payload"),
        "analysis_plan": analysis_plan,
        "limitations": [],
    }
    return response


def _attachment_workflows_from_execution(
    node_execution: dict[str, Any],
    *,
    structured_results: dict[str, Any],
    status: str,
) -> list[dict[str, Any]]:
    progress = (
        node_execution.get("progress")
        if isinstance(node_execution.get("progress"), dict)
        else {}
    )
    return build_attachment_workflows(
        attachments=[
            item
            for item in node_execution.get("attachments", [])
            if isinstance(item, dict)
        ],
        structured_results=structured_results,
        active_node=str(progress.get("active_node") or ""),
        overall_status=status,
        ocr_confirmation=(
            node_execution.get("ocr_confirmation")
            if isinstance(node_execution.get("ocr_confirmation"), dict)
            else None
        ),
    )


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
        supervisor_state = (
            node_execution.get("supervisor_state")
            if isinstance(node_execution.get("supervisor_state"), dict)
            else {}
        )
        fine_notice_intake = (
            supervisor_state.get("fine_notice_intake")
            if isinstance(supervisor_state.get("fine_notice_intake"), dict)
            else None
        )
        structured_results = dict(merged.get("structured_results") or {})
        attachment_workflows = _attachment_workflows_from_execution(
            node_execution,
            structured_results=structured_results,
            status=str(final_output.get("status") or "partial"),
        )
        return {
            "contract_version": "analysis_result.v2",
            "job_id": node_execution.get("job_id"),
            "status": str(final_output.get("status") or "partial"),
            "assistant_message": assistant_message,
            "structured_results": structured_results,
            "evidence": list(merged.get("evidence") or []),
            "limitations": list(merged.get("limitations") or []),
            "next_actions": list(merged.get("next_actions") or []),
            "deadline_guidance": dict(merged.get("deadline_guidance") or {}),
            "pending_questions": _merge_fine_notice_questions(
                merged.get("pending_questions"),
                fine_notice_intake,
            ),
            "cards": list(merged.get("cards") or []),
            "report_links": list(merged.get("report_links") or []),
            "supervisor_handoff": dict(node_execution.get("supervisor_handoff") or {}),
            "reporting_payload": dict(node_execution.get("reporting_payload") or {}),
            "fine_notice_intake": fine_notice_intake,
            "attachment_workflows": attachment_workflows,
        }
    reconstructed = _rebuild_persisted_supervisor_response(node_execution, executions)
    if reconstructed is not None:
        return reconstructed
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
    core_answer = "\n\n".join(_dedupe(summaries))
    answer = core_answer
    follow_up: dict[str, Any] | None = None
    if not answer:
        answer = "분석 결과를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요."
        core_answer = answer
    elif not any(item == "success" for item in statuses):
        # Not "no evidence" — a node can gather evidence (e.g. law_ground_search
        # finding provisions) but still flag low confidence via a non-success
        # status. Gate on whether *any* node fully succeeded, not on whether
        # evidence happens to be non-empty.
        follow_up = _needs_more_info_follow_up(node_execution)
        answer = f"{answer}\n\n{_follow_up_flat_text(follow_up)}"

    return {
        "contract_version": "analysis_result.v2",
        "job_id": node_execution.get("job_id"),
        "status": status,
        "assistant_message": {
            "answer": answer,
            "summary": answer,
            # Same text minus any appended follow-up prompt, so a UI that renders
            # `follow_up` separately doesn't have to duplicate it inside the bubble.
            "core_answer": core_answer,
            "follow_up": follow_up,
        },
        "structured_results": structured_results,
        "evidence": _dedupe_dicts(evidence, key="source_reference"),
        "limitations": _dedupe(limitations),
        "supervisor_handoff": dict(node_execution.get("supervisor_handoff") or {}),
        "reporting_payload": dict(node_execution.get("reporting_payload") or {}),
        "attachment_workflows": _attachment_workflows_from_execution(
            node_execution,
            structured_results=structured_results,
            status=status,
        ),
    }


def _rebuild_persisted_supervisor_response(
    node_execution: dict[str, Any],
    executions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Recover a safe final response when legacy persistence lacks the merge row."""

    upstream_results: dict[str, dict[str, Any]] = {}
    statuses: list[str] = []
    for execution in executions:
        output = execution.get("agent_output") if isinstance(execution.get("agent_output"), dict) else {}
        node_code = str(output.get("node_code") or execution.get("node_code") or "").strip()
        if not node_code:
            continue
        upstream_results[node_code] = output
        statuses.append(str(output.get("status") or "failed"))
    if "agent_result_validation" not in upstream_results:
        return None

    supervisor_state = (
        node_execution.get("supervisor_state")
        if isinstance(node_execution.get("supervisor_state"), dict)
        else {}
    )
    routing_intent = str(
        node_execution.get("routing_intent")
        or supervisor_state.get("routing_intent")
        or ""
    )
    evidence_only = routing_intent in {
        "accident_evidence_analysis",
        "accident_photo_evidence_analysis",
    }
    merged = merge_final_response(
        upstream_results,
        pending_questions=[
            item
            for item in supervisor_state.get("next_questions") or []
            if isinstance(item, dict)
        ],
        evidence_only=evidence_only,
        routing_intent=routing_intent,
        user_text=_user_text_from_supervisor_state(supervisor_state),
    )
    if not merged.get("structured_results"):
        return None
    status = _combined_status(statuses)
    structured_results = dict(merged.get("structured_results") or {})
    return {
        "contract_version": "analysis_result.v2",
        "job_id": node_execution.get("job_id"),
        "status": status,
        "assistant_message": dict(merged.get("assistant_message") or {}),
        "structured_results": structured_results,
        "evidence": list(merged.get("evidence") or []),
        "limitations": list(merged.get("limitations") or []),
        "next_actions": list(merged.get("next_actions") or []),
        "deadline_guidance": dict(merged.get("deadline_guidance") or {}),
        "pending_questions": list(merged.get("pending_questions") or []),
        "cards": list(merged.get("cards") or []),
        "report_links": list(merged.get("report_links") or []),
        "supervisor_handoff": dict(node_execution.get("supervisor_handoff") or {}),
        "reporting_payload": dict(node_execution.get("reporting_payload") or {}),
        "attachment_workflows": _attachment_workflows_from_execution(
            node_execution,
            structured_results=structured_results,
            status=status,
        ),
    }


def _needs_more_info_follow_up(node_execution: dict[str, Any]) -> dict[str, Any]:
    user_text = _user_text_from_supervisor_state(node_execution.get("supervisor_state"))
    attachments = [
        item for item in node_execution.get("attachments", []) if isinstance(item, dict)
    ]
    missing_categories = _missing_info_categories(user_text, attachments)
    if not missing_categories:
        return {"message": NO_MATCH_REPHRASE_PROMPT, "items": []}
    return {
        "message": "조금 더 구체적으로 알려주시면 이어서 확인해드릴게요.",
        "items": missing_categories,
    }


def _follow_up_flat_text(follow_up: dict[str, Any]) -> str:
    """Single-string fallback for consumers that only read assistant_message.answer/summary."""
    items = follow_up["items"]
    if not items:
        return follow_up["message"]
    required = [item["label"] for item in items if item["required"]]
    optional = [item["label"] for item in items if not item["required"]]
    parts = [follow_up["message"]]
    if required:
        parts.append(f"꼭 필요해요: {', '.join(required)}.")
    if optional:
        parts.append(f"알려주시면 더 좋아요: {', '.join(optional)}.")
    return " ".join(parts)


def _user_text_from_supervisor_state(supervisor_state: Any) -> str:
    if not isinstance(supervisor_state, dict):
        return ""
    for fact in supervisor_state.get("collected_facts") or []:
        if isinstance(fact, dict) and fact.get("field") == "user_text":
            return str(fact.get("value") or "")
    return ""


def _missing_info_categories(user_text: str, attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    has_notice_attachment = any(item.get("purpose") == "fine_notice" for item in attachments)
    missing: list[dict[str, Any]] = []
    if not any(keyword in user_text for keyword in _VIOLATION_TYPE_KEYWORDS):
        # Required: law_ground_search can't search meaningfully without knowing
        # what kind of violation/dispute this is.
        missing.append({"label": "정확한 위반·분쟁 유형", "required": True})
    if not _has_datetime_or_location(user_text):
        # Optional: narrows/improves the search (e.g. school-zone timing) but
        # a search can still run without it.
        missing.append({"label": "발생 일시와 장소", "required": False})
    if not has_notice_attachment and not any(keyword in user_text for keyword in _NOTICE_KEYWORDS):
        missing.append({"label": "받으신 고지서나 통지 내용", "required": False})
    return missing


def _normalize_input_safely(*, user_text: str, message_id: str) -> dict[str, Any]:
    try:
        return normalize_supervisor_input(
            user_text=user_text,
            source_message_id=message_id,
        )
    except Exception:
        logger.warning(
            "supervisor_input_normalization_failed",
            extra={"reason_code": "normalization_unavailable"},
        )
        return {
            "contract_version": NORMALIZED_INPUT_CONTRACT_VERSION,
            "policy_version": NORMALIZATION_POLICY_VERSION,
            "candidates": [],
            "clarifications": [],
        }


def _normalization_requires_input_hold(value: Mapping[str, Any]) -> bool:
    candidates = [
        item for item in value.get("candidates", []) if isinstance(item, Mapping)
    ]
    if any(item.get("decision") != "auto_applied" for item in candidates):
        return True
    values_by_field: dict[str, set[str]] = {}
    for item in candidates:
        field = str(item.get("field") or "")
        candidate_value = str(item.get("value") or "")
        if field and candidate_value:
            values_by_field.setdefault(field, set()).add(candidate_value)
    exclusive_fields = {
        "fine_type",
        "notice_stage",
        "vehicle_actions.self",
        "vehicle_actions.other",
    }
    return any(
        field in exclusive_fields and len(values) > 1
        for field, values in values_by_field.items()
    )


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


def _input_clarification_response(
    *,
    session_id: str,
    message_id: str,
    input_understanding: dict[str, Any],
) -> dict[str, Any]:
    question = str(input_understanding["message"])
    response = _needs_input_response(
        session_id=session_id,
        message_id=message_id,
    )
    response.update(
        {
            "routing_intent": "needs_clarification",
            "status": "needs_clarification",
            "assistant_message": {"answer": question, "summary": question},
            "progress": {
                "status": "needs_clarification",
                "active_node": "",
                "message": question,
            },
            "pending_questions": [
                {"field": "user_text", "question": question}
            ],
            "input_understanding": input_understanding["public_metadata"],
        }
    )
    response["analysis_plan"].update(
        {
            "routing_intent": "needs_clarification",
            "status": "needs_clarification",
            "steps": [],
        }
    )
    return response


def _normalization_needs_input_response(
    *,
    session_id: str,
    message_id: str,
    routing_intent: str,
    attachments: list[dict[str, Any]],
    input_normalization: dict[str, Any],
    pending_questions: list[dict[str, Any]],
) -> dict[str, Any]:
    response = _needs_input_response(session_id=session_id, message_id=message_id)
    question = str(pending_questions[0]["question"])
    response.update(
        {
            "routing_intent": routing_intent,
            "status": "needs_input",
            "assistant_message": {"answer": question, "summary": question},
            "progress": {
                "status": "needs_input",
                "active_node": "",
                "message": question,
            },
            "pending_questions": pending_questions,
            "attachments": attachments,
            "input_normalization": input_normalization,
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


def _merge_fine_notice_questions(
    existing: Any,
    intake: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    intake_questions = [
        dict(item)
        for item in (intake or {}).get("next_questions") or []
        if isinstance(item, Mapping) and str(item.get("field") or "").strip()
    ]
    other_questions = [
        dict(item)
        for item in existing or []
        if isinstance(item, Mapping) and str(item.get("field") or "").strip()
    ]
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*intake_questions, *other_questions]:
        field = str(item["field"]).strip()
        if field in seen:
            continue
        seen.add(field)
        merged.append(item)
    return merged


def _scope_guidance_response(
    *,
    session_id: str,
    message_id: str,
    routing_intent: str,
    attachments: list[dict[str, Any]],
    service_scope: dict[str, Any],
    input_normalization: dict[str, Any] | None,
) -> dict[str, Any]:
    message = str(service_scope["reason"])
    response = {
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
        "next_actions": list(service_scope["next_actions"]),
    }
    if input_normalization is not None:
        response["input_normalization"] = input_normalization
    return response


def _supervisor_unavailable_response(
    *,
    session_id: str,
    message_id: str,
    routing_intent: str,
    attachments: list[dict[str, Any]],
    supervisor_state: dict[str, Any],
    input_normalization: dict[str, Any],
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
        "input_normalization": input_normalization,
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
    input_normalization: dict[str, Any],
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
            "input_normalization": input_normalization,
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
    input_normalization: dict[str, Any],
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
        "input_normalization": input_normalization,
        "reporting_payload": None,
        "consultation_state": {
            "v2": consultation_state,
            "fact_state": fact_state,
            "promotion_gate": promotion_gate,
            "case_memory": dict(consultation_state.get("case_memory") or {}),
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


def _apply_ocr_confirmation_to_supervisor_state(
    supervisor_state: dict[str, Any],
    *,
    routing_intent: str,
    user_text: str,
    attachments: list[dict[str, Any]],
    ocr_confirmation: dict[str, Any],
) -> dict[str, Any]:
    """Keep fine-notice follow-up packages server-gated by user confirmation."""

    if routing_intent != "fine_notice_analysis":
        return supervisor_state

    state = dict(supervisor_state)
    packages = [
        dict(package)
        for package in state.get("agent_input_packages") or []
        if isinstance(package, dict)
        and package.get("node_code") not in {"law_ground_search", "appeal_decision_flow"}
    ]
    if not _has_valid_ocr_confirmation(ocr_confirmation):
        state["agent_input_packages"] = packages
        state["reporting_payload"] = None
        return state

    slot_state = state.get("slot_state") if isinstance(state.get("slot_state"), dict) else {}
    attachment_selectors = [
        {"attachment_id": str(attachment.get("attachment_id"))}
        for attachment in attachments
        if str(attachment.get("attachment_id") or "").strip()
    ]
    existing_codes = {str(package.get("node_code") or "") for package in packages}
    confirmed_fields = (
        ocr_confirmation.get("fields")
        if isinstance(ocr_confirmation.get("fields"), dict)
        else {}
    )
    law_code = str(confirmed_fields.get("law_code") or "").strip()
    violation_text = str(confirmed_fields.get("violation_text") or "").strip()
    law_search_query = " ".join(
        value for value in (law_code, violation_text) if value
    )
    for node_code in ("law_ground_search", "appeal_decision_flow"):
        if node_code in existing_codes:
            continue
        package_payload = {
            "user_text": user_text,
            "attachments": attachment_selectors,
            "slot_state": slot_state,
        }
        if node_code == "law_ground_search":
            if law_code:
                package_payload["law_code"] = law_code
            if law_search_query:
                package_payload["search_query"] = law_search_query
            if violation_text:
                package_payload["violation_text"] = violation_text
        packages.append(
            {
                "schema_version": "agent_input_schema.v1",
                "node_code": node_code,
                "status": "ready",
                "required_inputs": ["user_text|attachments"],
                "payload": package_payload,
            }
        )
    enriched_packages: list[dict[str, Any]] = []
    for package in packages:
        enriched, error = enrich_agent_package(package)
        if error or enriched is None:
            state["llm"] = {
                **(
                    state.get("llm")
                    if isinstance(state.get("llm"), dict)
                    else {}
                ),
                "status": "failed",
                "reason": error or "invalid_agent_package",
            }
            state["agent_input_packages"] = []
            state["reporting_payload"] = None
            return state
        enriched_packages.append(enriched)
    state["agent_input_packages"] = enriched_packages
    return state


def _fallback_supervisor_state(payload: dict[str, Any], routing_intent: str) -> dict[str, Any]:
    user_text = str(payload.get("user_text") or "").strip()
    ocr_confirmation = _normalized_ocr_confirmation(payload.get("ocr_confirmation"))
    report_requested = _report_requested_for_payload(
        payload,
        user_text=user_text,
        routing_intent=routing_intent,
        ocr_confirmation=ocr_confirmation,
    )
    node_codes = plan_node_codes(routing_intent, report_requested=report_requested)
    public_node_codes = [code for code in node_codes if code in PUBLIC_AGENT_NODE_CODES]
    projected_slot_state = normalized_slot_state(
        payload.get("input_normalization") or {}
    )
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
            },
            **dict(projected_slot_state.get("slots") or {}),
        },
    }
    return {
        "contract_version": "supervisor_conversation_state.v2",
        "scenario": routing_intent,
        "stage": "agent_execution_ready",
        "conversation_turn_count": len(payload.get("conversation_history") or []) + 1,
        "conversation_summary": user_text,
        "collected_facts": [{"field": "user_text", "value": user_text}] if user_text else [],
        "fact_conflicts": [],
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
                    "attachments": canonical_attachment_selectors(payload.get("attachments", [])),
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


def _report_requested_for_payload(
    payload: Mapping[str, Any],
    *,
    user_text: str,
    routing_intent: str,
    ocr_confirmation: Mapping[str, Any] | None,
) -> bool:
    requested = (
        report_generation_requested(user_text)
        or payload.get("_server_report_generation_requested") is True
    )
    if routing_intent in {
        "accident_evidence_analysis",
        "accident_photo_evidence_analysis",
    }:
        return False
    if routing_intent == "fine_notice_analysis":
        return _has_valid_ocr_confirmation(ocr_confirmation)
    return requested


def _fallback_accident_supervisor_state(
    payload: dict[str, Any],
    routing_intent: str,
) -> dict[str, Any]:
    explicit_fact_fields = _explicit_accident_fact_fields(payload)
    fact_state = reduce_consultation_fact_state(
        {
            **payload,
            "fact_candidates": [
                *[
                    item
                    for item in payload.get("fact_candidates") or []
                    if isinstance(item, dict)
                ],
                *[
                    item
                    for item in accident_fact_candidates(
                        payload.get("input_normalization") or {},
                        source_message_id=str(
                            payload.get("message_id")
                            or payload.get("session_id")
                            or ""
                        ),
                    )
                    if item.get("field") not in explicit_fact_fields
                ],
            ],
        }
    )
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
        "fact_conflicts": list(fact_state["conflicts"]),
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


def _explicit_accident_fact_fields(payload: Mapping[str, Any]) -> set[str]:
    facts = payload.get("facts")
    if not isinstance(facts, Mapping):
        return set()
    allowed = {field for field, _question in CORE_FACT_QUESTIONS}
    return {
        str(field)
        for field, value in facts.items()
        if str(field) in allowed and str(value or "").strip()
    }


def _analysis_plan(
    *,
    session_id: str,
    message_id: str,
    routing_intent: str,
    supervisor_state: dict[str, Any],
    report_requested: bool,
    ocr_confirmation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_confirmation = _normalized_ocr_confirmation(ocr_confirmation)
    node_codes = list(plan_node_codes(routing_intent, report_requested=report_requested))
    if routing_intent == "fine_notice_analysis" and _has_valid_ocr_confirmation(normalized_confirmation):
        validation_index = node_codes.index("agent_result_validation")
        node_codes[validation_index:validation_index] = [
            "law_ground_search",
            "appeal_decision_flow",
        ]
    expected_node_codes = [code for code in node_codes if code in PUBLIC_AGENT_NODE_CODES]
    evidence_only = routing_intent in {
        "accident_evidence_analysis",
        "accident_photo_evidence_analysis",
    }
    steps = []
    previous_node: str | None = None
    for order, node_code in enumerate(node_codes, start=1):
        context: dict[str, Any] = {"routing_intent": routing_intent}
        if routing_intent == "fine_notice_analysis":
            context["ocr_confirmation"] = normalized_confirmation
        if node_code == "agent_result_validation":
            context.update(
                {
                    "expected_node_codes": expected_node_codes,
                    "report_requested": report_requested,
                    "evidence_only": evidence_only,
                }
            )
        elif node_code == "final_response_merge":
            context.update(
                {
                    "pending_questions": list(supervisor_state.get("next_questions") or []),
                    "evidence_only": evidence_only,
                }
            )
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

