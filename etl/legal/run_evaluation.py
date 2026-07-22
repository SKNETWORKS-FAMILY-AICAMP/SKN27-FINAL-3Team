"""Run a local, public-law-only PostgreSQL lexical ↔ pgvector comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Sequence

from etl.legal import evaluation, evaluation_environment


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = PROJECT_ROOT / "etl" / "legal" / "evaluation_fixtures" / "public_law_queries.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output" / "law_ingestion" / "evaluation"
BACKENDS = ("postgres_lexical", "postgres_pgvector")
MAX_RAGAS_QUERY_COUNT = 20
RAGAS_METRIC_NAMES = (
    "context_precision",
    "context_recall",
    "faithfulness",
    "answer_relevancy",
)


def _load_service():
    backend_path = str(PROJECT_ROOT / "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from app.services import legal_rag_service

    return legal_rag_service


service: Any | None = None


def _get_service():
    """Initialize Django only after the explicit evaluation environment is validated."""

    global service
    if service is None:
        service = _load_service()
    return service


def collect_backend_runs(
    queries: Sequence[Mapping[str, object]],
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Call lexical and pgvector directly with identical resolved search filters."""

    return [
        evaluation.normalize_backend_response(_required_text(response, "query_id"), response)
        for response in collect_backend_responses(queries, top_k=top_k)
    ]


