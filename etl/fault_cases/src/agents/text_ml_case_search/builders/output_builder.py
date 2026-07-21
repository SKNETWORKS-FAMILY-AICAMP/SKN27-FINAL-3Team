from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.config import CONTRACT_VERSION, NODE_CODE
from etl.fault_cases.src.agents.text_ml_case_search.schemas import AgentOutput, AgentStatus


def build_output(
    *,
    status: AgentStatus,
    normalized_description: str,
    accident_type_candidates: list[dict[str, Any]],
    issue_tags: list[str],
    evidence_tags: list[str],
    recommended_evidence: list[dict[str, Any]],
    insurer_claim_review: dict[str, Any] | None,
    similar_cases: list[dict[str, Any]],
    ratio_range_label: str,
    display_evidence: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    next_actions: list[str],
    limitations: list[str],
    missing_fields: list[str],
    search_text: dict[str, Any] | None = None,
    rag_debug: dict[str, Any] | None = None,
    source_summary: dict[str, Any] | None = None,
    contract_version: str = CONTRACT_VERSION,
) -> AgentOutput:
    return {
        "contract_version": contract_version,
        "node_code": NODE_CODE,
        "status": status,
        "structured_result": {
            "normalized_description": normalized_description,
            "accident_type_candidates": accident_type_candidates,
            "issue_tags": issue_tags,
            "evidence_tags": evidence_tags,
            "recommended_evidence": recommended_evidence,
            "insurer_claim_review": insurer_claim_review,
            "similar_cases": similar_cases,
            "ratio_range_label": ratio_range_label,
            "display_evidence": display_evidence or [],
            "search_text": search_text or {},
            "rag_debug": rag_debug or {},
            "source_summary": source_summary or {},
            "reliability_score": None,
            "limitations": limitations,
        },
        "evidence": evidence,
        "next_actions": next_actions,
        "limitations": limitations,
        "missing_fields": missing_fields,
    }


def build_failed_output(
    *,
    missing_fields: list[str],
    errors: list[str],
    contract_version: str = CONTRACT_VERSION,
) -> AgentOutput:
    limitations = ["분석 가능한 사고 설명 또는 필수 실행 정보가 부족합니다."]
    limitations.extend(errors)

    return build_output(
        status="failed",
        normalized_description="",
        accident_type_candidates=[],
        issue_tags=[],
        evidence_tags=[],
        recommended_evidence=[],
        insurer_claim_review=None,
        similar_cases=[],
        ratio_range_label="",
        display_evidence=[],
        evidence=[],
        next_actions=["사고 상황 설명과 필수 식별자를 보강한 뒤 다시 요청해야 합니다."],
        limitations=limitations,
        missing_fields=missing_fields,
        contract_version=contract_version,
    )
