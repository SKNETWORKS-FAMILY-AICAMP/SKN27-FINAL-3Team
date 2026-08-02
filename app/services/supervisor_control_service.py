"""Deterministic internal control nodes used by the canonical Supervisor."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services.consultation_v2_service import CORE_FACT_QUESTIONS
from app.services.deadline_guidance_service import build_deadline_guidance
from app.services.fine_notice_intake_service import FINE_NOTICE_QUESTIONS
from app.services.law_ground_contract import normalize_law_structured_result
from app.services.public_law_projection_service import project_public_law_items
from app.services.fact_conflict_service import normalize_fact_conflicts
from app.services.supervisor_routing_service import agent_result_validation_policy


QUESTION_BY_FIELD = dict(CORE_FACT_QUESTIONS)
FIELD_BY_QUESTION = {question: field for field, question in CORE_FACT_QUESTIONS}
SUPERVISOR_INTERNAL_NODE_CODES = {
    "input_context_validation",
    "consultation_fact_state_reducer",
    "case_promotion_gate",
    "agent_result_validation",
    "final_response_merge",
}
_VALIDATION_POLICY = agent_result_validation_policy()
EVIDENCE_REQUIRED_NODE_CODES = _VALIDATION_POLICY["evidence_required_node_codes"]
REPORT_REQUIRED_NODES = _VALIDATION_POLICY["report_required_nodes"]
PARTIAL_RESULT_INTENTS = _VALIDATION_POLICY["partial_result_intents"]
EVIDENCE_ONLY_NOTICE = (
    "영상과 참고 근거를 증거 검토용으로 정리했습니다. "
    "이 결과는 과실비율, 법적 책임, 최종 사고유형을 확정하지 않습니다."
)


def reduce_consultation_fact_state(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge structured facts and question/answer turns without guessing facts."""

    facts: dict[str, dict[str, Any]] = {}
    conflicts = normalize_fact_conflicts(payload.get("fact_conflicts"))
    sources = _source_by_field(payload.get("fact_sources"))
    for field, raw_value in _dict(payload.get("facts")).items():
        if field not in QUESTION_BY_FIELD:
            continue
        record = _fact_record_from_input(field, raw_value, sources.get(field))
        if record:
            facts[field] = record

    for candidate in _fact_candidates(payload.get("fact_candidates")):
        _merge_fact_candidate(facts, conflicts, candidate)

    for candidate in _question_answer_candidates(payload.get("conversation_history")):
        _merge_fact_candidate(facts, conflicts, candidate)

    conflicts = normalize_fact_conflicts(conflicts)
    conflict_fields = {_text(item.get("field")) for item in conflicts}
    missing_fields = [
        field
        for field in QUESTION_BY_FIELD
        if field not in facts or field in conflict_fields
    ]
    return {
        "schema_version": "consultation_fact_state.v1",
        "facts": facts,
        "fact_values": {field: record["value"] for field, record in facts.items()},
        "conflicts": conflicts,
        "missing_fields": missing_fields,
    }


def evaluate_case_promotion(
    consultation_state: dict[str, Any],
    *,
    analysis_requested: bool,
    authenticated: bool,
    storage_consent: bool,
    facts_confirmed: bool = True,
) -> dict[str, Any]:
    risk_level = _text(_dict(consultation_state.get("risk_gate")).get("level"))
    readiness = _dict(consultation_state.get("readiness"))
    missing_fields = _string_list(readiness.get("missing_fields"))
    conflict_fields = _string_list(readiness.get("conflict_fields"))
    if risk_level == "high_risk":
        decision = "expert_handoff"
        requirements = ["emergency_and_expert_review"]
    elif (
        missing_fields
        or conflict_fields
        or not bool(readiness.get("ready_for_fault_range"))
    ):
        decision = "ask_more"
        requirements = [
            *[f"fact_conflict:{field}" for field in conflict_fields],
            *[
                f"fact:{field}"
                for field in missing_fields
                if field not in conflict_fields
            ],
        ]
    elif not analysis_requested:
        decision = "stay_in_chat"
        requirements = []
    else:
        decision = "ready_for_case"
        requirements = []
        if not facts_confirmed:
            requirements.append("fact_confirmation")
        if not authenticated:
            requirements.append("authentication")
        if not storage_consent:
            requirements.append("case_storage_consent")
    return {
        "schema_version": "case_promotion_gate.v1",
        "decision": decision,
        "requirements": requirements,
        "automatic_case_creation": False,
        "case_api_required": decision == "ready_for_case",
    }


