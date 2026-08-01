from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from app.services.approved_legal_seed_builder import (
    ApprovedLegalSeedBuildError,
    PaidEmbeddingApprovalRequired,
    build_approved_legal_seed,
)
from app.services.rag_seed_bundle import (
    build_rag_seed_manifest,
    load_and_validate_rag_seed_manifest,
)


DATASET_VERSION = "sha256:" + "d" * 64
NOW = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _legal_chunk(chunk_id: str, text_hash: str) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "source_id": "road_traffic_act",
        "source_name": "도로교통법",
        "source_type": "law",
        "chunk_type": "article",
        "provision_text": f"provision for {chunk_id}",
        "normalized_text": f"normalized for {chunk_id}",
        "embedding_text": f"embedding text for {chunk_id}",
        "embedding_text_hash": text_hash,
        "source_url": "https://www.law.go.kr/example/road-traffic-act",
        "enforce_date": "2026-01-01",
        "is_searchable": True,
    }


def _embedding_input(chunk_id: str, text_hash: str) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "embedding_text": f"embedding text for {chunk_id}",
        "embedding_text_hash": text_hash,
        "status": "pending",
    }


def _embedding_row(chunk_id: str, text_hash: str) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "embedding_text": f"embedding text for {chunk_id}",
        "embedding_text_hash": text_hash,
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-large",
        "embedding_dimensions": 1024,
        "embedding_vector": [1.0] + [0.0] * 1023,
        "status": "embedded",
    }


def _existing_bundle(root: Path, *, text_hash: str):
    paths = {
        "legal_chunks": "data/legal_chunks.jsonl",
        "legal_embeddings": "data/legal_embeddings.jsonl",
        "review_case_chunks": "data/review_case_chunks.jsonl",
        "precedent_fault_ratio_chunks": "data/precedent_fault_ratio_chunks.jsonl",
    }
    _write_jsonl(root / paths["legal_chunks"], [_legal_chunk("law-1", text_hash)])
    _write_jsonl(root / paths["legal_embeddings"], [_embedding_row("law-1", text_hash)])
    _write_jsonl(
        root / paths["review_case_chunks"],
        [
            {
                "review_case_id": "review-1",
                "chunk_id": "review-1-summary",
                "chunk_text": "교차로 직진 차량과 우측 진입 차량 충돌 심의 사례의 구체적인 사실관계와 적용 기준 및 판단 근거입니다.",
            }
        ],
    )
    _write_jsonl(
        root / paths["precedent_fault_ratio_chunks"],
        [
            {
                "case_id": "precedent-1",
                "chunk_id": "precedent-1-0",
                "chunk_index": 0,
                "chunk_type": "holding",
                "chunk_strategy": "structured",
                "chunk_text": "차선을 변경하던 차량과 후행 직진 차량 충돌 판례의 구체적인 사실관계와 적용 기준 및 과실비율 판단 근거입니다.",
            }
        ],
    )
    manifest_path = root / "rag-seed-manifest.json"
    build_rag_seed_manifest(
        bundle_root=root,
        artifact_paths=paths,
        manifest_path=manifest_path,
    )
    return load_and_validate_rag_seed_manifest(manifest_path)


def _ingestion_output(
    root: Path,
    *,
    text_hash: str,
    verified_at: datetime = NOW,
) -> Path:
    _write_jsonl(root / "chunks/law_chunks.jsonl", [_legal_chunk("law-1", text_hash)])
    _write_jsonl(
        root / "embeddings/embedding_inputs.jsonl",
        [_embedding_input("law-1", text_hash)],
    )
    summary = {
        "contract_version": "legal_ingestion_run_summary.v2",
        "run_id": "legal_ingestion:20260801000000",
        "mode": "artifact",
        "status": "success",
        "dataset_version": DATASET_VERSION,
        "source_summaries": [
            {
                "source_id": "road_traffic_act",
                "status": "success",
                "last_verified_at": verified_at.isoformat(),
            }
        ],
    }
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False),
        encoding="utf-8",
    )
    return root


