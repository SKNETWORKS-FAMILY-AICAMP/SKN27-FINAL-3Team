from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from django.core.management.base import CommandError

from app.services.rag_seed_bundle import (
    REQUIRED_RAG_SEED_ROLES,
    RagSeedValidationError,
    build_rag_seed_manifest,
    iter_rag_seed_jsonl,
    load_and_validate_rag_seed_manifest,
)
from backend.chatbot.management.commands import load_production_rag_seed
from backend.chatbot.management.commands import load_legal_rag_pgvector
from backend.chatbot.management.commands import smoke_text_ml_case_search
from backend.chatbot.management.commands import (
    build_production_rag_seed_manifest,
    verify_production_rag_seed_manifest,
)
from etl.legal.export_sql import export_to_sql
from etl.legal.load_sql import _embedding_db_row


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _valid_rows() -> dict[str, list[dict[str, object]]]:
    return {
        "legal_chunks": [
            {
                "chunk_id": "law-1",
                "source_id": "road-traffic-act",
                "source_name": "도로교통법",
                "source_type": "law",
                "chunk_type": "article",
                "source_url": "https://www.law.go.kr/example/road-traffic-act",
                "enforce_date": "2020-01-01",
                "provision_text": "신호를 준수해야 한다.",
                "normalized_text": "신호 준수",
            }
        ],
        "legal_embeddings": [
            {
                "chunk_id": "law-1",
                "embedding_vector": [1.0] + [0.0] * 1023,
                "embedding_provider": "sentence-transformers",
                "embedding_model": "intfloat/multilingual-e5-large",
                "embedding_dimensions": 1024,
            }
        ],
        "review_case_chunks": [
            {
                "review_case_id": "review-1",
                "chunk_id": "review-1-summary",
                "chunk_text": "교차로에서 직진 차량과 우측 진입 차량이 충돌한 심의 사례의 사실관계와 구체적인 판단 근거입니다.",
                "search_text": "교차로 직진 차량 우측 진입 차량 충돌 심의 사례 사실관계 판단 근거",
            }
        ],
        "precedent_fault_ratio_chunks": [
            {
                "case_id": "precedent-1",
                "chunk_id": "precedent-1-0",
                "chunk_index": 0,
                "chunk_type": "holding",
                "chunk_strategy": "structured",
                "chunk_text": "차선을 변경하던 차량과 후행 직진 차량이 충돌한 판례의 사실관계와 과실비율 판단 근거입니다.",
                "search_text": "차선 변경 후행 직진 차량 충돌 판례 사실관계 과실비율 판단 근거",
            }
        ],
    }


def _write_valid_bundle(tmp_path: Path) -> Path:
    rows_by_role = _valid_rows()
    relative_paths: dict[str, str] = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path
    manifest_path = tmp_path / "rag-seed-manifest.json"
    build_rag_seed_manifest(
        bundle_root=tmp_path,
        artifact_paths=relative_paths,
        manifest_path=manifest_path,
    )
    return manifest_path


def test_build_and_validate_manifest_with_exact_four_roles(tmp_path: Path) -> None:
    manifest_path = _write_valid_bundle(tmp_path)

    bundle = load_and_validate_rag_seed_manifest(manifest_path)

    assert bundle.contract_version == "production_rag_seed_manifest.v1"
    assert set(bundle.artifacts) == set(REQUIRED_RAG_SEED_ROLES)
    assert bundle.artifacts["legal_embeddings"].row_count == 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [item["role"] for item in manifest["artifacts"]] == list(REQUIRED_RAG_SEED_ROLES)


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda items: items[:-1], "exactly"),
        (lambda items: items + [dict(items[0])], "duplicate"),
        (
            lambda items: items[:-1] + [{**items[-1], "role": "unexpected"}],
            "exactly",
        ),
    ],
)
def test_manifest_rejects_missing_duplicate_or_unknown_roles(
    tmp_path: Path,
    mutate,
    expected: str,
) -> None:
    manifest_path = _write_valid_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"] = mutate(manifest["artifacts"])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RagSeedValidationError, match=expected):
        load_and_validate_rag_seed_manifest(manifest_path)


