from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.agent import run_text_ml_case_search
from etl.fault_cases.src.agents.text_ml_case_search.config import (
    FAULT_RATIO_PRECEDENT_INDEX,
    REVIEW_CASE_INDEX,
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


def test_agent_v2_output_includes_review_case_and_precedent_source_summary() -> None:
    fake_es = FakeElasticsearch()

    result = run_text_ml_case_search(
        {
            "session_id": "s1",
            "message_id": "m1",
            "job_id": "j1",
            "node_code": "text_ml_case_search",
            "query_text": "lane change fault ratio",
            "insurer_claim": {
                "claimed_ratio": "70:30",
                "reason_text": "insurer says lane-changing vehicle has larger fault",
            },
        },
        es_client=fake_es,
    )

    structured = result["structured_result"]
    source_summary = structured["source_summary"]

    assert result["status"] == "success"
    assert [call["index"] for call in fake_es.calls] == [
        REVIEW_CASE_INDEX,
        FAULT_RATIO_PRECEDENT_INDEX,
    ]
    assert source_summary["active_sources"] == ["review_case", "fault_ratio_precedent"]
    assert source_summary["source_counts"] == {
        "review_case": 1,
        "fault_ratio_precedent": 1,
    }
    assert source_summary["final_top_k"] == 10
    assert {item["source_type"] for item in result["evidence"]} == {
        "review_case",
        "fault_ratio_precedent",
    }
    assert any(
        item["source_type"] == "fault_ratio_precedent"
        and item["case_number"] == "2022da287284"
        for item in structured["display_evidence"]
    )
    assert structured["rag_debug"]["retriever"] == "unified_bm25_nori"
    assert structured["insurer_claim_review"]["reference_evidence_count"] == 2
