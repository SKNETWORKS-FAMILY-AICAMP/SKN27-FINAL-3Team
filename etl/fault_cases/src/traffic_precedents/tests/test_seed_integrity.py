from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pytest

from etl.fault_cases.src.traffic_precedents.config import (
    QWEN_DIMENSION,
    QWEN_MODEL_ID,
    QWEN_REVISION,
)
from etl.fault_cases.src.traffic_precedents.precedent_embedding.build_bootstrap import (
    SOURCE_METADATA_SHA256,
    SOURCE_NPY_SHA256,
)


ROOT = Path(__file__).resolve().parents[5]
EXPECTED_SEED_VERSION = (
    "sha256:af0a4a40f983dcdaeaaeb57e54962a514338b8644c33a6a807f1e6214878b2db"
)


def _service():
    return importlib.import_module(
        "etl.fault_cases.src.traffic_precedents.precedent_db_loading.seed_integrity"
    )


def _record() -> dict[str, Any]:
    return {
        "block_id": "block-1",
        "record_id": "case-1",
        "block_type": "ACCIDENT_FACT",
        "semantic_role": "ACCIDENT_FACT",
        "text": "검증된 판례 문장",
        "case_number": "2026다1",
        "case_name": "손해배상",
        "court_name": "대법원",
        "decision_date": "20260801",
        "internal_grade": "GENERAL_READY_DIRECT",
    }


def _snapshot(
    *,
    status: str = "staged",
    blocks: int = 3339,
    cases: int = 825,
    min_dims: int = 2560,
    max_dims: int = 2560,
    invalid_grades: int = 0,
) -> tuple[Any, ...]:
    return (
        status,
        SOURCE_NPY_SHA256,
        SOURCE_METADATA_SHA256,
        QWEN_MODEL_ID,
        QWEN_REVISION,
        3339,
        825,
        QWEN_DIMENSION,
        blocks,
        cases,
        min_dims,
        max_dims,
        invalid_grades,
    )


class RecordingCursor:
    def __init__(
        self,
        events: list[tuple[str, Any, Any]],
        response_for: Callable[[str, Any], Any],
    ) -> None:
        self.events = events
        self.response_for = response_for
        self.row: Any = None

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def execute(self, sql: str, params: Any = None) -> None:
        normalized = " ".join(sql.split())
        self.events.append(("execute", normalized, params))
        self.row = self.response_for(normalized, params)

    def fetchone(self):
        return self.row


class RecordingConnection:
    def __init__(
        self,
        events: list[tuple[str, Any, Any]],
        response_for: Callable[[str, Any], Any],
    ) -> None:
        self.events = events
        self.cursor_value = RecordingCursor(events, response_for)

    def __enter__(self):
        self.events.append(("connection_enter", None, None))
        return self

    def __exit__(self, exc_type, _exc, _tb):
        self.events.append(
            ("connection_exit", exc_type.__name__ if exc_type else None, None)
        )
        return False

    def cursor(self):
        return self.cursor_value


def _connection_factory(
    events: list[tuple[str, Any, Any]],
    response_for: Callable[[str, Any], Any],
):
    def factory():
        events.append(("connection_factory", None, None))
        return RecordingConnection(events, response_for)

    return factory


def _mock_bootstrap(monkeypatch, service, events) -> None:
    def load(_embeddings_path: Path, _metadata_path: Path):
        events.append(("source_validation", None, None))
        return [_record()], np.ones((1, QWEN_DIMENSION), dtype=np.float32)

    monkeypatch.setattr(service, "load_bootstrap_pair", load)


def test_seed_identity_is_deterministic() -> None:
    service = _service()

    first = service.compute_seed_identity()
    second = service.compute_seed_identity()

    assert first == second
    assert first.seed_version == EXPECTED_SEED_VERSION
    assert first.block_count == 3339
    assert first.case_count == 825
    assert first.embedding_dimension == 2560


