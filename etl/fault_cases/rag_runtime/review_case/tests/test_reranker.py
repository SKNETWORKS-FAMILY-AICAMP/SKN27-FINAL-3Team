from __future__ import annotations

import importlib.util
import sys
from types import SimpleNamespace
from typing import Any


def _candidate(case_id: str, rank: int) -> dict[str, Any]:
    return {
        "document_id": case_id,
        "rank": rank,
        "cosine_similarity": 1.0 - rank / 100,
        "evidence_text": f"사례 전체 문맥 {case_id}",
        "metadata": {"review_case_id": case_id},
    }


def test_review_case_reranker_module_exists() -> None:
    spec = importlib.util.find_spec(
        "etl.fault_cases.rag_runtime.review_case.reranker"
    )

    assert spec is not None


def test_rerank_scores_change_only_order_and_preserve_qwen_metadata() -> None:
    from etl.fault_cases.rag_runtime.review_case.reranker import (
        rerank_with_scores,
    )

    candidates = [
        _candidate("case-a", 1),
        _candidate("case-b", 2),
        _candidate("case-c", 3),
    ]

    ranked = rerank_with_scores(candidates, [0.1, 0.9, 0.4])

    assert [row["document_id"] for row in ranked] == [
        "case-b",
        "case-c",
        "case-a",
    ]
    assert {row["document_id"] for row in ranked} == {
        "case-a",
        "case-b",
        "case-c",
    }
    assert [row["rank"] for row in ranked] == [1, 2, 3]
    assert ranked[0]["first_stage_rank"] == 2
    assert ranked[0]["first_stage_score"] == 0.98
    assert candidates[0]["rank"] == 1
    assert "rerank_score" not in candidates[0]


def test_rerank_ties_keep_qwen_order() -> None:
    from etl.fault_cases.rag_runtime.review_case.reranker import (
        rerank_with_scores,
    )

    candidates = [
        _candidate("case-a", 1),
        _candidate("case-b", 2),
    ]

    ranked = rerank_with_scores(candidates, [0.5, 0.5])

    assert [row["document_id"] for row in ranked] == [
        "case-a",
        "case-b",
    ]


def test_reranker_failure_returns_sanitized_qwen_fallback() -> None:
    from etl.fault_cases.rag_runtime.review_case.config import load_config
    from etl.fault_cases.rag_runtime.review_case.reranker import (
        rerank_candidates,
    )

    candidates = [
        _candidate("case-a", 1),
        _candidate("case-b", 2),
    ]

    def failing_scorer(query_text, rows, config):
        raise RuntimeError("postgresql://user:password@secret-host")

    result = rerank_candidates(
        "차로 변경 사고",
        candidates,
        config=load_config({}),
        scorer=failing_scorer,
    )

    assert result.applied is False
    assert result.failure_code == "BGE_RERANKER_UNAVAILABLE"
    assert [row["document_id"] for row in result.candidates] == [
        "case-a",
        "case-b",
    ]
    assert "secret-host" not in str(result.limitation)


def test_bge_model_is_constructed_once_per_reranker(
    monkeypatch,
) -> None:
    from etl.fault_cases.rag_runtime.review_case.config import load_config
    from etl.fault_cases.rag_runtime.review_case.reranker import (
        BgeReranker,
    )

    constructed: list[dict[str, Any]] = []

    class Predictions:
        def __init__(self, values: list[float]) -> None:
            self.values = values

        def reshape(self, size: int):
            assert size == -1
            return self

        def tolist(self) -> list[float]:
            return self.values

    class FakeCrossEncoder:
        def __init__(self, model_name: str, **kwargs: Any) -> None:
            constructed.append(
                {"model_name": model_name, **kwargs}
            )

        def predict(self, pairs, **kwargs: Any) -> Predictions:
            return Predictions([0.25 for _ in pairs])

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(CrossEncoder=FakeCrossEncoder),
    )
    reranker = BgeReranker(load_config({}))
    candidates = [
        _candidate("case-a", 1),
        _candidate("case-b", 2),
    ]

    first = reranker.score("교차로 사고", candidates)
    second = reranker.score("차로 변경 사고", candidates)

    assert first == [0.25, 0.25]
    assert second == [0.25, 0.25]
    assert len(constructed) == 1
    assert constructed[0]["model_name"] == (
        "BAAI/bge-reranker-v2-m3"
    )
    assert constructed[0]["revision"] == (
        "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    )
