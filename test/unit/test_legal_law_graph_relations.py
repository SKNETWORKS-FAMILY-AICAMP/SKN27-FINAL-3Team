from __future__ import annotations

import json
from pathlib import Path

from ai.agents.law_ground_search.search import _expand_with_law_graph
from etl.legal.export_neo4j import import_legal_artifacts
from etl.legal.extract_extra_relations import build_extra_relations


def test_build_extra_relations_extracts_law_graph_edges():
    chunks = [
        {
            "chunk_id": "law:v1:article:제7조",
            "source_version_id": "law:v1",
            "chunk_type": "article",
            "article_no": "제7조",
            "provision_text": "제7조 원칙 조문",
        },
        {
            "chunk_id": "law:v1:article:제148의2조",
            "source_version_id": "law:v1",
            "chunk_type": "article",
            "article_no": "제148의2조",
            "provision_text": "제148의2조 본문",
        },
        {
            "chunk_id": "law:v1:article:제160조",
            "source_version_id": "law:v1",
            "chunk_type": "article",
            "article_no": "제160조",
            "provision_text": "제7조 및 제148조의2에 따른 과태료를 부과한다.",
        },
        {
            "chunk_id": "law:v1:article:제14조",
            "source_version_id": "law:v1",
            "chunk_type": "article",
            "article_no": "제14조",
            "provision_text": "다만 제7조에는 적용하지 아니한다.",
        },
        {
            "chunk_id": "law:v1:appendix:별표1",
            "source_version_id": "law:v1",
            "chunk_type": "appendix",
            "appendix_no": "별표1",
            "provision_text": "별표 1 내용",
        },
        {
            "chunk_id": "law:v1:article:제142조",
            "source_version_id": "law:v1",
            "chunk_type": "article",
            "article_no": "제142조",
            "provision_text": "별표 1에 따른다.",
        },
    ]

    relations = build_extra_relations(chunks)
    edges = {(row["relation_type"], row["from_chunk_id"], row["to_chunk_id"]) for row in relations}

    assert ("HAS_PENALTY", "law:v1:article:제7조", "law:v1:article:제160조") in edges
    assert ("HAS_PENALTY", "law:v1:article:제148의2조", "law:v1:article:제160조") in edges
    assert ("HAS_EXCEPTION", "law:v1:article:제7조", "law:v1:article:제14조") in edges
    assert ("HAS_APPENDIX", "law:v1:article:제142조", "law:v1:appendix:별표1") in edges
    assert ("RELATED_TO", "law:v1:article:제160조", "law:v1:article:제7조") in edges


def test_export_neo4j_imports_optional_extra_relations(tmp_path: Path):
    output_dir = tmp_path
    write_jsonl(
        output_dir / "normalized" / "legal_sources.jsonl",
        [{"source_id": "law", "source_name": "Test Law", "source_type": "law"}],
    )
    write_jsonl(
        output_dir / "normalized" / "legal_source_versions.jsonl",
        [{"source_version_id": "law:v1", "source_id": "law"}],
    )
    write_jsonl(
        output_dir / "chunks" / "law_chunks.jsonl",
        [
            {"chunk_id": "law:v1:article:제7조", "source_version_id": "law:v1"},
            {"chunk_id": "law:v1:article:제160조", "source_version_id": "law:v1"},
        ],
    )
    write_jsonl(
        output_dir / "relations" / "law_relations.jsonl",
        [
            {
                "relation_id": "rel:law:v1:HAS_ARTICLE:law:v1:article:제7조",
                "relation_type": "HAS_ARTICLE",
                "from_chunk_id": "law:v1",
                "to_chunk_id": "law:v1:article:제7조",
            }
        ],
    )
    write_jsonl(
        output_dir / "relations" / "law_extra_relations.jsonl",
        [
            {
                "relation_id": "rel:HAS_PENALTY:law:v1:article:제7조:law:v1:article:제160조",
                "relation_type": "HAS_PENALTY",
                "from_chunk_id": "law:v1:article:제7조",
                "to_chunk_id": "law:v1:article:제160조",
            }
        ],
    )

    session = FakeNeo4jSession()
    totals = import_legal_artifacts(session, output_dir, batch_size=10)

    assert totals["law_extra_relations"] == 1
    assert totals["law_relations"] == 2
    assert any("rel:HAS_PENALTY" in call["query"] for call in session.calls)


def test_expand_with_law_graph_records_relation_type():
    session = FakeLawGraphSession()
    result = _expand_with_law_graph(
        core_provisions=[{"chunk_id": "core", "score": 0.8}],
        article_refs=[],
        session=session,
        core_scores={"core": 0.8},
    )

    assert session.graph_params["relation_types"] == ["HAS_PENALTY", "HAS_APPENDIX", "HAS_EXCEPTION", "RELATED_TO"]
    assert result[1]["chunk_id"] == "expanded"
    assert result[1]["retrieval_score"] == 0.7200000000000001
    assert result[1]["match_reason"] == "graph_expansion:HAS_PENALTY"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class FakeNeo4jSession:
    def __init__(self):
        self.calls = []

    def run(self, query, **params):
        self.calls.append({"query": query, "params": params})
        return FakeResult()


class FakeLawGraphSession:
    def __init__(self):
        self.graph_params = None

    def run(self, query, **params):
        self.graph_params = params
        return [
            {
                "cid": "core",
                "relation_type": "HAS_PENALTY",
                "c2": {
                    "chunk_id": "expanded",
                    "source_ref": "law/v1/제160조",
                    "source_name": "Test Law",
                    "article_no": "제160조",
                    "appendix_no": None,
                    "article_title": "Penalty",
                    "provision_text": "Penalty text",
                    "source_type": "law",
                    "source_url": "https://example.test",
                },
            }
        ]


class FakeResult:
    def consume(self):
        return None