def test_frozen_metadata_checkout_preserves_the_approved_sha256() -> None:
    relative_path = (
        "etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/"
        "02_document_embedding_metadata.jsonl"
    )
    attributes_path = ROOT / ".gitattributes"
    attributes = (
        attributes_path.read_text(encoding="utf-8")
        if attributes_path.is_file()
        else ""
    )
    metadata_path = ROOT / relative_path

    assert f"{relative_path} text eol=lf" in attributes
    assert hashlib.sha256(metadata_path.read_bytes()).hexdigest() == (
        SOURCE_METADATA_SHA256
    )


def test_stage_validates_source_before_opening_transaction(monkeypatch) -> None:
    service = _service()
    events: list[tuple[str, Any, Any]] = []
    snapshots = iter([None, _snapshot()])

    def response(sql: str, _params: Any):
        if "FROM precedent_newplusplus.seed_releases AS release" in sql:
            return next(snapshots)
        return None

    _mock_bootstrap(monkeypatch, service, events)

    service.stage_seed(
        embeddings_path=Path("embeddings.npy"),
        metadata_path=Path("metadata.jsonl"),
        connection_factory=_connection_factory(events, response),
    )

    event_names = [event[0] for event in events]
    lock_index = next(
        index
        for index, event in enumerate(events)
        if event[0] == "execute" and "pg_advisory_xact_lock" in event[1]
    )
    assert event_names.index("source_validation") < event_names.index(
        "connection_factory"
    )
    assert event_names.index("source_validation") < lock_index


def test_stage_reuses_an_exact_existing_seed_without_inserting(monkeypatch) -> None:
    service = _service()
    events: list[tuple[str, Any, Any]] = []
    _mock_bootstrap(monkeypatch, service, events)

    def response(sql: str, _params: Any):
        if "FROM precedent_newplusplus.seed_releases AS release" in sql:
            return _snapshot(status="active")
        return None

    result = service.stage_seed(
        embeddings_path=Path("embeddings.npy"),
        metadata_path=Path("metadata.jsonl"),
        connection_factory=_connection_factory(events, response),
    )

    assert result["status"] == "reused"
    assert result["seed_version"] == EXPECTED_SEED_VERSION
    assert not any(
        "INSERT INTO precedent_newplusplus.block_versions" in event[1]
        for event in events
        if event[0] == "execute"
    )


def test_stage_checks_exact_counts_before_transaction_exit(monkeypatch) -> None:
    service = _service()
    events: list[tuple[str, Any, Any]] = []
    snapshots = iter([None, _snapshot(blocks=3338)])
    _mock_bootstrap(monkeypatch, service, events)

    def response(sql: str, _params: Any):
        if "FROM precedent_newplusplus.seed_releases AS release" in sql:
            return next(snapshots)
        return None

    with pytest.raises(service.SeedIntegrityError, match="exact seed verification"):
        service.stage_seed(
            embeddings_path=Path("embeddings.npy"),
            metadata_path=Path("metadata.jsonl"),
            connection_factory=_connection_factory(events, response),
        )

    assert any(
        event[0] == "execute"
        and "count(blocks.block_id)" in event[1]
        for event in events
    )
    assert events[-1] == ("connection_exit", "SeedIntegrityError", None)


def test_verify_seed_returns_exact_credential_safe_evidence() -> None:
    service = _service()
    events: list[tuple[str, Any, Any]] = []

    def response(sql: str, _params: Any):
        if "FROM precedent_newplusplus.seed_releases AS release" in sql:
            return _snapshot(status="active")
        return None

    result = service.verify_seed(
        expected_seed_version=EXPECTED_SEED_VERSION,
        connection_factory=_connection_factory(events, response),
    )

    assert result == {
        "contract_version": "precedent_newplusplus_seed.v1",
        "status": "verified",
        "seed_version": EXPECTED_SEED_VERSION,
        "release_status": "active",
        "block_count": 3339,
        "case_count": 825,
        "embedding_dimension": 2560,
    }