def validate_agent_results(
    upstream_results: dict[str, Any],
    *,
    routing_intent: str,
    expected_node_codes: list[str] | tuple[str, ...],
    report_requested: bool,
    evidence_only: bool = False,
) -> dict[str, Any]:
    expected = [
        code
        for code in expected_node_codes
        if code not in SUPERVISOR_INTERNAL_NODE_CODES and code != "objection_report_generation"
    ]
    accepted: list[str] = []
    rejected: list[dict[str, str]] = []
    limitations: list[str] = []
    statuses: dict[str, str] = {}

    for node_code in expected:
        output = _agent_output(upstream_results.get(node_code))
        reason = _result_rejection_reason(node_code, output)
        if reason:
            rejected.append({"node_code": node_code, "reason": reason})
            continue
        accepted.append(node_code)
        statuses[node_code] = _text(output.get("status"))
        limitations.extend(_string_list(output.get("limitations")))

    required_for_report = REPORT_REQUIRED_NODES.get(routing_intent, set())
    report_ready = (
        report_requested
        and bool(required_for_report)
        and required_for_report.issubset(set(accepted))
        and not rejected
        and all(statuses.get(node_code) == "success" for node_code in required_for_report)
    )
    missing_results = [
        item["node_code"]
        for item in rejected
        if item["reason"] == "result_missing"
    ]
    return {
        "merge_ready": bool(accepted),
        "result_status": (
            "partial"
            if evidence_only or routing_intent in PARTIAL_RESULT_INTENTS
            else "success" if accepted and not rejected else "partial"
        ),
        "report_ready": report_ready,
        "accepted_results": accepted,
        "rejected_results": rejected,
        "missing_fields": [f"agent_result:{node_code}" for node_code in missing_results],
        "limitations": _dedupe_strings(limitations),
    }


