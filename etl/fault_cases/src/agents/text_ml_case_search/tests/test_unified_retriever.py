from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.config import (
    FAULT_RATIO_PRECEDENT_INDEX,
    REVIEW_CASE_INDEX,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.unified_retriever import (
    run_unified_rag_pipeline,
)


class FakeElasticsearch:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"index": index, "body": body})
        if index == REVIEW_CASE_INDEX:
            return {
                "hits": {
                    "hits": [
                        {
                            "_index": REVIEW_CASE_INDEX,
                            "_score": 12.5,
                            "_source": {
                                "review_case_id": "rc_001",
                                "review_no": "2017-032889",
                                "chunk_id": "rc_001:case_overview",
                                "chunk_type": "case_overview",
                                "case_title": "review case title",
                                "decision_fault_ratio": "A 70 : B 30",
                                "chunk_text": "valid review case evidence text " * 5,
                                "search_text": "lane change fault ratio",
                            },
                        }
                    ]
                }
            }
        if index == FAULT_RATIO_PRECEDENT_INDEX:
            return {
                "hits": {
                    "hits": [
                        {
                            "_index": FAULT_RATIO_PRECEDENT_INDEX,
                            "_score": 31.5,
                            "_source": {
                                "case_id": "616249",
                                "chunk_id": "616249:structured_1500_250:0001",
                                "chunk_type": "fault_ratio_evidence",
                                "case_name": "precedent title",
                                "case_number": "2022da287284",
                                "court_name": "Supreme Court",
                                "decision_date": "2025-05-15",
                                "chunk_text": "valid precedent evidence text " * 5,
                                "search_text": "lane change fault ratio",
                            },
                        }
                    ]
                }
            }
        return {"hits": {"hits": []}}


def test_run_unified_rag_pipeline_searches_two_sources_and_builds_summary() -> None:
    fake_es = FakeElasticsearch()

    result = run_unified_rag_pipeline(
        es=fake_es,
        search_text={"schema_search_text": "lane change fault ratio"},
        top_k=5,
        min_text_len=20,
    )

    assert [call["index"] for call in fake_es.calls] == [
        REVIEW_CASE_INDEX,
        FAULT_RATIO_PRECEDENT_INDEX,
    ]
    assert result["retriever"] == "unified_bm25_nori"
    assert result["source_summary"]["source_counts"] == {
        "review_case": 1,
        "fault_ratio_precedent": 1,
    }
    assert result["source_summary"]["final_top_k"] == 10
    assert result["source_summary"]["merge_strategy"] == "source_quota"
    assert [item["source_type"] for item in result["evidence"]] == [
        "review_case",
        "fault_ratio_precedent",
    ]
    assert result["source_results"]["review_case"]["valid_evidence_count"] == 1
    assert result["source_results"]["fault_ratio_precedent"]["valid_evidence_count"] == 1


def test_run_unified_rag_pipeline_returns_empty_without_search_text() -> None:
    fake_es = FakeElasticsearch()

    result = run_unified_rag_pipeline(es=fake_es, search_text={})

    assert result["evidence"] == []
    assert result["source_summary"]["source_counts"] == {}
    assert result["source_results"]["review_case"]["valid_evidence_count"] == 0
    assert result["source_results"]["fault_ratio_precedent"]["valid_evidence_count"] == 0
