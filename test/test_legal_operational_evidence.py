from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path

import pytest
from django.core.management.base import CommandError

from app.services.legal_operational_evidence import (
    LegalOperationalEvidenceError,
    build_legal_operational_evidence,
)
from app.services.rag_seed_bundle import (
    build_rag_seed_manifest,
    load_and_validate_rag_seed_manifest,
)
from backend.chatbot.management.commands.build_legal_operational_evidence import (
    Command as BuildEvidenceCommand,
)


VERIFIED_AT = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
PRIVATE_PROVISION = "민감한 테스트 법령 본문은 운영 증적에 포함되면 안 됩니다."


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _verified_bundle(tmp_path: Path):
    legal_rows: list[dict[str, object]] = [
        {
            "chunk_id": "decree-1",
            "source_id": "road-traffic-decree",
            "source_name": "도로교통법 시행령",
            "source_type": "enforcement_decree",
            "chunk_type": "article",
            "source_url": "https://www.law.go.kr/example/road-traffic-decree",
            "enforce_date": "2025-01-01",
            "expire_date": None,
            "provision_text": PRIVATE_PROVISION,
            "normalized_text": PRIVATE_PROVISION,
        },
        {
            "chunk_id": "law-1",
            "source_id": "road-traffic-act",
            "source_name": "도로교통법",
            "source_type": "law",
            "chunk_type": "article",
            "source_url": "https://www.law.go.kr/example/road-traffic-act",
            "enforce_date": "2020-01-01",
            "expire_date": "2024-12-31",
            "provision_text": PRIVATE_PROVISION,
            "normalized_text": PRIVATE_PROVISION,
        },
        {
            "chunk_id": "law-2",
            "source_id": "road-traffic-act",
            "source_name": "도로교통법",
            "source_type": "law",
            "chunk_type": "article",
            "source_url": "https://www.law.go.kr/example/road-traffic-act",
            "enforce_date": "2025-01-01",
            "expire_date": None,
            "provision_text": PRIVATE_PROVISION,
            "normalized_text": PRIVATE_PROVISION,
        },
    ]
    rows_by_role = {
        "legal_chunks": legal_rows,
        "legal_embeddings": [
            {
                "chunk_id": row["chunk_id"],
                "embedding_vector": [1.0] + [0.0] * 1023,
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-3-large",
                "embedding_dimensions": 1024,
            }
            for row in legal_rows
        ],
        "review_case_chunks": [
            {
                "review_case_id": "review-1",
                "chunk_id": "review-1-summary",
                "chunk_text": "검토 사례를 위한 최소 길이 이상의 안전한 설명 텍스트입니다. " * 3,
            }
        ],
        "precedent_fault_ratio_chunks": [
            {
                "case_id": "precedent-1",
                "chunk_id": "precedent-1-0",
                "chunk_index": 0,
                "chunk_type": "holding",
                "chunk_strategy": "structured",
                "chunk_text": "과실비율 판례 검색을 위한 최소 길이 이상의 설명 텍스트입니다. " * 3,
            }
        ],
    }
    paths: dict[str, str] = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        paths[role] = relative_path
    manifest_path = tmp_path / "rag-seed-manifest.json"
    build_rag_seed_manifest(
        bundle_root=tmp_path,
        artifact_paths=paths,
        manifest_path=manifest_path,
    )
    return load_and_validate_rag_seed_manifest(manifest_path)


def test_build_evidence_is_release_bound_deterministic_and_content_safe(
    tmp_path: Path,
) -> None:
    bundle = _verified_bundle(tmp_path)

    first = build_legal_operational_evidence(
        bundle,
        dataset_version="pilot-2026-07-31",
        release_version="release-abc123",
        verified_at=VERIFIED_AT,
    )
    second = build_legal_operational_evidence(
        bundle,
        dataset_version="pilot-2026-07-31",
        release_version="release-abc123",
        verified_at=VERIFIED_AT,
    )

    assert first == second
    assert first["contract_version"] == "legal_ingestion_run_summary.v2"
    assert first["dataset_version"] == "pilot-2026-07-31"
    assert first["release_version"] == "release-abc123"
    assert first["status"] == "success"
    assert first["total_sources"] == 2
    assert first["total_versions"] == 3
    assert first["total_chunks"] == 3
    assert first["searchable_chunks"] == 3
    assert [
        row["source_id"] for row in first["source_summaries"]
    ] == ["road-traffic-act", "road-traffic-decree"]
    assert first["source_summaries"][0]["version_count"] == 2
    assert all(row["status"] == "success" for row in first["source_summaries"])
    rendered = json.dumps(first, ensure_ascii=False)
    assert PRIVATE_PROVISION not in rendered
    assert "text-embedding-3-large" not in rendered


@pytest.mark.parametrize(
    ("dataset_version", "release_version"),
    [
        ("", "release-abc123"),
        ("pilot current", "release-abc123"),
        ("pilot-2026-07-31", ""),
        ("pilot-2026-07-31", "release/current"),
    ],
)
def test_build_evidence_rejects_unsafe_provenance(
    tmp_path: Path,
    dataset_version: str,
    release_version: str,
) -> None:
    with pytest.raises(
        LegalOperationalEvidenceError,
        match="operational evidence provenance is invalid",
    ):
        build_legal_operational_evidence(
            _verified_bundle(tmp_path),
            dataset_version=dataset_version,
            release_version=release_version,
            verified_at=VERIFIED_AT,
        )


def test_build_evidence_rejects_naive_timestamp(tmp_path: Path) -> None:
    with pytest.raises(
        LegalOperationalEvidenceError,
        match="verified_at must include timezone information",
    ):
        build_legal_operational_evidence(
            _verified_bundle(tmp_path),
            dataset_version="pilot-2026-07-31",
            release_version="release-abc123",
            verified_at=datetime(2026, 7, 31, 12, 0),
        )


def test_management_command_prints_one_json_document(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path)
    stdout = StringIO()

    BuildEvidenceCommand(stdout=stdout).handle(
        manifest=str(bundle.manifest_path),
        dataset_version="pilot-2026-07-31",
        release_version="release-abc123",
        verified_at=VERIFIED_AT.isoformat(),
    )

    lines = stdout.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["release_version"] == "release-abc123"
    assert PRIVATE_PROVISION not in stdout.getvalue()


def test_management_command_returns_safe_error_for_bad_timestamp(
    tmp_path: Path,
) -> None:
    bundle = _verified_bundle(tmp_path)

    with pytest.raises(
        CommandError,
        match="operational evidence timestamp is invalid",
    ):
        BuildEvidenceCommand().handle(
            manifest=str(bundle.manifest_path),
            dataset_version="pilot-2026-07-31",
            release_version="release-abc123",
            verified_at="not-a-timestamp-with-secret",
        )
