"""Sync adapter for objection form and report-action generation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import os
from typing import Any

from app.security.pii_masking import sanitize_pii


logger = logging.getLogger(__name__)

_PETITION_SYSTEM_PROMPT = (
    "당신은 과태료 처분에 대한 이의신청서 초안을 작성하는 보조 도구입니다. "
    "아래 JSON에 제공된 사실관계와 법령 근거만 사용하여 신청취지와 신청이유를 작성하세요. "
    "제공되지 않은 사실을 만들거나 추측하지 말고, missing_fields가 있으면 사용자의 확인이 필요하다고 명시하세요. "
    "결과는 반드시 다음 JSON 스키마로만 반환하세요: "
    '{"petition_purpose":"신청취지 문장","petition_reason":"신청이유 문장"}'
)


TRAFFIC_ACCIDENT_DOCX_TYPE = "traffic_accident_objection_docx"

TRAFFIC_ACCIDENT_REQUIRED_FIELDS: tuple[dict[str, str], ...] = (
    {
        "field": "applicant_name",
        "label": "신청인 성명",
        "question": "이의신청서에 기재할 신청인 성명을 알려주세요.",
    },
    {
        "field": "recipient",
        "label": "수신 기관",
        "question": "이의신청서를 제출할 경찰서 또는 담당 기관을 알려주세요.",
    },
    {
        "field": "case_number",
        "label": "사건번호 / 접수번호",
        "question": "경찰 조사결과 통지서에 적힌 사건번호 또는 접수번호를 알려주세요.",
    },
    {
        "field": "incident_at",
        "label": "사고 일시",
        "question": "사고가 발생한 날짜와 시간을 알려주세요.",
    },
    {
        "field": "location",
        "label": "사고 장소",
        "question": "사고 장소를 도로명, 교차로명 등으로 구체적으로 알려주세요.",
    },
    {
        "field": "police_station",
        "label": "담당 경찰서",
        "question": "최초 조사를 담당한 경찰서를 알려주세요.",
    },
    {
        "field": "investigation_result_summary",
        "label": "기존 조사결과",
        "question": "경찰 조사결과에서 어떤 판단을 받았는지 핵심 내용을 알려주세요.",
    },
    {
        "field": "objection_points",
        "label": "이의신청 쟁점",
        "question": "기존 조사결과 중 어떤 판단이 잘못되었다고 보는지 알려주세요.",
    },
    {
        "field": "specific_request",
        "label": "구체적 요청사항",
        "question": "재검토, 현장 재조사, 블랙박스 확인 등 원하는 조치를 알려주세요.",
    },
)


def run_objection_report_generation(
    agent_input: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    node = context.get("node") if isinstance(context.get("node"), dict) else {}
    handoff_error = _strict_handoff_error(agent_input)
    if handoff_error:
        return _output(
            agent_input=agent_input,
            node=node,
            status="failed",
            summary="Persisted Supervisor reporting handoff validation failed.",
            structured_result={
                "document_type": "objection_form",
                "form_sections": [],
                "report_actions": [],
                "error_code": handoff_error,
                "readiness": {
                    "ready_for_download": False,
                    "requires_user_review": True,
                },
            },
            evidence=[],
            next_actions=["rebuild_supervisor_reporting_handoff"],
            limitations=["Reporting did not run without a valid persisted Supervisor handoff."],
        )
    notice_output = _upstream_output(agent_input, "fine_notice_analysis")
    text_ml_output = _upstream_output(agent_input, "text_ml_case_search")
    law_output = _upstream_output(agent_input, "law_ground_search")
    appeal_output = _upstream_output(agent_input, "appeal_decision_flow")
    notice_result = _structured_result(notice_output)
    text_ml_result = _structured_result(text_ml_output)
    law_result = _structured_result(law_output)
    appeal_result = _structured_result(appeal_output)
    user_facts = _user_facts(agent_input)
    document_variant = _document_variant(notice_result, text_ml_result)

    missing_fields = _missing_fields(
        notice_result=notice_result,
        text_ml_result=text_ml_result,
        law_result=law_result,
        user_facts=user_facts,
        document_variant=document_variant,
    )
    legal_grounds = _legal_grounds(law_result)
    recipient_agency = _recipient_agency(agent_input, notice_result, document_variant)
    case_summary = _case_summary(
        notice_result=notice_result,
        text_ml_result=text_ml_result,
        user_facts=user_facts,
        document_variant=document_variant,
    )
    objection_reasons = _objection_reasons(
        notice_result=notice_result,
        text_ml_result=text_ml_result,
        legal_grounds=legal_grounds,
        appeal_result=appeal_result,
        user_facts=user_facts,
        missing_fields=missing_fields,
        document_variant=document_variant,
    )
    requested_action = _requested_action(document_variant)
    required_attachments = _required_attachments(
        agent_input=agent_input,
        notice_result=notice_result,
        text_ml_result=text_ml_result,
        document_variant=document_variant,
    )
    form_data = _objection_form_data(
        agent_input=agent_input,
        text_ml_result=text_ml_result,
        recipient_agency=recipient_agency,
        case_summary=case_summary,
        requested_action=requested_action,
        objection_reasons=objection_reasons,
        required_attachments=required_attachments,
        document_variant=document_variant,
    )
    if document_variant == "fine_notice":
        form_data = _fine_notice_form_data(
            agent_input=agent_input,
            notice_result=notice_result,
            recipient_agency=recipient_agency,
        )
    document_readiness = _document_readiness(
        form_data=form_data,
        document_variant=document_variant,
        require_docx_fields=_requires_docx_fields(agent_input),
    )
    document_missing_fields = [
        item["field"]
        for item in document_readiness["missing_field_details"]
    ]
    combined_missing_fields = _unique([*missing_fields, *document_missing_fields])
    appeal_decision = _appeal_decision(appeal_result)
    appeal_gate = _appeal_gate(appeal_decision)
    petition_purpose = ""
    petition_reason = ""
    drafting_source = ""
    if document_variant == "fine_notice":
        disposition_details = _fine_notice_disposition_details(notice_result)
        petition = _draft_petition_text(
            disposition_details=disposition_details,
            legal_grounds=legal_grounds,
            user_facts=user_facts,
            missing_fields=combined_missing_fields,
            appeal_decision=appeal_decision,
        )
        if petition is None:
            drafting_source = "rule_based_fallback"
            petition_purpose = _fallback_petition_purpose(
                disposition_details=disposition_details,
                recipient_agency=recipient_agency,
                appeal_decision=appeal_decision,
            )
            petition_reason = _fallback_petition_reason(
                disposition_details=disposition_details,
                legal_grounds=legal_grounds,
                user_facts=user_facts,
                missing_fields=combined_missing_fields,
            )
        else:
            drafting_source = "llm"
            petition_purpose = petition["petition_purpose"]
            petition_reason = petition["petition_reason"]

    structured_result = {
        "document_type": "objection_form",
        "document_variant": document_variant,
        "document_title": _document_title(document_variant),
        "recipient_agency": recipient_agency,
        "case_summary": case_summary,
        "requested_action": requested_action,
        "objection_reasons": objection_reasons,
        "legal_grounds": legal_grounds,
        "required_attachments": required_attachments,
        "form_data": form_data,
        "document_readiness": document_readiness,
        "form_sections": _form_sections(
            recipient_agency=recipient_agency,
            case_summary=case_summary,
            requested_action=requested_action,
            objection_reasons=objection_reasons,
            legal_grounds=legal_grounds,
            required_attachments=required_attachments,
            document_variant=document_variant,
        ),
        "report_actions": _report_actions(
            document_variant=document_variant,
            ready_for_docx=document_readiness["ready_for_docx"],
        ) if not appeal_gate["blocked"] else [],
        "appeal_decision": appeal_decision,
        "appeal_gate": appeal_gate,
        "petition_purpose": petition_purpose,
        "petition_reason": petition_reason,
        "drafting_source": drafting_source,
        "supervisor_handoff": _handoff_trace(agent_input),
        "case_evidence": _case_evidence(agent_input),
        "missing_fields": combined_missing_fields,
        "readiness": {
            "ready_for_download": not combined_missing_fields and not appeal_gate["blocked"],
            "requires_user_review": True,
            "review_reason": appeal_gate["reason"]
            or "제출 전 사실관계, 관할 기관, 기한, 증빙자료를 사용자가 최종 확인해야 합니다.",
        },
    }

    handoff = _supervisor_handoff(agent_input)
    handoff_gate = handoff.get("gate") if isinstance(handoff.get("gate"), dict) else {}
    status = (
        "success"
        if not combined_missing_fields and not appeal_gate["blocked"] and handoff_gate.get("status") != "draft"
        else "partial"
    )
    return _output(
        agent_input=agent_input,
        node=node,
        status=status,
        summary=_summary(
            status,
            recipient_agency,
            combined_missing_fields,
            document_variant,
            next_questions=document_readiness["next_questions"],
        ),
        structured_result=structured_result,
        evidence=_evidence(
            agent_input,
            notice_output,
            text_ml_output,
            law_output,
            appeal_output,
            user_facts,
        ),
        next_actions=_next_actions(combined_missing_fields, appeal_blocked=appeal_gate["blocked"]),
        limitations=_limitations(
            combined_missing_fields,
            extra=[appeal_gate["reason"]] if appeal_gate["reason"] else None,
        ),
    )


def _output(
    *,
    agent_input: dict[str, Any],
    node: dict[str, Any],
    status: str,
    summary: str,
    structured_result: dict[str, Any],
    evidence: list[dict[str, Any]],
    next_actions: list[str],
    limitations: list[str],
) -> dict[str, Any]:
    return {
        "session_id": agent_input.get("session_id"),
        "message_id": agent_input.get("message_id"),
        "job_id": agent_input.get("job_id"),
        "node_name": node.get("node_name") or "이의신청서 생성/리포트 노드",
        "node_code": "objection_report_generation",
        "node_type": node.get("node_type") or "agent",
        "owner": node.get("owner") or "hi20260204-maker",
        "status": status,
        "summary": summary,
        "structured_result": structured_result,
        "evidence": evidence,
        "next_actions": next_actions,
        "limitations": limitations,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _upstream_output(agent_input: dict[str, Any], node_code: str) -> dict[str, Any]:
    handoff = _supervisor_handoff(agent_input)
    handoff_results = handoff.get("results") if isinstance(handoff.get("results"), dict) else {}
    persisted_output = handoff_results.get(node_code)
    if isinstance(persisted_output, dict):
        return deepcopy(persisted_output)
    if _handoff_required(agent_input):
        return {}
    upstream = agent_input.get("upstream_results")
    if not isinstance(upstream, dict):
        return {}
    output = upstream.get(node_code)
    if not isinstance(output, dict):
        return {}
    nested_output = output.get("agent_output")
    if isinstance(nested_output, dict):
        return nested_output
    return output


def _structured_result(output: dict[str, Any]) -> dict[str, Any]:
    structured_result = output.get("structured_result")
    return deepcopy(structured_result) if isinstance(structured_result, dict) else {}


def _user_facts(agent_input: dict[str, Any]) -> str:
    context = agent_input.get("context") if isinstance(agent_input.get("context"), dict) else {}
    handoff = _supervisor_handoff(agent_input)
    case_context = handoff.get("case_context") if isinstance(handoff.get("case_context"), dict) else {}
    if _handoff_required(agent_input):
        return _text(case_context.get("user_facts"))
    slot_state = agent_input.get("slot_state") if isinstance(agent_input.get("slot_state"), dict) else {}
    candidates = [
        case_context.get("user_facts"),
        context.get("user_facts"),
        context.get("fact_summary"),
        context.get("raw_user_text"),
        agent_input.get("user_text"),
        _slot_facts(slot_state),
    ]
    for candidate in candidates:
        text = _text(candidate)
        if text:
            return text
    return ""


def _case_evidence(agent_input: dict[str, Any]) -> dict[str, Any]:
    context = agent_input.get("context") if isinstance(agent_input.get("context"), dict) else {}
    handoff = _supervisor_handoff(agent_input)
    case_context = handoff.get("case_context") if isinstance(handoff.get("case_context"), dict) else {}
    value = case_context.get("case_evidence") if _handoff_required(agent_input) else context.get("case_evidence")
    if not isinstance(value, dict) or value.get("schema_version") != "case_evidence.v1":
        return {}
    return deepcopy(value)


def _slot_facts(slot_state: dict[str, Any]) -> str:
    slots = slot_state.get("slots")
    if not isinstance(slots, dict):
        return ""
    values = []
    for value in slots.values():
        if isinstance(value, dict):
            value = value.get("value") or value.get("text") or value.get("summary")
        text = _text(value)
        if text:
            values.append(text)
    return " / ".join(values)


def _document_variant(notice_result: dict[str, Any], text_ml_result: dict[str, Any]) -> str:
    if text_ml_result and not notice_result:
        return "traffic_accident"
    return "fine_notice"


def _document_title(document_variant: str) -> str:
    if document_variant == "traffic_accident":
        return "교통사고 이의신청서 초안"
    return "이의신청서 초안"


def _requested_action(document_variant: str) -> str:
    if document_variant == "traffic_accident":
        return "사고 사실관계 재검토 및 과실비율 조정 검토"
    return "처분 취소 또는 감경 검토"


def _text_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    items = []
    for value in values:
        text = _text(value)
        if text:
            items.append(text)
    return items


def _similar_cases(text_ml_result: dict[str, Any]) -> list[dict[str, Any]]:
    raw_cases = text_ml_result.get("similar_cases") or text_ml_result.get("top_cases")
    if not isinstance(raw_cases, list):
        return []
    return [deepcopy(item) for item in raw_cases if isinstance(item, dict)]


def _accident_query_text(text_ml_result: dict[str, Any], user_facts: str) -> str:
    return (
        _text(text_ml_result.get("query_text"))
        or _text(text_ml_result.get("normalized_description"))
        or _text(user_facts)
    )


def _missing_fields(
    *,
    notice_result: dict[str, Any],
    text_ml_result: dict[str, Any],
    law_result: dict[str, Any],
    user_facts: str,
    document_variant: str,
) -> list[str]:
    missing_fields = []
    if document_variant == "traffic_accident":
        if not text_ml_result:
            missing_fields.append("text_ml_case_result")
        if not user_facts and not _accident_query_text(text_ml_result, user_facts):
            missing_fields.append("user_facts")
    elif not notice_result:
        missing_fields.append("notice_analysis_result")
    if not law_result:
        missing_fields.append("law_ground_result")
    if document_variant != "traffic_accident" and not user_facts:
        missing_fields.append("user_facts")
    return missing_fields


def _recipient_agency(
    agent_input: dict[str, Any],
    notice_result: dict[str, Any],
    document_variant: str,
) -> str:
    context = agent_input.get("context") if isinstance(agent_input.get("context"), dict) else {}
    notice_fields = _notice_fields(notice_result)
    recipient = (
        ("" if _handoff_required(agent_input) else _text(context.get("recipient_agency")))
        or _text(notice_fields.get("agency"))
        or _text(notice_fields.get("issuing_authority"))
        or _text(notice_result.get("issuing_authority"))
    )
    if recipient:
        return recipient
    if document_variant == "traffic_accident":
        return "관할 경찰서 또는 분쟁조정 기관"
    return "관할 행정청"


def _case_summary(
    *,
    notice_result: dict[str, Any],
    text_ml_result: dict[str, Any],
    user_facts: str,
    document_variant: str,
) -> str:
    if document_variant == "traffic_accident":
        query_text = _accident_query_text(text_ml_result, user_facts)
        issue_tags = _text_list(text_ml_result.get("issue_tags"))
        accident_types = _text_list(text_ml_result.get("accident_type_candidates"))
        similar_cases = _similar_cases(text_ml_result)
        recommended_evidence = _text_list(text_ml_result.get("recommended_evidence"))

        parts = [f"대상 건은 {query_text or '교통사고 사실관계 확인이 필요한 사고'}에 관한 이의신청 초안입니다."]
        if accident_types:
            parts.append(f"사고 유형 후보는 {', '.join(accident_types[:2])}로 분류되었습니다.")
        if issue_tags:
            parts.append(f"주요 쟁점은 {', '.join(issue_tags[:4])}입니다.")
        if similar_cases:
            lead_case = _text(similar_cases[0].get('title')) or _text(similar_cases[0].get('summary'))
            if lead_case:
                parts.append(f"유사 사례 후보로는 {lead_case}가 우선 참고되었습니다.")
        if recommended_evidence:
            parts.append(f"추가 검토 자료로는 {', '.join(recommended_evidence[:3])}가 권장됩니다.")
        if user_facts and user_facts != query_text:
            parts.append(f"사용자 진술 요지: {_shorten(user_facts, 180)}")
        return " ".join(parts)

    notice_fields = _notice_fields(notice_result)
    violation = (
        _text(notice_fields.get("violation_text"))
        or _text(notice_result.get("violation_text"))
        or "고지서 기재 위반 사실"
    )
    location = _text(notice_fields.get("violation_location")) or _text(notice_result.get("violation_location"))
    violation_at = _text(notice_fields.get("violation_datetime")) or _text(notice_result.get("violation_datetime"))
    deadline = (
        _text(notice_fields.get("payment_deadline"))
        or _text(notice_result.get("opinion_deadline"))
        or _text(notice_result.get("payment_deadline"))
    )

    parts = [f"대상 처분은 {violation}에 관한 건입니다."]
    if violation_at:
        parts.append(f"위반 일시는 {violation_at}로 확인됩니다.")
    if location:
        parts.append(f"위반 장소는 {location}입니다.")
    if deadline:
        parts.append(f"의견제출 또는 납부 관련 기한은 {deadline}로 표시되어 있습니다.")
    if user_facts:
        parts.append(f"사용자 진술 요지: {_shorten(user_facts, 180)}")
    return " ".join(parts)


def _objection_reasons(
    *,
    notice_result: dict[str, Any],
    text_ml_result: dict[str, Any],
    legal_grounds: list[dict[str, Any]],
    appeal_result: dict[str, Any],
    user_facts: str,
    missing_fields: list[str],
    document_variant: str,
) -> list[str]:
    if document_variant == "traffic_accident":
        reasons = []
        issue_tags = _text_list(text_ml_result.get("issue_tags"))
        similar_cases = _similar_cases(text_ml_result)
        if user_facts:
            reasons.append("사용자 진술과 상대방 진술, 사진, 영상 사이에 사실관계 차이가 없는지 재확인할 필요가 있습니다.")
        if issue_tags:
            reasons.append(f"AI가 선별한 핵심 쟁점({', '.join(issue_tags[:4])})을 기준으로 책임 판단 요소를 다시 검토해야 합니다.")
        if legal_grounds:
            reasons.append("관련 법령과 판단 기준을 사고 경위에 대입해 과실비율 또는 책임 판단의 근거를 보강할 필요가 있습니다.")
        if similar_cases:
            reasons.append("유사 사례 후보가 존재하므로 사고 유형은 유사하지만, 실제 사실관계 차이를 항목별로 비교해야 합니다.")
        if "text_ml_case_result" in missing_fields:
            reasons.append("사고 쟁점 분석 결과가 없어 유사 사례와 핵심 판단 요소를 추가 확인해야 합니다.")
        if "law_ground_result" in missing_fields:
            reasons.append("법률 근거 검색 결과가 없어 조문 및 판단 기준을 추가 확인해야 합니다.")
        if not reasons:
            reasons.append("사고 경위와 제출 자료를 다시 확인해 이의신청 사유를 구체화해야 합니다.")
        return reasons

    reasons = []
    judgment_status = _text(appeal_result.get("judgment_status"))
    overall_possibility = _text(appeal_result.get("overall_possibility"))
    merit_basis = _text(appeal_result.get("merit_basis"))
    if judgment_status or overall_possibility:
        judgment_label = overall_possibility or judgment_status
        reasons.append(f"이의 가능성 판단 결과({judgment_label})를 초안 작성에 반영했습니다.")
    if merit_basis:
        reasons.append(f"이의 사유 타당성 판단 근거: {_shorten(merit_basis, 240)}")
    if user_facts:
        reasons.append("사용자 진술에 비추어 고지서 기재 사실관계와 실제 상황 사이에 다툼의 여지가 있습니다.")
    if legal_grounds:
        reasons.append("처분 근거 조항의 적용 요건을 고지서 사실관계에 대입해 재검토할 필요가 있습니다.")
    if notice_result:
        reasons.append("위반 일시, 장소, 통지일, 관할 기관 등 고지서 핵심 항목을 기준으로 제출 기한과 절차를 확인해야 합니다.")
    if "notice_analysis_result" in missing_fields:
        reasons.append("고지서 OCR/분석 결과가 없어 처분 번호, 관할 기관, 기한을 보강해야 합니다.")
    if "law_ground_result" in missing_fields:
        reasons.append("법률 근거 검색 결과가 없어 조문 및 판례 근거를 추가 확인해야 합니다.")
    if not reasons:
        reasons.append("사실관계와 법률 근거 확인 후 이의신청 사유를 확정해야 합니다.")
    return reasons


def _legal_grounds(law_result: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = law_result.get("law_provisions") or law_result.get("matched_laws") or law_result.get("legal_grounds")
    if not isinstance(raw_items, list):
        return []

    grounds = []
    for item in raw_items:
        if isinstance(item, str):
            grounds.append(
                {
                    "law_name": "관련 법령",
                    "article": "",
                    "summary": "세부 조항은 별도 확인이 필요합니다.",
                    "source_reference": _text(item),
                    "source_url": "",
                    "score": None,
                }
            )
            continue
        if not isinstance(item, dict):
            continue
        law_name = _text(item.get("source_name")) or _text(item.get("law_name")) or "관련 법령"
        article = (
            _text(item.get("article_no"))
            or _text(item.get("article"))
            or _text(item.get("article_title"))
            or _text(item.get("section_ref"))
        )
        summary = (
            _text(item.get("provision_text"))
            or _text(item.get("summary"))
            or _text(item.get("title"))
            or "세부 조문 내용은 원문 확인이 필요합니다."
        )
        grounds.append(
            {
                "law_name": law_name,
                "article": article,
                "summary": _shorten(summary, 260),
                "source_reference": (
                    _text(item.get("source_ref"))
                    or _text(item.get("source_reference"))
                    or _text(item.get("chunk_id"))
                ),
                "source_url": _text(item.get("source_url")),
                "score": item.get("retrieval_score") or item.get("score"),
            }
        )
    return grounds


def _fine_notice_disposition_details(notice_result: dict[str, Any]) -> dict[str, str]:
    notice_fields = _notice_fields(notice_result)
    return {
        "violation_text": _first_present(
            notice_fields.get("violation_text"),
            notice_result.get("violation_text"),
        ),
        "violation_datetime": _first_present(
            notice_fields.get("violation_datetime"),
            notice_result.get("violation_datetime"),
        ),
        "violation_location": _first_present(
            notice_fields.get("violation_location"),
            notice_result.get("violation_location"),
        ),
        "fine_amount": _first_present(
            notice_fields.get("fine_amount"),
            notice_result.get("fine_amount"),
        ),
        "payment_deadline": _first_present(
            notice_fields.get("payment_deadline"),
            notice_result.get("payment_deadline"),
        ),
        "case_number": _first_present(
            notice_fields.get("charge_number"),
            notice_result.get("charge_number"),
            notice_result.get("case_number"),
        ),
    }


def _draft_petition_text(
    *,
    disposition_details: dict[str, str],
    legal_grounds: list[dict[str, Any]],
    user_facts: str,
    missing_fields: list[str],
    appeal_decision: dict[str, Any],
) -> dict[str, str] | None:
    client = _openai_client()
    if client is None:
        return None

    prompt_payload = {
        "disposition_details": {
            key: disposition_details.get(key, "")
            for key in (
                "violation_text",
                "violation_datetime",
                "fine_amount",
                "payment_deadline",
            )
        },
        "legal_grounds": [
            {
                "law_name": item.get("law_name"),
                "article": item.get("article"),
                "summary": item.get("summary"),
            }
            for item in legal_grounds
        ],
        "user_facts": _shorten(user_facts, 600),
        "missing_fields": list(missing_fields),
        "appeal_decision": {
            "merit": appeal_decision.get("merit"),
            "merit_relief_type": appeal_decision.get("merit_relief_type"),
            "overall_possibility": appeal_decision.get("overall_possibility"),
        },
    }
    user_prompt = json.dumps(sanitize_pii(prompt_payload), ensure_ascii=False)
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=700,
            messages=[
                {"role": "system", "content": _PETITION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        parsed = json.loads(response.choices[0].message.content)
    except Exception as exc:
        logger.warning("objection petition drafting failed; error_class=%s", exc.__class__.__name__)
        return None
    if not isinstance(parsed, dict):
        return None
    sanitized = sanitize_pii(parsed)
    purpose = _text(sanitized.get("petition_purpose"))
    reason = _text(sanitized.get("petition_reason"))
    if not purpose or not reason:
        return None
    return {"petition_purpose": purpose, "petition_reason": reason}


def _openai_client() -> Any:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI

        return OpenAI(api_key=api_key)
    except Exception as exc:
        logger.warning("objection petition drafting disabled; error_class=%s", exc.__class__.__name__)
        return None


def _fallback_petition_purpose(
    *,
    disposition_details: dict[str, str],
    recipient_agency: str,
    appeal_decision: dict[str, Any],
) -> str:
    violation = disposition_details.get("violation_text") or "고지서 기재 위반 사실"
    relief_type = appeal_decision.get("merit_relief_type")
    action = "취소 또는 감경을"
    if relief_type == "감경":
        action = "감경을"
    elif relief_type == "면제":
        action = "취소를"
    return f"{recipient_agency}에 대하여 {violation}에 관한 처분의 {action} 요청합니다."


def _fallback_petition_reason(
    *,
    disposition_details: dict[str, str],
    legal_grounds: list[dict[str, Any]],
    user_facts: str,
    missing_fields: list[str],
) -> str:
    reasons: list[str] = []
    if user_facts:
        reasons.append(f"사용자 진술에 따르면: {_shorten(user_facts, 200)}")
    if disposition_details.get("violation_datetime") or disposition_details.get("violation_location"):
        reasons.append("고지서 기재 사실관계와 실제 상황 사이에 차이가 없는지 재확인할 필요가 있습니다.")
    if legal_grounds:
        top_ground = legal_grounds[0]
        reasons.append(
            f"{top_ground['law_name']} {top_ground.get('article') or ''}의 적용 요건을 사실관계에 대입해 재검토할 필요가 있습니다.".replace(
                "  ", " "
            )
        )
    if missing_fields:
        reasons.append(f"추가 확인이 필요한 항목: {', '.join(missing_fields)}")
    return " ".join(reasons) or "사실관계와 법률 근거 확인 후 신청 이유를 구체화해야 합니다."


def _required_attachments(
    *,
    agent_input: dict[str, Any],
    notice_result: dict[str, Any],
    text_ml_result: dict[str, Any],
    document_variant: str,
) -> list[str]:
    if document_variant == "traffic_accident":
        attachments = [
            "사고 접수 서류",
            "블랙박스 원본 또는 영상 캡처",
            "현장 사진",
            "보험사 접수 내역",
            "상대방 진술 또는 목격자 진술",
        ]
        attachments.extend(_text_list(text_ml_result.get("recommended_evidence")))
    else:
        attachments = ["고지서 원본", "이의신청 사유서", "관련 증빙자료"]
        required_documents = notice_result.get("required_documents")
        if isinstance(required_documents, list):
            attachments.extend(_text(item) for item in required_documents)
    attachment_candidates = agent_input.get("attachments") or []
    if _handoff_required(agent_input):
        handoff = _supervisor_handoff(agent_input)
        case_context = (
            handoff.get("case_context")
            if isinstance(handoff.get("case_context"), dict)
            else {}
        )
        attachment_candidates = case_context.get("attachment_refs") or []
    for attachment in attachment_candidates:
        if not isinstance(attachment, dict):
            continue
        label = (
            _text(attachment.get("filename"))
            or _text(attachment.get("purpose"))
            or _text(attachment.get("original_filename"))
        )
        if label:
            attachments.append(label)
    return _unique(attachments)


def _fine_notice_form_data(
    *,
    agent_input: dict[str, Any],
    notice_result: dict[str, Any],
    recipient_agency: str,
) -> dict[str, Any]:
    context = agent_input.get("context") if isinstance(agent_input.get("context"), dict) else {}
    applicant = context.get("applicant") if isinstance(context.get("applicant"), dict) else {}
    notice_fields = _notice_fields(notice_result)
    return {
        "recipient": recipient_agency,
        "applicant_name": _first_present(applicant.get("name"), context.get("applicant_name")),
        "address": _first_present(applicant.get("address"), context.get("address")),
        "contact": _first_present(
            applicant.get("contact"),
            applicant.get("phone"),
            context.get("applicant_contact"),
            context.get("contact"),
        ),
        "vehicle_number": _first_present(
            applicant.get("vehicle_number"),
            context.get("vehicle_number"),
        ),
        "notice_received_date": _first_present(
            context.get("notice_received_date"),
            notice_fields.get("notice_received_date"),
            notice_fields.get("violation_datetime"),
            notice_result.get("violation_datetime"),
        ),
        "fine_amount": _first_present(
            notice_fields.get("fine_amount"),
            notice_result.get("fine_amount"),
        ),
        "case_number": _first_present(
            notice_fields.get("charge_number"),
            notice_result.get("charge_number"),
            notice_result.get("case_number"),
        ),
        "violation_text": _first_present(
            notice_fields.get("violation_text"),
            notice_result.get("violation_text"),
        ),
        "payment_deadline": _first_present(
            notice_fields.get("payment_deadline"),
            notice_result.get("payment_deadline"),
        ),
    }


def _objection_form_data(
    *,
    agent_input: dict[str, Any],
    text_ml_result: dict[str, Any],
    recipient_agency: str,
    case_summary: str,
    requested_action: str,
    objection_reasons: list[str],
    required_attachments: list[str],
    document_variant: str,
) -> dict[str, Any]:
    if document_variant != "traffic_accident":
        return {}

    context = agent_input.get("context") if isinstance(agent_input.get("context"), dict) else {}
    supplied = context.get("objection_form") if isinstance(context.get("objection_form"), dict) else {}
    allowed_fields = {
        "recipient",
        "applicant_name",
        "birth_date",
        "address",
        "contact",
        "email",
        "relationship",
        "representative_name",
        "representative_birth_date",
        "representative_address",
        "representative_contact",
        "representative_relationship",
        "has_power_of_attorney",
        "case_number",
        "incident_at",
        "location",
        "police_station",
        "investigator",
        "notice_date",
        "vehicle_parties",
        "insurance_number",
        "investigation_result_summary",
        "objection_points",
        "timeline",
        "omitted_evidence",
        "specific_request",
        "write_date",
        "evidence_rows",
        "issue_rows",
    }
    form_data = {
        key: deepcopy(value)
        for key, value in supplied.items()
        if key in allowed_fields and value not in (None, "", [], {})
    }

    for field in allowed_fields:
        if field in form_data:
            continue
        value = context.get(field)
        if value not in (None, "", [], {}):
            form_data[field] = deepcopy(value)

    generic_recipients = {"관할 경찰서 또는 분쟁조정 기관", "관할 행정청"}
    if "recipient" not in form_data and recipient_agency not in generic_recipients:
        form_data["recipient"] = recipient_agency

    if "objection_points" not in form_data:
        issue_tags = _text_list(text_ml_result.get("issue_tags"))
        if issue_tags:
            form_data["objection_points"] = issue_tags[:4]

    form_data.setdefault("relationship", "운전자")
    form_data.setdefault("purpose", requested_action)
    form_data.setdefault("summary", case_summary)
    form_data.setdefault("rebuttal_summary", "\n".join(objection_reasons))
    form_data.setdefault("evidence_summary", " / ".join(required_attachments))
    form_data.setdefault("write_date", datetime.now(timezone.utc).strftime("%Y년 %m월 %d일"))
    form_data["evidence_rows"] = _form_evidence_rows(
        form_data.get("evidence_rows"),
        required_attachments,
    )
    return form_data


def _form_evidence_rows(raw_rows: Any, attachments: list[str]) -> list[dict[str, str]]:
    if isinstance(raw_rows, list):
        rows = [deepcopy(item) for item in raw_rows if isinstance(item, dict)]
        if rows:
            return rows[:10]
    return [
        {
            "no": str(index),
            "name": attachment,
            "fact": "기존 조사결과와 신청인 주장의 차이를 확인",
            "format": "원본 또는 사본",
            "note": "",
        }
        for index, attachment in enumerate(attachments[:10], start=1)
    ]


def _document_readiness(
    *,
    form_data: dict[str, Any],
    document_variant: str,
    require_docx_fields: bool = True,
) -> dict[str, Any]:
    if document_variant != "traffic_accident" or not require_docx_fields:
        return {
            "ready_for_docx": True,
            "missing_field_details": [],
            "next_questions": [],
        }

    missing_details = [
        deepcopy(spec)
        for spec in TRAFFIC_ACCIDENT_REQUIRED_FIELDS
        if not _form_value_present(form_data.get(spec["field"]))
    ]
    return {
        "ready_for_docx": not missing_details,
        "missing_field_details": missing_details,
        "next_questions": missing_details[:3],
    }


def _requires_docx_fields(agent_input: dict[str, Any]) -> bool:
    handoff = _supervisor_handoff(agent_input)
    target = handoff.get("target") if isinstance(handoff.get("target"), dict) else {}
    return target.get("report_type") != "fault_ratio_analysis"


def _form_value_present(value: Any) -> bool:
    if isinstance(value, list):
        return any(_text(item) for item in value)
    return bool(_text(value))


def _form_sections(
    *,
    recipient_agency: str,
    case_summary: str,
    requested_action: str,
    objection_reasons: list[str],
    legal_grounds: list[dict[str, Any]],
    required_attachments: list[str],
    document_variant: str,
) -> list[dict[str, str]]:
    legal_text = "\n".join(
        f"- {item['law_name']} {item.get('article') or ''}: {item['summary']}".strip()
        for item in legal_grounds
    ) or "- 관련 법령 및 판례는 추가 확인이 필요합니다."
    request_purpose = "사고 사실관계와 책임 판단 근거를 재검토해 달라는 취지입니다."
    if document_variant != "traffic_accident":
        request_purpose = "위 처분에 대하여 사실관계 및 법률 적용을 재검토해 처분 취소 또는 감경을 요청합니다."
    return [
        {
            "title": "수신",
            "body": recipient_agency,
        },
        {
            "title": "1. 이의신청 취지",
            "body": f"{requested_action}. {request_purpose}",
        },
        {
            "title": "2. 사실관계",
            "body": case_summary,
        },
        {
            "title": "3. 이의신청 사유",
            "body": "\n".join(f"- {item}" for item in objection_reasons),
        },
        {
            "title": "4. 관련 법령 및 근거",
            "body": legal_text,
        },
        {
            "title": "5. 첨부자료",
            "body": "\n".join(f"- {item}" for item in required_attachments),
        },
    ]


def _report_actions(
    *,
    document_variant: str,
    ready_for_docx: bool,
) -> list[dict[str, str]]:
    if document_variant == "traffic_accident":
        primary_action = (
            {
                "type": "download_objection",
                "label": "교통사고 이의신청서 DOCX 다운로드",
                "document_type": TRAFFIC_ACCIDENT_DOCX_TYPE,
                "document_format": "docx",
            }
            if ready_for_docx
            else {
                "type": "complete_objection_form",
                "label": "추가 정보 작성하기",
                "document_type": TRAFFIC_ACCIDENT_DOCX_TYPE,
            }
        )
        return [primary_action]
    return [
        {
            "type": "download_objection",
            "label": "이의신청서 DOCX 다운로드",
            "document_type": "objection_form",
            "document_format": "docx",
        },
        {
            "type": "copy_objection_draft",
            "label": "이의신청서 초안 복사",
            "document_type": "objection_form",
        },
    ]


def _evidence(
    agent_input: dict[str, Any],
    notice_output: dict[str, Any],
    text_ml_output: dict[str, Any],
    law_output: dict[str, Any],
    appeal_output: dict[str, Any],
    user_facts: str,
) -> list[dict[str, Any]]:
    evidence = []
    evidence.extend(_output_evidence(notice_output))
    evidence.extend(_output_evidence(text_ml_output))
    evidence.extend(_output_evidence(law_output))
    evidence.extend(_output_evidence(appeal_output))
    if user_facts:
        evidence.append(
            {
                "source_type": "user_statement",
                "title": "사용자 진술 요지",
                "source_reference": agent_input.get("message_id") or agent_input.get("session_id") or "user_text",
                "metadata": {"summary": _shorten(user_facts, 160)},
                "confidence": None,
            }
        )
    return evidence[:10]


def _supervisor_handoff(agent_input: dict[str, Any]) -> dict[str, Any]:
    context = agent_input.get("context") if isinstance(agent_input.get("context"), dict) else {}
    handoff = context.get("supervisor_reporting_handoff")
    return handoff if isinstance(handoff, dict) else {}


def _handoff_required(agent_input: dict[str, Any]) -> bool:
    context = agent_input.get("context") if isinstance(agent_input.get("context"), dict) else {}
    return context.get("handoff_required") is True


def _strict_handoff_error(agent_input: dict[str, Any]) -> str:
    if not _handoff_required(agent_input):
        return ""
    handoff = _supervisor_handoff(agent_input)
    if not handoff:
        return "supervisor_reporting_handoff_required"
    if handoff.get("contract_version") != "supervisor_reporting_handoff.v1":
        return "supervisor_reporting_handoff_version_invalid"
    target = handoff.get("target") if isinstance(handoff.get("target"), dict) else {}
    if target.get("node_code") != "objection_report_generation":
        return "supervisor_reporting_handoff_target_invalid"
    source = handoff.get("source") if isinstance(handoff.get("source"), dict) else {}
    if source.get("persistence") != "agent_results" or source.get("persisted") is not True:
        return "supervisor_reporting_handoff_source_invalid"
    gate = handoff.get("gate") if isinstance(handoff.get("gate"), dict) else {}
    if gate.get("status") not in {"ready", "draft"}:
        return "supervisor_reporting_handoff_gate_blocked"
    if not isinstance(handoff.get("results"), dict):
        return "supervisor_reporting_handoff_results_invalid"
    return ""


def _handoff_trace(agent_input: dict[str, Any]) -> dict[str, Any]:
    handoff = _supervisor_handoff(agent_input)
    source = handoff.get("source") if isinstance(handoff.get("source"), dict) else {}
    gate = handoff.get("gate") if isinstance(handoff.get("gate"), dict) else {}
    return {
        "contract_version": handoff.get("contract_version"),
        "handoff_id": handoff.get("handoff_id"),
        "gate_status": gate.get("status"),
        "source_fingerprint": source.get("fingerprint"),
        "source_result_ids": deepcopy(source.get("result_ids") or []),
    }


def _appeal_decision(appeal_result: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = (
        "judgment_status",
        "overall_possibility",
        "merit",
        "merit_basis",
        "merit_relief_type",
        "risk_flag",
        "risk_basis",
        "deadline_passed",
        "guide",
    )
    return {
        field: deepcopy(appeal_result.get(field))
        for field in allowed_fields
        if field in appeal_result
    }


def _appeal_gate(appeal_decision: dict[str, Any]) -> dict[str, Any]:
    judgment_status = _text(appeal_decision.get("judgment_status"))
    if judgment_status == "denied":
        reason = "이의신청 가능 기한이 지난 것으로 판단되어 다운로드와 제출을 진행할 수 없습니다."
    elif judgment_status == "not_applicable":
        reason = "이 사건 유형은 이의신청 대상이 아닌 것으로 판단되어 다운로드와 제출을 진행할 수 없습니다."
    elif appeal_decision.get("deadline_passed") is True:
        reason = "이의신청 기한이 지난 것으로 확인되어 다운로드와 제출을 진행할 수 없습니다."
    else:
        reason = ""
    return {
        "blocked": bool(reason),
        "reason": reason,
    }


def _output_evidence(output: dict[str, Any]) -> list[dict[str, Any]]:
    raw_evidence = output.get("evidence")
    if not isinstance(raw_evidence, list):
        return []
    return [deepcopy(item) for item in raw_evidence if isinstance(item, dict)]


def _next_actions(missing_fields: list[str], *, appeal_blocked: bool = False) -> list[str]:
    if appeal_blocked:
        return [
            "review_appeal_eligibility",
            "confirm_appeal_deadline_or_applicability",
        ]
    if missing_fields:
        return [
            "confirm_missing_inputs",
            "review_objection_draft",
            "download_objection_after_confirmation",
        ]
    return [
        "review_objection_draft",
        "download_objection",
        "review_report_screen",
    ]


def _limitations(missing_fields: list[str], *, extra: list[str] | None = None) -> list[str]:
    limitations = [
        "이 초안은 제출 보조용이며 처분 취소, 감경, 접수 결과를 보장하지 않습니다.",
        "제출 전 관할 기관, 제출 기한, 인적 사항, 사건 번호, 첨부자료를 사용자가 직접 확인해야 합니다.",
    ]
    if missing_fields:
        limitations.append(f"추가 확인 필요 입력: {', '.join(missing_fields)}")
    if extra:
        limitations.extend(item for item in extra if item)
    return limitations


def _summary(
    status: str,
    recipient_agency: str,
    missing_fields: list[str],
    document_variant: str,
    *,
    next_questions: list[dict[str, str]] | None = None,
) -> str:
    if status == "success":
        if document_variant == "traffic_accident":
            return f"{recipient_agency} 제출용 교통사고 이의신청서 초안과 리포트 다운로드 action을 생성했습니다."
        return f"{recipient_agency} 제출용 이의신청서 초안과 리포트 다운로드 action을 생성했습니다."
    question_text = " ".join(
        str(item.get("question") or "").strip()
        for item in next_questions or []
        if str(item.get("question") or "").strip()
    )
    summary = f"이의신청서 초안 구조를 만들었지만 추가 확인 입력이 필요합니다: {', '.join(missing_fields)}"
    return f"{summary} {question_text}".strip()


def _notice_fields(notice_result: dict[str, Any]) -> dict[str, Any]:
    notice_fields = notice_result.get("notice_fields")
    return notice_fields if isinstance(notice_fields, dict) else {}


def _first_present(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            text = _text(item)
            if text:
                parts.append(f"{key}: {text}")
        return " / ".join(parts)
    if isinstance(value, list):
        return " / ".join(_text(item) for item in value if _text(item))
    return str(value).strip()


def _shorten(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _unique(values: list[str]) -> list[str]:
    seen = set()
    unique_values = []
    for value in values:
        text = _text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        unique_values.append(text)
    return unique_values
