from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from etl.legal.validate_run_summary import evaluate_run_summary, main


NOW = datetime(2026, 7, 23, 2, tzinfo=timezone.utc)


def _summary(*, verified_at: str, status: str = "success") -> dict:
    return {
        "contract_version": "legal_ingestion_run_summary.v2",
        "run_id": "legal:test",
        "dataset_version": "sha256:dataset",
        "release_version": "release-abc123",
        "finished_at": verified_at,
        "source_summaries": [
            {
                "source_id": "road_traffic_act",
                "status": status,
                "last_verified_at": verified_at if status == "success" else None,
            }
        ],
    }


def test_validation_blocks_stale_and_missing_sources() -> None:
    result = evaluate_run_summary(
        _summary(verified_at="2026-07-22T00:00:00+00:00"),
        now=NOW,
        max_age_hours=24,
        required_sources=[
            "road_traffic_act",
            "road_traffic_act_enforcement_decree",
        ],
    )

    assert result["status"] == "failed"
    assert result["stale_sources"] == ["road_traffic_act"]
    assert result["missing_sources"] == ["road_traffic_act_enforcement_decree"]
    assert result["failed_sources"] == []


def test_validation_blocks_failed_source_and_wrong_contract() -> None:
    failed = evaluate_run_summary(
        _summary(
            verified_at="2026-07-23T01:30:00+00:00",
            status="failed",
        ),
        now=NOW,
        max_age_hours=24,
        required_sources=["road_traffic_act"],
    )
    wrong_contract = evaluate_run_summary(
        {
            **_summary(verified_at="2026-07-23T01:30:00+00:00"),
            "contract_version": "legal_ingestion_run_summary.v1",
        },
        now=NOW,
        max_age_hours=24,
        required_sources=["road_traffic_act"],
    )

    assert failed["status"] == "failed"
    assert failed["failed_sources"] == ["road_traffic_act"]
    assert wrong_contract["status"] == "failed"
    assert wrong_contract["errors"] == ["unsupported_contract_version"]


def test_validation_accepts_current_complete_summary() -> None:
    result = evaluate_run_summary(
        _summary(verified_at="2026-07-23T01:30:00+00:00"),
        now=NOW,
        max_age_hours=24,
        required_sources=["road_traffic_act"],
    )

    assert result["status"] == "success"
    assert result["missing_sources"] == []
    assert result["failed_sources"] == []
    assert result["stale_sources"] == []
    assert result["run_id"] == "legal:test"
    assert result["dataset_version"] == "sha256:dataset"
    assert result["release_version"] == "release-abc123"


def test_validation_rejects_dataset_and_release_provenance_mismatch() -> None:
    dataset_mismatch = evaluate_run_summary(
        _summary(verified_at="2026-07-23T01:30:00+00:00"),
        now=NOW,
        max_age_hours=24,
        required_sources=["road_traffic_act"],
        expected_dataset_version="sha256:different",
        expected_release_version="release-abc123",
    )
    release_mismatch = evaluate_run_summary(
        _summary(verified_at="2026-07-23T01:30:00+00:00"),
        now=NOW,
        max_age_hours=24,
        required_sources=["road_traffic_act"],
        expected_dataset_version="sha256:dataset",
        expected_release_version="release-different",
    )

    assert dataset_mismatch["status"] == "failed"
    assert dataset_mismatch["errors"] == ["dataset_version_mismatch"]
    assert release_mismatch["status"] == "failed"
    assert release_mismatch["errors"] == ["release_version_mismatch"]


def test_validation_rejects_summary_without_any_source() -> None:
    result = evaluate_run_summary(
        {
            "contract_version": "legal_ingestion_run_summary.v2",
            "run_id": "legal:empty",
            "dataset_version": "sha256:empty",
            "source_summaries": [],
        },
        now=NOW,
        max_age_hours=24,
        required_sources=[],
    )

    assert result["status"] == "failed"
    assert result["errors"] == ["no_sources_to_validate"]


def test_cli_writes_validation_evidence_and_returns_failure(tmp_path: Path) -> None:
    summary_path = tmp_path / "run_summary.json"
    output_path = tmp_path / "freshness_validation.json"
    summary_path.write_text(
        json.dumps(_summary(verified_at="2026-07-22T00:00:00+00:00")),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--summary",
            str(summary_path),
            "--max-age-hours",
            "24",
            "--required-source",
            "road_traffic_act",
            "--output",
            str(output_path),
            "--now",
            NOW.isoformat(),
        ]
    )

    assert exit_code == 1
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["contract_version"] == "legal_run_summary_validation.v1"
    assert persisted["stale_sources"] == ["road_traffic_act"]
