"""Run a local, public-law-only PostgreSQL lexical ↔ pgvector comparison."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from etl.legal import evaluation


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = PROJECT_ROOT / "etl" / "legal" / "evaluation_fixtures" / "public_law_queries.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output" / "law_ingestion" / "evaluation"
BACKENDS = ("postgres_lexical", "postgres_pgvector")
MAX_RAGAS_QUERY_COUNT = 20


def _load_service():
    backend_path = str(PROJECT_ROOT / "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from app.services import legal_rag_service

    return legal_rag_service


service = _load_service()


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

    responses: list[dict[str, Any]] = []
    for query in queries:
        query_id = _required_text(query, "query_id")
        query_text = _required_text(query, "query")
        temporal_basis = query.get("temporal_basis")
        scope = query.get("scope")
        allowed_source_types, effective_at, filter_error = service.resolve_legal_search_filters(
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

        lexical_response = service._search_law_chunks_lexical(
            query_text,
            top_k=top_k,
            source_type="law",
            allowed_source_types=allowed_source_types,
            effective_at=effective_at,
        )
        vector_response = service._search_pgvector(
            query_text,
            top_k=top_k,
            source_type="law",
            allowed_source_types=allowed_source_types,
            effective_at=effective_at,
        )
        responses.extend(
            (
                {**lexical_response, "query_id": query_id},
                {**vector_response, "query_id": query_id},
            )
        )
    return responses


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

    try:
        answered_records = _generate_ragas_answers(records, model=generator_model)
        metrics = _evaluate_ragas_samples(
            answered_records,
            judge_model=judge_model,
            embedding_model=embedding_model,
        )
    except ImportError:
        return {"status": "not_evaluated", "reason": "ragas_dependencies_not_installed"}
    except RuntimeError as exc:
        return {"status": "not_evaluated", "reason": _safe_ragas_reason(exc)}
    except Exception:
        return {"status": "not_evaluated", "reason": "ragas_execution_failed"}
    return {
        "status": "evaluated",
        "generator_model": generator_model,
        "judge_model": judge_model,
        "embedding_model": embedding_model,
        "metrics": metrics,
    }


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

    from datasets import Dataset
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

    dataset = Dataset.from_list(
        [
            {
                "question": _required_text(record, "question"),
                "ground_truth": _required_text(record, "ground_truth"),
                "answer": _required_text(record, "answer"),
                "contexts": [
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
    return {
        metric: round(float(value), 6)
        for metric, value in dict(result).items()
        if metric in {"context_precision", "context_recall", "faithfulness", "answer_relevancy"}
    }


def _safe_ragas_reason(exc: RuntimeError) -> str:
    reason = str(exc)
    return reason if reason in {"openai_api_key_missing", "empty_generated_answer"} else "ragas_runtime_unavailable"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
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
    queries = evaluation.load_public_law_queries(args.fixture)
    responses = collect_backend_responses(queries, top_k=args.top_k)
    runs = [
        evaluation.normalize_backend_response(_required_text(response, "query_id"), response)
        for response in responses
    ]
    summary = evaluation.summarize_backend_runs(runs, queries)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
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
            "backends": summary,
            "ragas": ragas_result,
            "transition_decision": decision,
        },
    )
    print(f"Wrote deterministic legal RAG evaluation artifacts to {output_dir}")
    return 0


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