def test_builder_refuses_pending_rows_before_provider_call(tmp_path: Path) -> None:
    bundle = _existing_bundle(tmp_path / "existing", text_hash="a" * 64)
    ingestion = _ingestion_output(tmp_path / "ingestion", text_hash="b" * 64)
    calls: list[dict[str, object]] = []

    with pytest.raises(PaidEmbeddingApprovalRequired) as raised:
        build_approved_legal_seed(
            existing_bundle=bundle,
            ingestion_output_root=ingestion,
            output_root=tmp_path / "output",
            expected_dataset_version=DATASET_VERSION,
            max_age_hours=168,
            required_sources=["road_traffic_act"],
            now=NOW,
            dry_run=False,
            allow_paid_embedding=False,
            approved_plan_sha256=None,
            embedding_generator=lambda **kwargs: calls.append(kwargs),
        )

    assert calls == []
    assert raised.value.plan.pending_count == 1
    assert not (tmp_path / "output/rag-seed-manifest.json").exists()


def test_builder_completes_without_provider_when_every_row_is_reused(
    tmp_path: Path,
) -> None:
    bundle = _existing_bundle(tmp_path / "existing", text_hash="a" * 64)
    ingestion = _ingestion_output(tmp_path / "ingestion", text_hash="a" * 64)

    result = build_approved_legal_seed(
        existing_bundle=bundle,
        ingestion_output_root=ingestion,
        output_root=tmp_path / "output",
        expected_dataset_version=DATASET_VERSION,
        max_age_hours=168,
        required_sources=["road_traffic_act"],
        now=NOW,
        dry_run=False,
        allow_paid_embedding=False,
        approved_plan_sha256=None,
        embedding_generator=lambda **kwargs: pytest.fail("provider called"),
    )

    assert result.status == "verified"
    assert result.reuse_plan.pending_count == 0
    verified = load_and_validate_rag_seed_manifest(result.manifest_path)
    assert verified.artifacts["legal_embeddings"].row_count == 1
    assert result.reuse_plan.reused_embeddings_path == (
        tmp_path / "output/data/legal_embeddings.jsonl"
    )
    assert not (tmp_path / "output/evidence/reuse/reused_embeddings.jsonl").exists()


def test_builder_preserves_conservative_source_verified_at(tmp_path: Path) -> None:
    bundle = _existing_bundle(tmp_path / "existing", text_hash="a" * 64)
    source_verified_at = datetime(2026, 7, 31, 23, 0, tzinfo=timezone.utc)
    ingestion = _ingestion_output(
        tmp_path / "ingestion",
        text_hash="a" * 64,
        verified_at=source_verified_at,
    )

    result = build_approved_legal_seed(
        existing_bundle=bundle,
        ingestion_output_root=ingestion,
        output_root=tmp_path / "output",
        expected_dataset_version=DATASET_VERSION,
        max_age_hours=168,
        required_sources=["road_traffic_act"],
        now=NOW,
        dry_run=False,
        allow_paid_embedding=False,
        approved_plan_sha256=None,
        embedding_generator=None,
    )

    assert result.verified_at == source_verified_at.isoformat()


def test_builder_embeds_only_exactly_approved_pending_plan(tmp_path: Path) -> None:
    bundle = _existing_bundle(tmp_path / "existing", text_hash="a" * 64)
    ingestion = _ingestion_output(tmp_path / "ingestion", text_hash="b" * 64)
    preview = build_approved_legal_seed(
        existing_bundle=bundle,
        ingestion_output_root=ingestion,
        output_root=tmp_path / "preview",
        expected_dataset_version=None,
        max_age_hours=168,
        required_sources=["road_traffic_act"],
        now=NOW,
        dry_run=True,
        allow_paid_embedding=False,
        approved_plan_sha256=None,
        embedding_generator=None,
    )
    calls: list[Path] = []

    def fake_generator(**kwargs) -> dict:
        input_path = Path(kwargs["input_path"])
        output_path = Path(kwargs["output_path"])
        calls.append(input_path)
        pending_rows = [
            json.loads(line)
            for line in input_path.read_text(encoding="utf-8").splitlines()
        ]
        _write_jsonl(
            output_path,
            [
                {
                    **row,
                    "embedding_provider": "openai",
                    "embedding_model": "text-embedding-3-large",
                    "embedding_dimensions": 1024,
                    "embedding_vector": [1.0] + [0.0] * 1023,
                    "status": "embedded",
                }
                for row in pending_rows
            ],
        )
        Path(kwargs["report_path"]).write_text(
            json.dumps({"status": "success", "embedded_count": len(pending_rows)}),
            encoding="utf-8",
        )
        return {"status": "success"}

    result = build_approved_legal_seed(
        existing_bundle=bundle,
        ingestion_output_root=ingestion,
        output_root=tmp_path / "final",
        expected_dataset_version=DATASET_VERSION,
        max_age_hours=168,
        required_sources=["road_traffic_act"],
        now=NOW,
        dry_run=False,
        allow_paid_embedding=True,
        approved_plan_sha256=preview.reuse_plan.plan_sha256,
        embedding_generator=fake_generator,
    )

    assert len(calls) == 1
    assert result.status == "verified"
    assert result.reuse_plan.changed_count == 1
    assert result.manifest_sha256 and len(result.manifest_sha256) == 64