@pytest.mark.parametrize("unsafe_path", ["../outside.jsonl", "/tmp/data.jsonl", "C:/data.jsonl", "data\\file.jsonl"])
def test_manifest_rejects_unsafe_artifact_paths(tmp_path: Path, unsafe_path: str) -> None:
    manifest_path = _write_valid_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["path"] = unsafe_path
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RagSeedValidationError, match="safe relative"):
        load_and_validate_rag_seed_manifest(manifest_path)


@pytest.mark.parametrize("field", ["sha256", "bytes", "row_count"])
def test_manifest_rejects_integrity_metadata_mismatch(tmp_path: Path, field: str) -> None:
    manifest_path = _write_valid_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = manifest["artifacts"][0]
    artifact[field] = "0" * 64 if field == "sha256" else int(artifact[field]) + 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RagSeedValidationError, match=field):
        load_and_validate_rag_seed_manifest(manifest_path)


def test_manifest_rejects_empty_jsonl(tmp_path: Path) -> None:
    manifest_path = _write_valid_bundle(tmp_path)
    empty_path = tmp_path / "data/legal_chunks.jsonl"
    empty_path.write_text("\n", encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    first = manifest["artifacts"][0]
    first["bytes"] = empty_path.stat().st_size
    first["sha256"] = hashlib.sha256(empty_path.read_bytes()).hexdigest()
    first["row_count"] = 0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RagSeedValidationError, match="must not be empty"):
        load_and_validate_rag_seed_manifest(manifest_path)


def test_manifest_builder_rejects_nested_manifest_path(tmp_path: Path) -> None:
    rows_by_role = _valid_rows()
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match="bundle root"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "manifests/rag-seed-manifest.json",
        )


@pytest.mark.parametrize(
    ("role", "invalid_row", "expected"),
    [
        ("legal_chunks", {"chunk_id": "law-1"}, "source_id"),
        ("review_case_chunks", {"chunk_id": "review-1", "chunk_text": ""}, "review_case_id"),
        (
            "precedent_fault_ratio_chunks",
            {
                "case_id": "p-1",
                "chunk_id": "p-1-0",
                "chunk_type": "holding",
                "chunk_strategy": "structured",
                "chunk_text": "text",
            },
            "chunk_index",
        ),
    ],
)
def test_manifest_rejects_jsonl_schema_violations(
    tmp_path: Path,
    role: str,
    invalid_row: dict[str, object],
    expected: str,
) -> None:
    rows_by_role = _valid_rows()
    rows_by_role[role] = [invalid_row]
    relative_paths = {}
    for current_role, rows in rows_by_role.items():
        relative_path = f"data/{current_role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[current_role] = relative_path

    with pytest.raises(RagSeedValidationError, match=expected):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


@pytest.mark.parametrize("dimensions", [0, 1023, 1025])
def test_legal_embeddings_must_have_exactly_1024_dimensions(tmp_path: Path, dimensions: int) -> None:
    rows_by_role = _valid_rows()
    rows_by_role["legal_embeddings"][0]["embedding_vector"] = [0.0] * dimensions
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match="1024"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


def test_legal_embeddings_require_an_explicit_provider(tmp_path: Path) -> None:
    rows_by_role = _valid_rows()
    rows_by_role["legal_embeddings"][0].pop("embedding_provider")
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match="embedding_provider"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("embedding_provider", "Sentence-Transformers"),
        ("embedding_model", " intfloat/multilingual-e5-large "),
    ],
)
def test_legal_embeddings_require_canonical_space_metadata(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    rows_by_role = _valid_rows()
    rows_by_role["legal_embeddings"][0][field] = value
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match=field):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


def test_legal_chunks_require_source_url(tmp_path: Path) -> None:
    rows_by_role = _valid_rows()
    rows_by_role["legal_chunks"][0].pop("source_url")
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match="source_url"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


