"""기존 `text_ml_case_search` 계약과 호환되는 공통 RAG 계약.

여기 타입은 외부 JSON 구조를 명확히 하기 위한 TypedDict다. 실제 검색·판단·최종
답변 생성을 수행하지 않으며, 기존 슈퍼바이저의 `AgentOutput`을 대체하지 않는다.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


DomainName = Literal["fault_standard", "precedent", "review_case", "law"]
ResultStatus = Literal["success", "partial", "failed", "unknown"]


class SearchEvidence(TypedDict, total=False):
    """한 건의 검색 근거를 표현하는 JSON 호환 구조."""

    source_type: DomainName
    source_reference: str
    title: str
    chunk_id: str
    chunk_text: str
    rank: int
    similarity_score: float
    retrieval_score: float
    rerank_score: float
    score_type: str
    confidence: str
    decision_fault_ratio: str | None
    metadata: dict[str, Any]
    limitations: list[str]


class RagRequest(TypedDict, total=False):
    """슈퍼바이저가 도메인 RAG에 전달하는 최소 요청 구조."""

    contract_version: str
    session_id: str | None
    message_id: str | None
    job_id: str | None
    node_code: str | None
    query_text: str
    raw_user_text: str
    accident_facts: dict[str, Any]
    required_domains: list[DomainName]
    # 아래 두 필드는 운영 슈퍼바이저 입력이 아니라 재현 평가·내부 호출 전용이다.
    # 외부 API 계층에서는 임의 벡터 주입을 허용하지 않는다.
    evaluation_query_id: str
    query_vector: list[float]


class DomainSearchResult(TypedDict, total=False):
    """각 도메인 RAG가 슈퍼바이저에 돌려주는 근거 묶음 구조."""

    contract_version: str
    domain: DomainName
    status: ResultStatus
    evidence: list[SearchEvidence]
    calculation_result: dict[str, Any] | None
    limitations: list[str]
    missing_fields: list[str]
