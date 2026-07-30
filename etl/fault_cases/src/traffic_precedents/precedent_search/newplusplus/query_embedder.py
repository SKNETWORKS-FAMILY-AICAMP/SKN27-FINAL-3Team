"""Qwen3-Embedding-4B 실시간 질문 임베딩."""

from __future__ import annotations

from typing import Any

import numpy as np

from .config import ServiceSettings
from .errors import SearchStageError


def build_query_text(query_text: str) -> str:
    return ServiceSettings().qwen_query_instruction + query_text.strip()


class QwenQueryEmbedder:
    def __init__(
        self,
        model: Any | None = None,
        *,
        dimension: int | None = None,
        device: str = "cuda",
    ) -> None:
        self.settings = ServiceSettings()
        self.dimension = dimension or self.settings.embedding_dimension
        self.device = device
        self._model = model

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise SearchStageError(
                "MODEL_NOT_READY", "Qwen 임베딩 의존성이 없습니다.", "embedding"
            ) from exc
        if self.device == "cuda" and not torch.cuda.is_available():
            raise SearchStageError(
                "MODEL_NOT_READY", "Qwen 임베딩용 CUDA GPU가 없습니다.", "embedding"
            )
        self._model = SentenceTransformer(
            self.settings.qwen_model_id,
            revision=self.settings.qwen_revision,
            trust_remote_code=True,
            device=self.device,
            model_kwargs={
                "torch_dtype": (
                    torch.bfloat16
                    if torch.cuda.is_bf16_supported()
                    else torch.float16
                )
            },
        )
        return self._model

    def encode(self, query_text: str) -> np.ndarray:
        if not isinstance(query_text, str) or not query_text.strip():
            raise SearchStageError("EMPTY_QUERY", "질문이 비어 있습니다.", "embedding")
        try:
            values = self._load_model().encode(
                [build_query_text(query_text)],
                batch_size=1,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            vector = np.asarray(values[0], dtype=np.float32)
            if vector.shape != (self.dimension,) or not np.isfinite(vector).all():
                raise ValueError(f"invalid vector shape={vector.shape}")
            norm = float(np.linalg.norm(vector))
            if not np.isfinite(norm) or norm <= 0:
                raise ValueError("invalid vector norm")
            return np.asarray(vector / norm, dtype=np.float32)
        except SearchStageError:
            raise
        except Exception as exc:
            raise SearchStageError(
                "EMBEDDING_FAILED", "질문 임베딩에 실패했습니다.", "embedding", True
            ) from exc