def test_promotion_rejects_an_unexpected_active_seed() -> None:
    service = _service()
    events: list[tuple[str, Any, Any]] = []

    def response(sql: str, _params: Any):
        if "FROM precedent_newplusplus.active_seed" in sql:
            return ("sha256:current", "sha256:previous")
        return None

    with pytest.raises(service.SeedIntegrityError, match="active seed changed"):
        service.promote_seed(
            seed_version=EXPECTED_SEED_VERSION,
            expected_active_seed_version="sha256:expected",
            connection_factory=_connection_factory(events, response),
        )

    assert not any(
        event[0] == "execute" and event[1].startswith("UPDATE")
        for event in events
    )


def test_promotion_atomically_sets_active_and_previous_versions() -> None:
    service = _service()
    events: list[tuple[str, Any, Any]] = []
    current = "sha256:" + "c" * 64

    def response(sql: str, _params: Any):
        if "FROM precedent_newplusplus.active_seed" in sql:
            return (current, "sha256:older")
        if "FROM precedent_newplusplus.seed_releases AS release" in sql:
            return _snapshot(status="staged")
        return None

    result = service.promote_seed(
        seed_version=EXPECTED_SEED_VERSION,
        expected_active_seed_version=current,
        connection_factory=_connection_factory(events, response),
    )

    assert result["status"] == "promoted"
    assert result["active_seed_version"] == EXPECTED_SEED_VERSION
    assert result["previous_seed_version"] == current
    statements = [event[1] for event in events if event[0] == "execute"]
    assert any("SET status = 'previous'" in sql for sql in statements)
    assert any("SET status = 'active'" in sql for sql in statements)
    assert any("INSERT INTO precedent_newplusplus.active_seed" in sql for sql in statements)


def test_rollback_rejects_a_missing_previous_seed() -> None:
    service = _service()
    events: list[tuple[str, Any, Any]] = []

    def response(sql: str, _params: Any):
        if "FROM precedent_newplusplus.active_seed" in sql:
            return (EXPECTED_SEED_VERSION, None)
        return None

    with pytest.raises(service.SeedIntegrityError, match="previous seed is unavailable"):
        service.rollback_seed(
            expected_active_seed_version=EXPECTED_SEED_VERSION,
            connection_factory=_connection_factory(events, response),
        )

    assert not any(
        event[0] == "execute" and event[1].startswith("UPDATE")
        for event in events
    )


def test_rollback_atomically_swaps_active_and_previous_versions() -> None:
    service = _service()
    events: list[tuple[str, Any, Any]] = []
    active = "sha256:" + "c" * 64
    previous = EXPECTED_SEED_VERSION

    def response(sql: str, _params: Any):
        if "FROM precedent_newplusplus.active_seed" in sql:
            return (active, previous)
        if "FROM precedent_newplusplus.seed_releases AS release" in sql:
            return _snapshot(status="previous")
        return None

    result = service.rollback_seed(
        expected_active_seed_version=active,
        connection_factory=_connection_factory(events, response),
    )

    assert result["status"] == "rolled_back"
    assert result["active_seed_version"] == previous
    assert result["previous_seed_version"] == active
    pointer_updates = [
        event
        for event in events
        if event[0] == "execute"
        and event[1].startswith("UPDATE precedent_newplusplus.active_seed")
    ]
    assert pointer_updates[-1][2] == (previous, active)


def test_legacy_cli_stages_through_service_and_never_writes_runtime_view() -> None:
    loader_source = (
        ROOT
        / "etl/fault_cases/src/traffic_precedents/precedent_db_loading/loader.py"
    ).read_text(encoding="utf-8")
    run_source = (
        ROOT / "etl/fault_cases/src/traffic_precedents/precedent_db_loading/run.py"
    ).read_text(encoding="utf-8")

    assert "INSERT INTO precedent_newplusplus.blocks" not in loader_source
    assert "stage_seed(" in run_source
    assert '"--promote"' in run_source
