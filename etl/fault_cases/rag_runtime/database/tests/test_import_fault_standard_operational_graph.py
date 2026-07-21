from __future__ import annotations

import json
from pathlib import Path

import pytest

from etl.fault_cases.rag_runtime.database.loaders.import_fault_standard_operational_graph import (
    import_graph,
    operational_labels,
    transform_node,
)


class FakeResult:
    def consume(self) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.queries: list[tuple[str, dict[str, object]]] = []

    def run(self, query: str, **parameters: object):
        self.queries.append((query, parameters))
        return FakeResult()


def test_operational_labels_remove_experiment_markers() -> None:
    labels = operational_labels(["V9Import", "Complete30V9", "Rule"])

    assert labels[0] == "FaultStandardOperational"
    assert set(labels) == {"FaultStandardOperational", "Rule"}


def test_transform_node_preserves_role_and_adds_provenance() -> None:
    row = {
        "element_id": "legacy-1",
        "labels": ["V9Import", "Complete30V9", "Rule"],
        "properties": {"_legacy_element_id": "legacy-1", "rule_id": "R-1"},
    }

    transformed = transform_node(row, schema_version=9, snapshot_id="snapshot-1")

    assert transformed["labels"] == ["FaultStandardOperational", "Rule"]
    assert transformed["properties"] == {
        "rule_id": "R-1",
        "schema_version": 9,
        "source_legacy_element_id": "legacy-1",
        "source_snapshot_id": "snapshot-1",
    }


def test_import_graph_rejects_non_v9_snapshot(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"namespace_label": "Complete30V7"}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Complete30V9"):
        import_graph(FakeSession(), tmp_path, "snapshot-1", 9)


def test_import_graph_uses_single_label_source_constraint(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"namespace_label": "Complete30V9"}), encoding="utf-8"
    )
    (tmp_path / "nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "relationships.jsonl").write_text("", encoding="utf-8")
    session = FakeSession()

    import_graph(session, tmp_path, "snapshot-1", 9)

    assert any("fault_standard_operational_source_id_unique" in query for query, _ in session.queries)
    assert not any("&Rule" in query for query, _ in session.queries)
