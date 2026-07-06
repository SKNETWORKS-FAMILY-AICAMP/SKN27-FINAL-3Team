from __future__ import annotations

from etl.fault_cases.src.agents.text_ml_case_search.rag.fault_ratio_precedent_evidence_mapper import (
    map_fault_ratio_precedent_hit_to_evidence,
    map_fault_ratio_precedent_hits_to_evidence,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.source_reference import (
    build_fault_ratio_precedent_source_reference,
)


def test_build_fault_ratio_precedent_source_reference_uses_stable_fallbacks() -> None:
    assert (
        build_fault_ratio_precedent_source_reference(
            case_id="616249",
            case_number="2022da287284",
            chunk_id="616249:structured_1500_250:0001",
        )
        == "fault_ratio_precedent_db:616249#616249:structured_1500_250:0001"
    )

    assert (
        build_fault_ratio_precedent_source_reference(
            case_id=None,
            case_number="2022da287284",
            chunk_id=None,
        )
        == "fault_ratio_precedent_db:2022da287284#unknown_chunk"
    )


def test_map_fault_ratio_precedent_hit_to_evidence_maps_core_fields() -> None:
    evidence = map_fault_ratio_precedent_hit_to_evidence(
        {
            "rank": 1,
            "retriever": "fault_ratio_precedent_bm25_nori",
            "score_type": "bm25_score",
            "retriever_score": 31.5,
            "index": "precedent_fault_ratio_chunks_bm25_nori_v1",
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
            "highlight": {"chunk_text": ["<em>fault ratio</em>"]},
            "source": {},
        }
    )

    metadata = evidence["metadata"]
    assert evidence["source_type"] == "fault_ratio_precedent"
    assert evidence["title"] == "lane change fault ratio precedent"
    assert (
        evidence["source_reference"]
        == "fault_ratio_precedent_db:616249#616249:structured_1500_250:0001"
    )
    assert metadata["case_number"] == "2022da287284"
    assert metadata["court_name"] == "Supreme Court"
    assert metadata["chunk_type"] == "fault_ratio_evidence"
    assert metadata["precedent_context"]["source_role"] == "fault_ratio_precedent"
    assert metadata["score"] == 31.5
    assert evidence["confidence"] is None


def test_map_fault_ratio_precedent_hits_to_evidence_maps_list() -> None:
    evidence = map_fault_ratio_precedent_hits_to_evidence(
        [
            {"source": {"case_id": "616249", "chunk_id": "c1"}},
            {"source": {"case_id": "240897", "chunk_id": "c2"}},
        ]
    )

    assert len(evidence) == 2
    assert evidence[0]["source_reference"] == "fault_ratio_precedent_db:616249#c1"
    assert evidence[1]["source_reference"] == "fault_ratio_precedent_db:240897#c2"
