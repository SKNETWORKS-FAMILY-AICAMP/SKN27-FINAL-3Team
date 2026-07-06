from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.config import (
    FAULT_RATIO_PRECEDENT_BM25_FIELDS,
    FAULT_RATIO_PRECEDENT_INDEX,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.fault_ratio_precedent_retriever import (
    build_fault_ratio_precedent_bm25_query,
    search_fault_ratio_precedent_bm25,
)


class FakeElasticsearch:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.called_with: dict[str, Any] | None = None

    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.called_with = {"index": index, "body": body}
        return self.response


def test_build_fault_ratio_precedent_bm25_query_uses_v2_search_policy() -> None:
    query = build_fault_ratio_precedent_bm25_query(
        search_text="lane change fault ratio precedent",
        top_k=7,
    )

    multi_match = query["query"]["multi_match"]
    assert query["size"] == 7
    assert multi_match["fields"] == FAULT_RATIO_PRECEDENT_BM25_FIELDS
    assert multi_match["type"] == "best_fields"
    assert multi_match["operator"] == "or"
    assert "search_text" in query["highlight"]["fields"]
    assert "chunk_text" in query["highlight"]["fields"]


def test_search_fault_ratio_precedent_bm25_returns_empty_for_blank_query() -> None:
    fake_es = FakeElasticsearch(response={})

    assert search_fault_ratio_precedent_bm25(es=fake_es, search_text="   ") == []
    assert fake_es.called_with is None


def test_search_fault_ratio_precedent_bm25_parses_hit() -> None:
    fake_es = FakeElasticsearch(
        response={
            "hits": {
                "hits": [
                    {
                        "_index": FAULT_RATIO_PRECEDENT_INDEX,
                        "_score": 31.5,
                        "_source": {
                            "case_id": "616249",
                            "chunk_id": "616249:structured_1500_250:0001",
                            "chunk_index": 1,
                            "chunk_type": "fault_ratio_evidence",
                            "chunk_strategy": "structured_1500_250",
                            "case_name": "lane change fault ratio precedent",
                            "case_number": "2022da287284",
                            "court_name": "Supreme Court",
                            "decision_date": "2025-05-15",
                            "chunk_text": "valid precedent chunk text " * 5,
                            "search_text": "lane change fault ratio",
                        },
                        "highlight": {"chunk_text": ["<em>fault ratio</em>"]},
                    }
                ]
            }
        }
    )

    results = search_fault_ratio_precedent_bm25(
        es=fake_es,
        search_text="lane change fault ratio",
        top_k=5,
    )

    assert fake_es.called_with is not None
    assert fake_es.called_with["index"] == FAULT_RATIO_PRECEDENT_INDEX
    assert results[0]["retriever"] == "fault_ratio_precedent_bm25_nori"
    assert results[0]["score_type"] == "bm25_score"
    assert results[0]["retriever_score"] == 31.5
    assert results[0]["case_id"] == "616249"
    assert results[0]["case_number"] == "2022da287284"
    assert results[0]["highlight"]["chunk_text"]
