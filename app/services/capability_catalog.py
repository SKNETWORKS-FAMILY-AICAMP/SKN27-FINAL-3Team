"""Canonical product capabilities exposed by the production API."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    code: str
    label: str
    description: str
    attachment_purposes: tuple[str, ...]
    report_type: str | None


CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition(
        code="fine_notice_objection",
        label="과태료 고지서 이의제기",
        description="고지서 OCR, 법령 근거 확인, 의견제출서 초안을 지원합니다.",
        attachment_purposes=("fine_notice", "supporting_evidence"),
        report_type="fine_notice_objection",
    ),
    CapabilityDefinition(
        code="fault_ratio_text",
        label="텍스트 기반 과실비율 상담",
        description="사고 설명과 검색 근거를 바탕으로 과실 쟁점을 정리합니다.",
        attachment_purposes=("supporting_evidence",),
        report_type="fault_ratio_analysis",
    ),
    CapabilityDefinition(
        code="traffic_law_search",
        label="교통 법령 검색",
        description="질문과 관련된 법령 조문 및 적용 한계를 제공합니다.",
        attachment_purposes=(),
        report_type=None,
    ),
    CapabilityDefinition(
        code="saved_report",
        label="저장 리포트 조회",
        description="본인 소유의 상담 리포트를 조회하고 내려받습니다.",
        attachment_purposes=(),
        report_type="general",
    ),
)


def capability_catalog_payload() -> dict[str, object]:
    return {
        "contract_version": "capability_catalog.v1",
        "capabilities": [
            {**asdict(capability), "attachment_purposes": list(capability.attachment_purposes)}
            for capability in CAPABILITIES
        ],
    }