def test_legal_chunks_reject_source_type_outside_legal_umbrella(tmp_path: Path) -> None:
    rows_by_role = _valid_rows()
    rows_by_role["legal_chunks"][0]["source_type"] = "statute"
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match="source_type"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


@pytest.mark.parametrize(
    ("role", "field", "limit"),
    [
        ("legal_chunks", "chunk_id", 255),
        ("legal_chunks", "source_id", 100),
        ("legal_chunks", "source_name", 255),
        ("legal_chunks", "source_type", 50),
        ("legal_chunks", "chunk_type", 50),
        ("legal_chunks", "article_no", 50),
        ("legal_chunks", "appendix_no", 50),
        ("legal_chunks", "form_no", 50),
        ("legal_embeddings", "chunk_id", 255),
        ("legal_embeddings", "embedding_provider", 50),
        ("legal_embeddings", "embedding_model", 255),
    ],
)
def test_manifest_enforces_postgresql_varchar_caps(
    tmp_path: Path,
    role: str,
    field: str,
    limit: int,
) -> None:
    rows_by_role = _valid_rows()
    rows_by_role[role][0][field] = "x" * (limit + 1)
    relative_paths = {}
    for current_role, rows in rows_by_role.items():
        relative_path = f"data/{current_role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[current_role] = relative_path

    with pytest.raises(RagSeedValidationError, match=rf"{field}.*{limit}"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


@pytest.mark.parametrize("provider", ["hash", "mock", "fake", "custom-provider"])
def test_production_manifest_rejects_synthetic_or_unsupported_embedding_providers(
    tmp_path: Path,
    provider: str,
) -> None:
    rows_by_role = _valid_rows()
    rows_by_role["legal_embeddings"][0]["embedding_provider"] = provider
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match="supported production provider"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


@pytest.mark.parametrize(
    "source_url",
    [
        "offline://law/road-traffic-act",
        "http://www.law.go.kr/법령/도로교통법",
        "https://localhost/law",
        "https://127.0.0.1/law",
        "https://[::1]/law",
        "https://legal-source.test/law",
        "https://legal-source.invalid/law",
        "https://legal-source.example/law",
        "https://example.org/law",
        "https://www.example.com/law",
        "https://offline/law",
        "https://user:secret@www.law.go.kr/law",
        "https://www.law.go.kr/law?X-Amz-Credential=AKIA_TEST&X-Amz-Signature=secret",
        "/relative/law",
    ],
)
def test_production_manifest_requires_absolute_non_placeholder_https_legal_urls(
    tmp_path: Path,
    source_url: str,
) -> None:
    rows_by_role = _valid_rows()
    rows_by_role["legal_chunks"][0]["source_url"] = source_url
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match="source_url.*HTTPS"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("is_searchable", "false"),
        ("is_searchable", False),
        ("domain_tags", "traffic"),
        ("domain_tags", ["traffic", ""]),
    ],
)
def test_legal_chunks_reject_unsafe_optional_search_fields(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    rows_by_role = _valid_rows()
    rows_by_role["legal_chunks"][0][field] = value
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match=field):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


@pytest.mark.parametrize("enforce_date", [None, "", "20200101", "2026-02-30"])
def test_legal_chunks_require_exact_valid_enforce_date(
    tmp_path: Path,
    enforce_date: object,
) -> None:
    rows_by_role = _valid_rows()
    rows_by_role["legal_chunks"][0]["enforce_date"] = enforce_date
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match="enforce_date"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


@pytest.mark.parametrize("expire_date", ["20200101", "2019-12-31", "2026-02-30"])
def test_legal_chunks_reject_invalid_or_reversed_expire_date(
    tmp_path: Path,
    expire_date: str,
) -> None:
    rows_by_role = _valid_rows()
    rows_by_role["legal_chunks"][0]["expire_date"] = expire_date
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match="expire_date"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


def test_legal_embeddings_reject_zero_norm_vector(tmp_path: Path) -> None:
    rows_by_role = _valid_rows()
    rows_by_role["legal_embeddings"][0]["embedding_vector"] = [0.0] * 1024
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match="non-zero"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


