"""검증된 Complete30/V9 논리 백업을 전용 Neo4j로 복원한다.

원본 법률 Neo4j 또는 기존 Complete30 실험 Neo4j에는 연결하지 않는다. 입력은
1단계에서 생성·검증한 JSONL 논리 백업이며, 대상은 `fault-standard-neo4j`뿐이다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from neo4j import GraphDatabase


SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def password_from_env(name: str) -> str:
    """대상 Neo4j 비밀번호를 환경변수에서만 읽는다."""

    value = os.environ.get(name)
    if not value:
        raise ValueError(f"필수 비밀번호 환경변수가 없습니다: {name}")
    return value


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    """대형 JSONL을 한 줄씩 읽고 형식 오류 위치를 알려 준다."""

    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"JSONL 형식 오류: {path}, {line_number}행") from error


def quoted_labels(labels: list[str]) -> str:
    """백업에 기록된 Neo4j 라벨을 안전하게 Cypher 라벨 구문으로 만든다."""

    all_labels = ["V9Import", *labels]
    if any(not SAFE_IDENTIFIER.fullmatch(label) for label in all_labels):
        raise ValueError(f"허용하지 않는 Neo4j 라벨입니다: {all_labels}")
    return ":" + ":".join(all_labels)


def quoted_type(value: str) -> str:
    """관계 유형을 안전하게 Cypher 관계 유형 구문으로 만든다."""

    if not SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"허용하지 않는 Neo4j 관계 유형입니다: {value}")
    return value


def batches(rows: list[dict[str, Any]], size: int = 300) -> Iterable[list[dict[str, Any]]]:
    """Neo4j 트랜잭션 크기를 제한하기 위한 작은 묶음을 만든다."""

    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def import_nodes(session: Any, nodes_path: Path) -> int:
    """노드를 legacy element ID로 MERGE해 중단 뒤 재실행도 가능하게 한다."""

    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(nodes_path):
        labels = tuple(sorted(str(label) for label in row["labels"]))
        properties = dict(row.get("properties") or {})
        properties.pop("_legacy_element_id", None)
        groups[labels].append({"legacy_id": str(row["element_id"]), "properties": properties})

    count = 0
    for labels, rows in groups.items():
        query = (
            f"UNWIND $rows AS row MERGE (node{quoted_labels(list(labels))} {{_legacy_element_id: row.legacy_id}}) "
            "SET node += row.properties"
        )
        for batch in batches(rows):
            session.run(query, rows=batch).consume()
            count += len(batch)
    return count


def import_relationships(session: Any, relationships_path: Path) -> int:
    """관계를 legacy element ID로 MERGE해 중복 복원을 막는다."""

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(relationships_path):
        properties = dict(row.get("properties") or {})
        properties.pop("_legacy_element_id", None)
        groups[str(row["relationship_type"])].append(
            {
                "legacy_id": str(row["element_id"]),
                "source_id": str(row["source_element_id"]),
                "target_id": str(row["target_element_id"]),
                "properties": properties,
            }
        )

    count = 0
    for relationship_type, rows in groups.items():
        query = (
            "UNWIND $rows AS row "
            "MATCH (source:V9Import {_legacy_element_id: row.source_id}) "
            "MATCH (target:V9Import {_legacy_element_id: row.target_id}) "
            f"MERGE (source)-[relationship:{quoted_type(relationship_type)} {{_legacy_element_id: row.legacy_id}}]->(target) "
            "SET relationship += row.properties"
        )
        for batch in batches(rows):
            session.run(query, rows=batch).consume()
            count += len(batch)
    return count


def main() -> None:
    """입력 백업 수와 대상 그래프 수를 대조하며 V9 그래프를 복원한다."""

    parser = argparse.ArgumentParser(description="Complete30 V9 그래프 전용 Neo4j 복원")
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--uri", required=True)
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password-env", required=True)
    parser.add_argument("--database", default="neo4j")
    parser.add_argument("--report-path", required=True)
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir)
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS":
        raise ValueError("PASS 상태의 논리 백업만 복원할 수 있습니다.")

    driver = GraphDatabase.driver(args.uri, auth=(args.user, password_from_env(args.password_env)))
    try:
        with driver.session(database=args.database) as session:
            session.run(
                "CREATE CONSTRAINT v9_import_legacy_id_unique IF NOT EXISTS "
                "FOR (node:V9Import) REQUIRE node._legacy_element_id IS UNIQUE"
            ).consume()
            node_count = import_nodes(session, backup_dir / "nodes.jsonl")
            relationship_count = import_relationships(session, backup_dir / "relationships.jsonl")
            target_node_count = session.run("MATCH (node:V9Import) RETURN count(node) AS count").single()["count"]
            target_relationship_count = session.run("MATCH ()-[relationship]->() RETURN count(relationship) AS count").single()["count"]
    finally:
        driver.close()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_backup": str(backup_dir),
        "source_manifest": manifest,
        "imported_nodes_this_run": node_count,
        "imported_relationships_this_run": relationship_count,
        "target_v9import_node_count": target_node_count,
        "target_relationship_count": target_relationship_count,
        "status": "PASS"
        if target_node_count == manifest["node_count"] and target_relationship_count == manifest["relationship_count"]
        else "FAIL",
        "safety_note": "대상은 fault-standard-neo4j 전용 그래프이며 기존 법률 Neo4j에는 쓰지 않았습니다.",
    }
    output = Path(args.report_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"V9 그래프 복원: 노드={target_node_count}, 관계={target_relationship_count}, 상태={report['status']}")
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