def test_builder_does_not_expose_partial_final_embeddings_when_append_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _existing_bundle(tmp_path / "existing", text_hash="a" * 64)
    ingestion = _ingestion_output(tmp_path / "ingestion", text_hash="b" * 64)
    preview = build_approved_legal_seed(
        existing_bundle=bundle,
        ingestion_output_root=ingestion,
        output_root=tmp_path / "preview",
        expected_dataset_version=None,
        max_age_hours=168,
        required_sources=["road_traffic_act"],
        now=NOW,
        dry_run=True,
        allow_paid_embedding=False,
        approved_plan_sha256=None,
        embedding_generator=None,
    )

    def fake_generator(**kwargs) -> dict:
        pending_rows = [
            json.loads(line)
            for line in Path(kwargs["input_path"])
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        _write_jsonl(
            Path(kwargs["output_path"]),
            [_embedding_row(row["chunk_id"], row["embedding_text_hash"]) for row in pending_rows],
        )
        Path(kwargs["report_path"]).write_text(
            json.dumps({"status": "success", "embedded_count": len(pending_rows)}),
            encoding="utf-8",
        )
        return {"status": "success"}

    def fail_during_append(source, target, *, length) -> None:
        target.write(source.read(1))
        raise OSError("simulated disk failure")

    monkeypatch.setattr(
        "app.services.approved_legal_seed_builder.shutil.copyfileobj",
        fail_during_append,
    )

    with pytest.raises(
        ApprovedLegalSeedBuildError,
        match="final production RAG seed validation failed",
    ):
        build_approved_legal_seed(
            existing_bundle=bundle,
            ingestion_output_root=ingestion,
            output_root=tmp_path / "final",
            expected_dataset_version=DATASET_VERSION,
            max_age_hours=168,
            required_sources=["road_traffic_act"],
            now=NOW,
            dry_run=False,
            allow_paid_embedding=True,
            approved_plan_sha256=preview.reuse_plan.plan_sha256,
            embedding_generator=fake_generator,
        )

    assert not (tmp_path / "final/data/legal_embeddings.jsonl").exists()


def test_builder_rejects_changed_plan_digest_before_provider_call(
    tmp_path: Path,
) -> None:
    bundle = _existing_bundle(tmp_path / "existing", text_hash="a" * 64)
    ingestion = _ingestion_output(tmp_path / "ingestion", text_hash="b" * 64)
    calls: list[dict[str, object]] = []

    with pytest.raises(ApprovedLegalSeedBuildError, match="plan sha256 mismatch"):
        build_approved_legal_seed(
            existing_bundle=bundle,
            ingestion_output_root=ingestion,
            output_root=tmp_path / "output",
            expected_dataset_version=DATASET_VERSION,
            max_age_hours=168,
            required_sources=["road_traffic_act"],
            now=NOW,
            dry_run=False,
            allow_paid_embedding=True,
            approved_plan_sha256="0" * 64,
            embedding_generator=lambda **kwargs: calls.append(kwargs),
        )

    assert calls == []
    assert not (tmp_path / "output/rag-seed-manifest.json").exists()


def test_builder_dry_run_does_not_materialize_reused_vectors(tmp_path: Path) -> None:
    bundle = _existing_bundle(tmp_path / "existing", text_hash="a" * 64)
    ingestion = _ingestion_output(tmp_path / "ingestion", text_hash="a" * 64)

    result = build_approved_legal_seed(
        existing_bundle=bundle,
        ingestion_output_root=ingestion,
        output_root=tmp_path / "preview",
        expected_dataset_version=None,
        max_age_hours=168,
        required_sources=["road_traffic_act"],
        now=NOW,
        dry_run=True,
        allow_paid_embedding=False,
        approved_plan_sha256=None,
        embedding_generator=None,
    )

    assert result.reuse_plan.reused_count == 1
    assert result.reuse_plan.reused_embeddings_path is None
    assert not (tmp_path / "preview/evidence/reuse/reused_embeddings.jsonl").exists()
