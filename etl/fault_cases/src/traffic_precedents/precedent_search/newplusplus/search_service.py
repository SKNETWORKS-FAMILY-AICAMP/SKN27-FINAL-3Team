"""NEW++-BGE 판례 전용 검색 오케스트레이터."""

from __future__ import annotations

import time
from typing import Any

from .bge_reranker import BgeReranker
from .candidate_retriever import CandidateRetriever
from .case_context_builder import CaseContextBuilder
from .config import ServiceSettings
from .contracts import validate_request, validate_response
from .errors import SearchStageError
from .query_embedder import QwenQueryEmbedder
from .result_builder import build_top5


def _milliseconds(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


class PrecedentSearchService:
    def __init__(
        self,
        *,
        embedder: Any | None = None,
        retriever: Any | None = None,
        context_builder: Any | None = None,
        reranker: Any | None = None,
    ) -> None:
        self.settings = ServiceSettings()
        self.embedder = embedder or QwenQueryEmbedder()
        self.retriever = retriever or CandidateRetriever()
        self.context_builder = context_builder or CaseContextBuilder()
        self.reranker = reranker or BgeReranker()

    def rank(self, request: dict[str, Any]) -> dict[str, Any]:
        validated = validate_request(request)
        stage_latency: dict[str, float] = {}
        total_start = time.perf_counter()

        start = time.perf_counter()
        try:
            query_vector = self.embedder.encode(validated["query_text"])
        except SearchStageError:
            raise
        except Exception as exc:
            raise SearchStageError(
                "EMBEDDING_FAILED", "질문 임베딩에 실패했습니다.", "embedding", True
            ) from exc
        stage_latency["embedding"] = _milliseconds(start)

        start = time.perf_counter()
        try:
            candidates = self.retriever.search(query_vector)
        except SearchStageError:
            raise
        except Exception as exc:
            raise SearchStageError(
                "RETRIEVAL_FAILED", "후보 검색에 실패했습니다.", "retrieval", True
            ) from exc
        stage_latency["retrieval"] = _milliseconds(start)

        start = time.perf_counter()
        try:
            contexts = self.context_builder.build_many(query_vector, candidates)
        except SearchStageError:
            raise
        except Exception as exc:
            raise SearchStageError(
                "CONTEXT_FAILED", "판례 문맥 구성에 실패했습니다.", "context", True
            ) from exc
        stage_latency["context"] = _milliseconds(start)

        start = time.perf_counter()
        try:
            scored = self.reranker.score(validated["query_text"], contexts)
        except SearchStageError:
            raise
        except Exception as exc:
            raise SearchStageError(
                "RERANK_FAILED", "후보 리랭킹에 실패했습니다.", "rerank", True
            ) from exc
        stage_latency["rerank"] = _milliseconds(start)
        stage_latency["total"] = _milliseconds(total_start)
        return {
            "request": validated,
            "ranked_candidates": scored,
            "candidate_count": len(candidates),
            "latency_ms": stage_latency,
        }

    def search(self, request: dict[str, Any]) -> dict[str, Any]:
        execution = self.rank(request)
        results = build_top5(
            execution["ranked_candidates"], final_top_k=self.settings.final_top_k
        )
        response = {
            "contract_version": "precedent-newplusplus-v1",
            "request_id": execution["request"]["request_id"],
            "domain": "precedent",
            "status": "success",
            "backend": "qwen4_pgvector_bge",
            "results": results,
            "candidate_count": execution["candidate_count"],
            "latency_ms": execution["latency_ms"],
            "error": None,
            "limitations": [
                "리랭커 점수는 정답 확률이 아닙니다.",
                "검색 결과는 법률 자문이나 법원의 최종 과실비율 판단이 아닙니다.",
            ],
        }
        return validate_response(response)

