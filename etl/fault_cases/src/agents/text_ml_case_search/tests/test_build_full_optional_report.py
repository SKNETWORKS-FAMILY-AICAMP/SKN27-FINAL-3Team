from __future__ import annotations

import json

from etl.fault_cases.src.agents.text_ml_case_search.build_full_optional_report import (
    build_markdown_report,
    build_report,
    load_jsonl,
    write_report,
)


def sample_record(*, status: str = "success", evidence_count: int = 1) -> dict:
    return {
        "run_index": 1,
        "session_id": "s1",
        "message_id": "m1",
        "job_id": "j1",
        "query_text": "lane change crash",
        "status": status,
        "evidence_count": evidence_count,
        "similar_case_count": evidence_count,
        "display_evidence_count": evidence_count,
        "ratio_range_label": "A 70 : B 30" if evidence_count else "",
        "insurer_claim_review_exists": True,
        "result": {
            "structured_result": {
                "display_evidence": [
                    {
                        "source_reference": "review_case_db:case1#chunk1",
                        "title": "sample title",
                        "summary": "sample summary",
                        "ratio_label": "A 70 : B 30",
                    }
                ]
                if evidence_count
                else []
            },
            "limitations": [],
            "next_actions": ["check evidence"],
        },
    }


def test_load_jsonl_skips_blank_lines(tmp_path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text(
        json.dumps({"run_index": 1}) + "\n\n" + json.dumps({"run_index": 2}),
        encoding="utf-8",
    )

    records = load_jsonl(path)

    assert [item["run_index"] for item in records] == [1, 2]


def test_build_report_marks_pass_when_all_records_have_evidence() -> None:
    summary = {
        "active_input_count": 1,
        "status_counts": {"success": 1},
        "total_evidence_count": 1,
        "total_similar_case_count": 1,
        "total_display_evidence_count": 1,
        "zero_evidence_count": 0,
    }

    report = build_report(summary, [sample_record()])

    assert report["checks"]["all_success"] is True
    assert report["checks"]["has_evidence_for_all"] is True
    assert report["checks"]["has_display_evidence_for_all"] is True
    assert report["conclusion"].startswith("PASS")


def test_build_report_flags_zero_evidence() -> None:
    summary = {
        "active_input_count": 1,
        "status_counts": {"partial": 1},
        "total_evidence_count": 0,
        "total_similar_case_count": 0,
        "total_display_evidence_count": 0,
        "zero_evidence_count": 1,
    }

    report = build_report(summary, [sample_record(status="partial", evidence_count=0)])

    assert report["checks"]["all_success"] is False
    assert report["checks"]["zero_evidence_run_indexes"] == [1]
    assert report["conclusion"].startswith("REVIEW")


def test_build_markdown_report_contains_case_table() -> None:
    report = build_report(
        {
            "input_path": "input.jsonl",
            "output_path": "output.jsonl",
            "search_variant": "schema_search_text",
            "active_input_count": 1,
            "status_counts": {"success": 1},
            "total_evidence_count": 1,
            "total_similar_case_count": 1,
            "total_display_evidence_count": 1,
            "zero_evidence_count": 0,
        },
        [sample_record()],
    )

    markdown = build_markdown_report(report)

    assert "text_ml_case_search active 10" in markdown
    assert "review_case_db:case1#chunk1" in markdown
    assert "schema_search_text" in markdown


def test_write_report_creates_json_and_md(tmp_path) -> None:
    outputs_jsonl = tmp_path / "outputs.jsonl"
    summary_json = tmp_path / "summary.json"
    report_json = tmp_path / "report.json"
    report_md = tmp_path / "report.md"

    outputs_jsonl.write_text(
        json.dumps(sample_record(), ensure_ascii=False),
        encoding="utf-8",
    )
    summary_json.write_text(
        json.dumps(
            {
                "active_input_count": 1,
                "status_counts": {"success": 1},
                "total_evidence_count": 1,
                "total_similar_case_count": 1,
                "total_display_evidence_count": 1,
                "zero_evidence_count": 0,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = write_report(
        outputs_jsonl=outputs_jsonl,
        summary_json=summary_json,
        report_json=report_json,
        report_md=report_md,
    )

    assert result["record_count"] == 1
    assert report_json.exists()
    assert report_md.exists()
