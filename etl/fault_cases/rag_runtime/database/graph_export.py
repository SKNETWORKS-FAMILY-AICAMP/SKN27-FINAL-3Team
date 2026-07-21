"""Export a labelled Neo4j subgraph as an auditable JSONL snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from neo4j import GraphDatabase


SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_label(label: str) -> str:
    if not SAFE_IDENTIFIER.fullmatch(label):
        raise ValueError(f"label must be a safe Neo4j identifier: {label!r}")
    return label


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    isoformat = getattr(value, "iso_format", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with path.open("wb") as handle:
        for row in rows:
            line = (json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            handle.write(line)
            digest.update(line)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_graph(session: Any, namespace_label: str, output_dir: Path) -> dict[str, Any]:
    label = _safe_label(namespace_label)
    node_query = (
        f"MATCH (n:{label}) "
        "RETURN n._legacy_element_id AS element_id, labels(n) AS labels, properties(n) AS properties "
        "ORDER BY element_id"
    )
    relationship_query = (
        f"MATCH (source:{label})-[relationship]->(target:{label}) "
        "RETURN relationship._legacy_element_id AS element_id, "
        "source._legacy_element_id AS source_element_id, "
        "target._legacy_element_id AS target_element_id, "
        "type(relationship) AS relationship_type, properties(relationship) AS properties "
        "ORDER BY element_id"
    )
    nodes = [dict(record) for record in session.run(node_query)]
    relationships = [dict(record) for record in session.run(relationship_query)]
    if any(not row.get("element_id") for row in nodes):
        raise ValueError(f"{label} contains a node without _legacy_element_id")
    if any(not row.get("element_id") for row in relationships):
        raise ValueError(f"{label} contains a relationship without _legacy_element_id")

    output_dir.mkdir(parents=True, exist_ok=True)
    node_path = output_dir / "nodes.jsonl"
    relationship_path = output_dir / "relationships.jsonl"
    manifest = {
        "format_version": 1,
        "namespace_label": label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "node_count": len(nodes),
        "relationship_count": len(relationships),
        "files": {},
    }
    manifest["files"]["nodes.jsonl"] = {"sha256": write_jsonl(node_path, nodes), "rows": len(nodes)}
    manifest["files"]["relationships.jsonl"] = {
        "sha256": write_jsonl(relationship_path, relationships),
        "rows": len(relationships),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(_jsonable(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _password_from_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"missing Neo4j password environment variable: {name}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--uri", default=os.environ.get("FAULT_STANDARD_NEO4J_URI", "bolt://127.0.0.1:7688"))
    parser.add_argument("--user", default=os.environ.get("FAULT_STANDARD_NEO4J_USER", "neo4j"))
    parser.add_argument("--password-env", default="FAULT_STANDARD_NEO4J_PASSWORD")
    parser.add_argument("--database", default=os.environ.get("FAULT_STANDARD_NEO4J_DATABASE", "neo4j"))
    args = parser.parse_args()

    driver = GraphDatabase.driver(args.uri, auth=(args.user, _password_from_env(args.password_env)))
    try:
        with driver.session(database=args.database) as session:
            manifest = export_graph(session, args.label, args.output_dir)
    finally:
        driver.close()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
