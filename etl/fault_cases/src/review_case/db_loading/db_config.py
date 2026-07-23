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

CANONICAL_EMBEDDING_PROVIDER = "openai"
CANONICAL_EMBEDDING_MODEL = "text-embedding-3-large"
CANONICAL_EMBEDDING_DIMENSIONS = 1024
CANONICAL_EMBEDDING_VERSION = "openai_text_embedding_3_large_1024_chunk_text_v1"


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
    provider: str = CANONICAL_EMBEDDING_PROVIDER
    model: str = CANONICAL_EMBEDDING_MODEL
    dim: int = CANONICAL_EMBEDDING_DIMENSIONS
    version: str = CANONICAL_EMBEDDING_VERSION
    input_field: str = "chunk_text"
    batch_size: int = 64
    max_input_chars: int = 6000
    max_retries: int = 3
    retry_sleep_seconds: float = 2.0


def resolve_embedding_settings(
    environ: dict[str, str] | None = None,
) -> EmbeddingSettings:
    env = os.environ if environ is None else environ
    return EmbeddingSettings(
        provider=env.get(
            "RAG_EMBEDDING_PROVIDER",
            env.get("OPENAI_EMBEDDING_PROVIDER", CANONICAL_EMBEDDING_PROVIDER),
        ).strip(),
        model=env.get(
            "RAG_EMBEDDING_MODEL",
            env.get("OPENAI_EMBEDDING_MODEL", CANONICAL_EMBEDDING_MODEL),
        ).strip(),
        dim=int(
            env.get(
                "RAG_EMBEDDING_DIMENSIONS",
                env.get("OPENAI_EMBEDDING_DIM", str(CANONICAL_EMBEDDING_DIMENSIONS)),
            )
        ),
        version=env.get(
            "REVIEW_CASE_EMBEDDING_VERSION",
            env.get("OPENAI_EMBEDDING_VERSION", CANONICAL_EMBEDDING_VERSION),
        ).strip(),
        input_field=env.get("OPENAI_EMBEDDING_INPUT_FIELD", "chunk_text").strip(),
        batch_size=int(env.get("OPENAI_EMBEDDING_BATCH_SIZE", "64")),
        max_input_chars=int(env.get("OPENAI_EMBEDDING_MAX_INPUT_CHARS", "6000")),
        max_retries=int(env.get("OPENAI_EMBEDDING_MAX_RETRIES", "3")),
        retry_sleep_seconds=float(
            env.get("OPENAI_EMBEDDING_RETRY_SLEEP_SECONDS", "2")
        ),
    )


EMBEDDING_SETTINGS = resolve_embedding_settings()


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