def test_legal_embeddings_reject_overflowing_numeric_values_as_validation_error(
    tmp_path: Path,
) -> None:
    rows_by_role = _valid_rows()
    rows_by_role["legal_embeddings"][0]["embedding_vector"][0] = 10**1000
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match="finite numbers"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


def test_legal_embeddings_reject_values_outside_finite_float32_range(
    tmp_path: Path,
) -> None:
    rows_by_role = _valid_rows()
    rows_by_role["legal_embeddings"][0]["embedding_vector"][0] = 1e100
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match="finite numbers.*float32"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


def test_legal_embeddings_reject_vectors_that_underflow_to_all_zero_float32(
    tmp_path: Path,
) -> None:
    rows_by_role = _valid_rows()
    rows_by_role["legal_embeddings"][0]["embedding_vector"] = [1e-50] * 1024
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match="non-zero.*float32"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


def test_legal_embeddings_require_one_provider_model_dimension_space(tmp_path: Path) -> None:
    rows_by_role = _valid_rows()
    second_chunk = dict(rows_by_role["legal_chunks"][0])
    second_chunk["chunk_id"] = "law-2"
    rows_by_role["legal_chunks"].append(second_chunk)
    second_embedding = dict(rows_by_role["legal_embeddings"][0])
    second_embedding["chunk_id"] = "law-2"
    second_embedding["embedding_model"] = "different-model"
    rows_by_role["legal_embeddings"].append(second_embedding)
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    with pytest.raises(RagSeedValidationError, match="embedding space"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


def test_manifest_records_verified_embedding_space(tmp_path: Path) -> None:
    manifest_path = _write_valid_bundle(tmp_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle = load_and_validate_rag_seed_manifest(manifest_path)

    expected = {
        "provider": "sentence-transformers",
        "model": "intfloat/multilingual-e5-large",
        "dimensions": 1024,
    }
    assert manifest["embedding_space"] == expected
    assert bundle.embedding_space == expected


def test_manifest_rejects_embedding_space_metadata_tampering(tmp_path: Path) -> None:
    manifest_path = _write_valid_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["embedding_space"]["model"] = "different-model"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RagSeedValidationError, match="embedding space mismatch"):
        load_and_validate_rag_seed_manifest(manifest_path)


@pytest.mark.parametrize("role", ["review_case_chunks", "precedent_fault_ratio_chunks"])
def test_text_ml_seed_rejects_chunks_shorter_than_runtime_evidence_contract(
    tmp_path: Path,
    role: str,
) -> None:
    rows_by_role = _valid_rows()
    rows_by_role[role][0]["chunk_text"] = "너무 짧은 근거"
    relative_paths = {}
    for current_role, rows in rows_by_role.items():
        relative_path = f"data/{current_role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[current_role] = relative_path

    with pytest.raises(RagSeedValidationError, match="at least 50"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "rag-seed-manifest.json",
        )


def test_manifest_builder_rejects_manifest_target_colliding_with_an_artifact(
    tmp_path: Path,
) -> None:
    rows_by_role = _valid_rows()
    relative_paths = {
        "legal_chunks": "legal_chunks.jsonl",
        "legal_embeddings": "data/legal_embeddings.jsonl",
        "review_case_chunks": "data/review_case_chunks.jsonl",
        "precedent_fault_ratio_chunks": "data/precedent_fault_ratio_chunks.jsonl",
    }
    for role, rows in rows_by_role.items():
        _write_jsonl(tmp_path / relative_paths[role], rows)
    original_artifact = (tmp_path / "legal_chunks.jsonl").read_bytes()

    with pytest.raises(RagSeedValidationError, match="manifest.*artifact"):
        build_rag_seed_manifest(
            bundle_root=tmp_path,
            artifact_paths=relative_paths,
            manifest_path=tmp_path / "legal_chunks.jsonl",
        )

    assert (tmp_path / "legal_chunks.jsonl").read_bytes() == original_artifact


def test_dry_run_validates_without_external_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = load_and_validate_rag_seed_manifest(_write_valid_bundle(tmp_path))

    def unexpected_write(*args, **kwargs):
        raise AssertionError("dry-run must not connect to an external service")

    monkeypatch.setattr(load_production_rag_seed, "_load_legal_pgvector", unexpected_write)

    result = load_production_rag_seed.execute_rag_seed_load(
        bundle,
        dry_run=True,
        replace_legal=False,
        batch_size=50,
    )

    assert result["status"] == "validated"
    assert result["external_writes"] is False
    assert result["artifacts"] == {role: 1 for role in REQUIRED_RAG_SEED_ROLES}
    assert result["targets"] == {
        "legal": "postgresql_pgvector",
        "review_case": "source_specific_pgvector_loader_required",
        "precedent_fault_ratio": "source_specific_pgvector_loader_required",
    }
    assert any(
        "verify_pgvector_rag_readiness" in condition
        for condition in result["preconditions"]
    )


def test_live_load_calls_all_existing_load_paths_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = load_and_validate_rag_seed_manifest(_write_valid_bundle(tmp_path))
    calls: list[tuple[object, bool, bool, int]] = []

    def load_legal(
        current_bundle,
        *,
        replace: bool,
        skip_schema: bool,
        batch_size: int,
    ):
        calls.append((current_bundle, replace, skip_schema, batch_size))
        return {"loaded": 1}

    monkeypatch.setattr(load_production_rag_seed, "_load_legal_pgvector", load_legal)

    result = load_production_rag_seed.execute_rag_seed_load(
        bundle,
        dry_run=False,
        replace_legal=True,
        skip_legal_schema=True,
        batch_size=25,
    )

    assert len(calls) == 1
    assert calls[0][0].manifest_path == bundle.manifest_path
    assert calls[0][0].embedding_space == bundle.embedding_space
    assert {
        role: artifact.sha256 for role, artifact in calls[0][0].artifacts.items()
    } == {role: artifact.sha256 for role, artifact in bundle.artifacts.items()}
    assert calls[0][1:] == (True, True, 25)
    assert result["status"] == "loaded"
    assert result["external_writes"] is True


def test_live_load_revalidates_bundle_before_external_writes(tmp_path: Path) -> None:
    bundle = load_and_validate_rag_seed_manifest(_write_valid_bundle(tmp_path))
    bundle.artifacts["legal_chunks"].path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(RagSeedValidationError, match="bytes mismatch|sha256 mismatch"):
        load_production_rag_seed.execute_rag_seed_load(
            bundle,
            dry_run=False,
            replace_legal=False,
            batch_size=10,
        )


def test_live_load_reuses_revalidated_read_only_bundle_without_snapshot_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = load_and_validate_rag_seed_manifest(_write_valid_bundle(tmp_path))
    copied_paths: list[Path] = []

    def unexpected_snapshot(*_args, **_kwargs):
        copied_paths.append(Path("snapshot"))
        raise AssertionError("read-only seed loads must not create a full snapshot")

    def load_legal(current_bundle, *, replace: bool, batch_size: int):
        assert replace is False
        assert batch_size == 10
        assert current_bundle.manifest_path == bundle.manifest_path
        assert current_bundle.artifacts["legal_chunks"].path == bundle.artifacts[
            "legal_chunks"
        ].path
        return {"loaded": 1}

    monkeypatch.setattr(
        load_production_rag_seed,
        "TemporaryDirectory",
        unexpected_snapshot,
        raising=False,
    )
    monkeypatch.setattr(load_production_rag_seed, "_load_legal_pgvector", load_legal)

    result = load_production_rag_seed.execute_rag_seed_load(
        bundle,
        dry_run=False,
        replace_legal=False,
        batch_size=10,
    )

    assert result["status"] == "loaded"
    assert copied_paths == []


def test_live_load_rejects_self_consistent_bundle_replacement(tmp_path: Path) -> None:
    manifest_path = _write_valid_bundle(tmp_path)
    approved_bundle = load_and_validate_rag_seed_manifest(manifest_path)
    replacement_rows = _valid_rows()
    replacement_rows["legal_chunks"][0]["chunk_id"] = "law-replacement"
    replacement_rows["legal_embeddings"][0]["chunk_id"] = "law-replacement"
    relative_paths = {}
    for role, rows in replacement_rows.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path
    build_rag_seed_manifest(
        bundle_root=tmp_path,
        artifact_paths=relative_paths,
        manifest_path=manifest_path,
    )

    with pytest.raises(load_production_rag_seed.SeedLoadError, match="changed after approval"):
        load_production_rag_seed.execute_rag_seed_load(
            approved_bundle,
            dry_run=False,
            replace_legal=False,
            batch_size=10,
        )


def test_legal_pgvector_load_rejects_manifest_count_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = load_and_validate_rag_seed_manifest(_write_valid_bundle(tmp_path))

    def fake_call_command(*_args, **kwargs):
        kwargs["stdout"].write(
            json.dumps(
                {
                    "loaded": {"chunks": 1, "embeddings": 0},
                    "counts": {"law_chunks": 1, "law_embeddings": 0},
                }
            )
        )

    monkeypatch.setattr(load_production_rag_seed, "call_command", fake_call_command)

    with pytest.raises(load_production_rag_seed.SeedLoadError, match="count did not match"):
        load_production_rag_seed._load_legal_pgvector(bundle, replace=False, batch_size=50)


def test_legal_pgvector_load_rejects_post_load_table_count_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = load_and_validate_rag_seed_manifest(_write_valid_bundle(tmp_path))

    def fake_call_command(*_args, **kwargs):
        kwargs["stdout"].write(
            json.dumps(
                {
                    "loaded": {"chunks": 1, "embeddings": 1},
                    "counts": {
                        "law_chunks": 2,
                        "searchable_law_chunks": 2,
                        "law_embeddings": 2,
                    },
                }
            )
        )

    monkeypatch.setattr(load_production_rag_seed, "call_command", fake_call_command)

    with pytest.raises(load_production_rag_seed.SeedLoadError, match="table count"):
        load_production_rag_seed._load_legal_pgvector(
            bundle,
            replace=True,
            batch_size=50,
        )


@pytest.mark.parametrize(
    "malformed_role",
    [["legal_chunks"], {"name": "legal_chunks"}],
)
def test_manifest_rejects_non_scalar_roles_as_validation_errors(
    tmp_path: Path,
    malformed_role: object,
) -> None:
    manifest_path = _write_valid_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["role"] = malformed_role
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RagSeedValidationError, match="artifact role"):
        load_and_validate_rag_seed_manifest(manifest_path)


