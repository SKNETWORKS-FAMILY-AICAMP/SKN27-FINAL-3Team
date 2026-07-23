from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from etl.legal.ingestion.reporter import build_run_summary
from etl.legal.rebuild_artifacts_from_embeddings import rebuild_artifacts


ROOT = Path(__file__).resolve().parents[1]


def _source() -> dict:
    return {
        "source_id": "road_traffic_act",
        "source_name": "도로교통법",
        "source_type": "law",
        "provider": "law_go_kr",
        "provider_source_id": "도로교통법",
    }


def _summary() -> dict:
    return build_run_summary(
        run_id="legal:test",
        mode="artifact",
        sources=[_source()],
        versions=[
            {
                "source_id": "road_traffic_act",
                "source_version_id": "road_traffic_act:20260701:1",
                "enforce_date": "2026-07-01",
            }
        ],
        raw_records=[
            {
                "source_id": "road_traffic_act",
                "source_version_id": "road_traffic_act:20260701:1",
                "fetched_at": "2026-07-23T01:00:00+00:00",
            }
        ],
        chunks=[
            {
                "source_id": "road_traffic_act",
                "chunk_id": "road_traffic_act:20260701:1:article:1",
                "content_hash": "sha256:abc",
                "is_searchable": True,
            }
        ],
        searchable_chunks=[
            {
                "source_id": "road_traffic_act",
                "chunk_id": "road_traffic_act:20260701:1:article:1",
            }
        ],
        relations=[],
        embedding_inputs=[],
        quality_report={"failed_chunks": 0, "status_counts": {}},
        failed_items=[],
        started_at="2026-07-23T00:59:00+00:00",
    )


def test_run_summary_contains_source_freshness_and_version_evidence() -> None:
    summary = _summary()

    assert summary["contract_version"] == "legal_ingestion_run_summary.v2"
    assert summary["dataset_version"].startswith("sha256:")
    source = summary["source_summaries"][0]
    assert source == {
        "source_id": "road_traffic_act",
        "source_name": "도로교통법",
        "source_type": "law",
        "provider": "law_go_kr",
        "provider_source_id": "도로교통법",
        "status": "success",
        "version_count": 1,
        "raw_document_count": 1,
        "chunk_count": 1,
        "searchable_chunk_count": 1,
        "first_effective_at": "2026-07-01",
        "last_effective_at": "2026-07-01",
        "collected_at": "2026-07-23T01:00:00+00:00",
        "last_verified_at": summary["finished_at"],
        "data_version": source["data_version"],
        "errors": [],
    }
    assert source["data_version"].startswith("sha256:")


def test_run_summary_marks_missing_source_failed() -> None:
    summary = build_run_summary(
        run_id="legal:failed",
        mode="artifact",
        sources=[_source()],
        versions=[],
        raw_records=[],
        chunks=[],
        searchable_chunks=[],
        relations=[],
        embedding_inputs=[],
        quality_report={"failed_chunks": 0, "status_counts": {}},
        failed_items=[
            {"source_id": "road_traffic_act", "error": "provider_unavailable"}
        ],
        started_at="2026-07-23T00:59:00+00:00",
    )

    source = summary["source_summaries"][0]
    assert source["status"] == "failed"
    assert source["last_verified_at"] is None
    assert source["errors"] == ["provider_unavailable"]


def test_run_summary_is_partial_when_any_manifest_source_is_missing() -> None:
    summary = build_run_summary(
        run_id="legal:partial",
        mode="artifact",
        sources=[
            _source(),
            {
                **_source(),
                "source_id": "road_traffic_act_enforcement_decree",
                "source_name": "도로교통법 시행령",
                "source_type": "enforcement_decree",
                "provider_source_id": "도로교통법 시행령",
            },
        ],
        versions=[
            {
                "source_id": "road_traffic_act",
                "source_version_id": "road_traffic_act:20260701:1",
                "enforce_date": "2026-07-01",
            }
        ],
        raw_records=[],
        chunks=[
            {
                "source_id": "road_traffic_act",
                "chunk_id": "road_traffic_act:20260701:1:article:1",
                "content_hash": "sha256:abc",
            }
        ],
        searchable_chunks=[],
        relations=[],
        embedding_inputs=[],
        quality_report={"failed_chunks": 0, "status_counts": {}},
        failed_items=[],
        started_at="2026-07-23T00:59:00+00:00",
    )

    assert summary["status"] == "partial"
    assert summary["source_summaries"][1]["status"] == "missing"


