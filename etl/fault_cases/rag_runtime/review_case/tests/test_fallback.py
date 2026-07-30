from __future__ import annotations

from typing import Any

from etl.fault_cases.rag_runtime.review_case import retriever
from etl.fault_cases.rag_runtime.review_case.config import load_config
from etl.fault_cases.rag_runtime.review_case.reranker import (
    RerankResult,
)


class DriverFailure(Exception):
    """테스트용 PostgreSQL 드라이버 계층 오류."""


def _row(case_id: str, rank: int) -> dict[str, Any]:
    return {
        "source_reference": f"review/{case_id}.pdf",
        "title": case_id,
        "document_id": case_id,
        "chunk_id": f"{case_id}_decision",
        "target_id": f"{case_id}_decision",
        "evidence_text": f"결정이유 {case_id}",
        "rank": rank,
        "cosine_similarity": 1.0 - rank / 100,
        "metadata": {
            "review_case_id": case_id,
            "decision_fault_ratio": f"{rank * 10} : {100 - rank * 10}",
        },
    }


def _stub_vector(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever,
        "_resolve_vector",
        lambda request: [0.0] * 2559 + [1.0],
    )


def test_qwen_driver_failure_is_sanitized_failed_result(
    monkeypatch,
) -> None:
    _stub_vector(monkeypatch)

    def fail_search(*args, **kwargs):
        raise DriverFailure(
            "postgresql://user:password@secret-review-host"
        )

    monkeypatch.setattr(retriever, "search_by_vector", fail_search)

    result = retriever.search_review_case({"query_text": "사고"})

    assert result["status"] == "failed"
    assert result["evidence"] == []
    assert result["calculation_result"] is None
    public_limitations = " ".join(result["limitations"])
    assert "secret-review-host" not in public_limitations
    assert "DriverFailure" not in public_limitations


def test_context_driver_failure_returns_qwen_top_five(
    monkeypatch,
) -> None:
    rows = [_row(f"case-{index}", index) for index in range(1, 6)]
    _stub_vector(monkeypatch)
    monkeypatch.setattr(
        retriever,
        "search_by_vector",
        lambda *args, **kwargs: rows,
    )

    def fail_context(*args, **kwargs):
        raise DriverFailure("password=secret-value")

    monkeypatch.setattr(
        retriever,
        "fetch_document_chunks",
        fail_context,
    )

    result = retriever.search_review_case(
        {"query_text": "사고"},
        config=load_config({}),
    )

    assert result["status"] == "partial"
    assert [
        item["metadata"]["review_case_id"]
        for item in result["evidence"]
    ] == [f"case-{index}" for index in range(1, 6)]
    assert all(
        item["metadata"]["reranker_applied"] is False
        for item in result["evidence"]
    )
    assert "secret-value" not in " ".join(result["limitations"])


def test_missing_fault_ratio_is_explicit_and_does_not_drop_case(
    monkeypatch,
) -> None:
    rows = [
        _row(f"case-{index}", index) for index in range(1, 5)
    ]
    missing = _row("case-without-ratio", 5)
    missing["metadata"].pop("decision_fault_ratio")
    rows.append(missing)
    _stub_vector(monkeypatch)
    monkeypatch.setattr(
        retriever,
        "search_by_vector",
        lambda *args, **kwargs: rows,
    )
    monkeypatch.setattr(
        retriever,
        "fetch_document_chunks",
        lambda *args, **kwargs: {},
    )

    def applied(query_text, candidates, *, config):
        ranked = [dict(item) for item in candidates]
        for item in ranked:
            item["first_stage_rank"] = item["rank"]
            item["first_stage_score"] = item[
                "cosine_similarity"
            ]
            item["rerank_score"] = 1.0
        return RerankResult(ranked, applied=True)

    result = retriever.search_review_case(
        {"query_text": "사고"},
        config=load_config({}),
        rerank=applied,
    )

    assert result["status"] == "partial"
    assert len(result["evidence"]) == 5
    assert result["evidence"][-1]["decision_fault_ratio"] is None
    assert result["evidence"][-1]["metadata"][
        "decision_fault_ratio"
    ] is None
    assert any(
        "case-without-ratio" in limitation
        for limitation in result["limitations"]
    )


def test_duplicate_reranker_output_falls_back_to_original_five(
    monkeypatch,
) -> None:
    rows = [_row(f"case-{index}", index) for index in range(1, 6)]
    _stub_vector(monkeypatch)
    monkeypatch.setattr(
        retriever,
        "search_by_vector",
        lambda *args, **kwargs: rows,
    )
    monkeypatch.setattr(
        retriever,
        "fetch_document_chunks",
        lambda *args, **kwargs: {},
    )

    def duplicated(query_text, candidates, *, config):
        ranked = [dict(candidates[0])] + [
            dict(item) for item in candidates
        ]
        for rank, item in enumerate(ranked, start=1):
            item["first_stage_rank"] = item["rank"]
            item["first_stage_score"] = item[
                "cosine_similarity"
            ]
            item["rerank_score"] = float(10 - rank)
            item["rank"] = rank
        return RerankResult(ranked, applied=True)

    result = retriever.search_review_case(
        {"query_text": "사고"},
        config=load_config({}),
        rerank=duplicated,
    )

    assert result["status"] == "partial"
    assert [
        item["metadata"]["review_case_id"]
        for item in result["evidence"]
    ] == [f"case-{index}" for index in range(1, 6)]
    assert all(
        item["metadata"]["reranker_applied"] is False
        for item in result["evidence"]
    )
