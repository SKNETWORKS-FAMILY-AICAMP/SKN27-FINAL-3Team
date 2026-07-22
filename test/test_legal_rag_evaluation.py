from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import date
from types import ModuleType, SimpleNamespace

import pytest

from etl.legal import evaluation
from etl.legal import run_evaluation


COMPLETE_RAGAS_METRICS = {
    "context_precision": 0.8,
    "context_recall": 0.7,
    "faithfulness": 0.9,
    "answer_relevancy": 0.6,
}


def ragas_record(
    query_id: str,
    backend: str = "postgres_lexical",
    contexts: list[str] | None = None,
) -> dict[str, object]:
    return {
        "query_id": query_id,
        "backend": backend,
        "question": "공개 법령 질의",
        "ground_truth": "공개 법령 정답",
        "contexts": contexts if contexts is not None else ["공개 법령 조문"],
    }


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
    fake_service = SimpleNamespace()
    monkeypatch.setattr(run_evaluation, "_get_service", lambda: fake_service)
    monkeypatch.setattr(
        fake_service,
        "resolve_legal_search_filters",
        lambda **_kwargs: (("law",), date(2026, 7, 21), ""),
        raising=False,
    )
    monkeypatch.setattr(
        fake_service,
        "_search_law_chunks_lexical",
        lambda _query, **kwargs: calls.append(("lexical", kwargs))
        or {"backend": "postgres_lexical", "status": "ready", "latency_ms": 1, "results": []},
        raising=False,
    )
    monkeypatch.setattr(
        fake_service,
        "_search_pgvector",
        lambda _query, **kwargs: calls.append(("pgvector", kwargs))
        or {"backend": "postgres_pgvector", "status": "ready", "latency_ms": 1, "results": []},
        raising=False,
    )

    runs = run_evaluation.collect_backend_runs([query])

    assert [run["backend"] for run in runs] == ["postgres_lexical", "postgres_pgvector"]
    assert calls[0][1]["effective_at"] == calls[1][1]["effective_at"]
    assert calls[0][1]["allowed_source_types"] == calls[1][1]["allowed_source_types"]
    assert calls[0][1]["top_k"] == calls[1][1]["top_k"] == 5


def test_collect_backend_runs_normalizes_openai_auth_error_without_recording_message(monkeypatch) -> None:
    query = {
        "query_id": "law-q001",
        "query": "공개 법률 질의",
        "temporal_basis": {"mode": "as_of", "effective_at": "2026-07-21"},
        "scope": {"allowed_source_types": ["law"]},
    }
    fake_service = SimpleNamespace()
    monkeypatch.setattr(run_evaluation, "_get_service", lambda: fake_service)
    monkeypatch.setattr(
        fake_service,
        "resolve_legal_search_filters",
        lambda **_kwargs: (("law",), date(2026, 7, 21), ""),
        raising=False,
    )
    monkeypatch.setattr(
        fake_service,
        "_search_law_chunks_lexical",
        lambda _query, **_kwargs: {"backend": "postgres_lexical", "status": "ready", "latency_ms": 1, "results": []},
        raising=False,
    )
    monkeypatch.setattr(
        fake_service,
        "_search_pgvector",
        lambda _query, **_kwargs: {
            "backend": "postgres_pgvector",
            "status": "unavailable",
            "latency_ms": 1,
            "error_code": 'Error code: 401 - Incorrect API key provided: "sk-secret"',
            "results": [],
        },
        raising=False,
    )

    runs = run_evaluation.collect_backend_runs([query])

    assert runs[1]["error_code"] == "openai_authentication_failed"
    assert "sk-secret" not in str(runs[1])


