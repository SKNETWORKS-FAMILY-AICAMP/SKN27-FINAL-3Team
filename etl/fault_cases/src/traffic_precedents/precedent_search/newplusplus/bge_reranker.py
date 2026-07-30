"""BGE cross-encoder 리랭커."""

from __future__ import annotations

import math
import hashlib
from typing import Any

from .config import ServiceSettings
from .errors import SearchStageError


class BgeReranker:
    def __init__(self, model: Any | None = None, *, device: str = "cuda") -> None:
        self.settings = ServiceSettings()
        self.device = device
        self._model = model

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            import torch
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise SearchStageError(
                "MODEL_NOT_READY", "BGE 리랭커 의존성이 없습니다.", "rerank"
            ) from exc
        if self.device == "cuda" and not torch.cuda.is_available():
            raise SearchStageError(
                "MODEL_NOT_READY", "BGE 리랭커용 CUDA GPU가 없습니다.", "rerank"
            )
        self._model = CrossEncoder(
            self.settings.bge_model_id,
            revision=self.settings.bge_revision,
            max_length=self.settings.bge_max_length,
            device=self.device,
            trust_remote_code=False,
        )
        return self._model

    def score(
        self, query_text: str, candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        pairs = [(query_text, str(row["reranker_text"])) for row in candidates]
        try:
            scores = self._load_model().predict(
                pairs,
                batch_size=self.settings.bge_batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            if isinstance(scores, (float, int)):
                scores = [scores]
            if len(scores) != len(candidates):
                raise ValueError("score count mismatch")
            result = []
            for candidate, score_value in zip(candidates, scores):
                score = float(score_value)
                if not math.isfinite(score):
                    raise ValueError("non-finite rerank score")
                row = dict(candidate)
                row["rerank_score"] = score
                row["reranker_input_sha256"] = hashlib.sha256(
                    (query_text + "\0" + str(row["reranker_text"])).encode("utf-8")
                ).hexdigest()
                result.append(row)
            return sorted(
                result,
                key=lambda row: (
                    -row["rerank_score"],
                    row["candidate_rank"],
                    str(row["record_id"]),
                ),
            )
        except SearchStageError:
            raise
        except Exception as exc:
            raise SearchStageError(
                "RERANK_FAILED", "BGE 리랭킹에 실패했습니다.", "rerank", True
            ) from exc
