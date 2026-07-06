from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class ElasticsearchSettings:
    host: str = os.getenv(
        "ELASTICSEARCH_HOST",
        f"http://localhost:{os.getenv('ELASTICSEARCH_PORT', '9200')}",
    )
    username: str = os.getenv("ELASTICSEARCH_USER", "elastic")
    password: str = os.getenv("ELASTIC_PASSWORD", "change-me")
    request_timeout: int = int(os.getenv("ELASTICSEARCH_REQUEST_TIMEOUT", "120"))
    bulk_chunk_size: int = int(os.getenv("ELASTICSEARCH_BULK_CHUNK_SIZE", "500"))
    default_top_k: int = int(os.getenv("PRECEDENT_ES_TOP_K", str(SEARCH_SETTINGS.default_top_k)))
    analyzer_name: str = os.getenv("PRECEDENT_ES_ANALYZER", "nori")
    bm25_index_version: str = os.getenv("PRECEDENT_ES_BM25_INDEX_VERSION", "bm25_nori_v1")
    vector_index_version: str = os.getenv("PRECEDENT_ES_VECTOR_INDEX_VERSION", "vector_hybrid_v1")
    vector_num_candidates: int = int(os.getenv("PRECEDENT_ES_VECTOR_NUM_CANDIDATES", "100"))
    hybrid_rrf_k: int = int(os.getenv("PRECEDENT_ES_HYBRID_RRF_K", "60"))


ELASTICSEARCH_SETTINGS = ElasticsearchSettings()


ELASTICSEARCH_EXPORT_ROOT = POSTGRES_EXPORT_ROOT.parent / "elasticsearch_exports"
RETRIEVAL_AB_EXPORT_ROOT = POSTGRES_EXPORT_ROOT.parent / "retrieval_ab_exports"


DATASET_SEARCH_CONFIGS: dict[str, dict[str, Any]] = {
    "traffic": {
        "db_name": SETTINGS.traffic_db,
        "case_table": "traffic_precedent_cases",
        "chunk_table": "traffic_precedent_chunks",
        "embedding_table": "traffic_precedent_chunk_embeddings",
        "index_name": "idx_traffic_precedent_chunk_embeddings_cosine_hnsw",
        "elasticsearch_index": "precedent_traffic_chunks_bm25_nori_v1",
        "elasticsearch_vector_index": "precedent_traffic_chunks_vector_hybrid_v1",
        "index_report_path": POSTGRES_EXPORT_ROOT / "traffic" / "traffic_pgvector_index_report.json",
        "sample_report_path": POSTGRES_EXPORT_ROOT / "traffic" / "traffic_pgvector_sample_queries.json",
        "elasticsearch_index_report_path": ELASTICSEARCH_EXPORT_ROOT
        / "traffic"
        / "traffic_elasticsearch_bm25_index_report.json",
        "elasticsearch_sample_report_path": ELASTICSEARCH_EXPORT_ROOT
        / "traffic"
        / "traffic_elasticsearch_bm25_sample_queries.json",
        "elasticsearch_vector_index_report_path": ELASTICSEARCH_EXPORT_ROOT
        / "traffic"
        / "traffic_elasticsearch_vector_index_report.json",
        "elasticsearch_vector_sample_report_path": ELASTICSEARCH_EXPORT_ROOT
        / "traffic"
        / "traffic_elasticsearch_vector_sample_queries.json",
        "elasticsearch_hybrid_sample_report_path": ELASTICSEARCH_EXPORT_ROOT
        / "traffic"
        / "traffic_elasticsearch_hybrid_sample_queries.json",
    },
    "fault_ratio": {
        "db_name": SETTINGS.fault_ratio_db,
        "case_table": "fault_ratio_precedent_cases",
        "chunk_table": "fault_ratio_precedent_chunks",
        "embedding_table": "fault_ratio_precedent_chunk_embeddings",
        "index_name": "idx_fault_ratio_precedent_chunk_embeddings_cosine_hnsw",
        "elasticsearch_index": "precedent_fault_ratio_chunks_bm25_nori_v1",
        "elasticsearch_vector_index": "precedent_fault_ratio_chunks_vector_hybrid_v1",
        "index_report_path": POSTGRES_EXPORT_ROOT
        / "fault_ratio"
        / "fault_ratio_pgvector_index_report.json",
        "sample_report_path": POSTGRES_EXPORT_ROOT
        / "fault_ratio"
        / "fault_ratio_pgvector_sample_queries.json",
        "elasticsearch_index_report_path": ELASTICSEARCH_EXPORT_ROOT
        / "fault_ratio"
        / "fault_ratio_elasticsearch_bm25_index_report.json",
        "elasticsearch_sample_report_path": ELASTICSEARCH_EXPORT_ROOT
        / "fault_ratio"
        / "fault_ratio_elasticsearch_bm25_sample_queries.json",
        "elasticsearch_vector_index_report_path": ELASTICSEARCH_EXPORT_ROOT
        / "fault_ratio"
        / "fault_ratio_elasticsearch_vector_index_report.json",
        "elasticsearch_vector_sample_report_path": ELASTICSEARCH_EXPORT_ROOT
        / "fault_ratio"
        / "fault_ratio_elasticsearch_vector_sample_queries.json",
        "elasticsearch_hybrid_sample_report_path": ELASTICSEARCH_EXPORT_ROOT
        / "fault_ratio"
        / "fault_ratio_elasticsearch_hybrid_sample_queries.json",
    },
}


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
