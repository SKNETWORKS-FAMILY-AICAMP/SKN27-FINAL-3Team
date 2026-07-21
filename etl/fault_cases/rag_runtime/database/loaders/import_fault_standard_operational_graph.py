"""Import a Complete30 V9 snapshot into a clean operational graph namespace."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from neo4j import GraphDatabase


OPERATIONAL_LABEL = "FaultStandardOperational"
EXPERIMENT_LABELS = {"Complete30V7", "Complete30V9", "V9Import"}
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(value: str) -> str:
    if not SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe Neo4j identifier: {value!r}")
    return value


def operational_labels(source_labels: list[str]) -> list[str]:
    role_labels = sorted(set(source_labels) - EXPERIMENT_LABELS - {OPERATIONAL_LABEL})
    if any(not SAFE_IDENTIFIER.fullmatch(label) for label in role_labels):
        raise ValueError(f"unsafe source label: {source_labels!r}")
    return [OPERATIONAL_LABEL, *role_labels]


def transform_node(row: dict[str, Any], schema_version: int, snapshot_id: str) -> dict[str, Any]:
    source_id = str(row.get("element_id") or "")
    if not source_id:
        raise ValueError("node row has no element_id")
    properties = dict(row.get("properties") or {})
    properties.pop("_legacy_element_id", None)
    properties.update(
        {
            "schema_version": int(schema_version),
            "source_snapshot_id": str(snapshot_id),
            "source_legacy_element_id": source_id,
        }
    )
    return {
        "labels": operational_labels([str(label) for label in row.get("labels") or []]),
        "properties": properties,
        "source_legacy_element_id": source_id,
    }


def _transform_relationship(row: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    source_id = str(row.get("source_element_id") or "")
    target_id = str(row.get("target_element_id") or "")
    relationship_id = str(row.get("element_id") or "")
    relationship_type = _safe_identifier(str(row.get("relationship_type") or ""))
    if not source_id or not target_id or not relationship_id:
        raise ValueError("relationship row is missing a source, target, or element_id")
    properties = dict(row.get("properties") or {})
    properties.pop("_legacy_element_id", None)
    properties.update(
        {
            "source_snapshot_id": str(snapshot_id),
            "source_legacy_element_id": relationship_id,
        }
    )
    return {
        "source_legacy_element_id": source_id,
        "target_legacy_element_id": target_id,
        "relationship_type": relationship_type,
        "source_relationship_id": relationship_id,
        "properties": properties,
    }


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSONL at {path}:{line_number}") from error
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row is not an object at {path}:{line_number}")
            yield row


def _batches(rows: list[dict[str, Any]], size: int = 300) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _labels_clause(labels: list[str]) -> str:
    return ":" + ":".join(_safe_identifier(label) for label in labels)


def _validate_manifest(backup_dir: Path) -> dict[str, Any]:
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("namespace_label") != "Complete30V9":
        raise ValueError("operational importer requires a Complete30V9 snapshot")
    return manifest


def _create_constraints(session: Any) -> None:
    session.run(
        "CREATE CONSTRAINT fault_standard_operational_source_id_unique IF NOT EXISTS "
        f"FOR (node:{OPERATIONAL_LABEL}) REQUIRE node.source_legacy_element_id IS UNIQUE"
    ).consume()


def import_graph(session: Any, backup_dir: Path, snapshot_id: str, schema_version: int) -> dict[str, Any]:
    manifest = _validate_manifest(backup_dir)
    nodes = [transform_node(row, schema_version, snapshot_id) for row in _read_jsonl(backup_dir / "nodes.jsonl")]
    relationships = [_transform_relationship(row, snapshot_id) for row in _read_jsonl(backup_dir / "relationships.jsonl")]
    _create_constraints(session)

    grouped_nodes: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in nodes:
        grouped_nodes.setdefault(tuple(row["labels"]), []).append(row)
    for labels, rows in grouped_nodes.items():
        label_clause = _labels_clause(list(labels))
        query = (
            f"UNWIND $rows AS row MERGE (node{label_clause} "
            "{source_legacy_element_id: row.source_legacy_element_id}) SET node += row.properties"
        )
        for batch in _batches(rows):
            session.run(query, rows=batch).consume()

    grouped_relationships: dict[str, list[dict[str, Any]]] = {}
    for row in relationships:
        grouped_relationships.setdefault(str(row["relationship_type"]), []).append(row)
    for relationship_type, rows in grouped_relationships.items():
        query = (
            "UNWIND $rows AS row "
            f"MATCH (source:{OPERATIONAL_LABEL} {{source_legacy_element_id: row.source_legacy_element_id}}) "
            f"MATCH (target:{OPERATIONAL_LABEL} {{source_legacy_element_id: row.target_legacy_element_id}}) "
            f"MERGE (source)-[relationship:{_safe_identifier(relationship_type)} "
            "{source_legacy_element_id: row.source_relationship_id}]->(target) "
            "SET relationship += row.properties"
        )
        for batch in _batches(rows):
            session.run(query, rows=batch).consume()

    return {
        "source_manifest": manifest,
        "snapshot_id": snapshot_id,
        "schema_version": schema_version,
        "imported_nodes": len(nodes),
        "imported_relationships": len(relationships),
        "status": "PASS",
    }


def _password_from_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"missing Neo4j password environment variable: {name}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("--snapshot-id", default="complete30-v9-operational")
    parser.add_argument("--schema-version", default=9, type=int)
    parser.add_argument("--uri", required=True)
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password-env", required=True)
    parser.add_argument("--database", default="neo4j")
    parser.add_argument("--report-path", required=True, type=Path)
    args = parser.parse_args()

    driver = GraphDatabase.driver(args.uri, auth=(args.user, _password_from_env(args.password_env)))
    try:
        with driver.session(database=args.database) as session:
            report = import_graph(session, args.backup_dir, args.snapshot_id, args.schema_version)
    finally:
        driver.close()
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
