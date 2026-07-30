"""기존 Qwen Top-5에 BGE 순서 재정렬만 적용하는 심의사례 RAG."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from etl.fault_cases.rag_runtime.contracts import (
    DomainSearchResult,
    RagRequest,
)
from etl.fault_cases.rag_runtime.shared.qwen4_retrieval import (
    encode_live_query,
    fetch_document_chunks,
    precomputed_query_vectors,
    search_by_vector,
    validate_vector,
)

from .config import DEFAULT_CONFIG, ReviewCaseRagConfig
from .context_builder import build_case_context
from .reranker import RerankResult, rerank_candidates


RerankFunction = Callable[..., RerankResult]


def _query_text(request: RagRequest) -> str:
    return str(
        request.get("query_text")
        or request.get("raw_user_text")
        or ""
    )


def _resolve_vector(request: RagRequest) -> list[float]:
    """운영 질의 또는 내부 평가 질의의 기존 Qwen 벡터를 결정한다."""

    supplied = request.get("query_vector")
    if supplied is not None:
        values = [float(value) for value in supplied]
        validate_vector(values)
        return values
    evaluation_query_id = request.get("evaluation_query_id")
    if evaluation_query_id:
        return precomputed_query_vectors("review_case")[
            str(evaluation_query_id)
        ]
    return encode_live_query(_query_text(request))


def _decision_ratio(metadata: dict[str, Any]) -> str | None:
    value = (
        metadata.get("decision_fault_ratio")
        or metadata.get("final_ratio")
    )
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _evidence(
    row: dict[str, Any],
    *,
    reranker_applied: bool,
) -> dict[str, Any]:
    metadata = dict(row.get("metadata") or {})
    metadata.setdefault(
        "review_case_id",
        str(row["document_id"]),
    )
    ratio = _decision_ratio(metadata)
    metadata["decision_fault_ratio"] = ratio
    metadata.update(
        {
            "first_stage_rank": int(
                row.get("first_stage_rank", row["rank"])
            ),
            "first_stage_score": float(
                row.get(
                    "first_stage_score",
                    row["cosine_similarity"],
                )
            ),
            "reranker_applied": reranker_applied,
            "ranking_method": (
                "bge_reranker_v2_m3"
                if reranker_applied
                else "qwen_vector_only"
            ),
        }
    )
    retrieval_score = (
        float(row["rerank_score"])
        if reranker_applied
        else float(row["cosine_similarity"])
    )
    evidence: dict[str, Any] = {
        "source_type": "review_case",
        "source_reference": str(row["source_reference"]),
        "title": str(row.get("title") or row["document_id"]),
        "chunk_id": str(
            row.get("chunk_id") or row["target_id"]
        ),
        "chunk_text": str(row.get("evidence_text") or ""),
        "rank": int(row["rank"]),
        "similarity_score": float(row["cosine_similarity"]),
        "retrieval_score": retrieval_score,
        "score_type": (
            "bge_reranker_v2_m3_raw_logit"
            if reranker_applied
            else "qwen3_4b_cosine_similarity"
        ),
        "confidence": "not_calibrated",
        "decision_fault_ratio": ratio,
        "metadata": metadata,
        "limitations": [
            "검색 점수는 정답 확률이나 과실비율 판단값이 아닙니다."
        ],
    }
    if reranker_applied:
        evidence["rerank_score"] = float(row["rerank_score"])
    return evidence


def _qwen_fallback(
    rows: list[dict[str, Any]],
    limitation: str,
) -> RerankResult:
    candidates: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        row["first_stage_rank"] = int(source["rank"])
        row["first_stage_score"] = float(
            source["cosine_similarity"]
        )
        candidates.append(row)
    return RerankResult(
        candidates=candidates,
        applied=False,
        failure_code="BGE_RERANKER_UNAVAILABLE",
        limitation=limitation,
    )


def _add_full_case_contexts(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    document_ids = [str(row["document_id"]) for row in rows]
    chunks_by_document = fetch_document_chunks(
        "review_case",
        document_ids,
    )
    contextualized: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        document_id = str(row["document_id"])
        chunks = chunks_by_document.get(document_id, [])
        row["evidence_text"] = build_case_context(row, chunks)

        metadata = dict(row.get("metadata") or {})
        if _decision_ratio(metadata) is None:
            for chunk in chunks:
                chunk_metadata = dict(chunk.get("metadata") or {})
                ratio = _decision_ratio(chunk_metadata)
                if ratio is not None:
                    metadata["decision_fault_ratio"] = ratio
                    break
        row["metadata"] = metadata
        contextualized.append(row)
    return contextualized


def search_review_case(
    request: RagRequest,
    *,
    config: ReviewCaseRagConfig = DEFAULT_CONFIG,
    rerank: RerankFunction = rerank_candidates,
) -> DomainSearchResult:
    """기존 Qwen 고유사례 Top-5의 구성은 보존하고 순서만 재정렬한다."""

    try:
        rows = search_by_vector(
            "review_case",
            _resolve_vector(request),
            top_k=config.unique_case_k,
            candidate_k=config.candidate_chunk_k,
        )
    except Exception:
        return {
            "contract_version": request.get(
                "contract_version",
                "v1",
            ),
            "domain": "review_case",
            "status": "failed",
            "evidence": [],
            "calculation_result": None,
            "limitations": [
                "심의사례 Qwen 임베딩 또는 DB 검색을 "
                "실행하지 못했습니다."
            ],
            "missing_fields": [],
        }

    if not rows:
        return {
            "contract_version": request.get(
                "contract_version",
                "v1",
            ),
            "domain": "review_case",
            "status": "partial",
            "evidence": [],
            "calculation_result": None,
            "limitations": [
                "서로 다른 심의사례 검색 결과가 없습니다.",
                "심의사례는 유사 근거만 제공하며 "
                "최종 과실 판단을 하지 않습니다.",
            ],
            "missing_fields": [],
        }

    try:
        contextualized = _add_full_case_contexts(rows)
        outcome = rerank(
            _query_text(request),
            contextualized,
            config=config,
        )
        source_ids = {
            str(row["document_id"]) for row in contextualized
        }
        reranked_id_list = [
            str(row["document_id"])
            for row in outcome.candidates
        ]
        reranked_ids = set(reranked_id_list)
        if (
            len(reranked_id_list) != len(contextualized)
            or len(reranked_ids) != len(reranked_id_list)
            or source_ids != reranked_ids
        ):
            outcome = _qwen_fallback(
                contextualized,
                "BGE 결과가 Qwen 후보 집합과 달라 "
                "Qwen 사례 순위를 유지했습니다.",
            )
    except Exception:
        outcome = _qwen_fallback(
            rows,
            "BGE 리랭커 문맥을 준비하지 못해 "
            "Qwen 사례 순위를 유지했습니다.",
        )

    limitations = [
        "심의사례는 유사 사례 근거를 제공하며 "
        "최종 과실 판단을 수행하지 않습니다."
    ]
    if outcome.limitation:
        limitations.append(outcome.limitation)
    if len(outcome.candidates) < config.final_output_k:
        limitations.append(
            f"고유 심의사례가 "
            f"{len(outcome.candidates)}건만 검색됐습니다."
        )

    evidence = [
        _evidence(row, reranker_applied=outcome.applied)
        for row in outcome.candidates[: config.final_output_k]
    ]
    missing_ratio_ids = [
        str(row["metadata"]["review_case_id"])
        for row in evidence
        if row["decision_fault_ratio"] is None
    ]
    if missing_ratio_ids:
        limitations.append(
            "결정 과실비율이 없는 심의사례: "
            + ", ".join(missing_ratio_ids)
        )

    return {
        "contract_version": request.get(
            "contract_version",
            "v1",
        ),
        "domain": "review_case",
        "status": (
            "success"
            if outcome.applied
            and len(outcome.candidates) == config.final_output_k
            and not missing_ratio_ids
            else "partial"
        ),
        "evidence": evidence,
        "calculation_result": None,
        "limitations": limitations,
        "missing_fields": [],
    }
