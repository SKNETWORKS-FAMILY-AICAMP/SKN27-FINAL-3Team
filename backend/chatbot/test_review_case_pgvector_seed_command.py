from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.management.base import CommandError

from backend.chatbot.management.commands import (
    load_review_case_pgvector_seed as command_module,
)


def _bundle(path: Path, *, row_count: int = 2) -> SimpleNamespace:
    return SimpleNamespace(
        embedding_space={
            "provider": "openai",
            "model": "text-embedding-3-large",
            "dimensions": 1024,
        },
        artifacts={
            "review_case_chunks": SimpleNamespace(
                path=path,
                row_count=row_count,
            )
        },
    )


def _options(manifest: Path, *, approved: bool) -> dict[str, object]:
    return {
        "manifest": str(manifest),
        "replace": True,
        "allow_paid_provider_call": approved,
        "format": "json",
    }


def test_command_rejects_paid_work_without_explicit_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks_path = tmp_path / "review.jsonl"
    bundle = _bundle(chunks_path)
    database_writes: list[object] = []
    provider_calls: list[object] = []
    monkeypatch.setattr(
        command_module,
        "load_and_validate_rag_seed_manifest",
        lambda _: bundle,
    )
    monkeypatch.setattr(
        command_module,
        "replace_and_upsert_review_case_rows",
        lambda *args, **kwargs: database_writes.append((args, kwargs)),
    )
    monkeypatch.setattr(
        command_module,
        "create_embeddings",
        lambda *args, **kwargs: provider_calls.append((args, kwargs)),
    )

    with pytest.raises(CommandError, match="explicit paid provider approval"):
        command_module.Command(stdout=StringIO()).handle(
            **_options(tmp_path / "rag-seed-manifest.json", approved=False)
        )

    assert database_writes == []
    assert provider_calls == []


def test_approved_command_loads_exact_manifest_rows_and_verifies_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks_path = tmp_path / "review.jsonl"
    rows = [SimpleNamespace(chunk_id="chunk-1"), SimpleNamespace(chunk_id="chunk-2")]
    bundle = _bundle(chunks_path)
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        command_module,
        "load_and_validate_rag_seed_manifest",
        lambda _: bundle,
    )
    monkeypatch.setattr(
        command_module,
        "read_review_case_seed_rows",
        lambda path: calls.append(("read", path)) or rows,
    )
    monkeypatch.setattr(
        command_module,
        "replace_and_upsert_review_case_rows",
        lambda loaded_rows, *, replace: calls.append(
            ("load", loaded_rows, replace)
        )
        or {
            "review_case_documents": 1,
            "review_case_chunks": 2,
        },
    )
    monkeypatch.setattr(
        command_module,
        "create_embeddings",
        lambda *, limit, dry_run: calls.append(
            ("embed", limit, dry_run)
        )
        or {
            "pending_chunk_count_selected": 2,
            "inserted_or_updated_embeddings": 2,
        },
    )
    monkeypatch.setattr(
        command_module,
        "count_embedding_rows",
        lambda: calls.append(("count",)) or 2,
    )
    monkeypatch.setattr(
        command_module,
        "index_exists",
        lambda index_name: calls.append(("index", index_name)) or True,
    )
    stdout = StringIO()

    command_module.Command(stdout=stdout).handle(
        **_options(tmp_path / "rag-seed-manifest.json", approved=True)
    )

    result = json.loads(stdout.getvalue())
    assert calls[0] == ("read", chunks_path)
    assert calls[1] == ("load", rows, True)
    assert calls[2] == ("embed", None, False)
    assert calls[3] == ("count",)
    assert calls[4] == (
        "index",
        command_module.PGVECTOR_INDEX_SETTINGS.index_name,
    )
    assert result == {
        "contract_version": "review_case_pgvector_seed_load.v1",
        "status": "loaded",
        "source": {
            "review_case_documents": 1,
            "review_case_chunks": 2,
        },
        "embedding": {
            "provider": "openai",
            "model": "text-embedding-3-large",
            "version": "openai_text_embedding_3_large_1024_chunk_text_v1",
            "dimensions": 1024,
            "pending_selected": 2,
            "inserted_or_updated": 2,
            "count_after": 2,
        },
        "index": {
            "name": "idx_review_case_chunk_embeddings_cosine_hnsw",
            "exists": True,
        },
    }


