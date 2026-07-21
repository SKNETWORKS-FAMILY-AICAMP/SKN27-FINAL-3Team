from __future__ import annotations

from etl.fault_cases.rag_runtime.database.validation.validate_fault_standard_operational_graph import (
    EXPECTED_NODE_COUNT,
    EXPECTED_RELATIONSHIP_COUNTS,
    EXPECTED_RELATIONSHIP_COUNT,
    EXPECTED_ROLE_COUNTS,
    validate_report,
)


class PassSession:
    def run(self, query: str, **parameters: object):
        if "NOT (n)--()" in query:
            return [{"count": 0}]
        if "NOT (r)-[:" in query:
            return [{"count": 0}]
        if "count(n) AS count" in query and "Rule" not in query and "OR n:" not in query:
            return [{"count": EXPECTED_NODE_COUNT}]
        if "count(r) AS count" in query and "relationship_type" not in query:
            return [{"count": EXPECTED_RELATIONSHIP_COUNT}]
        if "OR n:Complete30V9" in query:
            return [{"count": 0}]
        if "source_legacy_element_id IS NULL" in query:
            return [{"count": 0}]
        if "source_snapshot_id IS NULL" in query or "schema_version" in query:
            return [{"count": 0}]
        if "DISTINCT n.rule_id" in query:
            return [{"count": 277, "distinct_count": 277, "invalid_count": 0}]
        if "collect(name)" in query:
            return [{"names": ["fault_standard_operational_source_id_unique", "fault_standard_operational_rule_id_unique"]}]
        if "role_count" in query:
            for role, count in EXPECTED_ROLE_COUNTS.items():
                if f":{role})" in query:
                    return [{"role_count": count}]
            return [{"role_count": -1}]
        if "relationship_type" in query:
            return [
                {"relationship_type": relationship_type, "relationship_count": count}
                for relationship_type, count in EXPECTED_RELATIONSHIP_COUNTS.items()
            ]
        return [{"count": 0}]


def test_validate_report_accepts_clean_operational_graph() -> None:
    report = validate_report(PassSession())

    assert report["status"] == "PASS"
    assert report["counts"] == {
        "nodes": EXPECTED_NODE_COUNT,
        "relationships": EXPECTED_RELATIONSHIP_COUNT,
    }