def merge_final_response(
    upstream_results: dict[str, Any],
    *,
    pending_questions: list[dict[str, Any]] | None = None,
    evidence_only: bool = False,
    routing_intent: str = "",
    user_text: str = "",
) -> dict[str, Any]:
    validation = _agent_output(upstream_results.get("agent_result_validation"))
    validation_result = _dict(validation.get("structured_result"))
    accepted = _string_list(validation_result.get("accepted_results"))
    summaries: list[str] = []
    evidence: list[dict[str, Any]] = []
    limitations = _string_list(validation_result.get("limitations"))
    structured_results: dict[str, dict[str, Any]] = {}

    for node_code in accepted:
        output = _agent_output(upstream_results.get(node_code))
        summary = _text(output.get("summary"))
        if summary:
            summaries.append(summary)
        structured_result = _dict(output.get("structured_result"))
        if node_code == "law_ground_search" and structured_result.get("law_provisions"):
            # Completed jobs are recomposed from persisted AgentResult rows.
            # Normalize again here so legacy/raw agent fields such as
            # source_name and article_no render identically to live adapter
            # output instead of falling back to its retrieval-count summary.
            structured_result = normalize_law_structured_result(structured_result)
        structured_results[node_code] = structured_result
        evidence.extend(_dict_list(output.get("evidence")))
        limitations.extend(_string_list(output.get("limitations")))

    report_output = _agent_output(upstream_results.get("objection_report_generation"))
    if (
        not evidence_only
        and report_output
        and _text(report_output.get("status")) in {"success", "partial"}
    ):
        report_summary = _text(report_output.get("summary"))
        if report_summary:
            summaries.append(report_summary)
        structured_results["objection_report_generation"] = _dict(
            report_output.get("structured_result")
        )
        evidence.extend(_dict_list(report_output.get("evidence")))
        limitations.extend(_string_list(report_output.get("limitations")))

    questions = _dict_list(pending_questions)
    unavailable_guidance = (
        _verified_result_unavailable_guidance(
            routing_intent=routing_intent,
            user_text=user_text,
        )
        if not accepted
        else {}
    )
    if not accepted and not questions and unavailable_guidance:
        questions = _dict_list(unavailable_guidance.get("pending_questions"))
        limitations.extend(_string_list(unavailable_guidance.get("limitations")))
    deadline_guidance = None
    if evidence_only:
        cards = []
    else:
        try:
            cards = _result_cards(
                accepted,
                upstream_results,
                routing_intent=routing_intent,
            )
        except Exception:
            cards = []
            limitations.append(
                "Verified result cards are temporarily unavailable; review persisted agent results."
            )
        try:
            deadline_guidance = _deadline_guidance(accepted, structured_results)
        except Exception:
            deadline_guidance = None
            limitations.append(
                "Verified deadline guidance is temporarily unavailable; review persisted agent results."
            )
    if deadline_guidance and deadline_guidance["status"] != "normal":
        cards.insert(
            0,
            {
                "card_type": "deadline_guidance",
                "status": (
                    "success"
                    if deadline_guidance["status"] == "due_soon"
                    else "partial"
                ),
                "title": deadline_guidance["card_title"],
                "summary": deadline_guidance["reason"],
            },
        )
        limitations.extend(_string_list(deadline_guidance["limitations"]))
    fine_notice_answer = (
        _fine_notice_procedure_answer(structured_results)
        if routing_intent == "fine_notice_procedure"
        and "law_ground_search" in accepted
        else ""
    )
    if evidence_only:
        answer = EVIDENCE_ONLY_NOTICE
    elif fine_notice_answer:
        answer = fine_notice_answer
    elif summaries:
        answer = "\n\n".join(_dedupe_strings(summaries))
    elif questions:
        answer = (
            _text(unavailable_guidance.get("answer"))
            if unavailable_guidance
            else _text(questions[0].get("question"))
        ) or "사실관계를 추가로 알려주세요."
    else:
        answer = "검증을 통과한 분석 결과가 없습니다. 입력 자료와 근거를 확인한 뒤 다시 시도해 주세요."

    next_actions = (
        ["review_evidence_with_case_and_law_sources"]
        if evidence_only
        else
        _string_list(deadline_guidance["next_actions"])
        if deadline_guidance and deadline_guidance["status"] != "normal"
        else _string_list(unavailable_guidance.get("next_actions"))
        if unavailable_guidance
        else ["answer_pending_question"] if questions else ["review_verified_results"]
    )
    if (
        routing_intent in {"fine_notice_procedure", "fine_notice_analysis"}
        and "law_ground_search" in structured_results
    ):
        structured_results["law_ground_search"] = {
            "matched_laws": project_public_law_items(
                structured_results["law_ground_search"]
            )
        }
    return _build_final_response_payload(
        answer=answer,
        structured_results=structured_results,
        evidence=evidence,
        limitations=limitations,
        deadline_guidance=deadline_guidance,
        pending_questions=questions,
        cards=cards,
        next_actions=next_actions,
        fallback_answer=(
            EVIDENCE_ONLY_NOTICE
            if evidence_only
            else "\n\n".join(_dedupe_strings(summaries))
            if summaries
            else "Verified response aggregation is temporarily unavailable; review persisted agent results."
        ),
    )


def _verified_result_unavailable_guidance(
    *,
    routing_intent: str,
    user_text: str,
) -> dict[str, Any]:
    if routing_intent != "fine_notice_procedure":
        return {}

    emergency_context = any(
        marker in user_text
        for marker in ("응급", "병원", "진료", "아파", "고열", "구급")
    )
    pending_questions = [
        {"field": field, "question": question}
        for field, question in FINE_NOTICE_QUESTIONS.items()
    ]
    if emergency_context:
        pending_questions.append(
            {
                "field": "emergency_evidence",
                "question": "응급상황을 확인할 수 있는 진료기록이나 영수증이 있나요?",
            }
        )
    evidence_guidance = (
        "응급상황을 확인할 자료(진료기록·영수증 등)를 확보한 뒤 "
        if emergency_context
        else "정차 또는 위반 당시 사정을 확인할 자료를 확보한 뒤 "
    )
    return {
        "answer": (
            "단속 여부를 지금 확정할 수 없습니다. 실제 고지서나 단속 통지를 받았다면 "
            "발급기관과 의견제출·이의신청 기한을 먼저 확인하세요. 정차 시각·장소와 "
            f"불가피했던 사정을 시간순으로 정리하고, {evidence_guidance}"
            "관할기관에 적용 가능한 절차를 문의하세요. 검증된 법령 검색 결과가 "
            "확보되기 전에는 단속 제외나 처분 취소를 단정할 수 없습니다."
        ),
        "pending_questions": pending_questions,
        "limitations": [
            "현재 실행에서는 검증 가능한 법령 검색 결과를 확보하지 못했습니다.",
            "일반적인 준비 순서이며 실제 단속 제외나 처분 취소를 보장하지 않습니다.",
        ],
        "next_actions": [
            "verified_law_evidence_unavailable",
            (
                "collect_notice_and_emergency_evidence"
                if emergency_context
                else "collect_notice_details_and_evidence"
            ),
        ],
    }


