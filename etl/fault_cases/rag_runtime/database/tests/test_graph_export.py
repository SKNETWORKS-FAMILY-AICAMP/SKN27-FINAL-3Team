from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from etl.fault_cases.rag_runtime.database.graph_export import (
    export_graph,
    sha256_file,
    write_jsonl,
)


class FakeSession:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def run(self, query: str):
        self.queries.append(query)
        if "RETURN n._legacy_element_id" in query:
            return [
                {
                    "element_id": "node-1",
                    "labels": ["Complete30V9", "Rule"],
                    "properties": {"rule_id": "rule-1", "record_json": "{}"},
                }
            ]
        return [
            {
                "element_id": "rel-1",
                "source_element_id": "node-1",
                "target_element_id": "node-1",
                "relationship_type": "HAS_CONTEXT",
                "properties": {"weight": 1},
            }
        ]


def test_write_jsonl_is_stable_and_hashable(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    digest = write_jsonl(path, [{"z": 1, "a": "한글"}])

    expected_bytes = '{"a":"한글","z":1}\n'.encode("utf-8")
    assert path.read_bytes() == expected_bytes
    assert digest == hashlib.sha256(expected_bytes).hexdigest()
    assert sha256_file(path) == digest


def test_export_graph_writes_nodes_relationships_and_manifest(tmp_path: Path) -> None:
    session = FakeSession()

    report = export_graph(session, "Complete30V9", tmp_path)

    assert report["namespace_label"] == "Complete30V9"
    assert report["node_count"] == 1
    assert report["relationship_count"] == 1
    assert json.loads((tmp_path / "nodes.jsonl").read_text(encoding="utf-8")) == {
        "element_id": "node-1",
        "labels": ["Complete30V9", "Rule"],
        "properties": {"record_json": "{}", "rule_id": "rule-1"},
    }
    assert json.loads((tmp_path / "relationships.jsonl").read_text(encoding="utf-8"))[
        "relationship_type"
    ] == "HAS_CONTEXT"
    assert (tmp_path / "manifest.json").exists()
    assert any("Complete30V9" in query for query in session.queries)


def test_export_graph_rejects_unsafe_label(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="label"):
        export_graph(FakeSession(), "Complete30V9` MATCH (n)", tmp_path)