def test_summarize_ragas_scores_averages_public_metric_rows() -> None:
    summary = run_evaluation.summarize_ragas_scores(
        [
            {
                "context_precision": 0.8,
                "context_recall": 0.6,
                "faithfulness": 1.0,
                "answer_relevancy": 0.4,
            },
            {
                "context_precision": 0.6,
                "context_recall": 0.8,
                "faithfulness": 0.5,
                "answer_relevancy": 0.6,
            },
        ]
    )

    assert summary == {
        "context_precision": 0.7,
        "context_recall": 0.7,
        "faithfulness": 0.75,
        "answer_relevancy": 0.5,
    }


def test_collect_backend_runs_preserves_invalid_filter_as_non_search_result(monkeypatch) -> None:
    query = {
        "query_id": "law-q001",
        "query": "신호 지시 준수",
        "temporal_basis": {"mode": "as_of", "effective_at": "not-a-date"},
        "scope": {"allowed_source_types": ["law"]},
    }
    fake_service = SimpleNamespace()
    monkeypatch.setattr(run_evaluation, "_get_service", lambda: fake_service)
    monkeypatch.setattr(
        fake_service,
        "resolve_legal_search_filters",
        lambda **_kwargs: ((), None, "invalid_effective_at"),
        raising=False,
    )

    runs = run_evaluation.collect_backend_runs([query])

    assert [run["status"] for run in runs] == ["invalid_filter", "invalid_filter"]
    assert [run["error_code"] for run in runs] == ["invalid_effective_at", "invalid_effective_at"]


def test_collect_evaluation_preflight_rejects_missing_legal_rag_tables() -> None:
    connection = SimpleNamespace(
        vendor="postgresql",
        introspection=SimpleNamespace(table_names=lambda: ["unrelated_table"]),
    )

    result = run_evaluation.collect_evaluation_preflight(
        connection,
        expected_embedding_space={
            "provider": "sentence-transformers",
            "model": "intfloat/multilingual-e5-large",
            "dimensions": 1024,
        },
    )

    assert result == {
        "status": "not_ready",
        "reason": "law_rag_tables_missing",
        "table_names": ["unrelated_table"],
    }


