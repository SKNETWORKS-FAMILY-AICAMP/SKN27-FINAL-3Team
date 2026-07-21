"""전용 Complete30 V9 Neo4j에서 관계 대조·계산용 데이터를 읽는 어댑터.

이 모듈은 기존 법률 Neo4j에 연결하지 않는다. C2b 선택기가 필요한 V9 관계만
`fault-standard-neo4j`에서 읽어, 검색 후보와 사고 Fact의 관계를 판정한다.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Any

from neo4j import GraphDatabase

from .graph_schema import node_pattern


def _config() -> tuple[str, str, str, str]:
    """인정기준 전용 Neo4j 접속 정보만 환경변수에서 읽는다."""

    uri = os.environ.get("FAULT_STANDARD_NEO4J_URI", "bolt://fault-standard-neo4j:7687")
    user = os.environ.get("FAULT_STANDARD_NEO4J_USER", "neo4j")
    password = os.environ.get("FAULT_STANDARD_NEO4J_PASSWORD")
    database = os.environ.get("FAULT_STANDARD_NEO4J_DATABASE", "neo4j")
    if not password:
        raise RuntimeError("FAULT_STANDARD_NEO4J_PASSWORD가 없습니다.")
    return uri, user, password, database


def graph_data(rule_ids: list[str]) -> dict[str, dict[str, Any]]:
    """C2b 관계 대조와 계산기에 필요한 V9 원본 레코드를 후보별로 반환한다."""

    output: dict[str, dict[str, Any]] = {
        rule_id: {
            "conditions": [],
            "parties": [],
            "paths": defaultdict(list),
            "steps": defaultdict(list),
            "contexts": [],
            "variants": [],
            "bases": [],
            "adjustments": [],
            "groups": [],
            "precedence": [],
            "potential_conflicts": [],
        }
        for rule_id in rule_ids
    }
    uri, user, password, database = _config()
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) as session:
            # 각 관계는 source-record JSON을 그대로 반환해 계산기 입력을 임의 재구성하지 않는다.
            queries = (
                (f"MATCH {node_pattern('r', 'Rule')}-[:REQUIRES_FACT]->{node_pattern('n', 'Fact')} WHERE r.rule_id IN $ids RETURN r.rule_id AS rid,n.record_json AS raw", "conditions"),
                (f"MATCH {node_pattern('r', 'Rule')}-[:HAS_PARTY]->{node_pattern('n', 'Party')} WHERE r.rule_id IN $ids RETURN r.rule_id AS rid,n.record_json AS raw", "parties"),
                (f"MATCH {node_pattern('r', 'Rule')}-[:HAS_BASE_FAULT]->{node_pattern('n', 'BaseFault')} WHERE r.rule_id IN $ids RETURN r.rule_id AS rid,n.record_json AS raw", "bases"),
                (f"MATCH {node_pattern('r', 'Rule')}-[:HAS_ADJUSTMENT]->{node_pattern('n', 'Adjustment')} WHERE r.rule_id IN $ids RETURN r.rule_id AS rid,n.record_json AS raw", "adjustments"),
                (f"MATCH {node_pattern('r', 'Rule')}-[:HAS_VARIANT]->{node_pattern('n', 'Variant')} WHERE r.rule_id IN $ids RETURN r.rule_id AS rid,n.record_json AS raw", "variants"),
                (f"MATCH {node_pattern('r', 'Rule')}-[:HAS_CONTEXT]->{node_pattern('n', 'Context')} WHERE r.rule_id IN $ids RETURN r.rule_id AS rid,n.record_json AS raw", "contexts"),
                (f"MATCH {node_pattern('g', 'RuleGroup')}-[:CONTAINS_RULE]->{node_pattern('r', 'Rule')} WHERE r.rule_id IN $ids RETURN r.rule_id AS rid,g.group_name AS group_name", "groups"),
                (f"MATCH {node_pattern('p', 'Party')}-[:PRECEDES_ENTRY]->{node_pattern('q', 'Party')} WHERE p.rule_id IN $ids RETURN p.rule_id AS rid,p.party_key AS first,q.party_key AS late", "precedence"),
                (f"MATCH {node_pattern('p', 'Party')}-[:FOLLOWS_PATH]->{node_pattern('x', 'LanePath')}-[:HAS_STEP]->{node_pattern('s', 'LaneStep')} WHERE p.rule_id IN $ids RETURN p.rule_id AS rid,p.party_key AS party,x.record_json AS path,s.record_json AS step", "paths_steps"),
                (f"MATCH {node_pattern('s', 'LaneStep')}-[:POTENTIALLY_CONVERGES_ON]->{node_pattern('z', 'PotentialConflictZone')} WHERE s.rule_id IN $ids RETURN s.rule_id AS rid,s.party_key AS party,z.lane AS lane", "potential_conflicts"),
            )
            for cypher, kind in queries:
                for row in session.run(cypher, ids=rule_ids):
                    rule_id = str(row["rid"])
                    if kind == "paths_steps":
                        path, step = json.loads(row["path"]), json.loads(row["step"])
                        party = str(row["party"])
                        if path not in output[rule_id]["paths"][party]:
                            output[rule_id]["paths"][party].append(path)
                        output[rule_id]["steps"][party].append(step)
                    elif kind == "groups":
                        output[rule_id][kind].append(row["group_name"])
                    elif kind == "precedence":
                        output[rule_id][kind].append({"first": row["first"], "late": row["late"]})
                    elif kind == "potential_conflicts":
                        output[rule_id][kind].append({"party": row["party"], "lane": row["lane"]})
                    else:
                        output[rule_id][kind].append(json.loads(row["raw"]))
    finally:
        driver.close()
    # Neo4j 관계 반환 순서에 의존하지 않도록 차로 단계는 명시 순번으로 고정한다.
    for graph in output.values():
        for steps in graph["steps"].values():
            steps.sort(key=lambda item: int(item.get("seq") or 0))
    return output
