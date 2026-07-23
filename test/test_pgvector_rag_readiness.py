from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest


MODULE_NAME = "backend.chatbot.management.commands.verify_pgvector_rag_readiness"
ROOT = Path(__file__).resolve().parents[1]


def test_review_case_defaults_to_the_validated_legal_embedding_space(monkeypatch) -> None:
    config = importlib.import_module(
        "etl.fault_cases.src.review_case.db_loading.db_config"
    )
    monkeypatch.delenv("RAG_EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("RAG_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("RAG_EMBEDDING_DIMENSIONS", raising=False)

    settings = config.resolve_embedding_settings()

    assert settings.provider == "openai"
    assert settings.model == "text-embedding-3-large"
    assert settings.dim == 1024


def test_pgvector_readiness_requires_law_and_review_case_in_one_space(monkeypatch) -> None:
    assert importlib.util.find_spec(MODULE_NAME) is not None, (
        "pgvector readiness command must exist before ES readiness is removed"
    )
    command = importlib.import_module(MODULE_NAME)
    monkeypatch.setattr(
        command,
        "_verify_legal",
        lambda: {
            "status": "ready",
            "embedding_count": 3,
            "hnsw_index": True,
            "embedding_space": {
                "provider": "openai",
                "model": "text-embedding-3-large",
                "dimensions": 1024,
            },
        },
    )
    monkeypatch.setattr(
        command,
        "_verify_review_case",
        lambda: {
            "status": "ready",
            "embedding_count": 5,
            "hnsw_index": True,
            "embedding_space": {
                "provider": "openai",
                "model": "text-embedding-3-large",
                "dimensions": 1024,
            },
        },
    )
    monkeypatch.setattr(
        command,
        "_verify_fault_ratio_precedent",
        lambda: {"status": "unavailable", "error_code": "optional_store_offline"},
    )

    result = command.verify_pgvector_rag_readiness()

    assert result["contract_version"] == "pgvector_rag_readiness.v1"
    assert result["status"] == "ready"
    assert result["required_domains"] == ["legal", "review_case"]
    assert result["shared_embedding_space"] == {
        "provider": "openai",
        "model": "text-embedding-3-large",
        "dimensions": 1024,
    }
    assert result["domains"]["fault_ratio_precedent"]["required"] is False


def test_pgvector_readiness_fails_when_law_and_review_case_spaces_differ(
    monkeypatch,
) -> None:
    assert importlib.util.find_spec(MODULE_NAME) is not None, (
        "pgvector readiness command must exist before ES readiness is removed"
    )
    command = importlib.import_module(MODULE_NAME)
    monkeypatch.setattr(
        command,
        "_verify_legal",
        lambda: {
            "status": "ready",
            "embedding_space": {
                "provider": "openai",
                "model": "text-embedding-3-large",
                "dimensions": 1024,
            },
        },
    )
    monkeypatch.setattr(
        command,
        "_verify_review_case",
        lambda: {
            "status": "ready",
            "embedding_space": {
                "provider": "openai",
                "model": "text-embedding-3-small",
                "dimensions": 1536,
            },
        },
    )
    monkeypatch.setattr(
        command,
        "_verify_fault_ratio_precedent",
        lambda: {"status": "ready"},
    )

    result = command.verify_pgvector_rag_readiness()

    assert result["status"] == "fail"
    assert result["error_code"] == "shared_embedding_space_mismatch"


def test_review_case_schema_uses_1024_dimensions() -> None:
    schema = (ROOT / "storage/schemas/review_case_db_schema.sql").read_text(
        encoding="utf-8"
    )

    assert "embedding_vector vector(1024)" in schema
    assert "embedding_dim INTEGER NOT NULL DEFAULT 1024" in schema
    assert "CHECK (embedding_dim = 1024)" in schema
    assert "text-embedding-3-small" not in schema


def test_review_case_search_rejects_a_vector_from_another_embedding_space(
    monkeypatch,
) -> None:
    retriever = importlib.import_module(
        "etl.fault_cases.src.review_case.search.pgvector.retriever"
    )
    monkeypatch.setattr(
        retriever,
        "get_connection",
        lambda *_args, **_kwargs: pytest.fail("database must not be queried"),
    )

    with pytest.raises(RuntimeError, match="embedding_space_mismatch"):
        retriever.search_by_vector([0.0] * 1536)


def test_deployment_examples_use_the_shared_law_review_case_space() -> None:
    for name in (".env.example", ".env.production.example"):
        example = (ROOT / name).read_text(encoding="utf-8")
        assert "RAG_EMBEDDING_PROVIDER=openai" in example
        assert "RAG_EMBEDDING_MODEL=text-embedding-3-large" in example
        assert "RAG_EMBEDDING_DIMENSIONS=1024" in example
        assert "LEGAL_RAG_QUERY_EMBEDDING_PROVIDER=sentence-transformers" not in example


def test_review_case_dimension_migration_is_backup_gated() -> None:
    migration = (
        ROOT
        / "storage/migrations/20260723_unify_law_review_case_embeddings.sql"
    ).read_text(encoding="utf-8")

    assert "review_case_chunk_embeddings_1536_backup_20260723" in migration
    assert "backup_row_count_mismatch" in migration
    assert "TRUNCATE TABLE review_case_chunk_embeddings" in migration
    assert "TYPE vector(1024)" in migration
    assert "CHECK (embedding_dim = 1024)" in migration
    assert "COMMIT;" in migration


def test_text_ml_smoke_exposes_pgvector_requirement_flag() -> None:
    from backend.chatbot.management.commands import smoke_text_ml_case_search

    class RecordingParser:
        def __init__(self) -> None:
            self.arguments: list[tuple[tuple, dict]] = []

        def add_argument(self, *args, **kwargs):
            self.arguments.append((args, kwargs))

    parser = RecordingParser()
    smoke_text_ml_case_search.Command().add_arguments(parser)

    assert any("--require-pgvector" in args for args, _kwargs in parser.arguments)
    assert not any("--require-es" in args for args, _kwargs in parser.arguments)
