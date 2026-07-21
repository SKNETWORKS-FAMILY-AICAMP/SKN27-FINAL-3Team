from __future__ import annotations

import json
from pathlib import Path
from datetime import date

import pytest

from etl.legal import evaluation
from etl.legal import run_evaluation


def test_load_public_law_queries_requires_twenty_public_law_rows(tmp_path: Path) -> None:
    fixture = tmp_path / "queries.json"
    fixture.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="at least 20"):
        evaluation.load_public_law_queries(fixture)


def test_validate_public_law_query_rejects_non_public_classification() -> None:
    with pytest.raises(ValueError, match="data_classification"):
        evaluation.validate_public_law_query(
            {
                "query_id": "law-q001",
                "data_classification": "ocr",
            }
        )


def test_load_public_law_queries_reads_valid_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "queries.json"
    query = {
        "query_id": "law-q001",
        "query": "신호 지시를 따라야 하는 근거는 무엇인가?",
        "temporal_basis": {"mode": "as_of", "effective_at": "2026-07-21"},
        "scope": {"allowed_source_types": ["law"]},
        "expected_source_references": ["도로교통법|제5조"],
        "reference_answer": "도로교통법 제5조를 확인한다.",
        "scenario": "신호 지시 준수",
        "data_classification": "public_law",
    }
    fixture.write_text(
        json.dumps(
            [{**query, "query_id": f"law-q{index:03d}"} for index in range(1, 21)],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = evaluation.load_public_law_queries(fixture)

    assert len(loaded) == 20
    assert loaded[0]["query_id"] == "law-q001"


def test_normalize_backend_response_removes_raw_text_and_keeps_ranked_metadata() -> None:
    normalized = evaluation.normalize_backend_response(
        "law-q001",
        {
            "backend": "postgres_lexical",
            "status": "ready",
            "latency_ms": 12,
            "error_code": "",
            "results": [
                {
                    "source_reference": "volatile-chunk-id",
                    "source_name": "도로교통법",
                    "article": "제5조",
                    "source_type": "law",
                    "source_url": "https://law.go.kr/example",
                    "effective_date": "2026-01-01",
                    "expire_date": None,
                    "score": 0.9,
                    "summary": "원문 요약은 결과 파일에 저장하지 않는다.",
                    "provision_text": "원문은 평가 artifact에 저장하지 않는다.",
                }
            ],
        },
    )

    assert normalized["query_id"] == "law-q001"
    assert normalized["results"][0]["rank"] == 1
    assert normalized["results"][0]["source_reference"] == "volatile-chunk-id"
    assert "summary" not in normalized["results"][0]
    assert "provision_text" not in normalized["results"][0]


def test_summary_calculates_recall_mrr_ndcg_latency_and_metadata() -> None:
    queries = [
        {"query_id": "law-q001", "expected_source_references": ["도로교통법|제5조"]},
        {"query_id": "law-q002", "expected_source_references": ["도로교통법|제32조"]},
    ]
    runs = [
        {
            "query_id": "law-q001",
            "backend": "postgres_lexical",
            "status": "ready",
            "latency_ms": 10,
            "results": [
                {
                    "rank": 1,
                    "source_reference": "chunk-1",
                    "source_name": "도로교통법",
                    "article": "제5조",
                    "source_url": "https://law.go.kr/1",
                    "effective_date": "2026-01-01",
                    "expire_date": None,
                }
            ],
        },
        {
            "query_id": "law-q002",
            "backend": "postgres_lexical",
            "status": "ready",
            "latency_ms": 30,
            "results": [
                {
                    "rank": 1,
                    "source_reference": "chunk-2",
                    "source_name": "도로교통법",
                    "article": "제13조",
                    "source_url": "https://law.go.kr/2",
                    "effective_date": "2026-01-01",
                    "expire_date": None,
                },
                {
                    "rank": 2,
                    "source_reference": "chunk-3",
                    "source_name": "도로교통법",
                    "article": "제32조",
                    "source_url": "https://law.go.kr/3",
                    "effective_date": "2026-01-01",
                    "expire_date": None,
                },
            ],
        },
    ]

    summary = evaluation.summarize_backend_runs(runs, queries)

    lexical = summary["postgres_lexical"]
    assert lexical["recall_at_1"] == 0.5
    assert lexical["recall_at_3"] == 1.0
    assert lexical["recall_at_5"] == 1.0
    assert lexical["mrr"] == 0.75
    assert lexical["ndcg_at_5"] == pytest.approx(0.815465, abs=0.000001)
    assert lexical["p50_latency_ms"] == 10
    assert lexical["p95_latency_ms"] == 30
    assert lexical["metadata_complete_rate"] == 1.0


def test_collect_backend_runs_uses_identical_resolved_filters(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    query = {
        "query_id": "law-q001",
        "query": "신호 지시 준수",
        "temporal_basis": {"mode": "as_of", "effective_at": "2026-07-21"},
        "scope": {"allowed_source_types": ["law"]},
    }
    monkeypatch.setattr(
        run_evaluation.service,
        "resolve_legal_search_filters",
        lambda **_kwargs: (("law",), date(2026, 7, 21), ""),
    )
    monkeypatch.setattr(
        run_evaluation.service,
        "_search_law_chunks_lexical",
        lambda _query, **kwargs: calls.append(("lexical", kwargs))
        or {"backend": "postgres_lexical", "status": "ready", "latency_ms": 1, "results": []},
    )
    monkeypatch.setattr(
        run_evaluation.service,
        "_search_pgvector",
        lambda _query, **kwargs: calls.append(("pgvector", kwargs))
        or {"backend": "postgres_pgvector", "status": "ready", "latency_ms": 1, "results": []},
    )

    runs = run_evaluation.collect_backend_runs([query])

    assert [run["backend"] for run in runs] == ["postgres_lexical", "postgres_pgvector"]
    assert calls[0][1]["effective_at"] == calls[1][1]["effective_at"]
    assert calls[0][1]["allowed_source_types"] == calls[1][1]["allowed_source_types"]
    assert calls[0][1]["top_k"] == calls[1][1]["top_k"] == 5


def test_collect_backend_runs_preserves_invalid_filter_as_non_search_result(monkeypatch) -> None:
    query = {
        "query_id": "law-q001",
        "query": "신호 지시 준수",
        "temporal_basis": {"mode": "as_of", "effective_at": "not-a-date"},
        "scope": {"allowed_source_types": ["law"]},
    }
    monkeypatch.setattr(
        run_evaluation.service,
        "resolve_legal_search_filters",
        lambda **_kwargs: ((), None, "invalid_effective_at"),
    )

    runs = run_evaluation.collect_backend_runs([query])

    assert [run["status"] for run in runs] == ["invalid_filter", "invalid_filter"]
    assert [run["error_code"] for run in runs] == ["invalid_effective_at", "invalid_effective_at"]


def test_build_ragas_records_caps_public_contexts_at_top_five() -> None:
    query = {
        "query_id": "law-q001",
        "query": "신호 지시 준수",
        "reference_answer": "도로교통법 제5조를 확인한다.",
        "data_classification": "public_law",
    }
    raw_response = {
        "query_id": "law-q001",
        "backend": "postgres_pgvector",
        "results": [
            {"provision_text": f"공개 법령 조문 {index}"}
            for index in range(1, 8)
        ],
    }

    records = run_evaluation.build_ragas_records([query], [raw_response])

    assert records == [
        {
            "query_id": "law-q001",
            "backend": "postgres_pgvector",
            "question": "신호 지시 준수",
            "ground_truth": "도로교통법 제5조를 확인한다.",
            "contexts": [f"공개 법령 조문 {index}" for index in range(1, 6)],
        }
    ]


def test_build_ragas_records_rejects_non_public_input() -> None:
    with pytest.raises(ValueError, match="public_law"):
        run_evaluation.build_ragas_records(
            [
                {
                    "query_id": "law-q001",
                    "query": "첨부 OCR 원문",
                    "reference_answer": "답변",
                    "data_classification": "ocr",
                }
            ],
            [],
        )


def test_run_ragas_uses_fixed_generator_and_judge_for_each_backend_record(monkeypatch) -> None:
    records = [
        {
            "query_id": "law-q001",
            "backend": "postgres_lexical",
            "question": "신호 지시 준수",
            "ground_truth": "도로교통법 제5조를 확인한다.",
            "contexts": ["공개 법령 조문"],
        }
    ]
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        run_evaluation,
        "_generate_ragas_answers",
        lambda rows, **kwargs: captured.update(generator=kwargs, rows=rows)
        or [{**rows[0], "answer": "생성된 법령 답변"}],
    )
    monkeypatch.setattr(
        run_evaluation,
        "_evaluate_ragas_samples",
        lambda rows, **kwargs: captured.update(judge=kwargs, evaluated_rows=rows)
        or {"faithfulness": 1.0, "answer_relevancy": 0.9},
    )

    result = run_evaluation.run_ragas(
        records,
        generator_model="gpt-test-generator",
        judge_model="gpt-test-judge",
        embedding_model="text-embedding-test",
    )

    assert result["status"] == "evaluated"
    assert result["metrics"]["faithfulness"] == 1.0
    assert captured["generator"] == {"model": "gpt-test-generator"}
    assert captured["judge"] == {
        "judge_model": "gpt-test-judge",
        "embedding_model": "text-embedding-test",
    }


def test_run_ragas_requires_at_most_twenty_public_questions() -> None:
    records = [
        {
            "query_id": f"law-q{index:03d}",
            "backend": "postgres_lexical",
            "question": "공개 법령 질의",
            "ground_truth": "공개 법령 정답",
            "contexts": ["공개 법령 조문"],
        }
        for index in range(1, 22)
    ]

    with pytest.raises(ValueError, match="at most 20"):
        run_evaluation.run_ragas(records, generator_model="g", judge_model="j", embedding_model="e")