def test_manifest_rejects_non_finite_json_number_as_validation_error(tmp_path: Path) -> None:
    manifest_path = _write_valid_bundle(tmp_path)
    raw_manifest = manifest_path.read_text(encoding="utf-8")
    raw_manifest = raw_manifest.replace('"row_count": 1', '"row_count": NaN', 1)
    manifest_path.write_text(raw_manifest, encoding="utf-8")

    with pytest.raises(RagSeedValidationError, match="valid UTF-8 JSON"):
        load_and_validate_rag_seed_manifest(manifest_path)


def test_build_and_verify_management_command_wrappers(tmp_path: Path) -> None:
    rows_by_role = _valid_rows()
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(tmp_path / relative_path, rows)
        relative_paths[role] = relative_path

    build_output = io.StringIO()
    build_production_rag_seed_manifest.Command(stdout=build_output).handle(
        bundle_root=str(tmp_path),
        manifest="rag-seed-manifest.json",
        legal_chunks=relative_paths["legal_chunks"],
        legal_embeddings=relative_paths["legal_embeddings"],
        review_case_chunks=relative_paths["review_case_chunks"],
        precedent_fault_ratio_chunks=relative_paths["precedent_fault_ratio_chunks"],
        format="json",
    )
    built = json.loads(build_output.getvalue())
    assert built["status"] == "built"
    assert built["artifacts"] == {role: 1 for role in REQUIRED_RAG_SEED_ROLES}

    verify_output = io.StringIO()
    verify_production_rag_seed_manifest.Command(stdout=verify_output).handle(
        manifest=str(tmp_path / "rag-seed-manifest.json"),
        format="json",
    )
    verified = json.loads(verify_output.getvalue())
    assert verified["status"] == "verified"
    assert verified["artifacts"] == built["artifacts"]


