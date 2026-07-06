from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

from openai import OpenAI

from .embedding_config import EMBEDDING_SETTINGS, EmbeddingSettings


@dataclass(frozen=True)
class EmbeddingBatchResult:
    vectors: list[list[float]]
    model: str
    prompt_tokens: int | None
    total_tokens: int | None


class OpenAIEmbedder:
    def __init__(self, settings: EmbeddingSettings = EMBEDDING_SETTINGS) -> None:
        self.settings = settings
        self.client = OpenAI()

    def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatchResult:
        if not texts:
            return EmbeddingBatchResult(vectors=[], model=self.settings.model, prompt_tokens=0, total_tokens=0)

        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                response = self.client.embeddings.create(
                    model=self.settings.model,
                    input=list(texts),
                    dimensions=self.settings.dim,
                    encoding_format="float",
                )
                vectors = [item.embedding for item in response.data]
                usage = getattr(response, "usage", None)
                return EmbeddingBatchResult(
                    vectors=vectors,
                    model=response.model or self.settings.model,
                    prompt_tokens=getattr(usage, "prompt_tokens", None),
                    total_tokens=getattr(usage, "total_tokens", None),
                )
            except Exception as exc:  # OpenAI SDK exceptions vary by version.
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                time.sleep(self.settings.retry_sleep_seconds * attempt)

        raise RuntimeError(f"OpenAI embedding request failed after {self.settings.max_retries} attempts") from last_error

