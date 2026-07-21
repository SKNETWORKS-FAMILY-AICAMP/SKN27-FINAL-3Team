"""Validate the structure and provenance contract of the operational fault graph."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

from etl.fault_cases.rag_runtime.fault_standard.graph_schema import (
    LEGACY_EXPERIMENT_LABELS,
    OPERATIONAL_LABEL,
    SAFE_IDENTIFIER,
    node_pattern,
)


EXPECTED_NODE_COUNT = 7815
EXPECTED_RELATIONSHIP_COUNT = 13196
EXPECTED_ROLE_COUNTS = {
    "Adjustment": 2303,
    "AdjustmentCondition": 2303,
    "BaseFault": 277,
    "Context": 403,
    "Direction": 22,
    "Evidence": 277,
    "Fact": 1164,
    "Lane": 51,
    "LanePath": 30,
    "LaneStep": 75,
    "Party": 554,
    "PotentialConflictZone": 10,
    "Rule": 277,
    "RuleGroup": 29,
    "Variant": 40,
}
EXPECTED_RELATIONSHIP_COUNTS = {
    "ADJUSTS": 2303,
    "APPLIES_TO": 2303,
    "ASSIGNS_FAULT": 77,
    "CIRCULATES_IN": 22,
    "CONTAINS_RULE": 277,
    "DESCRIBES_PARTY": 76,
    "ENTERS_LANE": 23,
    "EXITS_TO": 11,
    "FOLLOWS_PATH": 30,
    "HAS_ADJUSTMENT": 2303,
    "HAS_BASE_FAULT": 277,
    "HAS_CONTEXT": 403,
    "HAS_EVIDENCE": 277,
    "HAS_PARTY": 554,
    "HAS_PMCONTEXT": 38,
    "HAS_PRIORITYCONTEXT": 23,
    "HAS_PROFILE": 277,
    "HAS_ROADCONTEXT": 61,
    "HAS_ROUNDABOUTCONTEXT": 15,
    "HAS_SCENARIO": 7,
    "HAS_SIGNALCONTEXT": 38,
    "HAS_STEP": 75,
    "HAS_USAGENOTE": 183,
    "HAS_VARIANT": 40,
    "HAS_VEHICLECONTEXT": 38,
    "LEFT_SIDE_PARTY": 1,
    "NEXT_STEP": 45,
    "POTENTIALLY_CONVERGES_ON": 20,
    "PRECEDES_ENTRY": 6,
    "REQUIRES_FACT": 2328,
    "RIGHT_SIDE_PARTY": 5,
    "SIGNAL_FOR": 38,
    "TOWARD": 24,
    "TRANSITIONS_TO": 35,
    "TRIGGERED_BY": 2303,
    "USES_LANE": 61,
    "VARIANT_OF": 40,
}
REQUIRED_RULE_RELATIONSHIPS = ("HAS_BASE_FAULT", "HAS_EVIDENCE", "HAS_PARTY", "REQUIRES_FACT")


def _first(session: Any, query: str) -> dict[str, Any]:
    record = next(iter(session.run(query)), None)
    return dict(record or {})


def _safe_role(role: str) -> str:
    if not SAFE_IDENTIFIER.fullmatch(role):
        raise ValueError(f"unsafe role label: {role!r}")
    return role


def validate_report(session: Any) -> dict[str, Any]:
    node_count = int(_first(session, f"MATCH (n:{OPERATIONAL_LABEL}) RETURN count(n) AS count").get("count", -1))
    relationship_count = int(_first(session, "MATCH ()-[r]->() RETURN count(r) AS count").get("count", -1))
    forbidden_count = int(
        _first(
            session,
            "MATCH (n) WHERE " + " OR ".join(f"n:{label}" for label in sorted(LEGACY_EXPERIMENT_LABELS)) + " RETURN count(n) AS count",
        ).get("count", -1)
    )
    missing_provenance = int(
        _first(
            session,
            f"MATCH (n:{OPERATIONAL_LABEL}) RETURN count(CASE WHEN n.schema_version IS NULL OR n.source_snapshot_id IS NULL OR n.source_legacy_element_id IS NULL THEN 1 END) AS count",
        ).get("count", -1)
    )
    identity = _first(
        session,
        f"MATCH (n:{OPERATIONAL_LABEL}:Rule) RETURN count(n) AS count, count(DISTINCT n.rule_id) AS distinct_count, count(CASE WHEN n.rule_id IS NULL OR trim(toString(n.rule_id)) = '' THEN 1 END) AS invalid_count",
    )
    isolated_count = int(_first(session, f"MATCH (n:{OPERATIONAL_LABEL}) WHERE NOT (n)--() RETURN count(n) AS count").get("count", -1))
    missing_record_json = int(
        _first(
            session,
            f"MATCH (n:{OPERATIONAL_LABEL}) RETURN count(CASE WHEN n.record_json IS NULL OR trim(toString(n.record_json)) = '' THEN 1 END) AS count",
        ).get("count", -1)
    )

    role_counts: dict[str, int] = {}
    for role in EXPECTED_ROLE_COUNTS:
        role = _safe_role(role)
        role_counts[role] = int(_first(session, f"MATCH {node_pattern('n', role)} RETURN count(n) AS role_count").get("role_count", -1))

    relationship_counts = {
        str(row["relationship_type"]): int(row["relationship_count"])
        for row in session.run("MATCH ()-[r]->() RETURN type(r) AS relationship_type, count(r) AS relationship_count ORDER BY relationship_type")
    }
    missing_required = {}
    for relationship_type in REQUIRED_RULE_RELATIONSHIPS:
        safe_type = _safe_role(relationship_type)
        missing_required[relationship_type] = int(
            _first(
                session,
                f"MATCH {node_pattern('r', 'Rule')} WHERE NOT (r)-[:{safe_type}]->({node_pattern('n', safe_type.replace('HAS_', ''))}) RETURN count(r) AS count",
            ).get("count", -1)
        )
    constraints = _first(session, "SHOW CONSTRAINTS YIELD name RETURN collect(name) AS names").get("names", [])
    constraints = [str(name) for name in constraints]

    checks = {
        "node_count": node_count == EXPECTED_NODE_COUNT,
        "relationship_count": relationship_count == EXPECTED_RELATIONSHIP_COUNT,
        "forbidden_labels_absent": forbidden_count == 0,
        "provenance_complete": missing_provenance == 0,
        "rule_identity": int(identity.get("count", -1)) == 277 and int(identity.get("distinct_count", -1)) == 277 and int(identity.get("invalid_count", -1)) == 0,
        "no_isolated_nodes": isolated_count == 0,
        "record_json_complete": missing_record_json == 0,
        "role_counts": role_counts == EXPECTED_ROLE_COUNTS,
        "relationship_counts": relationship_counts == EXPECTED_RELATIONSHIP_COUNTS,
        "required_rule_relationships": all(value == 0 for value in missing_required.values()),
        "constraints": {"fault_standard_operational_source_id_unique", "fault_standard_operational_rule_id_unique"}.issubset(constraints),
    }
    return {
        "status": "PASS" if all(value is True for value in checks.values()) else "FAIL",
        "counts": {"nodes": node_count, "relationships": relationship_count},
        "checks": checks,
        "observed": {
            "forbidden_label_nodes": forbidden_count,
            "missing_provenance": missing_provenance,
            "rules": identity,
            "isolated_nodes": isolated_count,
            "missing_record_json": missing_record_json,
            "role_counts": role_counts,
            "relationship_counts": relationship_counts,
            "missing_required_rule_relationships": missing_required,
            "constraints": constraints,
        },
    }


def _password_from_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"missing Neo4j password environment variable: {name}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", required=True)
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password-env", required=True)
    parser.add_argument("--database", default="neo4j")
    parser.add_argument("--report-path", required=True, type=Path)
    args = parser.parse_args()
    driver = GraphDatabase.driver(args.uri, auth=(args.user, _password_from_env(args.password_env)))
    try:
        with driver.session(database=args.database) as session:
            report = validate_report(session)
    finally:
        driver.close()
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
