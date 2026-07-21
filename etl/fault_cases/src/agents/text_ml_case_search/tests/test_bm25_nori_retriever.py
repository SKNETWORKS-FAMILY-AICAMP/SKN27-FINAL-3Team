from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.config import BM25_SEARCH_FIELDS
from etl.fault_cases.src.agents.text_ml_case_search.rag.bm25_nori_retriever import (
    build_bm25_query,
    search_bm25_nori,
)


class FakeElasticsearch:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.called_with: dict[str, Any] | None = None

    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.called_with = {"index": index, "body": body}
        return self.response


def test_build_bm25_query_uses_agent_search_policy() -> None:
    query = build_bm25_query(search_text="신호 없는 교차로 사고", top_k=7)

    multi_match = query["query"]["multi_match"]
    assert query["size"] == 7
    assert multi_match["fields"] == BM25_SEARCH_FIELDS
    assert multi_match["operator"] == "or"
    assert "search_text" in query["highlight"]["fields"]
    assert "chunk_text" in query["highlight"]["fields"]


def test_search_bm25_nori_returns_empty_for_blank_query() -> None:
    fake_es = FakeElasticsearch(response={})

    assert search_bm25_nori(es=fake_es, search_text="   ") == []
    assert fake_es.called_with is None


def test_search_bm25_nori_parses_review_case_hit() -> None:
    fake_es = FakeElasticsearch(
        response={
            "hits": {
                "hits": [
                    {
                        "_index": "review_case_chunks_bm25_nori_v1",
                        "_score": 12.5,
                        "_source": {
                            "review_case_id": "rc_001",
                            "review_no": "2017-032889",
                            "chunk_id": "rc_001:case_overview",
                            "chunk_type": "case_overview",
                            "case_title": "역주행사고",
                            "reference_chart_key": "249",
                            "decision_fault_ratio": "A 0 : B 100",
                            "signal_condition": "신호등 없음",
                            "road_feature": "중앙선 설치된 도로",
                            "chunk_text": "중앙선 침범 역주행 사고",
                            "search_text": "신호등 없음 중앙선 설치된 도로",
                        },
                        "highlight": {"chunk_text": ["<em>역주행</em> 사고"]},
                    }
                ]
            }
        }
    )

    results = search_bm25_nori(
        es=fake_es,
        search_text="중앙선 침범 역주행 사고",
        index_names=["review_case_chunks_bm25_nori_v1"],
        top_k=5,
    )

    assert fake_es.called_with is not None
    assert fake_es.called_with["index"] == "review_case_chunks_bm25_nori_v1"
    assert results[0]["retriever"] == "bm25_nori"
    assert results[0]["score_type"] == "bm25_score"
    assert results[0]["retriever_score"] == 12.5
    assert results[0]["review_no"] == "2017-032889"
    assert results[0]["chunk_id"] == "rc_001:case_overview"
    assert results[0]["source"]["reference_chart_key"] == "249"
    assert results[0]["highlight"]["chunk_text"]
