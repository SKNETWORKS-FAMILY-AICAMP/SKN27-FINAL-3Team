from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.config import (
    POSTGRES_EXPORT_ROOT,
    SETTINGS,
)


@dataclass(frozen=True)
class SearchSettings:
    embedding_model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    embedding_dim: int = int(os.getenv("OPENAI_EMBEDDING_DIM", "1536"))
    embedding_version: str = os.getenv(
        "OPENAI_EMBEDDING_VERSION",
        "openai_text_embedding_3_small_chunk_text_v1",
    )
    default_top_k: int = int(os.getenv("PRECEDENT_SEARCH_TOP_K", "5"))
    index_method: str = os.getenv("PRECEDENT_PGVECTOR_INDEX_METHOD", "hnsw").lower()
    hnsw_m: int = int(os.getenv("PRECEDENT_PGVECTOR_HNSW_M", "16"))
    hnsw_ef_construction: int = int(os.getenv("PRECEDENT_PGVECTOR_HNSW_EF_CONSTRUCTION", "64"))


SEARCH_SETTINGS = SearchSettings()


DATASET_SEARCH_CONFIGS: dict[str, dict[str, object]] = {
    "traffic": {
        "db_name": SETTINGS.traffic_db,
        "case_table": "traffic_precedent_cases",
        "chunk_table": "traffic_precedent_chunks",
        "embedding_table": "traffic_precedent_chunk_embeddings",
        "index_name": "idx_traffic_precedent_chunk_embeddings_cosine_hnsw",
        "index_report_path": POSTGRES_EXPORT_ROOT / "traffic" / "traffic_pgvector_index_report.json",
        "sample_report_path": POSTGRES_EXPORT_ROOT / "traffic" / "traffic_pgvector_sample_queries.json",
    },
    "fault_ratio": {
        "db_name": SETTINGS.fault_ratio_db,
        "case_table": "fault_ratio_precedent_cases",
        "chunk_table": "fault_ratio_precedent_chunks",
        "embedding_table": "fault_ratio_precedent_chunk_embeddings",
        "index_name": "idx_fault_ratio_precedent_chunk_embeddings_cosine_hnsw",
        "index_report_path": POSTGRES_EXPORT_ROOT
        / "fault_ratio"
        / "fault_ratio_pgvector_index_report.json",
        "sample_report_path": POSTGRES_EXPORT_ROOT
        / "fault_ratio"
        / "fault_ratio_pgvector_sample_queries.json",
    },
}


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