def test_command_rejects_source_count_mismatch_before_database_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path / "review.jsonl", row_count=2)
    writes: list[object] = []
    monkeypatch.setattr(
        command_module,
        "load_and_validate_rag_seed_manifest",
        lambda _: bundle,
    )
    monkeypatch.setattr(
        command_module,
        "read_review_case_seed_rows",
        lambda _: [SimpleNamespace(chunk_id="only-one")],
    )
    monkeypatch.setattr(
        command_module,
        "replace_and_upsert_review_case_rows",
        lambda *args, **kwargs: writes.append((args, kwargs)),
    )

    with pytest.raises(CommandError, match="source row count"):
        command_module.Command(stdout=StringIO()).handle(
            **_options(tmp_path / "rag-seed-manifest.json", approved=True)
        )

    assert writes == []


def test_command_requires_exact_embedding_count_and_existing_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path / "review.jsonl", row_count=2)
    monkeypatch.setattr(
        command_module,
        "load_and_validate_rag_seed_manifest",
        lambda _: bundle,
    )
    monkeypatch.setattr(
        command_module,
        "read_review_case_seed_rows",
        lambda _: [SimpleNamespace(), SimpleNamespace()],
    )
    monkeypatch.setattr(
        command_module,
        "replace_and_upsert_review_case_rows",
        lambda *args, **kwargs: {
            "review_case_documents": 1,
            "review_case_chunks": 2,
        },
    )
    monkeypatch.setattr(
        command_module,
        "create_embeddings",
        lambda **_: {},
    )
    monkeypatch.setattr(command_module, "count_embedding_rows", lambda: 1)
    monkeypatch.setattr(command_module, "index_exists", lambda _: True)

    with pytest.raises(CommandError, match="embedding row count"):
        command_module.Command(stdout=StringIO()).handle(
            **_options(tmp_path / "rag-seed-manifest.json", approved=True)
        )

    monkeypatch.setattr(command_module, "count_embedding_rows", lambda: 2)
    monkeypatch.setattr(command_module, "index_exists", lambda _: False)
    with pytest.raises(CommandError, match="HNSW index"):
        command_module.Command(stdout=StringIO()).handle(
            **_options(tmp_path / "rag-seed-manifest.json", approved=True)
        )


def test_command_masks_provider_failure_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path / "review.jsonl", row_count=1)
    monkeypatch.setattr(
        command_module,
        "load_and_validate_rag_seed_manifest",
        lambda _: bundle,
    )
    monkeypatch.setattr(
        command_module,
        "read_review_case_seed_rows",
        lambda _: [SimpleNamespace()],
    )
    monkeypatch.setattr(
        command_module,
        "replace_and_upsert_review_case_rows",
        lambda *args, **kwargs: {
            "review_case_documents": 1,
            "review_case_chunks": 1,
        },
    )
    monkeypatch.setattr(
        command_module,
        "create_embeddings",
        lambda **_: (_ for _ in ()).throw(
            RuntimeError("OPENAI_API_KEY=should-never-appear")
        ),
    )

    with pytest.raises(CommandError) as exc_info:
        command_module.Command(stdout=StringIO()).handle(
            **_options(tmp_path / "rag-seed-manifest.json", approved=True)
        )

    assert "should-never-appear" not in str(exc_info.value)
    assert "review-case pgvector seed load failed" in str(exc_info.value)


def test_command_does_not_attempt_runtime_index_creation() -> None:
    source = Path(command_module.__file__).read_text(encoding="utf-8")

    assert "create_hnsw_index" not in source
