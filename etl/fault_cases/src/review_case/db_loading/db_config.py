from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[5]
ARTIFACT_ROOT = PROJECT_ROOT / "etl" / "fault_cases" / "artifacts" / "review_case_output"
REVIEW_CASE_MD_ROOT = PROJECT_ROOT / "etl" / "fault_cases" / "Fault_cases_MD" / "심의사례"
PREPROCESSED_DIR = ARTIFACT_ROOT / "preprocessed"
POSTGRES_EXPORT_ROOT = ARTIFACT_ROOT / "postgres_exports"
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
