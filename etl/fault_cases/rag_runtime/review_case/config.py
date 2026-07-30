"""심의사례 리랭커의 동결 운영 설정."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ReviewCaseRagConfig:
    candidate_chunk_k: int = 200
    unique_case_k: int = 5
    reranker_input_k: int = 5
    final_output_k: int = 5
    reranker_model_name: str = "BAAI/bge-reranker-v2-m3"
    reranker_revision: str = (
        "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    )
    reranker_max_length: int = 4096
    reranker_device: str = "cuda"
    reranker_batch_size: int = 4


def load_config(
    environ: Mapping[str, str] | None = None,
) -> ReviewCaseRagConfig:
    values = os.environ if environ is None else environ
    batch_size = int(
        values.get("REVIEW_CASE_RERANKER_BATCH_SIZE", "4")
    )
    if batch_size < 1:
        raise ValueError(
            "REVIEW_CASE_RERANKER_BATCH_SIZE must be positive"
        )
    return ReviewCaseRagConfig(
        reranker_device=values.get(
            "REVIEW_CASE_RERANKER_DEVICE",
            "cuda",
        ),
        reranker_batch_size=batch_size,
    )


DEFAULT_CONFIG = load_config()
