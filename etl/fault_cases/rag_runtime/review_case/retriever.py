"""심의사례 Qwen 4B·pgvector 운영 검색기."""

from __future__ import annotations

from typing import Any

from etl.fault_cases.rag_runtime.contracts import DomainSearchResult, RagRequest
from etl.fault_cases.rag_runtime.shared.qwen4_retrieval import encode_live_query, precomputed_query_vectors, search_by_vector, validate_vector


def _resolve_vector(request: RagRequest) -> list[float]:
    """운영 질의 또는 내부 평가 질의의 Qwen 4B 벡터를 안전하게 결정한다."""

    supplied = request.get("query_vector")
    if supplied is not None:
        values = [float(value) for value in supplied]
        validate_vector(values)
        return values
    evaluation_query_id = request.get("evaluation_query_id")
    if evaluation_query_id:
        return precomputed_query_vectors("review_case")[str(evaluation_query_id)]
    return encode_live_query(str(request.get("query_text") or request.get("raw_user_text") or ""))


def _evidence(row: dict[str, Any]) -> dict[str, Any]:
    """DB 검색 행을 슈퍼바이저 공통 근거 JSON으로 변환한다."""

    return {
        "source_type": "review_case",
        "source_reference": str(row["source_reference"]),
        "title": str(row.get("title") or row["document_id"]),
        "chunk_id": str(row.get("chunk_id") or row["target_id"]),
        "chunk_text": str(row.get("evidence_text") or ""),
        "rank": int(row["rank"]),
        "similarity_score": float(row["cosine_similarity"]),
        "retrieval_score": float(row["cosine_similarity"]),
        "score_type": "qwen3_4b_cosine_similarity",
        "confidence": "not_calibrated",
        "metadata": dict(row.get("metadata") or {}),
        "limitations": ["코사인 유사도는 정답 확률이나 과실비율 판단값이 아닙니다."],
    }


def search_review_case(request: RagRequest) -> DomainSearchResult:
    """심의사례 전용 DB에서 사례 단위 Top-10 근거를 반환한다."""

    try:
        rows = search_by_vector("review_case", _resolve_vector(request), top_k=10, candidate_k=200)
    except (KeyError, RuntimeError, ValueError, OSError) as error:
        return {
            "contract_version": request.get("contract_version", "v1"),
            "domain": "review_case",
            "status": "failed",
            "evidence": [],
            "limitations": [f"심의사례 검색을 실행하지 못했습니다: {error}"],
            "missing_fields": [],
        }
    return {
        "contract_version": request.get("contract_version", "v1"),
        "domain": "review_case",
        "status": "success" if rows else "partial",
        "evidence": [_evidence(row) for row in rows],
        "calculation_result": None,
        "limitations": ["심의사례는 유사 사례 근거를 제공하며 최종 과실 판단을 수행하지 않습니다."],
        "missing_fields": [],
    }
