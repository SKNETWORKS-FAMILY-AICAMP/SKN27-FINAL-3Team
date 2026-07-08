"""Sync adapter for objection form and report-action generation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


def run_objection_report_generation(
    agent_input: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    node = context.get("node") if isinstance(context.get("node"), dict) else {}
    notice_output = _upstream_output(agent_input, "fine_notice_analysis")
    text_ml_output = _upstream_output(agent_input, "text_ml_case_search")
    law_output = _upstream_output(agent_input, "law_ground_search")
    notice_result = _structured_result(notice_output)
    text_ml_result = _structured_result(text_ml_output)
    law_result = _structured_result(law_output)
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
        "form_sections": _form_sections(
            recipient_agency=recipient_agency,
            case_summary=case_summary,
            requested_action=requested_action,
            objection_reasons=objection_reasons,
            legal_grounds=legal_grounds,
            required_attachments=required_attachments,
            document_variant=document_variant,
        ),
        "report_actions": _report_actions(),
        "missing_fields": missing_fields,
        "readiness": {
            "ready_for_download": not missing_fields,
            "requires_user_review": True,
            "review_reason": "제출 전 사실관계, 관할 기관, 기한, 증빙자료를 사용자가 최종 확인해야 합니다.",
        },
    }

    status = "success" if not missing_fields else "partial"
    return _output(
        agent_input=agent_input,
        node=node,
        status=status,
        summary=_summary(status, recipient_agency, missing_fields, document_variant),
        structured_result=structured_result,
        evidence=_evidence(agent_input, notice_output, text_ml_output, law_output, user_facts),
        next_actions=_next_actions(missing_fields),
        limitations=_limitations(missing_fields),
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
    slot_state = agent_input.get("slot_state") if isinstance(agent_input.get("slot_state"), dict) else {}
    candidates = [
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
        _text(context.get("recipient_agency"))
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
    for attachment in agent_input.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        label = _text(attachment.get("filename")) or _text(attachment.get("original_filename"))
        if label:
            attachments.append(label)
    return _unique(attachments)


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


def _report_actions() -> list[dict[str, str]]:
    return [
        {
            "type": "download_objection",
            "label": "이의신청서 PDF 다운로드",
            "document_type": "objection_form",
        },
        {
            "type": "download_report",
            "label": "분석 리포트 PDF 다운로드",
            "document_type": "report",
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
    user_facts: str,
) -> list[dict[str, Any]]:
    evidence = []
    evidence.extend(_output_evidence(notice_output))
    evidence.extend(_output_evidence(text_ml_output))
    evidence.extend(_output_evidence(law_output))
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


def _output_evidence(output: dict[str, Any]) -> list[dict[str, Any]]:
    raw_evidence = output.get("evidence")
    if not isinstance(raw_evidence, list):
        return []
    return [deepcopy(item) for item in raw_evidence if isinstance(item, dict)]


def _next_actions(missing_fields: list[str]) -> list[str]:
    if missing_fields:
        return [
            "confirm_missing_inputs",
            "review_objection_draft",
            "download_objection_after_confirmation",
        ]
    return [
        "review_objection_draft",
        "download_objection",
        "download_report",
    ]


def _limitations(missing_fields: list[str]) -> list[str]:
    limitations = [
        "이 초안은 제출 보조용이며 처분 취소, 감경, 접수 결과를 보장하지 않습니다.",
        "제출 전 관할 기관, 제출 기한, 인적 사항, 사건 번호, 첨부자료를 사용자가 직접 확인해야 합니다.",
    ]
    if missing_fields:
        limitations.append(f"추가 확인 필요 입력: {', '.join(missing_fields)}")
    return limitations


def _summary(
    status: str,
    recipient_agency: str,
    missing_fields: list[str],
    document_variant: str,
) -> str:
    if status == "success":
        if document_variant == "traffic_accident":
            return f"{recipient_agency} 제출용 교통사고 이의신청서 초안과 리포트 다운로드 action을 생성했습니다."
        return f"{recipient_agency} 제출용 이의신청서 초안과 리포트 다운로드 action을 생성했습니다."
    return f"이의신청서 초안 구조를 만들었지만 추가 확인 입력이 필요합니다: {', '.join(missing_fields)}"


def _notice_fields(notice_result: dict[str, Any]) -> dict[str, Any]:
    notice_fields = notice_result.get("notice_fields")
    return notice_fields if isinstance(notice_fields, dict) else {}


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
