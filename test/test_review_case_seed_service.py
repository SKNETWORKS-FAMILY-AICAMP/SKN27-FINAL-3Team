from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

import app.services.review_case_seed_service as seed_service
from app.services.review_case_seed_service import (
    ReviewCaseSeedError,
    read_review_case_seed_rows,
    replace_and_upsert_review_case_rows,
)


def _valid_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "review_case_id": "review_case_2018_051544",
        "chunk_id": "review_case_2018_051544_case_overview",
        "review_no": "2018-051544",
        "chunk_type": "case_overview",
        "sequence_no": 1,
        "chunk_text": "교차로 신호위반 사고의 과실비율 판단 근거를 설명하는 충분한 길이의 본문입니다.",
        "source_ref": "review_case:2018-051544",
        "source_type": "review_case",
        "source_reliability_score": 3,
        "parse_status": "valid",
        "quality_flags": [],
    }
    row.update(overrides)
    return row


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8-sig",
    )


def test_read_review_case_seed_rows_normalizes_real_manifest_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "review.jsonl"
    _write_rows(path, [_valid_row()])

    rows = read_review_case_seed_rows(path)

    assert rows[0].review_case_id == "review_case_2018_051544"
    assert rows[0].review_no == "2018-051544"
    assert rows[0].search_text == rows[0].chunk_text
    assert rows[0].quality_flags == []
    assert rows[0].raw_json["source_ref"] == "review_case:2018-051544"


@pytest.mark.parametrize(
    "missing",
    ["review_case_id", "review_no", "chunk_id", "chunk_text"],
)
def test_read_review_case_seed_rows_rejects_missing_required_fields(
    tmp_path: Path,
    missing: str,
) -> None:
    row = _valid_row()
    row.pop(missing)
    path = tmp_path / "review.jsonl"
    _write_rows(path, [row])

    with pytest.raises(ReviewCaseSeedError, match=missing):
        read_review_case_seed_rows(path)


def test_read_review_case_seed_rows_rejects_short_text(tmp_path: Path) -> None:
    path = tmp_path / "review.jsonl"
    _write_rows(path, [_valid_row(chunk_text="너무 짧은 본문")])

    with pytest.raises(ReviewCaseSeedError, match="20"):
        read_review_case_seed_rows(path)


def test_read_review_case_seed_rows_rejects_negative_sequence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "review.jsonl"
    _write_rows(path, [_valid_row(sequence_no=-1)])

    with pytest.raises(ReviewCaseSeedError, match="sequence_no"):
        read_review_case_seed_rows(path)


def test_read_review_case_seed_rows_rejects_duplicate_chunk_ids(
    tmp_path: Path,
) -> None:
    path = tmp_path / "review.jsonl"
    _write_rows(path, [_valid_row(), _valid_row(sequence_no=2)])

    with pytest.raises(ReviewCaseSeedError, match="duplicate.*chunk_id"):
        read_review_case_seed_rows(path)


def test_read_review_case_seed_rows_accepts_two_chunks_for_one_document(
    tmp_path: Path,
) -> None:
    path = tmp_path / "review.jsonl"
    _write_rows(
        path,
        [
            _valid_row(),
            _valid_row(
                chunk_id="review_case_2018_051544_arguments",
                chunk_type="arguments",
                sequence_no=2,
            ),
        ],
    )

    rows = read_review_case_seed_rows(path)

    assert len(rows) == 2
    assert {row.review_case_id for row in rows} == {
        "review_case_2018_051544"
    }


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

    def execute(
        self,
        statement: str | bytes,
        params: tuple[Any, ...] | None = None,
    ) -> None:
        if isinstance(statement, bytes):
            statement = statement.decode("utf-8")
        self.connection.events.append((statement, params))


class _RecordingConnection:
    encoding = "UTF8"

    def __init__(self) -> None:
        self.events: list[tuple[str, tuple[Any, ...] | None]] = []
        self.values: list[tuple[Any, ...]] = []

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self)


def _recording_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_RecordingConnection, list[tuple[str, bool]]]:
    connection = _RecordingConnection()
    calls: list[tuple[str, bool]] = []

    @contextmanager
    def fake_get_connection(
        db_name: str,
        autocommit: bool = False,
    ) -> Iterator[_RecordingConnection]:
        calls.append((db_name, autocommit))
        yield connection

    monkeypatch.setattr(seed_service, "get_connection", fake_get_connection)
    return connection, calls


def test_replace_and_upsert_review_case_rows_is_one_scoped_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "review.jsonl"
    _write_rows(
        path,
        [
            _valid_row(),
            _valid_row(
                chunk_id="review_case_2018_051544_arguments",
                chunk_type="arguments",
                sequence_no=2,
            ),
        ],
    )
    rows = read_review_case_seed_rows(path)
    connection, calls = _recording_connection(monkeypatch)

    result = replace_and_upsert_review_case_rows(rows, replace=True)

    statements = [event[0] for event in connection.events]
    assert calls == [(seed_service.SETTINGS.review_case_db, False)]
    assert "DELETE FROM review_case_documents" in statements[0]
    assert "WHERE source_type = %s" in statements[0]
    assert "INSERT INTO review_case_documents" in statements[1]
    assert "INSERT INTO review_case_chunks" in statements[2]
    assert result == {
        "review_case_documents": 1,
        "review_case_chunks": 2,
    }


def test_upsert_preserves_embeddings_until_chunk_text_hash_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "review.jsonl"
    _write_rows(path, [_valid_row()])
    rows = read_review_case_seed_rows(path)
    connection, _calls = _recording_connection(monkeypatch)

    replace_and_upsert_review_case_rows(rows)

    statements = "\n".join(event[0] for event in connection.events)
    normalized_statements = " ".join(statements.split())
    assert "DELETE FROM review_case_documents" not in statements
    assert (
        "review_case_chunks.text_hash IS DISTINCT FROM EXCLUDED.text_hash"
        in normalized_statements
    )
    assert "THEN 'pending'" in statements
    assert "ELSE review_case_chunks.embedding_status" in statements
    assert "CREATE TABLE" not in statements
    assert "CREATE INDEX" not in statements
