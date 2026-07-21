from __future__ import annotations

from etl.fault_cases.src.agents.text_ml_case_search.rag.evidence_mapper import (
    map_review_case_hit_to_evidence,
    map_review_case_hits_to_evidence,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.source_reference import (
    build_review_case_source_reference,
)


def test_build_review_case_source_reference_uses_stable_fallbacks() -> None:
    assert (
        build_review_case_source_reference(
            review_case_id="rc_001",
            review_no="2017-032889",
            chunk_id="rc_001:case_overview",
        )
        == "review_case_db:rc_001#rc_001:case_overview"
    )

    assert (
        build_review_case_source_reference(
            review_case_id=None,
            review_no="2017-032889",
            chunk_id=None,
        )
        == "review_case_db:2017-032889#unknown_chunk"
    )


def test_map_review_case_hit_to_evidence_maps_core_fields() -> None:
    evidence = map_review_case_hit_to_evidence(
        {
            "rank": 1,
            "retriever": "bm25_nori",
            "score_type": "bm25_score",
            "retriever_score": 11.7,
            "index": "review_case_chunks_bm25_nori_v1",
            "review_case_id": "rc_001",
            "review_no": "2017-032889",
            "chunk_id": "rc_001:case_overview",
            "chunk_type": "case_overview",
            "case_title": "역주행사고",
            "reference_chart_key": "249",
            "decision_fault_ratio": "A 0 : B 100",
            "claimant_final_ratio": "0",
            "respondent_final_ratio": "100",
            "signal_condition": "신호등 없음",
            "road_feature": "중앙선 설치된 도로",
            "standard_a_behavior": "직진",
            "standard_b_behavior": "중앙선 침범 역주행",
            "chunk_text": "중앙선 침범 역주행 사고",
            "search_text": "신호등 없음 중앙선 설치된 도로",
            "highlight": {"chunk_text": ["<em>역주행</em> 사고"]},
            "source": {},
        }
    )

    metadata = evidence["metadata"]
    assert evidence["source_type"] == "review_case"
    assert evidence["title"] == "역주행사고"
    assert evidence["source_reference"] == "review_case_db:rc_001#rc_001:case_overview"
    assert evidence["chunk_text"] == "중앙선 침범 역주행 사고"
    assert evidence["confidence"] is None
    assert metadata["score"] == 11.7
    assert metadata["score_type"] == "bm25_score"
    assert metadata["reference_chart_key"] == "249"
    assert metadata["decision_fault_ratio"] == "A 0 : B 100"
    assert metadata["standard_context"]["signal_condition"] == "신호등 없음"
    assert metadata["standard_context"]["standard_b_behavior"] == "중앙선 침범 역주행"
    assert metadata["matched_facts"] == []
    assert metadata["different_facts"] == []


def test_map_review_case_hit_to_evidence_falls_back_to_source() -> None:
    evidence = map_review_case_hit_to_evidence(
        {
            "rank": 2,
            "retriever_score": 8.2,
            "source": {
                "review_case_id": "rc_002",
                "chunk_id": "rc_002:decision_reason",
                "case_title": "신호위반사고",
                "chunk_text": "적색 신호 진입 사고",
            },
        }
    )

    assert evidence["title"] == "신호위반사고"
    assert evidence["source_reference"] == "review_case_db:rc_002#rc_002:decision_reason"
    assert evidence["chunk_text"] == "적색 신호 진입 사고"
    assert evidence["metadata"]["retriever"] == "bm25_nori"
    assert evidence["metadata"]["score_type"] == "bm25_score"


def test_map_review_case_hits_to_evidence_maps_list() -> None:
    evidence = map_review_case_hits_to_evidence(
        [
            {"source": {"review_case_id": "rc_001", "chunk_id": "c1"}},
            {"source": {"review_case_id": "rc_002", "chunk_id": "c2"}},
        ]
    )

    assert len(evidence) == 2
    assert evidence[0]["source_reference"] == "review_case_db:rc_001#c1"
    assert evidence[1]["source_reference"] == "review_case_db:rc_002#c2"