def test_build_command_resolves_relative_manifest_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_root = tmp_path / "bundle"
    rows_by_role = _valid_rows()
    relative_paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(bundle_root / relative_path, rows)
        relative_paths[role] = relative_path

    monkeypatch.chdir(tmp_path)
    output = io.StringIO()
    build_production_rag_seed_manifest.Command(stdout=output).handle(
        bundle_root="bundle",
        manifest="rag-seed-manifest.json",
        legal_chunks=relative_paths["legal_chunks"],
        legal_embeddings=relative_paths["legal_embeddings"],
        review_case_chunks=relative_paths["review_case_chunks"],
        precedent_fault_ratio_chunks=relative_paths["precedent_fault_ratio_chunks"],
        format="json",
    )

    result = json.loads(output.getvalue())
    expected_manifest = (bundle_root / "rag-seed-manifest.json").resolve()
    assert expected_manifest.is_file()
    assert result["manifest"] == str(expected_manifest)
    assert not (bundle_root / "bundle" / "rag-seed-manifest.json").exists()


def test_legal_loader_keeps_jsonl_memory_bounded_to_batch_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {
        "chunk_produced": 0,
        "chunk_consumed": 0,
        "embedding_produced": 0,
        "embedding_consumed": 0,
    }

    def bounded_rows(kind: str):
        for index in range(5):
            if state[f"{kind}_produced"] - state[f"{kind}_consumed"] >= 2:
                raise AssertionError(f"{kind} rows were materialized beyond batch_size")
            state[f"{kind}_produced"] += 1
            yield (f"{kind}-{index}",)

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def executemany(self, sql, rows):
            materialized = list(rows)
            kind = "embedding" if "law_embeddings" in sql else "chunk"
            state[f"{kind}_consumed"] += len(materialized)

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(load_legal_rag_pgvector, "connection", FakeConnection())
    monkeypatch.setattr(load_legal_rag_pgvector, "_chunk_rows", lambda _path: bounded_rows("chunk"))
    monkeypatch.setattr(
        load_legal_rag_pgvector,
        "_embedding_rows",
        lambda _path: bounded_rows("embedding"),
    )

    result = load_legal_rag_pgvector._load_jsonl_artifacts(
        chunks_path=tmp_path / "chunks.jsonl",
        embeddings_path=tmp_path / "embeddings.jsonl",
        batch_size=2,
    )

    assert result == {"chunks": 5, "embeddings": 5}
    assert state == {
        "chunk_produced": 5,
        "chunk_consumed": 5,
        "embedding_produced": 5,
        "embedding_consumed": 5,
    }


