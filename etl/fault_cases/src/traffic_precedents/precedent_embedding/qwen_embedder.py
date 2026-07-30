from __future__ import annotations

from typing import Iterable

import numpy as np

from ..config import QWEN_DIMENSION, QWEN_MODEL_ID, QWEN_REVISION


def embed_texts(
    texts: Iterable[str],
    *,
    batch_size: int = 4,
    device: str | None = None,
) -> np.ndarray:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        QWEN_MODEL_ID,
        revision=QWEN_REVISION,
        device=device,
        trust_remote_code=True,
    )
    values = model.encode(
        list(texts),
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )
    matrix = np.asarray(values, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[1] != QWEN_DIMENSION:
        raise ValueError(f"unexpected embedding shape: {matrix.shape}")
    return matrix