def run_supervisor_control_node(
    node_code: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    context = _dict(payload.get("context"))
    upstream_results = _dict(payload.get("upstream_results"))
    if node_code == "input_context_validation":
        user_text = _text(payload.get("user_text"))
        attachments = _dict_list(payload.get("attachments"))
        missing = [] if user_text or attachments else ["user_text|attachments"]
        return {
            "status": "success" if not missing else "partial",
            "summary": "사용자 입력과 첨부 입력 경계를 검증했습니다.",
            "structured_result": {
                "input_summary": user_text,
                "routing_intent": context.get("routing_intent"),
                "missing_fields": missing,
            },
            "limitations": [],
        }
    if node_code == "consultation_fact_state_reducer":
        reduced = reduce_consultation_fact_state(payload)
        return {
            "status": "success" if not reduced["conflicts"] else "partial",
            "summary": "대화에서 확인된 사고 사실을 병합했습니다.",
            "structured_result": reduced,
            "limitations": [],
        }
    if node_code == "case_promotion_gate":
        promotion = evaluate_case_promotion(
            _dict(context.get("consultation_state")),
            analysis_requested=bool(context.get("analysis_requested")),
            authenticated=bool(context.get("authenticated")),
            storage_consent=bool(context.get("storage_consent")),
            facts_confirmed=bool(context.get("facts_confirmed")),
        )
        return {
            "status": "success" if promotion["decision"] == "ready_for_case" else "partial",
            "summary": "상담을 정식 사건으로 전환할 수 있는지 확인했습니다.",
            "structured_result": promotion,
            "limitations": [],
        }
    if node_code == "agent_result_validation":
        validated = validate_agent_results(
            upstream_results,
            routing_intent=_text(context.get("routing_intent")),
            expected_node_codes=_string_list(context.get("expected_node_codes")),
            report_requested=bool(context.get("report_requested")),
            evidence_only=bool(context.get("evidence_only")),
        )
        return {
            "status": validated["result_status"],
            "summary": "에이전트 결과의 상태, 근거, 병합 및 보고서 준비 조건을 검증했습니다.",
            "structured_result": validated,
            "limitations": validated["limitations"],
        }
    if node_code == "final_response_merge":
        merged = merge_final_response(
            upstream_results,
            pending_questions=_dict_list(context.get("pending_questions")),
            evidence_only=bool(context.get("evidence_only")),
            routing_intent=_text(context.get("routing_intent")),
            user_text=_text(payload.get("user_text")),
        )
        return {
            "status": "partial" if context.get("evidence_only") else "success" if merged["structured_results"] else "partial",
            "summary": merged["assistant_message"]["summary"],
            "structured_result": merged,
            "evidence": merged["evidence"],
            "limitations": merged["limitations"],
            "next_actions": merged["next_actions"],
        }
    raise ValueError(f"unsupported_supervisor_control_node:{node_code}")


def _question_answer_candidates(history: Any) -> list[dict[str, Any]]:
    turns = _dict_list(history)
    candidates: list[dict[str, Any]] = []
    pending_field = ""
    for index, turn in enumerate(turns):
        role = _text(turn.get("role")).lower()
        content = _text(turn.get("content"))
        if role == "assistant":
            pending_field = next(
                (field for question, field in FIELD_BY_QUESTION.items() if question in content),
                "",
            )
            continue
        if role != "user" or not pending_field or not content:
            continue
        candidates.append(
            {
                "field": pending_field,
                "value": content,
                "source_message_id": _text(turn.get("message_id")) or f"history:{index}",
                "confidence": 1.0,
                "confirmed": True,
            }
        )
        pending_field = ""
    return candidates


def _fact_candidates(value: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in _dict_list(value):
        field = _text(item.get("field"))
        candidate_value = item.get("value")
        if field not in QUESTION_BY_FIELD or not _text(candidate_value):
            continue
        confidence = item.get("confidence", 0.0)
        candidates.append(
            {
                "field": field,
                "value": deepcopy(candidate_value),
                "source_message_id": _text(item.get("source_message_id")) or "supervisor:fact_candidate",
                "confidence": confidence if isinstance(confidence, (int, float)) else 0.0,
                "confirmed": bool(item.get("confirmed", False)),
            }
        )
    return candidates


def _merge_fact_candidate(
    facts: dict[str, dict[str, Any]],
    conflicts: list[dict[str, Any]],
    candidate: dict[str, Any],
) -> None:
    field = candidate["field"]
    existing = facts.get(field)
    if existing and _normalized(existing.get("value")) != _normalized(candidate["value"]):
        conflict = {
            "field": field,
            "candidates": [
                {
                    "value": _text(existing.get("value")),
                    "source_message_id": _text(existing.get("source_message_id")),
                    "confidence": existing.get("confidence", 1.0),
                },
                {
                    "value": _text(candidate.get("value")),
                    "source_message_id": _text(candidate.get("source_message_id")),
                    "confidence": candidate.get("confidence", 1.0),
                },
            ],
        }
        conflicts[:] = normalize_fact_conflicts([*conflicts, conflict])
        return
    if existing and existing.get("confirmed") and not candidate.get("confirmed"):
        return
    facts[field] = candidate


def _fact_record_from_input(
    field: str,
    value: Any,
    source: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if isinstance(value, dict) and "value" in value:
        raw_value = value.get("value")
        source_message_id = _text(value.get("source_message_id"))
        confidence = value.get("confidence", 1.0)
        confirmed = bool(value.get("confirmed", False))
    else:
        raw_value = value
        source_message_id = ""
        confidence = 1.0
        confirmed = False
    if not _text(raw_value):
        return None
    source = source or {}
    source_type = _text(source.get("source_type"))
    return {
        "field": field,
        "value": deepcopy(raw_value),
        "source_message_id": source_message_id or _text(source.get("source_message_id")) or "payload:facts",
        "confidence": confidence,
        "confirmed": confirmed or source_type == "user_confirmation",
    }


def _result_rejection_reason(node_code: str, output: dict[str, Any]) -> str:
    if not output:
        return "result_missing"
    status = _text(output.get("status"))
    if status not in {"success", "partial"}:
        return "result_failed"
    if not isinstance(output.get("structured_result"), dict):
        return "structured_result_invalid"
    if node_code in EVIDENCE_REQUIRED_NODE_CODES and not _dict_list(output.get("evidence")):
        return "required_evidence_missing"
    return ""


def _agent_output(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    nested = value.get("agent_output")
    return dict(nested) if isinstance(nested, dict) else dict(value)


def _result_cards(
    accepted: list[str],
    upstream_results: dict[str, Any],
    *,
    routing_intent: str = "",
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for node_code in accepted:
        output = _agent_output(upstream_results.get(node_code))
        structured_result = _dict(output.get("structured_result"))
        law_entries = _law_provision_entries(structured_result)
        if (
            routing_intent == "fine_notice_procedure"
            and node_code == "law_ground_search"
            and law_entries
        ):
            cards.append(
                {
                    "card_type": "verified_law_result",
                    "node_code": node_code,
                    "status": output.get("status"),
                    "title": "확인된 관련 법령",
                    "summary": " · ".join(label for label, _detail in law_entries),
                }
            )
            continue
        cards.append(
            {
                "card_type": "verified_agent_result",
                "node_code": node_code,
                "status": output.get("status"),
                "summary": output.get("summary"),
            }
        )
    return cards


def _fine_notice_procedure_answer(structured_results: dict[str, dict[str, Any]]) -> str:
    """Render verified law retrieval as safe, readable next steps.

    This intentionally avoids calculating a deadline or deciding whether an
    objection will succeed.  Those require the notice itself and, where
    applicable, the dedicated OCR/appeal workflow.
    """

    law_entries = _law_provision_entries(structured_results.get("law_ground_search"))
    if not law_entries:
        return ""
    conditions = _string_list(
        _dict(structured_results.get("law_ground_search")).get(
            "applicable_conditions"
        )
    )
    lines = [
        "과태료 고지서를 받으셨다면 다음 순서로 확인해 보세요.",
        "1. 고지서에 적힌 처분명·위반 일시와 장소·적용 법조문을 실제 사실과 대조하세요.",
        "2. 다툴 사유가 있으면 당시 사진·영상과 관련 영수증·기록을 원본으로 보관하세요.",
        "3. 의견제출 또는 이의제기 방법은 발급기관 안내를 확인하고, 기한은 고지서에 기재된 기한을 기준으로 판단하세요.",
        "관련 법령 근거(참고)",
        *[
            f"- {label}{f': {detail}' if detail else ''}"
            for label, detail in law_entries
        ],
    ]
    if conditions:
        lines.append(f"적용 전 확인: {conditions[0]}")
    return "\n".join(lines)


def _law_provision_entries(value: Any) -> list[tuple[str, str]]:
    structured_result = _dict(value)
    entries: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in project_public_law_items(structured_result):
        law_name = _text(item.get("law_name"))
        article = _text(item.get("article"))
        label = " ".join(part for part in (law_name, article) if part)
        if not label:
            continue
        detail = _text(item.get("summary"))
        entry = (label, detail)
        if entry not in seen:
            seen.add(entry)
            entries.append(entry)
    return entries


def _deadline_guidance(
    accepted: list[str],
    structured_results: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if "appeal_decision_flow" not in accepted:
        return None
    return build_deadline_guidance(
        structured_results.get("appeal_decision_flow") or {},
        source_node_code="appeal_decision_flow",
    )


def _build_final_response_payload(
    *,
    answer: str,
    structured_results: dict[str, dict[str, Any]],
    evidence: list[dict[str, Any]],
    limitations: list[str],
    deadline_guidance: dict[str, Any] | None,
    pending_questions: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    next_actions: list[str],
    fallback_answer: str,
) -> dict[str, Any]:
    try:
        return {
            "assistant_message": {"answer": answer, "summary": answer},
            "structured_results": structured_results,
            "evidence": _dedupe_evidence(evidence),
            "limitations": _dedupe_strings(limitations),
            "deadline_guidance": deadline_guidance,
            "pending_questions": pending_questions,
            "cards": cards,
            "report_links": [],
            "next_actions": next_actions,
        }
    except Exception:
        fallback_limitations = list(limitations)
        fallback_limitations.append(
            "Verified response aggregation is temporarily unavailable; review persisted agent results."
        )
        return {
            "assistant_message": {
                "answer": fallback_answer,
                "summary": fallback_answer,
            },
            "structured_results": structured_results,
            "evidence": _dict_list(evidence),
            "limitations": _dedupe_strings(fallback_limitations),
            "deadline_guidance": None,
            "pending_questions": pending_questions,
            "cards": [],
            "report_links": [],
            "next_actions": next_actions or ["review_verified_results"],
        }


def _source_by_field(value: Any) -> dict[str, dict[str, Any]]:
    return {
        _text(item.get("field")): item
        for item in _dict_list(value)
        if _text(item.get("field"))
    }


def _dedupe_evidence(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        identity = _text(value.get("source_reference")) or repr(sorted(value.items()))
        if identity in seen:
            continue
        seen.add(identity)
        result.append(value)
    return result


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if _text(value)))


def _normalized(value: Any) -> str:
    normalized = "".join(_text(value).lower().split()).rstrip(".,!?…。！？")
    for sentence_ending in ("이었습니다", "였습니다", "입니다"):
        if normalized.endswith(sentence_ending):
            return normalized[: -len(sentence_ending)]
    return normalized


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value or [] if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    return [_text(item) for item in value or [] if _text(item)]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""
