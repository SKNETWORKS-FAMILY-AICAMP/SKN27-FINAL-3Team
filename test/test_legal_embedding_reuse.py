from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.services.legal_embedding_reuse import (
    LegalEmbeddingReuseError,
    build_embedding_reuse_plan,
)
from app.services.rag_seed_bundle import (
    build_rag_seed_manifest,
    load_and_validate_rag_seed_manifest,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _embedding_input(chunk_id: str, text_hash: str) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "embedding_text": f"text for {chunk_id}",
        "embedding_text_hash": text_hash,
        "status": "pending",
    }


def _embedding_row(chunk_id: str, text_hash: str, value: float) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "embedding_text_hash": text_hash,
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-large",
        "embedding_dimensions": 1024,
        "embedding_vector": [value] + [0.0] * 1023,
        "status": "embedded",
    }


def _legal_chunk(chunk_id: str) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "source_id": "road_traffic_act",
        "source_name": "도로교통법",
        "source_type": "law",
        "chunk_type": "article",
        "provision_text": f"provision for {chunk_id}",
        "normalized_text": f"normalized for {chunk_id}",
        "source_url": "https://www.law.go.kr/example/road-traffic-act",
        "enforce_date": "2026-01-01",
        "is_searchable": True,
    }


def _verified_bundle(tmp_path: Path):
    old_rows = [
        ("same", "a" * 64, 1.0),
        ("changed", "b" * 64, 2.0),
        ("removed", "c" * 64, 3.0),
    ]
    paths = {
        "legal_chunks": "data/legal_chunks.jsonl",
        "legal_embeddings": "data/legal_embeddings.jsonl",
        "review_case_chunks": "data/review_case_chunks.jsonl",
        "precedent_fault_ratio_chunks": "data/precedent_fault_ratio_chunks.jsonl",
    }
    _write_jsonl(
        tmp_path / paths["legal_chunks"],
        [_legal_chunk(chunk_id) for chunk_id, _, _ in old_rows],
    )
    _write_jsonl(
        tmp_path / paths["legal_embeddings"],
        [_embedding_row(*row) for row in old_rows],
    )
    _write_jsonl(
        tmp_path / paths["review_case_chunks"],
        [
            {
                "review_case_id": "review-1",
                "chunk_id": "review-1-summary",
                "chunk_text": "교차로 직진 차량과 우측 진입 차량 충돌 심의 사례의 구체적인 사실관계와 적용 기준 및 판단 근거입니다.",
            }
        ],
    )
    _write_jsonl(
        tmp_path / paths["precedent_fault_ratio_chunks"],
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
    manifest_path = tmp_path / "rag-seed-manifest.json"
    build_rag_seed_manifest(
        bundle_root=tmp_path,
        artifact_paths=paths,
        manifest_path=manifest_path,
    )
    return load_and_validate_rag_seed_manifest(manifest_path)


def test_plan_reuses_only_matching_chunk_and_text_hash(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path / "existing")
    fresh = _write_jsonl(
        tmp_path / "fresh.jsonl",
        [
            _embedding_input("same", "a" * 64),
            _embedding_input("changed", "d" * 64),
            _embedding_input("new", "e" * 64),
        ],
    )

    plan = build_embedding_reuse_plan(
        bundle=bundle,
        fresh_inputs_path=fresh,
        output_dir=tmp_path / "plan",
        dataset_version="sha256:" + "f" * 64,
    )

    assert plan.reused_count == 1
    assert plan.changed_count == 1
    assert plan.new_count == 1
    assert plan.removed_count == 1
    assert plan.pending_count == 2
    assert len(plan.plan_sha256) == 64

    reused = [
        json.loads(line)
        for line in plan.reused_embeddings_path.read_text(encoding="utf-8").splitlines()
    ]
    pending = [
        json.loads(line)
        for line in plan.pending_inputs_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["chunk_id"] for row in reused] == ["same"]
    assert reused[0]["embedding_vector"][0] == 1.0
    assert [row["chunk_id"] for row in pending] == ["changed", "new"]

    report = json.loads(plan.report_path.read_text(encoding="utf-8"))
    assert report["contract_version"] == "legal_embedding_reuse_plan.v1"
    assert "embedding_vector" not in json.dumps(report)
    assert "embedding_text" not in json.dumps(report)

    with plan.audit_path.open("r", encoding="utf-8", newline="") as handle:
        audit_rows = list(csv.DictReader(handle))
    assert [row["classification"] for row in audit_rows] == [
        "changed",
        "new",
        "removed",
        "reused",
    ]
    assert "embedding_vector" not in plan.audit_path.read_text(encoding="utf-8")
    assert "text for" not in plan.audit_path.read_text(encoding="utf-8")


def test_plan_rejects_duplicate_fresh_chunk_identity_without_outputs(
    tmp_path: Path,
) -> None:
    bundle = _verified_bundle(tmp_path / "existing")
    fresh = _write_jsonl(
        tmp_path / "fresh.jsonl",
        [
            _embedding_input("same", "a" * 64),
            _embedding_input("same", "a" * 64),
        ],
    )
    output_dir = tmp_path / "plan"

    with pytest.raises(LegalEmbeddingReuseError, match="duplicate chunk_id"):
        build_embedding_reuse_plan(
            bundle=bundle,
            fresh_inputs_path=fresh,
            output_dir=output_dir,
            dataset_version="sha256:" + "f" * 64,
        )

    assert not output_dir.exists()


def test_plan_rejects_missing_embedding_text_hash(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path / "existing")
    fresh = _write_jsonl(
        tmp_path / "fresh.jsonl",
        [{"chunk_id": "same", "embedding_text": "same", "status": "pending"}],
    )

    with pytest.raises(LegalEmbeddingReuseError, match="embedding_text_hash"):
        build_embedding_reuse_plan(
            bundle=bundle,
            fresh_inputs_path=fresh,
            output_dir=tmp_path / "plan",
            dataset_version="sha256:" + "f" * 64,
        )


def test_plan_digest_is_stable_across_fresh_input_order(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path / "existing")
    rows = [
        _embedding_input("new", "e" * 64),
        _embedding_input("changed", "d" * 64),
        _embedding_input("same", "a" * 64),
    ]
    first = _write_jsonl(tmp_path / "first.jsonl", rows)
    second = _write_jsonl(tmp_path / "second.jsonl", list(reversed(rows)))

    first_plan = build_embedding_reuse_plan(
        bundle=bundle,
        fresh_inputs_path=first,
        output_dir=tmp_path / "first-plan",
        dataset_version="sha256:" + "f" * 64,
    )
    second_plan = build_embedding_reuse_plan(
        bundle=bundle,
        fresh_inputs_path=second,
        output_dir=tmp_path / "second-plan",
        dataset_version="sha256:" + "f" * 64,
    )

    assert first_plan.plan_sha256 == second_plan.plan_sha256
