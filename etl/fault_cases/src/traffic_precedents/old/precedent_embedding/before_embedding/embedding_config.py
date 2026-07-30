from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.config import (
    POSTGRES_EXPORT_ROOT,
    SETTINGS,
)


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str = os.getenv("OPENAI_EMBEDDING_PROVIDER", "openai")
    model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    dim: int = int(os.getenv("OPENAI_EMBEDDING_DIM", "1536"))
    version: str = os.getenv(
        "OPENAI_EMBEDDING_VERSION",
        "openai_text_embedding_3_small_chunk_text_v1",
    )
    input_field: str = os.getenv("OPENAI_EMBEDDING_INPUT_FIELD", "chunk_text")
    batch_size: int = int(os.getenv("OPENAI_EMBEDDING_BATCH_SIZE", "64"))
    max_input_chars: int = int(os.getenv("OPENAI_EMBEDDING_MAX_INPUT_CHARS", "6000"))
    max_retries: int = int(os.getenv("OPENAI_EMBEDDING_MAX_RETRIES", "3"))
    retry_sleep_seconds: float = float(os.getenv("OPENAI_EMBEDDING_RETRY_SLEEP_SECONDS", "2"))


EMBEDDING_SETTINGS = EmbeddingSettings()


DATASET_EMBEDDING_CONFIGS = {
    "traffic": {
        "db_name": SETTINGS.traffic_db,
        "chunk_table": "traffic_precedent_chunks",
        "embedding_table": "traffic_precedent_chunk_embeddings",
        "report_path": POSTGRES_EXPORT_ROOT / "traffic" / "traffic_embeddings_load_report.json",
        "validation_report_path": POSTGRES_EXPORT_ROOT
        / "traffic"
        / "traffic_embeddings_validation_report.json",
    },
    "fault_ratio": {
        "db_name": SETTINGS.fault_ratio_db,
        "chunk_table": "fault_ratio_precedent_chunks",
        "embedding_table": "fault_ratio_precedent_chunk_embeddings",
        "report_path": POSTGRES_EXPORT_ROOT
        / "fault_ratio"
        / "fault_ratio_embeddings_load_report.json",
        "validation_report_path": POSTGRES_EXPORT_ROOT
        / "fault_ratio"
        / "fault_ratio_embeddings_validation_report.json",
    },
}


def ensure_report_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
