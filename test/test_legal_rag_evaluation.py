from __future__ import annotations

import json
from pathlib import Path

import pytest

from etl.legal import evaluation


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
