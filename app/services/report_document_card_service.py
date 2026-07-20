"""Build safe, copy-only document cards from public report sections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any


DOCUMENT_CARD_TYPES = (
    "objection_draft",
    "fact_summary",
    "insurance_submission",
)
OFFICIAL_OBJECTION_DOCUMENT_VARIANTS = {"fine_notice", "traffic_accident"}


def build_report_document_cards(
    *,
    document_variant: object,
    sections: object,
    document_readiness: object,
    appeal_gate: object,
) -> list[dict[str, Any]]:
    """Return the three public, copy-only document cards for one report."""

    safe_sections = _normalize_sections(sections)
    readiness = _mapping(document_readiness)
    gate = _mapping(appeal_gate)
    official_document = _text(document_variant) in OFFICIAL_OBJECTION_DOCUMENT_VARIANTS
    blocked = bool(gate.get("blocked"))
    objection_sections = _select_sections(
        safe_sections,
        ("신청", "이의", "사유", "법령", "근거", "첨부"),
    )
    fact_sections = _select_sections(safe_sections, ("사실", "경위", "개요"))
    insurance_sections = _select_sections(
        safe_sections,
        ("사실", "경위", "개요", "근거", "법령", "첨부", "자료"),
    )

    return [
        _objection_draft_card(
            objection_sections,
            official_document=official_document,
            blocked=blocked,
            gate_reason=_text(gate.get("reason")),
            ready_for_docx=bool(readiness.get("ready_for_docx")),
        ),
        _card(
            card_type="fact_summary",
            title="사실관계 정리",
            description="확인된 사실과 추가 확인이 필요한 내용을 구분해 정리합니다.",
            sections=fact_sections,
            notice="확인되지 않은 내용은 제출 전에 보완해 주세요.",
        ),
        _card(
            card_type="insurance_submission",
            title="보험사 제출용 요약",
            description="보험사에 전달할 사실관계와 검토 자료를 한눈에 정리합니다.",
            sections=insurance_sections,
            notice="보험금·합의금·과실 비율을 확정하는 문서가 아닙니다.",
        ),
    ]


def filter_report_actions_for_view(value: object) -> list[dict[str, Any]]:
    """Keep existing actions except the unavailable generic report download."""

    return [
        deepcopy(dict(action))
        for item in _sequence(value)
        if isinstance(item, Mapping)
        if _text((action := _mapping(item)).get("type")) != "download_report"
    ]


def _objection_draft_card(
    sections: list[dict[str, Any]],
    *,
    official_document: bool,
    blocked: bool,
    gate_reason: str,
    ready_for_docx: bool,
) -> dict[str, Any]:
    if not official_document:
        return _unavailable_card(
            card_type="objection_draft",
            title="이의신청서 초안",
            description="공식 이의신청 대상 리포트에서만 초안을 정리합니다.",
            notice="현재 리포트는 이의신청서 초안 대상이 아닙니다.",
        )
    if blocked:
        return _unavailable_card(
            card_type="objection_draft",
            title="이의신청서 초안",
            description="이의신청 가능 여부를 확인한 뒤 초안을 제공합니다.",
            notice=gate_reason or "현재 절차 상태에서는 이의신청서 초안을 제공할 수 없습니다.",
        )

    card = _card(
        card_type="objection_draft",
        title="이의신청서 초안",
        description="신청 취지, 사유, 근거와 첨부자료를 제출 전 검토용으로 정리합니다.",
        sections=sections,
        notice="공식 DOCX는 사실관계·관할기관·기한·첨부자료 최종 확인 후에만 다운로드할 수 있습니다.",
    )
    if card["status"] == "ready" and not ready_for_docx:
        card["status"] = "partial"
        card["notice"] = "공식 DOCX를 받으려면 누락된 정보를 보완하고 최종 확인을 완료해 주세요."
    return card


def _card(
    *,
    card_type: str,
    title: str,
    description: str,
    sections: list[dict[str, Any]],
    notice: str,
) -> dict[str, Any]:
    card: dict[str, Any] = {
        "type": card_type,
        "title": title,
        "description": description,
        "status": "ready" if sections else "partial",
        "sections": sections,
        "notice": notice,
    }
    if sections:
        card["copy_text"] = _copy_text(title, sections)
    return card


def _unavailable_card(
    *,
    card_type: str,
    title: str,
    description: str,
    notice: str,
) -> dict[str, Any]:
    return {
        "type": card_type,
        "title": title,
        "description": description,
        "status": "unavailable",
        "sections": [],
        "notice": notice,
    }


def _normalize_sections(value: object) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in _sequence(value):
        source = _mapping(item)
        title = _text(source.get("title"))
        body = _text(source.get("body"))
        items = [text for raw_item in _sequence(source.get("items")) if (text := _text(raw_item))]
        if not any((title, body, items)):
            continue
        normalized.append(
            {
                "title": title,
                "body": body,
                "items": items,
            }
        )
    return normalized


def _select_sections(
    sections: list[dict[str, Any]],
    keywords: tuple[str, ...],
) -> list[dict[str, Any]]:
    return [
        section
        for section in sections
        if any(keyword in str(section.get("title") or "") for keyword in keywords)
    ]


def _copy_text(title: str, sections: list[dict[str, Any]]) -> str:
    blocks = [title]
    for section in sections:
        lines = [str(section.get("title") or "")]
        if section.get("body"):
            lines.append(str(section["body"]))
        lines.extend(str(item) for item in section.get("items") or [])
        blocks.append("\n".join(line for line in lines if line))
    return "\n\n".join(blocks)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""
