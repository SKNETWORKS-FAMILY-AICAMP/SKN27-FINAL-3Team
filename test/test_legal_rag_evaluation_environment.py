from __future__ import annotations

from pathlib import Path

from etl.legal import evaluation_environment as environment


def _ready_values() -> dict[str, str]:
    return {
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
