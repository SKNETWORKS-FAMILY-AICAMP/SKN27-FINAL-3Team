from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from etl.fault_cases.src.review_case.db_loading.db_config import EmbeddingSettings
from etl.fault_cases.src.review_case.embedding import run_embedding
from etl.fault_cases.src.review_case.search.pgvector import retriever


class _RecordingCursor:
    def __init__(self, connection: "_RecordingConnection") -> None:
        self.connection = connection

    def __enter__(self) -> "_RecordingCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def mogrify(self, template: bytes, args: tuple[Any, ...]) -> bytes:
        self.connection.values.append(args)
        return b"(" + b",".join(b"%s" for _ in args) + b")"

    def execute(self, statement: str | bytes, params: object = None) -> None:
        if isinstance(statement, bytes):
            statement = statement.decode("utf-8")
        self.connection.events.append((statement, params))

    def fetchall(self) -> list[object]:
        return []


class _RecordingConnection:
    encoding = "UTF8"

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.values: list[tuple[Any, ...]] = []

    def cursor(self, **_kwargs: object) -> _RecordingCursor:
        return _RecordingCursor(self)


def _record_connection(monkeypatch, module) -> _RecordingConnection:
    connection = _RecordingConnection()

    @contextmanager
    def fake_get_connection(*_args: object, **_kwargs: object) -> Iterator[_RecordingConnection]:
        yield connection

    monkeypatch.setattr(module, "get_connection", fake_get_connection)
    return connection


def test_pending_selection_requires_an_active_chunk_without_matching_hash(
    monkeypatch,
) -> None:
    connection = _record_connection(monkeypatch, run_embedding)
    settings = EmbeddingSettings()

    assert run_embedding.fetch_pending_chunks(settings) == []

    statement = connection.events[0][0]
    assert "c.is_active IS TRUE" in statement
    assert "e.source_text_hash = c.text_hash" in statement
    assert "e.embedding_dim = %s" in statement


def test_embedding_write_keeps_an_existing_hash_revision_immutable(monkeypatch) -> None:
    connection = _record_connection(monkeypatch, run_embedding)
    monkeypatch.setattr(
        run_embedding,
        "execute_values",
        lambda cursor, statement, values, **_kwargs: cursor.execute(statement)
        or connection.values.extend(values),
    )
    settings = EmbeddingSettings()
    row = {
        "chunk_id": "chunk-1",
        "review_case_id": "case-1",
        "review_no": "2026-000001",
        "chunk_type": "case_chunk",
        "char_count": 20,
        "token_count": 4,
        "text_hash": "current-hash",
        "embedding_input_char_count": 20,
        "embedding_input_exceeds_limit": False,
    }

    assert run_embedding.upsert_embedding_batch(
        [row],
        [[0.0] * settings.dim],
        settings,
        response_model=settings.model,
        prompt_tokens=1,
        total_tokens=1,
    ) == 1

    embedding_statement = connection.events[0][0]
    assert "source_text_hash" in embedding_statement
    assert (
        "ON CONFLICT (chunk_id, embedding_model, embedding_version, source_text_hash) DO NOTHING"
        in " ".join(embedding_statement.split())
    )
    assert "embedding_vector = EXCLUDED.embedding_vector" not in embedding_statement


def test_retrieval_uses_only_active_current_hash_revisions(monkeypatch) -> None:
    connection = _record_connection(monkeypatch, retriever)

    assert retriever.search_by_vector([0.0] * 1024) == []

    statement = connection.events[0][0]
    assert "c.is_active IS TRUE" in statement
    assert "e.source_text_hash = c.text_hash" in statement
