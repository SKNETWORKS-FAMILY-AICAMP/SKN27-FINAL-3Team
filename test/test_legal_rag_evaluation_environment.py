from __future__ import annotations

from pathlib import Path

from etl.legal import evaluation_environment as environment


def _ready_values() -> dict[str, str]:
    return {
        "DJANGO_DATABASE_ENGINE": "postgres",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "law_db",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "local-secret",
        "LEGAL_RAG_VECTOR_ENABLED": "1",
        "LEGAL_RAG_QUERY_EMBEDDING_PROVIDER": "sentence-transformers",
        "LEGAL_RAG_QUERY_EMBEDDING_MODEL": "intfloat/multilingual-e5-large",
        "LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS": "1024",
        "LEGAL_RAG_SEED_EMBEDDING_PROVIDER": "sentence-transformers",
        "LEGAL_RAG_SEED_EMBEDDING_MODEL": "intfloat/multilingual-e5-large",
        "LEGAL_RAG_SEED_EMBEDDING_DIMENSIONS": "1024",
    }


def test_validate_evaluation_environment_requires_enabled_matching_1024_space() -> None:
    result = environment.validate_evaluation_environment({"LEGAL_RAG_VECTOR_ENABLED": "0"})

    assert result["status"] == "not_ready"
    assert "POSTGRES_HOST" in result["missing"]
    assert "LEGAL_RAG_VECTOR_ENABLED" in result["missing"]


def test_validate_evaluation_environment_rejects_seed_query_space_mismatch() -> None:
    values = _ready_values()
    values["LEGAL_RAG_SEED_EMBEDDING_MODEL"] = "other-model"

    result = environment.validate_evaluation_environment(values)

    assert result["status"] == "not_ready"
    assert result["reason"] == "embedding_space_mismatch"


def test_validate_evaluation_environment_requires_django_postgres_engine() -> None:
    values = _ready_values()
    values["DJANGO_DATABASE_ENGINE"] = "sqlite"

    result = environment.validate_evaluation_environment(values)

    assert result["status"] == "not_ready"
    assert result["reason"] == "django_database_engine_not_postgres"


def test_evaluation_environment_example_matches_documented_pgvector_seed_space() -> None:
    example = (
        Path(__file__).resolve().parents[1] / ".env.rag-eval.example"
    ).read_text(encoding="utf-8")

    assert "DJANGO_DATABASE_ENGINE=postgres" in example
    assert "LEGAL_RAG_QUERY_EMBEDDING_PROVIDER=openai" in example
    assert "LEGAL_RAG_QUERY_EMBEDDING_MODEL=text-embedding-3-large" in example
    assert "LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS=1024" in example
    assert "LEGAL_RAG_SEED_EMBEDDING_PROVIDER=openai" in example
    assert "LEGAL_RAG_SEED_EMBEDDING_MODEL=text-embedding-3-large" in example
    assert "LEGAL_RAG_SEED_EMBEDDING_DIMENSIONS=1024" in example


def test_sanitized_environment_result_never_contains_api_key_or_password(tmp_path: Path) -> None:
    path = tmp_path / ".env.rag-eval"
    path.write_text(
        "OPENAI_API_KEY=openai-secret\nPOSTGRES_PASSWORD=postgres-secret\n"
        "LEGAL_RAG_VECTOR_ENABLED=0\n",
        encoding="utf-8",
    )

    result = environment.validate_evaluation_environment(environment.load_evaluation_environment(path))

    assert "openai-secret" not in repr(result)
    assert "postgres-secret" not in repr(result)
