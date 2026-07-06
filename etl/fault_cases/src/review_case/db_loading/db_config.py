from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[5]
ARTIFACT_ROOT = PROJECT_ROOT / "etl" / "fault_cases" / "artifacts" / "review_case_output"
REVIEW_CASE_MD_ROOT = PROJECT_ROOT / "etl" / "fault_cases" / "Fault_cases_MD" / "심의사례"
PREPROCESSED_DIR = ARTIFACT_ROOT / "preprocessed"
POSTGRES_EXPORT_ROOT = ARTIFACT_ROOT / "postgres_exports"
ELASTICSEARCH_EXPORT_ROOT = ARTIFACT_ROOT / "elasticsearch_exports"
RETRIEVAL_AB_EXPORT_ROOT = ARTIFACT_ROOT / "retrieval_ab_exports"
SCHEMA_PATH = PROJECT_ROOT / "storage" / "schemas" / "review_case_db_schema.sql"


def load_dotenv_if_available() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv_if_available()


@dataclass(frozen=True)
class PostgresSettings:
    host: str = os.getenv("POSTGRES_HOST", "localhost")
    port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    user: str = os.getenv("POSTGRES_USER", "postgres")
    password: str = os.getenv("POSTGRES_PASSWORD", "change-me")
    maintenance_db: str = os.getenv("POSTGRES_DB", "law_db")
    review_case_db: str = os.getenv("REVIEW_CASE_DB", "review_case_db")


SETTINGS = PostgresSettings()


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


@dataclass(frozen=True)
class PgvectorIndexSettings:
    index_name: str = os.getenv(
        "REVIEW_CASE_PGVECTOR_INDEX_NAME",
        "idx_review_case_chunk_embeddings_cosine_hnsw",
    )
    index_method: str = os.getenv("REVIEW_CASE_PGVECTOR_INDEX_METHOD", "hnsw")
    hnsw_m: int = int(os.getenv("REVIEW_CASE_PGVECTOR_HNSW_M", "16"))
    hnsw_ef_construction: int = int(os.getenv("REVIEW_CASE_PGVECTOR_HNSW_EF_CONSTRUCTION", "64"))


PGVECTOR_INDEX_SETTINGS = PgvectorIndexSettings()


@dataclass(frozen=True)
class PgvectorSearchSettings:
    default_top_k: int = int(os.getenv("REVIEW_CASE_PGVECTOR_TOP_K", "5"))
    sample_report_name: str = os.getenv(
        "REVIEW_CASE_PGVECTOR_SAMPLE_REPORT_NAME",
        "review_case_pgvector_sample_queries.json",
    )


PGVECTOR_SEARCH_SETTINGS = PgvectorSearchSettings()


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
    default_top_k: int = int(os.getenv("REVIEW_CASE_ES_TOP_K", str(PGVECTOR_SEARCH_SETTINGS.default_top_k)))
    analyzer_name: str = os.getenv("REVIEW_CASE_ES_ANALYZER", "review_case_nori")
    bm25_index_name: str = os.getenv(
        "REVIEW_CASE_ES_BM25_INDEX",
        "review_case_chunks_bm25_nori_v1",
    )
    bm25_index_version: str = os.getenv("REVIEW_CASE_ES_BM25_INDEX_VERSION", "bm25_nori_v1")
    bm25_index_report_name: str = os.getenv(
        "REVIEW_CASE_ES_BM25_INDEX_REPORT_NAME",
        "review_case_elasticsearch_bm25_index_report.json",
    )
    bm25_sample_report_name: str = os.getenv(
        "REVIEW_CASE_ES_BM25_SAMPLE_REPORT_NAME",
        "review_case_elasticsearch_bm25_sample_queries.json",
    )
    vector_index_name: str = os.getenv(
        "REVIEW_CASE_ES_VECTOR_INDEX",
        "review_case_chunks_vector_hybrid_v1",
    )
    vector_index_version: str = os.getenv("REVIEW_CASE_ES_VECTOR_INDEX_VERSION", "vector_hybrid_v1")
    vector_index_report_name: str = os.getenv(
        "REVIEW_CASE_ES_VECTOR_INDEX_REPORT_NAME",
        "review_case_elasticsearch_vector_index_report.json",
    )
    vector_sample_report_name: str = os.getenv(
        "REVIEW_CASE_ES_VECTOR_SAMPLE_REPORT_NAME",
        "review_case_elasticsearch_vector_sample_queries.json",
    )
    hybrid_sample_report_name: str = os.getenv(
        "REVIEW_CASE_ES_HYBRID_SAMPLE_REPORT_NAME",
        "review_case_elasticsearch_hybrid_sample_queries.json",
    )
    vector_num_candidates: int = int(os.getenv("REVIEW_CASE_ES_VECTOR_NUM_CANDIDATES", "100"))
    hybrid_rrf_k: int = int(os.getenv("REVIEW_CASE_ES_HYBRID_RRF_K", "60"))


ELASTICSEARCH_SETTINGS = ElasticsearchSettings()