def test_legal_replace_uses_app_role_delete_privileges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def execute(self, sql):
            statements.append(" ".join(sql.split()))

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(load_legal_rag_pgvector, "connection", FakeConnection())

    load_legal_rag_pgvector._delete_legal_rows()

    assert statements == [
        "DELETE FROM law_embeddings;",
        "DELETE FROM law_chunks;",
    ]


def test_legal_replace_rejects_inexact_counts_before_transaction_commit() -> None:
    with pytest.raises(CommandError, match="exact replacement"):
        load_legal_rag_pgvector._validate_replacement_counts(
            loaded={"chunks": 1, "embeddings": 1},
            counts={
                "law_chunks": 2,
                "searchable_law_chunks": 2,
                "law_embeddings": 2,
            },
        )


def test_legal_pgvector_loader_preserves_embedding_space(tmp_path: Path) -> None:
    embedding_path = tmp_path / "embeddings.jsonl"
    embedding = _valid_rows()["legal_embeddings"][0]
    _write_jsonl(embedding_path, [embedding])

    row = next(load_legal_rag_pgvector._embedding_rows(embedding_path))

    assert row[2:] == (
        "sentence-transformers",
        "intfloat/multilingual-e5-large",
        1024,
    )


def test_official_legal_etl_preserves_embedding_space_in_sql(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    embeddings_path = tmp_path / "embeddings.jsonl"
    output_path = tmp_path / "seed.sql"
    rows = _valid_rows()
    _write_jsonl(chunks_path, rows["legal_chunks"])
    _write_jsonl(embeddings_path, rows["legal_embeddings"])

    assert export_to_sql(str(chunks_path), str(embeddings_path), str(output_path)) == 0

    sql = output_path.read_text(encoding="utf-8")
    assert "embedding_vector vector(1024) NOT NULL" in sql
    assert "embedding_model VARCHAR(255) NOT NULL" in sql
    assert "embedding_dimensions INTEGER NOT NULL" in sql
    assert "intfloat/multilingual-e5-large" in sql
    assert "embedding_provider, embedding_model, embedding_dimensions" in sql

    db_row = _embedding_db_row(rows["legal_embeddings"][0], vector_dim=1024)
    assert db_row[2:] == (
        "sentence-transformers",
        "intfloat/multilingual-e5-large",
        1024,
    )


def test_all_new_legal_embedding_table_definitions_require_non_null_vectors() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = (root / "storage/schemas/law_db_schema.sql").read_text(encoding="utf-8")
    loader = (root / "etl/legal/load_sql.py").read_text(encoding="utf-8")

    assert "embedding_vector vector(1024) NOT NULL" in schema
    assert "embedding_vector vector({vector_dim}) NOT NULL" in loader


def test_text_ml_smoke_require_results_rejects_empty_pgvector_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke_text_ml_case_search,
        "execute_agent_node",
        lambda _payload: {
            "execution_mode": "sync",
            "adapter_context": {"execution_mode": "sync"},
            "agent_output": {
                "status": "success",
                "limitations": [],
                "structured_result": {
                    "retrieval": {
                        "adapter_source": "fault_ratio_knowledge_agent",
                        "backend": "unified_pgvector",
                    },
                    "similar_cases": [],
                    "recommended_evidence": [],
                },
            },
        },
    )

    with pytest.raises(CommandError, match="smoke failed"):
        smoke_text_ml_case_search.Command(stdout=io.StringIO()).handle(
            user_text="교차로 충돌",
            session_id="ses-rag-smoke",
            message_id="msg-rag-smoke",
            job_id="job-rag-smoke",
            require_pgvector=True,
            require_results=True,
            format="json",
        )