def test_main_writes_not_ready_summary_without_loading_django_service(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env.rag-eval"
    env_file.write_text("LEGAL_RAG_VECTOR_ENABLED=0\n", encoding="utf-8")
    monkeypatch.setattr(
        run_evaluation,
        "_get_service",
        lambda: pytest.fail("Django service must not load for an invalid evaluation environment"),
    )

    result = run_evaluation.main(
        [
            "--env-file",
            str(env_file),
            "--output-dir",
            str(tmp_path / "output"),
            "--run-id",
            "invalid-environment",
        ]
    )

    summary = json.loads((tmp_path / "output" / "invalid-environment" / "summary.json").read_text(encoding="utf-8"))
    assert result == 2
    assert summary["preflight"]["status"] == "not_ready"
    assert summary["preflight"]["reason"] == "evaluation_environment_invalid"
    assert "OPENAI_API_KEY" not in json.dumps(summary)


def test_local_evaluation_wrapper_is_explicit_and_does_not_seed_or_print_secrets() -> None:
    script = (Path(__file__).resolve().parents[1] / "scripts" / "run-legal-rag-ab-evaluation.ps1").read_text(
        encoding="utf-8"
    )

    assert "[switch]$StartPostgres" in script
    assert "docker compose up -d postgres" in script
    assert "--env-file" in script
    assert "etl.legal.run_evaluation" in script
    assert "run_pipeline" not in script
    assert "load_legal_rag_pgvector" not in script
    assert "Write-Host $line" not in script


def test_local_evaluation_wrapper_reuses_a_running_named_postgres_container() -> None:
    script = (Path(__file__).resolve().parents[1] / "scripts" / "run-legal-rag-ab-evaluation.ps1").read_text(
        encoding="utf-8"
    )

    assert 'docker ps -q --filter "name=^/skn27-postgres$"' in script
    assert "Local PostgreSQL container is already running; reusing it." in script


def test_local_evaluation_wrapper_allows_an_explicit_python_executable() -> None:
    script = (Path(__file__).resolve().parents[1] / "scripts" / "run-legal-rag-ab-evaluation.ps1").read_text(
        encoding="utf-8"
    )

    assert '[string]$PythonExecutable = "python"' in script
    assert "& $PythonExecutable @arguments" in script


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


def test_evaluate_ragas_samples_uses_ragas_evaluation_dataset(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeEvaluationDataset:
        def __init__(self, samples: list[dict[str, object]]) -> None:
            self.samples = [SimpleNamespace(**sample) for sample in samples]

        @classmethod
        def from_list(cls, samples: list[dict[str, object]]):
            return cls(samples)

    class LegacyDataset:
        @classmethod
        def from_list(cls, _samples: list[dict[str, object]]):
            raise AssertionError("legacy Hugging Face Dataset path must not be used")

    datasets_module = ModuleType("datasets")
    datasets_module.Dataset = LegacyDataset
    langchain_openai_module = ModuleType("langchain_openai")
    langchain_openai_module.ChatOpenAI = lambda **kwargs: kwargs
    langchain_openai_module.OpenAIEmbeddings = lambda **kwargs: kwargs
    ragas_module = ModuleType("ragas")
    ragas_module.__path__ = []
    ragas_module.evaluate = lambda dataset, **kwargs: captured.update(dataset=dataset, kwargs=kwargs) or SimpleNamespace(
        scores=[COMPLETE_RAGAS_METRICS]
    )
    ragas_dataset_schema_module = ModuleType("ragas.dataset_schema")
    ragas_dataset_schema_module.EvaluationDataset = FakeEvaluationDataset
    ragas_embeddings_module = ModuleType("ragas.embeddings")
    ragas_embeddings_module.LangchainEmbeddingsWrapper = lambda value: value
    ragas_llms_module = ModuleType("ragas.llms")
    ragas_llms_module.LangchainLLMWrapper = lambda value: value
    ragas_metrics_module = ModuleType("ragas.metrics")
    ragas_metrics_module.answer_relevancy = "answer_relevancy"
    ragas_metrics_module.context_precision = "context_precision"
    ragas_metrics_module.context_recall = "context_recall"
    ragas_metrics_module.faithfulness = "faithfulness"
    for module_name, module in {
        "datasets": datasets_module,
        "langchain_openai": langchain_openai_module,
        "ragas": ragas_module,
        "ragas.dataset_schema": ragas_dataset_schema_module,
        "ragas.embeddings": ragas_embeddings_module,
        "ragas.llms": ragas_llms_module,
        "ragas.metrics": ragas_metrics_module,
    }.items():
        monkeypatch.setitem(sys.modules, module_name, module)

    result = run_evaluation._evaluate_ragas_samples(
        [{**ragas_record("law-q001"), "answer": "공개 법령 근거 답변"}],
        judge_model="gpt-test-judge",
        embedding_model="text-embedding-test",
    )

    assert result == COMPLETE_RAGAS_METRICS
    assert isinstance(captured["dataset"], FakeEvaluationDataset)
    assert captured["dataset"].samples[0].question == "공개 법령 질의"


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
        or COMPLETE_RAGAS_METRICS,
    )

    result = run_evaluation.run_ragas(
        records,
        generator_model="gpt-test-generator",
        judge_model="gpt-test-judge",
        embedding_model="text-embedding-test",
    )

    assert result["status"] == "evaluated"
    assert result["metrics"]["faithfulness"] == 0.9
    assert set(result["query_results"][0]) == {
        "query_id",
        "backend",
        "status",
        "error_code",
        "latency_ms",
    }
    assert result["query_results"][0]["status"] == "evaluated"
    assert result["query_results"][0]["error_code"] is None
    assert captured["generator"] == {"model": "gpt-test-generator"}
    assert captured["judge"] == {
        "judge_model": "gpt-test-judge",
        "embedding_model": "text-embedding-test",
    }


def test_run_ragas_continues_after_one_query_failure_without_leaking_exception_text(monkeypatch) -> None:
    generated: list[str] = []

    def generate(rows, **_kwargs):
        query_id = rows[0]["query_id"]
        generated.append(query_id)
        if query_id == "law-q002":
            raise RuntimeError("provider response included api_key=secret-value")
        return [{**rows[0], "answer": "생성 답변"}]

    monkeypatch.setattr(run_evaluation, "_generate_ragas_answers", generate)
    monkeypatch.setattr(
        run_evaluation,
        "_evaluate_ragas_samples",
        lambda _rows, **_kwargs: COMPLETE_RAGAS_METRICS,
    )

    result = run_evaluation.run_ragas(
        [ragas_record("law-q001"), ragas_record("law-q002"), ragas_record("law-q003")],
        generator_model="g",
        judge_model="j",
        embedding_model="e",
    )

    assert generated == ["law-q001", "law-q002", "law-q003"]
    assert result["status"] == "not_evaluated"
    assert result["reason"] == "incomplete_ragas_evidence"
    assert result["query_results"][1]["query_id"] == "law-q002"
    assert result["query_results"][1]["status"] == "not_evaluated"
    assert result["query_results"][1]["error_code"] == "ragas_runtime_unavailable"
    assert set(result["query_results"][1]) == {
        "query_id",
        "backend",
        "status",
        "error_code",
        "latency_ms",
    }
    assert "secret-value" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize(
    ("metrics", "expected_error_code"),
    [
        ({"faithfulness": 1.0}, "ragas_metrics_incomplete"),
        ({**COMPLETE_RAGAS_METRICS, "faithfulness": float("nan")}, "ragas_metrics_invalid"),
        ({**COMPLETE_RAGAS_METRICS, "context_recall": 1.01}, "ragas_metrics_invalid"),
    ],
)
def test_run_ragas_rejects_incomplete_or_invalid_query_metrics(
    monkeypatch,
    metrics: dict[str, float],
    expected_error_code: str,
) -> None:
    monkeypatch.setattr(
        run_evaluation,
        "_generate_ragas_answers",
        lambda rows, **_kwargs: [{**rows[0], "answer": "생성 답변"}],
    )
    monkeypatch.setattr(
        run_evaluation,
        "_evaluate_ragas_samples",
        lambda _rows, **_kwargs: metrics,
    )

    result = run_evaluation.run_ragas(
        [ragas_record("law-q001")],
        generator_model="g",
        judge_model="j",
        embedding_model="e",
    )

    assert result["status"] == "not_evaluated"
    assert result["reason"] == "incomplete_ragas_evidence"
    assert "metrics" not in result
    assert result["query_results"][0]["status"] == "not_evaluated"
    assert result["query_results"][0]["error_code"] == expected_error_code


def test_run_ragas_averages_complete_metrics_only_after_every_query_succeeds(monkeypatch) -> None:
    metrics_by_query_id = {
        "law-q001": COMPLETE_RAGAS_METRICS,
        "law-q002": {
            "context_precision": 0.6,
            "context_recall": 0.5,
            "faithfulness": 0.7,
            "answer_relevancy": 0.8,
        },
    }
    monkeypatch.setattr(
        run_evaluation,
        "_generate_ragas_answers",
        lambda rows, **_kwargs: [{**rows[0], "answer": "생성 답변"}],
    )
    monkeypatch.setattr(
        run_evaluation,
        "_evaluate_ragas_samples",
        lambda rows, **_kwargs: metrics_by_query_id[rows[0]["query_id"]],
    )

    result = run_evaluation.run_ragas(
        [ragas_record("law-q001"), ragas_record("law-q002")],
        generator_model="g",
        judge_model="j",
        embedding_model="e",
    )

    assert result["status"] == "evaluated"
    assert result["metrics"] == {
        "context_precision": 0.7,
        "context_recall": 0.6,
        "faithfulness": 0.8,
        "answer_relevancy": 0.7,
    }
    assert [row["status"] for row in result["query_results"]] == ["evaluated", "evaluated"]


def test_run_ragas_skips_empty_contexts_without_calling_external_services(monkeypatch) -> None:
    def should_not_run(*_args, **_kwargs):
        raise AssertionError("empty contexts must not invoke an external RAGAS service")

    monkeypatch.setattr(run_evaluation, "_generate_ragas_answers", should_not_run)
    monkeypatch.setattr(run_evaluation, "_evaluate_ragas_samples", should_not_run)

    result = run_evaluation.run_ragas(
        [ragas_record("law-q001", contexts=[])],
        generator_model="g",
        judge_model="j",
        embedding_model="e",
    )

    assert result["status"] == "not_evaluated"
    assert result["reason"] == "incomplete_ragas_evidence"
    assert result["query_results"] == [
        {
            "query_id": "law-q001",
            "backend": "postgres_lexical",
            "status": "not_evaluated",
            "error_code": "no_ragas_contexts",
            "latency_ms": 0,
        }
    ]


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


def test_transition_decision_rejects_missing_ragas_evidence() -> None:
    summary = {
        "postgres_lexical": {
            "recall_at_5": 1.0,
            "mrr": 1.0,
            "ndcg_at_5": 1.0,
            "no_result_rate": 0.0,
            "p95_latency_ms": 10,
            "metadata_complete_rate": 1.0,
        },
        "postgres_pgvector": {
            "recall_at_5": 1.0,
            "mrr": 1.0,
            "ndcg_at_5": 1.0,
            "no_result_rate": 0.0,
            "p95_latency_ms": 10,
            "metadata_complete_rate": 1.0,
        },
    }

    decision = evaluation.transition_decision(
        summary,
        {
            "postgres_lexical": {"status": "not_evaluated"},
            "postgres_pgvector": {"status": "not_evaluated"},
        },
    )

    assert decision["eligible"] is False
    assert "ragas_not_evaluated" in decision["failed_gates"]


def test_transition_decision_rejects_vector_quality_regression() -> None:
    summary = {
        "postgres_lexical": {
            "recall_at_5": 1.0,
            "mrr": 1.0,
            "ndcg_at_5": 1.0,
            "no_result_rate": 0.0,
            "p95_latency_ms": 10,
            "metadata_complete_rate": 1.0,
        },
        "postgres_pgvector": {
            "recall_at_5": 0.9,
            "mrr": 0.97,
            "ndcg_at_5": 0.97,
            "no_result_rate": 0.1,
            "p95_latency_ms": 20,
            "metadata_complete_rate": 0.9,
        },
    }
    ragas = {
        "postgres_lexical": {"status": "evaluated", "metrics": {"context_recall": 1.0, "faithfulness": 1.0}},
        "postgres_pgvector": {"status": "evaluated", "metrics": {"context_recall": 0.9, "faithfulness": 0.9}},
    }

    decision = evaluation.transition_decision(summary, ragas)

    assert decision["eligible"] is False
    assert set(decision["failed_gates"]) >= {
        "recall_at_5_regression",
        "mrr_regression",
        "ndcg_at_5_regression",
        "no_result_rate_regression",
        "p95_latency_regression",
        "metadata_incomplete",
        "ragas_context_recall_regression",
        "ragas_faithfulness_regression",
    }


def test_summary_counts_disabled_backend_as_not_ready() -> None:
    summary = evaluation.summarize_backend_runs(
        [
            {
                "query_id": "law-q001",
                "backend": "postgres_pgvector",
                "status": "disabled",
                "latency_ms": 0,
                "results": [],
            }
        ],
        [{"query_id": "law-q001", "expected_source_references": ["도로교통법|제5조"]}],
    )

    assert summary["postgres_pgvector"]["unavailable_rate"] == 1.0
