"""Qwen Top-5의 구성은 보존하고 순서만 바꾸는 BGE 리랭커."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .config import DEFAULT_CONFIG, ReviewCaseRagConfig


Candidate = dict[str, Any]
ScoreFunction = Callable[
    [str, Sequence[Candidate], ReviewCaseRagConfig],
    Sequence[float],
]


@dataclass(frozen=True)
class RerankResult:
    candidates: list[Candidate]
    applied: bool
    failure_code: str | None = None
    limitation: str | None = None


def _case_id(row: Candidate) -> str:
    metadata = dict(row.get("metadata") or {})
    value = metadata.get("review_case_id") or row.get("document_id")
    if not value:
        raise ValueError("candidate has no stable review case ID")
    return str(value)


def rerank_with_scores(
    candidates: Sequence[Candidate],
    scores: Sequence[float],
) -> list[Candidate]:
    if len(candidates) != len(scores):
        raise ValueError("candidate and reranker score counts differ")
    if not all(math.isfinite(float(score)) for score in scores):
        raise ValueError("reranker returned NaN or Inf")

    case_ids = [_case_id(row) for row in candidates]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("reranker input contains duplicate review cases")

    scored: list[Candidate] = []
    for source, score in zip(candidates, scores, strict=True):
        row = dict(source)
        row["first_stage_rank"] = int(source["rank"])
        row["first_stage_score"] = float(
            source["cosine_similarity"]
        )
        row["rerank_score"] = float(score)
        scored.append(row)

    ranked = sorted(
        scored,
        key=lambda row: (
            -float(row["rerank_score"]),
            int(row["first_stage_rank"]),
            _case_id(row),
        ),
    )
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
    return ranked


def _qwen_fallback(
    candidates: Sequence[Candidate],
) -> RerankResult:
    rows: list[Candidate] = []
    for source in candidates:
        row = dict(source)
        row["first_stage_rank"] = int(source["rank"])
        row["first_stage_score"] = float(
            source["cosine_similarity"]
        )
        rows.append(row)
    return RerankResult(
        candidates=rows,
        applied=False,
        failure_code="BGE_RERANKER_UNAVAILABLE",
        limitation=(
            "BGE 리랭커를 적용하지 못해 "
            "Qwen 사례 순위를 유지했습니다."
        ),
    )


class BgeReranker:
    def __init__(self, config: ReviewCaseRagConfig) -> None:
        self._config = config
        self._model: Any | None = None
        self._lock = threading.Lock()

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(
                    self._config.reranker_model_name,
                    revision=self._config.reranker_revision,
                    max_length=self._config.reranker_max_length,
                    device=self._config.reranker_device,
                )
        return self._model

    def score(
        self,
        query_text: str,
        candidates: Sequence[Candidate],
    ) -> list[float]:
        if not query_text.strip():
            raise ValueError("query text is required for BGE reranking")
        pairs = [
            (query_text, str(row.get("evidence_text") or ""))
            for row in candidates
        ]
        predictions = self._get_model().predict(
            pairs,
            batch_size=self._config.reranker_batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [
            float(value)
            for value in predictions.reshape(-1).tolist()
        ]


_DEFAULT_RERANKERS: dict[ReviewCaseRagConfig, BgeReranker] = {}
_DEFAULT_RERANKERS_LOCK = threading.Lock()


def _default_score(
    query_text: str,
    candidates: Sequence[Candidate],
    config: ReviewCaseRagConfig,
) -> Sequence[float]:
    with _DEFAULT_RERANKERS_LOCK:
        reranker = _DEFAULT_RERANKERS.setdefault(
            config,
            BgeReranker(config),
        )
    return reranker.score(query_text, candidates)


def rerank_candidates(
    query_text: str,
    candidates: Sequence[Candidate],
    *,
    config: ReviewCaseRagConfig = DEFAULT_CONFIG,
    scorer: ScoreFunction | None = None,
) -> RerankResult:
    if len(candidates) > config.reranker_input_k:
        raise ValueError(
            "reranker input exceeds the frozen Top-5 contract"
        )
    case_ids = [_case_id(row) for row in candidates]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError(
            "reranker input contains duplicate review cases"
        )

    try:
        score_function = scorer or _default_score
        scores = score_function(query_text, candidates, config)
        ranked = rerank_with_scores(candidates, scores)
    except Exception:
        return _qwen_fallback(candidates)
    return RerankResult(candidates=ranked, applied=True)