def test_law_search_uses_configured_runtime_rag_instead_of_hardcoded_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai.agents.law_ground_search import search as law_search
    from app.services import legal_rag_service
    from etl.legal import search as etl_search

    etl_calls = []

    def unexpected_etl_search(**kwargs):
        etl_calls.append(kwargs)
        raise AssertionError("law agent must not bypass configured runtime RAG")

    monkeypatch.setattr(
        etl_search,
        "search_laws",
        unexpected_etl_search,
    )
    monkeypatch.setattr(
        legal_rag_service,
        "search_legal_rag",
        lambda query, *, top_k, source_type, temporal_basis, scope: {
            "status": "ready",
                "backend": "postgres_pgvector",
            "query": query,
            "top_k": top_k,
            "results": [
                {
                    "source_reference": "law-runtime-1",
                    "source_type": source_type,
                    "source_name": "도로교통법",
                    "article": "제5조",
                    "summary": "신호 또는 지시에 따라야 한다.",
                    "provision_text": "모든 차마의 운전자는 신호 또는 지시에 따라야 한다.",
                    "matched_token_count": 3,
                    "query_token_count": 3,
                    "score": 1.0,
                }
            ],
        },
    )

    provisions = law_search.search_law_provisions(
        query_text="신호 지시 준수",
        article_refs=[],
        temporal_basis={},
        scope={},
    )

    assert provisions[0]["chunk_id"] == "law-runtime-1"
    assert provisions[0]["match_reason"] == "pgvector_similarity"
    assert etl_calls == []
