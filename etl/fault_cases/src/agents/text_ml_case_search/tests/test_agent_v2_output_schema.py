from __future__ import annotations

from etl.fault_cases.src.agents.text_ml_case_search import agent as text_ml_agent


def test_agent_v2_output_includes_pgvector_source_summary(monkeypatch) -> None:
    evidence = [
        {
            "source_type": "review_case",
            "title": "review case title",
            "source_reference": "review_case_db:rc_001#rc_001:case_overview",
            "chunk_text": "valid review case evidence text " * 5,
            "search_text": "lane change fault ratio",
            "metadata": {
                "review_case_id": "rc_001",
                "review_no": "2017-032889",
                "chunk_id": "rc_001:case_overview",
                "decision_fault_ratio": "A 70 : B 30",
                "score_type": "cosine_similarity",
                "retriever": "review_case_pgvector",
            },
        },
        {
            "source_type": "fault_ratio_precedent",
            "title": "precedent title",
            "source_reference": "fault_ratio_precedent_db:616249#616249:structured_1500_250:0001",
            "chunk_text": "valid precedent evidence text " * 5,
            "search_text": "lane change fault ratio",
            "metadata": {
                "case_id": "616249",
                "case_number": "2022da287284",
                "chunk_id": "616249:structured_1500_250:0001",
                "court_name": "Supreme Court",
                "decision_date": "2025-05-15",
                "score_type": "cosine_similarity",
                "retriever": "fault_ratio_precedent_pgvector",
            },
        },
    ]

    def fake_pgvector_pipeline(*, search_text, search_variant):
        return {
            "retriever": "unified_pgvector",
            "requested_search_variant": search_variant,
            "search_variant": "schema_search_text",
            "top_k": 5,
            "final_top_k": 10,
            "active_sources": ["review_case", "fault_ratio_precedent"],
            "standby_sources": ["traffic_precedent"],
            "excluded_sources": ["standard"],
            "source_results": {
                "review_case": {"status": "ready", "retriever": "review_case_pgvector", "source_type": "review_case", "raw_hit_count": 1, "mapped_evidence_count": 1, "valid_evidence_count": 1, "validation_report": {}},
                "fault_ratio_precedent": {"status": "ready", "retriever": "fault_ratio_precedent_pgvector", "source_type": "fault_ratio_precedent", "raw_hit_count": 1, "mapped_evidence_count": 1, "valid_evidence_count": 1, "validation_report": {}},
            },
            "merge_result": {
                "merge_strategy": "source_quota",
                "review_case_quota": 5,
                "fault_ratio_precedent_quota": 5,
                "final_top_k": 10,
                "source_counts": {"review_case": 1, "fault_ratio_precedent": 1},
                "input_counts": {"review_case": 1, "fault_ratio_precedent": 1},
                "output_count": 2,
            },
            "source_summary": {
                "active_sources": ["review_case", "fault_ratio_precedent"],
                "source_counts": {"review_case": 1, "fault_ratio_precedent": 1},
                "source_statuses": {"review_case": "ready", "fault_ratio_precedent": "ready"},
                "final_top_k": 10,
                "merge_strategy": "source_quota",
            },
            "evidence": evidence,
        }

    monkeypatch.setattr(text_ml_agent, "run_unified_pgvector_pipeline", fake_pgvector_pipeline)
    result = text_ml_agent.run_text_ml_case_search(
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
        }
    )

    structured = result["structured_result"]
    source_summary = structured["source_summary"]
    assert result["status"] == "success"
    assert source_summary["active_sources"] == ["review_case", "fault_ratio_precedent"]
    assert source_summary["source_counts"] == {
        "review_case": 1,
        "fault_ratio_precedent": 1,
    }
    assert source_summary["source_statuses"] == {
        "review_case": "ready",
        "fault_ratio_precedent": "ready",
    }
    assert {item["source_type"] for item in result["evidence"]} == {
        "review_case",
        "fault_ratio_precedent",
    }
    assert any(
        item["source_type"] == "fault_ratio_precedent"
        and item["case_number"] == "2022da287284"
        for item in structured["display_evidence"]
    )
    assert structured["rag_debug"]["retriever"] == "unified_pgvector"
    assert structured["insurer_claim_review"]["reference_evidence_count"] == 2