def collect_backend_responses(
    queries: Sequence[Mapping[str, object]],
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Collect raw public-law responses once for metrics and optional RAGAS input."""

    if top_k <= 0:
        raise ValueError("top_k must be greater than zero")

    rag_service = _get_service()
    responses: list[dict[str, Any]] = []
    for query in queries:
        query_id = _required_text(query, "query_id")
        query_text = _required_text(query, "query")
        temporal_basis = query.get("temporal_basis")
        scope = query.get("scope")
        allowed_source_types, effective_at, filter_error = rag_service.resolve_legal_search_filters(
            source_type="law",
            temporal_basis=temporal_basis if isinstance(temporal_basis, dict) else None,
            scope=scope if isinstance(scope, dict) else None,
        )

        if filter_error:
            for backend in BACKENDS:
                responses.append(
                    {
                        "query_id": query_id,
                        "backend": backend,
                        "status": "invalid_filter",
                        "latency_ms": 0,
                        "error_code": filter_error,
                        "results": [],
                    }
                )
            continue

        lexical_response = rag_service._search_law_chunks_lexical(
            query_text,
            top_k=top_k,
            source_type="law",
            allowed_source_types=allowed_source_types,
            effective_at=effective_at,
        )
        vector_response = rag_service._search_pgvector(
            query_text,
            top_k=top_k,
            source_type="law",
            allowed_source_types=allowed_source_types,
            effective_at=effective_at,
        )
        responses.extend(
            (
                _evaluation_response(lexical_response, query_id=query_id),
                _evaluation_response(vector_response, query_id=query_id),
            )
        )
    return responses


def _evaluation_response(response: Mapping[str, Any], *, query_id: str) -> dict[str, Any]:
    sanitized = dict(response)
    sanitized["query_id"] = query_id
    sanitized["error_code"] = _safe_evaluation_error_code(sanitized.get("error_code"))
    return sanitized


def _safe_evaluation_error_code(value: object) -> str:
    error_code = str(value or "").strip()
    if not error_code:
        return ""
    if error_code in {
        "vector_disabled",
        "source_type_not_supported",
        "postgresql_connection_required",
        "no_eligible_seed_embeddings",
        "query_embedding_disabled",
        "embedding_space_mismatch",
        "query_embedding_space_not_configured",
        "sentence_transformers_unavailable",
        "openai_api_key_required",
        "openai_sdk_unavailable",
        "django_apps_not_ready",
        "no_search_tokens",
    }:
        return error_code
    normalized = error_code.lower()
    if "incorrect api key" in normalized or "authentication" in normalized or "error code: 401" in normalized:
        return "openai_authentication_failed"
    if error_code.startswith("missing_tables:"):
        return "rag_tables_missing"
    if error_code.startswith("unsupported_embedding_provider:"):
        return "unsupported_embedding_provider"
    return "backend_runtime_unavailable"


def build_ragas_records(
    queries: Sequence[Mapping[str, object]],
    responses: Sequence[Mapping[str, object]],
) -> list[dict[str, Any]]:
    """Prepare local RAGAS inputs from public-law contexts, capped to five per backend."""

    public_queries: dict[str, Mapping[str, object]] = {}
    for query in queries:
        if query.get("data_classification") != "public_law":
            raise ValueError("RAGAS input must be limited to public_law queries")
        query_id = _required_text(query, "query_id")
        public_queries[query_id] = query

    records: list[dict[str, Any]] = []
    for response in responses:
        query_id = _required_text(response, "query_id")
        query = public_queries.get(query_id)
        if query is None:
            continue
        raw_results = response.get("results")
        results = raw_results if isinstance(raw_results, list) else []
        contexts = [
            text.strip()
            for result in results[:5]
            if isinstance(result, Mapping)
            for text in [result.get("provision_text")]
            if isinstance(text, str) and text.strip()
        ]
        records.append(
            {
                "query_id": query_id,
                "backend": _required_text(response, "backend"),
                "question": _required_text(query, "query"),
                "ground_truth": _required_text(query, "reference_answer"),
                "contexts": contexts,
            }
        )
    return records


def run_ragas(
    records: Sequence[Mapping[str, object]],
    *,
    generator_model: str,
    judge_model: str,
    embedding_model: str,
) -> dict[str, Any]:
    """Evaluate public legal A/B records with one fixed generator and judge configuration."""

    query_ids = {_required_text(record, "query_id") for record in records}
    if len(query_ids) > MAX_RAGAS_QUERY_COUNT:
        raise ValueError(f"RAGAS evaluation supports at most {MAX_RAGAS_QUERY_COUNT} public questions")
    if not records:
        return {"status": "not_evaluated", "reason": "no_ragas_records"}

    query_results: list[dict[str, object]] = []
    per_query_metrics: list[Mapping[str, object]] = []
    for record in records:
        if not _has_ragas_contexts(record):
            query_results.append(
                _ragas_query_result(
                    record,
                    status="not_evaluated",
                    error_code="no_ragas_contexts",
                    latency_ms=0,
                )
            )
            continue

        started_at = perf_counter()
        try:
            answered_records = _generate_ragas_answers([record], model=generator_model)
            metrics = _evaluate_ragas_samples(
                answered_records,
                judge_model=judge_model,
                embedding_model=embedding_model,
            )
        except Exception as exc:
            query_results.append(
                _ragas_query_result(
                    record,
                    status="not_evaluated",
                    error_code=_safe_ragas_error_code(exc),
                    latency_ms=_elapsed_milliseconds(started_at),
                )
            )
            continue

        metrics_error_code = _ragas_metrics_error_code(metrics)
        if metrics_error_code:
            query_results.append(
                _ragas_query_result(
                    record,
                    status="not_evaluated",
                    error_code=metrics_error_code,
                    latency_ms=_elapsed_milliseconds(started_at),
                )
            )
            continue

        per_query_metrics.append(metrics)
        query_results.append(
            _ragas_query_result(
                record,
                status="evaluated",
                error_code=None,
                latency_ms=_elapsed_milliseconds(started_at),
            )
        )

    result: dict[str, Any] = {
        "generator_model": generator_model,
        "judge_model": judge_model,
        "embedding_model": embedding_model,
        "query_results": query_results,
    }
    if any(query_result["status"] != "evaluated" for query_result in query_results):
        return {
            "status": "not_evaluated",
            "reason": "incomplete_ragas_evidence",
            **result,
        }

    return {
        "status": "evaluated",
        **result,
        "metrics": summarize_ragas_scores(per_query_metrics),
    }


def _ragas_query_result(
    record: Mapping[str, object],
    *,
    status: str,
    error_code: str | None,
    latency_ms: int,
) -> dict[str, object]:
    return {
        "query_id": _required_text(record, "query_id"),
        "backend": _required_text(record, "backend"),
        "status": status,
        "error_code": error_code,
        "latency_ms": latency_ms,
    }


def _elapsed_milliseconds(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))


def _has_ragas_contexts(record: Mapping[str, object]) -> bool:
    contexts = record.get("contexts")
    return isinstance(contexts, list) and any(
        isinstance(context, str) and context.strip() for context in contexts
    )


def _safe_ragas_error_code(exc: Exception) -> str:
    if isinstance(exc, ImportError):
        return "ragas_dependencies_not_installed"
    if isinstance(exc, RuntimeError):
        return _safe_ragas_reason(exc)
    return "ragas_runtime_unavailable"


def _ragas_metrics_error_code(metrics: object) -> str | None:
    if not isinstance(metrics, Mapping):
        return "ragas_metrics_invalid"
    if any(metric_name not in metrics for metric_name in RAGAS_METRIC_NAMES):
        return "ragas_metrics_incomplete"
    for metric_name in RAGAS_METRIC_NAMES:
        value = metrics[metric_name]
        if isinstance(value, bool):
            return "ragas_metrics_invalid"
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return "ragas_metrics_invalid"
        if not math.isfinite(numeric_value) or not 0 <= numeric_value <= 1:
            return "ragas_metrics_invalid"
    return None


def _generate_ragas_answers(
    records: Sequence[Mapping[str, object]],
    *,
    model: str,
) -> list[dict[str, Any]]:
    """Generate one answer per backend from only the retrieved public-law contexts."""

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("openai_api_key_missing")
    from openai import OpenAI

    client = OpenAI()
    answered: list[dict[str, Any]] = []
    for record in records:
        contexts = record.get("contexts")
        if not isinstance(contexts, list):
            contexts = []
        context_text = "\n\n".join(
            text.strip() for text in contexts if isinstance(text, str) and text.strip()
        )
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": "답변은 제공된 공개 법령 근거만 사용하고, 근거가 부족하면 부족하다고 답하세요.",
                },
                {
                    "role": "user",
                    "content": f"질문:\n{_required_text(record, 'question')}\n\n법령 근거:\n{context_text}",
                },
            ],
        )
        answer = response.choices[0].message.content or ""
        if not answer.strip():
            raise RuntimeError("empty_generated_answer")
        answered.append({**record, "answer": answer.strip()})
    return answered


def _evaluate_ragas_samples(
    records: Sequence[Mapping[str, object]],
    *,
    judge_model: str,
    embedding_model: str,
) -> dict[str, float]:
    """Run the version-pinned legacy RAGAS API with explicit judge and embedding models."""

    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import evaluate
    from ragas.dataset_schema import EvaluationDataset
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

    dataset = EvaluationDataset.from_list(
        [
            {
                "user_input": _required_text(record, "question"),
                "reference": _required_text(record, "ground_truth"),
                "response": _required_text(record, "answer"),
                "retrieved_contexts": [
                    text for text in record.get("contexts", []) if isinstance(text, str) and text.strip()
                ],
            }
            for record in records
        ]
    )
    judge_llm = LangchainLLMWrapper(ChatOpenAI(model=judge_model, temperature=0))
    embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model=embedding_model))
    result = evaluate(
        dataset,
        metrics=[context_precision, context_recall, faithfulness, answer_relevancy],
        llm=judge_llm,
        embeddings=embeddings,
        raise_exceptions=True,
    )
    return summarize_ragas_scores(result.scores)


def summarize_ragas_scores(scores: Sequence[Mapping[str, object]]) -> dict[str, float]:
    summary: dict[str, float] = {}
    for metric_name in RAGAS_METRIC_NAMES:
        values: list[float] = []
        for score in scores:
            try:
                value = float(score.get(metric_name))
            except (TypeError, ValueError):
                continue
            if not math.isnan(value):
                values.append(value)
        if values:
            summary[metric_name] = round(sum(values) / len(values), 6)
    return summary


def _safe_ragas_reason(exc: RuntimeError) -> str:
    reason = str(exc)
    return reason if reason in {"openai_api_key_missing", "empty_generated_answer"} else "ragas_runtime_unavailable"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.rag-eval")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--run-ragas", action="store_true")
    parser.add_argument("--ragas-generator-model", default="gpt-4o-mini")
    parser.add_argument("--ragas-judge-model", default="gpt-4o-mini")
    parser.add_argument("--ragas-embedding-model", default="text-embedding-3-small")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        environment_values = evaluation_environment.load_evaluation_environment(args.env_file)
    except (FileNotFoundError, ValueError):
        return _write_not_ready_summary(
            output_dir,
            run_id=run_id,
            args=args,
            preflight={"status": "not_ready", "reason": "evaluation_environment_invalid"},
        )

    environment = evaluation_environment.validate_evaluation_environment(environment_values)
    if environment["status"] != "ready":
        return _write_not_ready_summary(
            output_dir,
            run_id=run_id,
            args=args,
            preflight={"status": "not_ready", "reason": "evaluation_environment_invalid", "environment": environment},
        )

    evaluation_environment.apply_evaluation_environment(environment_values)
    _get_service()
    from django.db import connection

    preflight = collect_evaluation_preflight(
        connection,
        expected_embedding_space=environment["seed_embedding_space"],
    )
    if preflight["status"] != "ready":
        return _write_not_ready_summary(output_dir, run_id=run_id, args=args, preflight=preflight)

    queries = evaluation.load_public_law_queries(args.fixture)
    responses = collect_backend_responses(queries, top_k=args.top_k)
    runs = [
        evaluation.normalize_backend_response(_required_text(response, "query_id"), response)
        for response in responses
    ]
    summary = evaluation.summarize_backend_runs(runs, queries)
    _write_json(output_dir / "candidates.json", {"runs": runs})
    ragas_records = build_ragas_records(queries, responses)
    _write_jsonl(output_dir / "ragas_input.jsonl", ragas_records)
    ragas_result = _run_ragas_by_backend(
        ragas_records,
        enabled=args.run_ragas,
        generator_model=args.ragas_generator_model,
        judge_model=args.ragas_judge_model,
        embedding_model=args.ragas_embedding_model,
    )
    decision = evaluation.transition_decision(summary, ragas_result)
    _write_json(
        output_dir / "summary.json",
        {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fixture": str(args.fixture),
            "query_count": len(queries),
            "top_k": args.top_k,
            "preflight": preflight,
            "backends": summary,
            "ragas": ragas_result,
            "transition_decision": decision,
        },
    )
    print(f"Wrote deterministic legal RAG evaluation artifacts to {output_dir}")
    return 0


def collect_evaluation_preflight(
    connection: Any,
    *,
    expected_embedding_space: Mapping[str, object],
) -> dict[str, Any]:
    """Verify only aggregate seed state before either backend is queried."""

    if getattr(connection, "vendor", "") != "postgresql":
        return {"status": "not_ready", "reason": "postgresql_required"}
    try:
        table_names = sorted(connection.introspection.table_names())
    except Exception:
        return {"status": "not_ready", "reason": "database_introspection_unavailable"}
    required_tables = {"law_chunks", "law_embeddings"}
    if not required_tables.issubset(table_names):
        return {"status": "not_ready", "reason": "law_rag_tables_missing", "table_names": table_names}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM law_chunks WHERE is_searchable = TRUE;")
            searchable_chunks = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM law_embeddings;")
            embeddings = int(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT embedding_provider, embedding_model, embedding_dimensions, COUNT(*)
                FROM law_embeddings
                GROUP BY embedding_provider, embedding_model, embedding_dimensions
                ORDER BY embedding_provider, embedding_model, embedding_dimensions
                """
            )
            embedding_spaces = [
                {
                    "provider": str(provider),
                    "model": str(model),
                    "dimensions": int(dimensions),
                    "count": int(count),
                }
                for provider, model, dimensions, count in cursor.fetchall()
            ]
            cursor.execute("SELECT chunk_id FROM law_embeddings ORDER BY chunk_id;")
            snapshot = hashlib.sha256()
            for (chunk_id,) in cursor.fetchall():
                snapshot.update(str(chunk_id).encode("utf-8"))
                snapshot.update(b"\n")
    except Exception:
        return {"status": "not_ready", "reason": "database_query_unavailable"}

    result: dict[str, Any] = {
        "status": "ready",
        "reason": "",
        "searchable_chunks": searchable_chunks,
        "embeddings": embeddings,
        "embedding_spaces": embedding_spaces,
        "corpus_snapshot": snapshot.hexdigest(),
    }
    if searchable_chunks == 0 or embeddings == 0:
        result.update(status="not_ready", reason="law_rag_seed_missing")
        return result
    expected = {
        "provider": str(expected_embedding_space.get("provider") or ""),
        "model": str(expected_embedding_space.get("model") or ""),
        "dimensions": int(expected_embedding_space.get("dimensions") or 0),
    }
    matching_spaces = [
        space
        for space in embedding_spaces
        if {key: space[key] for key in expected} == expected
    ]
    if len(embedding_spaces) != 1:
        result.update(status="not_ready", reason="seed_embedding_space_ambiguous")
    elif not matching_spaces:
        result.update(status="not_ready", reason="seed_embedding_space_mismatch")
    return result


