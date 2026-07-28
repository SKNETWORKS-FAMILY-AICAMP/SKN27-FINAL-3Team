from __future__ import annotations

import json
from pathlib import Path

from app.services.rag_seed_bundle import build_rag_seed_manifest, load_and_validate_rag_seed_manifest


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _build_verified_bundle(root: Path, *, reverse_legal_rows: bool):
    legal_rows: list[dict[str, object]] = [
        {
            "chunk_id": "law:1",
            "source_id": "road-traffic-act",
            "source_name": "도로교통법",
            "source_type": "law",
            "chunk_type": "article",
            "article_no": "제1조",
            "provision_text": "제2조의2에 따른 과태료의 기준을 정한다.",
            "normalized_text": "제2조의2에 따른 과태료의 기준을 정한다.",
            "source_url": "https://www.law.go.kr/법령/도로교통법",
            "enforce_date": "2020-01-01",
        },
        {
            "chunk_id": "law:2",
            "source_id": "road-traffic-act",
            "source_name": "도로교통법",
            "source_type": "law",
            "chunk_type": "article",
            "article_no": "제2조의2",
            "provision_text": "운전자는 안전운전 의무를 지켜야 한다.",
            "normalized_text": "운전자는 안전운전 의무를 지켜야 한다.",
            "source_url": "https://www.law.go.kr/법령/도로교통법",
            "enforce_date": "2020-01-01",
        },
    ]
    if reverse_legal_rows:
        legal_rows.reverse()
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
    paths = {}
    for role, rows in rows_by_role.items():
        relative_path = f"data/{role}.jsonl"
        _write_jsonl(root / relative_path, rows)
        paths[role] = relative_path
    manifest = root / "rag-seed-manifest.json"
    build_rag_seed_manifest(bundle_root=root, artifact_paths=paths, manifest_path=manifest)
    return load_and_validate_rag_seed_manifest(manifest)


def test_graph_seed_is_deterministic_for_verified_legal_chunks(tmp_path: Path) -> None:
    from app.services.law_graph_seed import build_law_graph_seed

    first = build_law_graph_seed(
        _build_verified_bundle(tmp_path / "first", reverse_legal_rows=False),
        dataset_version="2026-07-28-law-v1",
    )
    second = build_law_graph_seed(
        _build_verified_bundle(tmp_path / "second", reverse_legal_rows=True),
        dataset_version="2026-07-28-law-v1",
    )

    assert first.canonical_chunk_sha256 == second.canonical_chunk_sha256
    assert [row["chunk_id"] for row in first.chunks] == ["law:1", "law:2"]
    assert first.sources == second.sources
    assert first.versions == second.versions
    assert first.relations == second.relations
    assert first.versions[0]["source_version_id"] == "road-traffic-act:2020-01-01:active"
    assert first.relations == (
        {
            "relation_id": "rel:HAS_PENALTY:law:2:law:1",
            "relation_type": "HAS_PENALTY",
            "from_chunk_id": "law:2",
            "to_chunk_id": "law:1",
            "confidence": 0.9,
            "evidence_text": "Text-derived penalty reference",
            "created_at": "1970-01-01T00:00:00+00:00",
        },
        {
            "relation_id": "rel:RELATED_TO:law:1:law:2",
            "relation_type": "RELATED_TO",
            "from_chunk_id": "law:1",
            "to_chunk_id": "law:2",
            "confidence": 0.6,
            "evidence_text": "Text-derived article reference",
            "created_at": "1970-01-01T00:00:00+00:00",
        },
    )


def test_graph_seed_import_uses_bounded_merge_batches(tmp_path: Path) -> None:
    from app.services.law_graph_seed import build_law_graph_seed
    from etl.legal.export_neo4j import import_law_graph_seed

    seed = build_law_graph_seed(
        _build_verified_bundle(tmp_path / "bundle", reverse_legal_rows=False),
        dataset_version="2026-07-28-law-v1",
    )
    session = _FakeSession()

    totals = import_law_graph_seed(session, seed, batch_size=1)

    assert totals == {
        "legal_sources": 1,
        "law_versions": 1,
        "law_chunks": 2,
        "law_relations": 2,
    }
    assert all(len(call["rows"]) <= 1 for call in session.calls)
    assert any("MERGE (chunk:LawChunk" in call["query"] for call in session.calls)
    assert any("MERGE (fromNode)-[rel:HAS_PENALTY]" in call["query"] for call in session.calls)


class _FakeResult:
    def consume(self) -> None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, query: str, **params: object) -> _FakeResult:
        self.calls.append({"query": query, **params})
        return _FakeResult()
