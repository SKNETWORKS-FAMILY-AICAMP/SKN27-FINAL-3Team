from __future__ import annotations

from typing import Any, Literal, TypedDict


AgentStatus = Literal["success", "partial", "failed"]
EvidencePriority = Literal["high", "medium", "low"]


class ValidationResult(TypedDict):
    ok: bool
    missing_fields: list[str]
    errors: list[str]


class AgentContext(TypedDict, total=False):
    session_id: str | None
    message_id: str | None
    job_id: str | None
    node_code: str | None
    query_text: str
    raw_user_text: str
    vision_evidence: list[dict[str, Any]]
    ocr_evidence: dict[str, Any] | None
    insurer_claim: dict[str, Any] | None
    required_outputs: list[str]


class RecommendedEvidence(TypedDict, total=False):
    type: str
    title: str
    description: str
    related_issue: str
    priority: EvidencePriority
    based_on: list[str]


class SimilarCase(TypedDict, total=False):
    source_type: str
    case_id: str
    review_no: str
    title: str
    source_reference: str
    chunk_id: str
    chunk_type: str
    reference_chart_key: str
    decision_fault_ratio: str
    claimant_final_ratio: str
    respondent_final_ratio: str
    score: float
    score_type: str
    rank: int
    summary: str
    standard_context: dict[str, Any]


class DisplayEvidence(TypedDict, total=False):
    source_type: str
    title: str
    source_reference: str
    reference_chart_key: str
    case_number: str
    court_name: str
    decision_date: str
    ratio_label: str
    summary: str
    matched_snippets: list[str]
    display_warnings: list[str]


class Evidence(TypedDict, total=False):
    source_type: str
    title: str
    source_reference: str
    metadata: dict[str, Any]
    chunk_text: str
    search_text: str
    confidence: float | None


class InsurerClaimReview(TypedDict, total=False):
    claimed_ratio: str
    claim_summary: str
    comparison_summary: str
    key_dispute_points: list[str]
    reference_ratio_label: str
    reference_evidence_count: int
    reference_evidence: list[dict[str, Any]]
    needed_evidence: list[str]
    limitations: list[str]


class StructuredResult(TypedDict):
    normalized_description: str
    accident_type_candidates: list[dict[str, Any]]
    issue_tags: list[str]
    evidence_tags: list[str]
    recommended_evidence: list[RecommendedEvidence]
    insurer_claim_review: InsurerClaimReview | None
    similar_cases: list[SimilarCase]
    ratio_range_label: str
    display_evidence: list[DisplayEvidence]
    search_text: dict[str, Any]
    rag_debug: dict[str, Any]
    source_summary: dict[str, Any]
    reliability_score: float | None
    limitations: list[str]


class AgentOutput(TypedDict):
    contract_version: str
    node_code: str
    status: AgentStatus
    structured_result: StructuredResult
    evidence: list[Evidence]
    next_actions: list[str]
    limitations: list[str]
    missing_fields: list[str]
