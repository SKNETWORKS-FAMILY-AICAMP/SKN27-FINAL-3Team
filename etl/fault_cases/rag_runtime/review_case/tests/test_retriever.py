from __future__ import annotations

from typing import Any

from etl.fault_cases.rag_runtime.review_case import retriever


def _row(case_number: int) -> dict[str, Any]:
    case_id = f"review_case_{case_number:02d}"
    return {
        "source_reference": f"review/{case_id}.pdf",
        "title": f"심의사례 {case_number}",
        "document_id": case_id,
        "chunk_id": f"{case_id}_decision",
        "target_id": f"{case_id}_decision",
        "evidence_text": f"결정이유 {case_number}",
        "rank": case_number,
        "cosine_similarity": 1.0 - case_number / 100,
        "metadata": {
            "review_case_id": case_id,
            "decision_fault_ratio": f"청구 {case_number * 10} : 피청구 {100 - case_number * 10}",
        },
    }


def test_search_requests_exactly_five_unique_review_cases(monkeypatch) -> None:
    observed: dict[str, Any] = {}
    rows = [_row(index) for index in range(1, 11)]

    monkeypatch.setattr(
        retriever,
        "_resolve_vector",
        lambda request: [0.0] * 2559 + [1.0],
    )

    def fake_search(
        corpus: str,
        query_vector: list[float],
        top_k: int,
        candidate_k: int,
    ) -> list[dict[str, Any]]:
        observed["args"] = (corpus, top_k, candidate_k)
        return rows[:top_k]

    monkeypatch.setattr(retriever, "search_by_vector", fake_search)

    result = retriever.search_review_case(
        {"contract_version": "v1", "query_text": "교차로 충돌"},
    )

    assert observed["args"] == ("review_case", 5, 200)
    assert len(result["evidence"]) == 5
    assert len(
        {
            item["metadata"]["review_case_id"]
            for item in result["evidence"]
        }
    ) == 5
    assert all(
        "decision_fault_ratio" in item["metadata"]
        for item in result["evidence"]
    )
    assert result["calculation_result"] is None


def test_bge_reorders_same_five_and_returns_fault_ratios(
    monkeypatch,
) -> None:
    from etl.fault_cases.rag_runtime.review_case.config import load_config
    from etl.fault_cases.rag_runtime.review_case.reranker import (
        RerankResult,
    )

    qwen_rows = [_row(index) for index in range(1, 6)]
    qwen_ids = {
        str(row["metadata"]["review_case_id"]) for row in qwen_rows
    }
    observed: dict[str, Any] = {}

    monkeypatch.setattr(
        retriever,
        "_resolve_vector",
        lambda request: [0.0] * 2559 + [1.0],
    )
    monkeypatch.setattr(
        retriever,
        "search_by_vector",
        lambda corpus, query_vector, top_k, candidate_k: qwen_rows,
    )

    def fake_fetch(
        corpus: str,
        document_ids: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        observed["fetch"] = (corpus, document_ids)
        return {
            document_id: [
                {
                    "chunk_type": "case_overview",
                    "chunk_text": f"사고내용 {document_id}",
                },
                {
                    "chunk_type": "arguments",
                    "chunk_text": f"당사자 주장 {document_id}",
                },
                {
                    "chunk_type": "evidence_issue",
                    "chunk_text": f"증거 및 쟁점 {document_id}",
                },
                {
                    "chunk_type": "decision",
                    "chunk_text": f"결정이유 {document_id}",
                },
            ]
            for document_id in document_ids
        }

    monkeypatch.setattr(
        retriever,
        "fetch_document_chunks",
        fake_fetch,
        raising=False,
    )

    def fake_rerank(query_text, candidates, *, config):
        observed["contexts"] = [
            str(row["evidence_text"]) for row in candidates
        ]
        ranked = [dict(row) for row in reversed(candidates)]
        for rank, row in enumerate(ranked, start=1):
            row["first_stage_rank"] = int(row["rank"])
            row["first_stage_score"] = float(
                row["cosine_similarity"]
            )
            row["rerank_score"] = float(10 - rank)
            row["rank"] = rank
        return RerankResult(candidates=ranked, applied=True)

    result = retriever.search_review_case(
        {"contract_version": "v1", "query_text": "교차로 충돌"},
        config=load_config({}),
        rerank=fake_rerank,
    )

    result_ids = {
        str(row["metadata"]["review_case_id"])
        for row in result["evidence"]
    }
    assert observed["fetch"] == (
        "review_case",
        [str(row["document_id"]) for row in qwen_rows],
    )
    assert all(
        "[CASE_OVERVIEW]" in context
        and "[ARGUMENTS]" in context
        and "[EVIDENCE_ISSUE]" in context
        and "[DECISION]" in context
        for context in observed["contexts"]
    )
    assert result["status"] == "success"
    assert result_ids == qwen_ids
    assert result["evidence"][0]["title"] == "심의사례 5"
    assert result["evidence"][0]["decision_fault_ratio"] == (
        "청구 50 : 피청구 50"
    )
    assert result["evidence"][0]["metadata"][
        "decision_fault_ratio"
    ] == "청구 50 : 피청구 50"
    assert result["evidence"][0]["retrieval_score"] == 9.0
    assert result["evidence"][0]["score_type"] == (
        "bge_reranker_v2_m3_raw_logit"
    )