def test_run_summary_does_not_expose_raw_provider_error_details() -> None:
    summary = build_run_summary(
        run_id="legal:safe-error",
        mode="artifact",
        sources=[_source()],
        versions=[],
        raw_records=[],
        chunks=[],
        searchable_chunks=[],
        relations=[],
        embedding_inputs=[],
        quality_report={"failed_chunks": 0, "status_counts": {}},
        failed_items=[
            {
                "source_id": "road_traffic_act",
                "stage": "collect",
                "error": "GET https://provider.test?api_key=supersecret failed",
            }
        ],
        started_at="2026-07-23T00:59:00+00:00",
    )

    rendered = json.dumps(summary)
    assert "supersecret" not in rendered
    assert summary["source_summaries"][0]["errors"] == ["collect_failed"]
    assert summary["limitations"] == ["collect_failed"]


def test_run_summary_does_not_verify_source_without_searchable_chunks() -> None:
    summary = build_run_summary(
        run_id="legal:no-searchable-chunks",
        mode="artifact",
        sources=[_source()],
        versions=[
            {
                "source_id": "road_traffic_act",
                "source_version_id": "road_traffic_act:20260701:1",
                "enforce_date": "2026-07-01",
            }
        ],
        raw_records=[
            {
                "source_id": "road_traffic_act",
                "source_version_id": "road_traffic_act:20260701:1",
                "fetched_at": "2026-07-23T01:00:00+00:00",
            }
        ],
        chunks=[
            {
                "source_id": "road_traffic_act",
                "chunk_id": "road_traffic_act:20260701:1:article:1",
                "content_hash": "sha256:abc",
            }
        ],
        searchable_chunks=[],
        relations=[],
        embedding_inputs=[],
        quality_report={"failed_chunks": 1, "status_counts": {}},
        failed_items=[],
        started_at="2026-07-23T00:59:00+00:00",
    )

    source = summary["source_summaries"][0]
    assert summary["status"] == "partial"
    assert source["status"] == "partial"
    assert source["last_verified_at"] is None


def test_embedding_rebuild_uses_v2_run_summary(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump({"sources": [_source()]}, allow_unicode=True),
        encoding="utf-8",
    )
    embeddings_path = tmp_path / "embeddings.jsonl"
    embeddings_path.write_text(
        json.dumps(
            {
                "chunk_id": "road_traffic_act:20260701:1:article:1",
                "embedding_text": "[도로교통법 제1조 목적] 테스트 본문",
                "embedding_text_hash": "sha256:abc",
                "embedded_at": "2026-07-23T01:00:00+00:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = rebuild_artifacts(
        manifest_path=manifest_path,
        embeddings_path=embeddings_path,
        output_dir=tmp_path / "out",
    )

    assert summary["contract_version"] == "legal_ingestion_run_summary.v2"
    assert summary["source_summaries"][0]["source_id"] == "road_traffic_act"
    assert summary["source_summaries"][0]["status"] == "success"
    assert summary["source_summaries"][0]["chunk_count"] == 1
    assert summary["source_summaries"][0]["searchable_chunk_count"] == 1
    assert summary["embedding_input_count"] == 1
    persisted = json.loads(
        (tmp_path / "out/reports/run_summary.json").read_text(encoding="utf-8")
    )
    assert persisted["dataset_version"] == summary["dataset_version"]


def test_embedding_rebuild_script_keeps_direct_cli_compatibility() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "etl/legal/rebuild_artifacts_from_embeddings.py"),
            "--help",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--embeddings" in result.stdout
