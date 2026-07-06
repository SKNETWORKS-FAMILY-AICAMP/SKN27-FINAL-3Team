from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.rag.retrieval_pipeline import (
    run_review_case_bm25_pipeline,
    select_search_text,
)


class FakeElasticsearch:
    def __init__(self, hits: list[dict[str, Any]]) -> None:
        self.hits = hits
        self.called_with: dict[str, Any] | None = None

    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.called_with = {"index": index, "body": body}
        return {"hits": {"hits": self.hits}}


def test_select_search_text_uses_requested_variant() -> None:
    selected = select_search_text(
        search_text={
            "schema_search_text": "schema query",
            "natural_query_text": "natural query",
        },
        search_variant="natural_query_text",
    )

    assert selected == {
        "search_variant": "natural_query_text",
        "search_text": "natural query",
    }


def test_select_search_text_falls_back_to_schema_text() -> None:
    selected = select_search_text(
        search_text={
            "schema_search_text": "schema query",
            "natural_query_text": "natural query",
        },
        search_variant="missing_variant",
    )

    assert selected == {
        "search_variant": "schema_search_text",
        "search_text": "schema query",
    }


def test_pipeline_returns_empty_without_search_text() -> None:
    fake_es = FakeElasticsearch(hits=[])

    result = run_review_case_bm25_pipeline(
        es=fake_es,
        search_text={},
        top_k=5,
    )

    assert fake_es.called_with is None
    assert result["raw_hit_count"] == 0
    assert result["mapped_evidence_count"] == 0
    assert result["valid_evidence_count"] == 0
    assert result["evidence"] == []


def test_pipeline_searches_maps_and_validates_evidence() -> None:
    fake_es = FakeElasticsearch(
        hits=[
            {
                "_index": "review_case_chunks_bm25_nori_v1",
                "_score": 11.5,
                "_source": {
                    "review_case_id": "rc_001",
                    "review_no": "2017-032889",
                    "chunk_id": "rc_001:case_overview",
                    "chunk_type": "case_overview",
                    "case_title": "case title",
                    "chunk_text": "valid chunk text " * 5,
                    "search_text": "schema query",
                },
            },
            {
                "_index": "review_case_chunks_bm25_nori_v1",
                "_score": 8.1,
                "_source": {
                    "review_case_id": "rc_002",
                    "chunk_id": "rc_002:short",
                    "case_title": "short case",
                    "chunk_text": "short",
                    "search_text": "schema query",
                },
            },
        ]
    )

    result = run_review_case_bm25_pipeline(
        es=fake_es,
        search_text={"schema_search_text": "schema query"},
        index_names=["review_case_chunks_bm25_nori_v1"],
        top_k=5,
        min_text_len=20,
    )

    assert fake_es.called_with is not None
    assert fake_es.called_with["index"] == "review_case_chunks_bm25_nori_v1"
    assert result["search_variant"] == "schema_search_text"
    assert result["raw_hit_count"] == 2
    assert result["mapped_evidence_count"] == 2
    assert result["valid_evidence_count"] == 1
    assert result["validation_report"]["invalid_reason_counts"] == {
        "chunk_text_too_short": 1
    }
    assert result["evidence"][0]["source_reference"] == "review_case_db:rc_001#rc_001:case_overview"
