from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from backend.chatbot.management.commands import build_approved_legal_rag_seed


def test_command_dry_run_never_enables_embedding_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ingestion_root = tmp_path / "output/ingestion"
    source_config = tmp_path / "sources.yaml"
    source_config.write_text(
        """sources:
  - source_id: road_traffic_act
    source_name: 도로교통법
    source_type: law
    provider: law_go_kr
    enabled: true
    priority: 1
""",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        build_approved_legal_rag_seed,
        "load_and_validate_rag_seed_manifest",
        lambda path: SimpleNamespace(manifest_path=Path(path)),
    )
    monkeypatch.setattr(
        build_approved_legal_rag_seed,
        "_run_legal_ingestion",
        lambda **kwargs: ingestion_root,
    )

    def fake_build(**kwargs):
        captured.update(kwargs)
        plan = SimpleNamespace(
            plan_sha256="a" * 64,
            reused_count=97394,
            changed_count=0,
            new_count=0,
            removed_count=0,
            pending_count=0,
        )
        return SimpleNamespace(
            status="planned",
            dataset_version="sha256:" + "d" * 64,
            verified_at="2026-08-01T00:00:00+00:00",
            reuse_plan=plan,
            manifest_path=None,
            manifest_sha256=None,
        )

    monkeypatch.setattr(
        build_approved_legal_rag_seed,
        "build_approved_legal_seed",
        fake_build,
    )
    stdout = io.StringIO()

    call_command(
        build_approved_legal_rag_seed.Command(),
        source_config=str(source_config),
        existing_manifest=str(tmp_path / "rag-seed-manifest.json"),
        output_root=str(tmp_path / "output"),
        max_age_hours=168,
        client="offline",
        base_date="2026-08-01",
        history_years=3,
        dry_run=True,
        format="json",
        stdout=stdout,
    )

    assert captured["dry_run"] is True
    assert captured["allow_paid_embedding"] is False
    assert captured["embedding_generator"] is None
    payload = json.loads(stdout.getvalue())
    assert payload["contract_version"] == "approved_legal_rag_seed_build.v1"
    assert payload["status"] == "planned"
    assert payload["counts"] == {
        "changed": 0,
        "new": 0,
        "pending": 0,
        "removed": 0,
        "reused": 97394,
    }
    assert "embedding_vector" not in stdout.getvalue()


def test_command_rejects_paid_flag_without_exact_plan_sha(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="approved-plan-sha256"):
        call_command(
            build_approved_legal_rag_seed.Command(),
            source_config=str(tmp_path / "sources.yaml"),
            existing_manifest=str(tmp_path / "rag-seed-manifest.json"),
            output_root=str(tmp_path / "output"),
            dataset_version="sha256:" + "d" * 64,
            max_age_hours=168,
            client="offline",
            base_date="2026-08-01",
            history_years=3,
            allow_paid_embedding=True,
            format="json",
        )


def test_run_legal_ingestion_uses_real_offline_pipeline(tmp_path: Path) -> None:
    source_config = tmp_path / "sources.yaml"
    source_config.write_text(
        """sources:
  - source_id: road_traffic_act
    source_name: 도로교통법
    source_type: law
    provider: law_go_kr
    enabled: true
    priority: 1
""",
        encoding="utf-8",
    )
    output_root = tmp_path / "ingestion"

    result_root = build_approved_legal_rag_seed._run_legal_ingestion(
        source_config=source_config,
        output_root=output_root,
        base_date=date(2026, 8, 1),
        history_years=3,
        client="offline",
    )

    summary = json.loads(
        (result_root / "reports/run_summary.json").read_text(encoding="utf-8")
    )
    assert summary["status"] == "success"
    assert summary["source_summaries"][0]["source_id"] == "road_traffic_act"
