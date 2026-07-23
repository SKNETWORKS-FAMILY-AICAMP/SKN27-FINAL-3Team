from __future__ import annotations

import importlib
import importlib.util

from openai import OpenAIError

MODULE_NAME = (
    "etl.fault_cases.src.agents.text_ml_case_search.rag.pgvector_unified_retriever"
)


def _load_module():
    assert importlib.util.find_spec(MODULE_NAME) is not None, (
        "pgvector unified retriever must be available to text-ML"
    )
    return importlib.import_module(MODULE_NAME)


def _search_text() -> dict[str, str]:
    return {
        "schema_search_text": "신호 없는 교차로 직진 차량과 우측 진입 차량 충돌",
        "natural_query_text": "교차로 사고",
    }


def _review_case_row() -> dict[str, object]:
    return {
        "review_case_id": "rc-1",
        "review_no": "2025-001",
        "chunk_id": "rc-1:chunk-1",
        "chunk_type": "case_overview",
        "case_title": "교차로 심의사례",
        "decision_fault_ratio": "A 70 : B 30",
        "claimant_final_ratio": "70",
        "respondent_final_ratio": "30",
        "chunk_text": "심의사례 근거 문장입니다. " * 8,
        "search_text": "교차로 직진 우측 진입",
        "cosine_similarity": 0.81,
        "rank": 1,
    }


def _fault_ratio_row() -> dict[str, object]:
    return {
        "case_id": "fr-1",
        "case_number": "2024-0001",
        "chunk_id": "fr-1:chunk-1",
        "chunk_index": 1,
        "chunk_type": "fault_ratio_evidence",
        "chunk_strategy": "structured",
        "case_name": "과실비율 판례",
        "court_name": "대법원",
        "decision_date": "2024-01-01",
        "chunk_text": "과실비율 판례 근거 문장입니다. " * 8,
        "search_text": "교차로 우선권 과실비율",
        "cosine_similarity": 0.75,
        "rank": 1,
    }


def test_unified_pgvector_pipeline_maps_two_source_results(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "search_review_case_pgvector", lambda query, top_k: [_review_case_row()])
    monkeypatch.setattr(
        module,
        "search_fault_ratio_precedent_pgvector",
        lambda dataset, query, top_k: [_fault_ratio_row()],
    )

    result = module.run_unified_pgvector_pipeline(search_text=_search_text())

    assert result["retriever"] == "unified_pgvector"
    assert result["source_results"]["review_case"]["retriever"] == "review_case_pgvector"
    assert result["source_results"]["fault_ratio_precedent"]["retriever"] == (
        "fault_ratio_precedent_pgvector"
    )
    assert result["merge_result"]["source_counts"] == {
        "review_case": 1,
        "fault_ratio_precedent": 1,
    }
    assert result["evidence"][0]["metadata"]["score_type"] == "cosine_similarity"
    assert result["evidence"][1]["metadata"]["score_type"] == "cosine_similarity"


def test_unified_pgvector_pipeline_keeps_healthy_source_when_other_fails(monkeypatch) -> None:
    module = _load_module()

    def raise_review_case(query, top_k):
        raise RuntimeError("review db unavailable")

    monkeypatch.setattr(module, "search_review_case_pgvector", raise_review_case)
    monkeypatch.setattr(
        module,
        "search_fault_ratio_precedent_pgvector",
        lambda dataset, query, top_k: [_fault_ratio_row()],
    )

    result = module.run_unified_pgvector_pipeline(search_text=_search_text())

    assert result["status"] == "partial"
    assert result["source_results"]["review_case"]["status"] == "unavailable"
    assert result["source_results"]["fault_ratio_precedent"]["status"] == "ready"
    assert [item["source_type"] for item in result["evidence"]] == [
        "fault_ratio_precedent"
    ]


def test_unified_pgvector_pipeline_treats_embedding_credential_failure_as_unavailable(
    monkeypatch,
) -> None:
    module = _load_module()

    def raise_missing_credentials(query, top_k):
        raise OpenAIError("missing credentials")

    monkeypatch.setattr(module, "search_review_case_pgvector", raise_missing_credentials)
    monkeypatch.setattr(
        module,
        "search_fault_ratio_precedent_pgvector",
        lambda dataset, query, top_k: [_fault_ratio_row()],
    )

    result = module.run_unified_pgvector_pipeline(search_text=_search_text())

    assert result["status"] == "partial"
    assert result["source_results"]["review_case"]["error_code"] == "pgvector_unavailable"
    assert result["source_results"]["review_case"]["error_class"] == "OpenAIError"
