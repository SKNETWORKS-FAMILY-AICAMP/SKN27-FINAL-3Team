from __future__ import annotations

import json

from etl.fault_cases.src.agents.text_ml_case_search.run_full_optional_inputs import (
    build_run_summary,
    load_active_agent_inputs,
)


def test_load_active_agent_inputs_skips_comment_lines(tmp_path) -> None:
    path = tmp_path / "inputs.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"agent_input": {"session_id": "s1", "query_text": "q1"}}),
                "// " + json.dumps({"agent_input": {"session_id": "s2", "query_text": "q2"}}),
                "",
                json.dumps({"agent_input": {"session_id": "s3", "query_text": "q3"}}),
            ]
        ),
        encoding="utf-8",
    )

    inputs = load_active_agent_inputs(path)

    assert [item["session_id"] for item in inputs] == ["s1", "s3"]


def test_load_active_agent_inputs_respects_limit(tmp_path) -> None:
    path = tmp_path / "inputs.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"agent_input": {"session_id": "s1", "query_text": "q1"}}),
                json.dumps({"agent_input": {"session_id": "s2", "query_text": "q2"}}),
            ]
        ),
        encoding="utf-8",
    )

    inputs = load_active_agent_inputs(path, limit=1)

    assert [item["session_id"] for item in inputs] == ["s1"]


def test_build_run_summary_counts_status_and_evidence(tmp_path) -> None:
    summary = build_run_summary(
        started_at="2026-07-05T10:00:00",
        input_path=tmp_path / "input.jsonl",
        output_path=tmp_path / "output.jsonl",
        search_variant="schema_search_text",
        limit=10,
        records=[
            {
                "run_index": 1,
                "session_id": "s1",
                "message_id": "m1",
                "job_id": "j1",
                "status": "success",
                "evidence_count": 2,
                "review_case_evidence_count": 1,
                "fault_ratio_precedent_evidence_count": 1,
                "similar_case_count": 2,
                "display_evidence_count": 2,
                "ratio_range_label": "A 70 : B 30",
                "insurer_claim_review_exists": True,
                "source_summary": {
                    "source_counts": {"review_case": 1, "fault_ratio_precedent": 1}
                },
            },
            {
                "run_index": 2,
                "session_id": "s2",
                "message_id": "m2",
                "job_id": "j2",
                "status": "partial",
                "evidence_count": 0,
                "review_case_evidence_count": 0,
                "fault_ratio_precedent_evidence_count": 0,
                "similar_case_count": 0,
                "display_evidence_count": 0,
                "ratio_range_label": "",
                "insurer_claim_review_exists": True,
                "source_summary": {"source_counts": {}},
            },
        ],
    )

    assert summary["active_input_count"] == 2
    assert summary["status_counts"] == {"success": 1, "partial": 1}
    assert summary["total_evidence_count"] == 2
    assert summary["total_review_case_evidence_count"] == 1
    assert summary["total_fault_ratio_precedent_evidence_count"] == 1
    assert summary["total_display_evidence_count"] == 2
    assert summary["zero_evidence_count"] == 1