def _write_not_ready_summary(
    output_dir: Path,
    *,
    run_id: str,
    args: argparse.Namespace,
    preflight: Mapping[str, object],
) -> int:
    _write_json(
        output_dir / "summary.json",
        {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fixture": str(args.fixture),
            "query_count": 0,
            "top_k": args.top_k,
            "preflight": dict(preflight),
            "backends": {},
            "ragas": {
                backend: {"status": "not_evaluated", "reason": "preflight_not_ready"}
                for backend in BACKENDS
            },
            "transition_decision": {"eligible": False, "failed_gates": ["preflight_not_ready"]},
        },
    )
    print(f"Wrote not-ready legal RAG evaluation summary to {output_dir}")
    return 2


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _run_ragas_by_backend(
    records: Sequence[Mapping[str, object]],
    *,
    enabled: bool,
    generator_model: str,
    judge_model: str,
    embedding_model: str,
) -> dict[str, dict[str, Any]]:
    by_backend = {
        backend: [record for record in records if record.get("backend") == backend]
        for backend in BACKENDS
    }
    if not enabled:
        return {
            backend: {"status": "not_evaluated", "reason": "run_ragas_not_requested"}
            for backend in BACKENDS
        }
    return {
        backend: run_ragas(
            backend_records,
            generator_model=generator_model,
            judge_model=judge_model,
            embedding_model=embedding_model,
        )
        for backend, backend_records in by_backend.items()
    }


def _required_text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


if __name__ == "__main__":
    raise SystemExit(main())
