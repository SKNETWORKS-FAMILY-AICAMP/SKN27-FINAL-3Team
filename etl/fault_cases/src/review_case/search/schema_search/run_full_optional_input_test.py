from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from etl.fault_cases.src.review_case.db_loading.db_config import ARTIFACT_ROOT, PROJECT_ROOT
from etl.fault_cases.src.review_case.search.elasticsearch.bm25_retriever import search_bm25
from etl.fault_cases.src.review_case.search.elasticsearch.hybrid_retriever import search_hybrid
from etl.fault_cases.src.review_case.search.pgvector.retriever import search_query as search_pgvector


DEFAULT_INPUT_PATH = (
    ARTIFACT_ROOT
    / "schema_search_test"
    / "text_ml_case_search_agent_input_full_optional_fields.jsonl"
)
DEFAULT_OUTPUT_DIR = ARTIFACT_ROOT / "schema_search_test"
DEFAULT_REPORT_MD_PATH = (
    PROJECT_ROOT
    / "etl"
    / "fault_cases"
    / "Fault_cases_MD"
    / "심의사례"
    / "심의사례 스키마 검색 테스트 결과 스코어 및 보고서.md"
)
DEFAULT_MODEL = "models/bge-reranker-v2-m3"
DEFAULT_TOP_K = 5
DEFAULT_CANDIDATE_K = 10


@dataclass(frozen=True)
class TestCase:
    query_id: str
    agent_input: dict[str, Any]


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1 / (1 + z)
    z = math.exp(value)
    return z / (1 + z)


def load_test_cases(path: Path) -> list[TestCase]:
    cases: list[TestCase] = []
    active_index = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            active_index += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {line_no}: {exc}") from exc
            agent_input = row.get("agent_input") or {}
            message_id = agent_input.get("message_id") or f"msg_{active_index:04d}"
            cases.append(TestCase(query_id=f"full_optional_{message_id}", agent_input=agent_input))
    return cases


def compact_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, list):
        return " ".join(part for item in value if (part := compact_text(item)))
    if isinstance(value, dict):
        return " ".join(part for item in value.values() if (part := compact_text(item)))
    return str(value)


def build_optional_context_text(agent_input: dict[str, Any]) -> str:
    query_text = compact_text(agent_input.get("query_text"))
    raw_user_text = compact_text(agent_input.get("raw_user_text"))
    vision_evidence = agent_input.get("vision_evidence") or []
    ocr = agent_input.get("ocr_evidence") or {}
    insurer_claim = agent_input.get("insurer_claim") or {}

    parts: list[str] = []
    if query_text:
        parts.append(f"[질문] {query_text}")
    if raw_user_text and raw_user_text != query_text:
        parts.append(f"[사용자 원문] {raw_user_text}")

    for item in vision_evidence:
        description = compact_text(item.get("description"))
        observations = compact_text(item.get("observations"))
        if description or observations:
            parts.append(f"[영상 단서] {description} {observations}".strip())

    ocr_text = compact_text(
        [
            ocr.get("accident_type"),
            ocr.get("accident_cause"),
            ocr.get("accident_description"),
            ocr.get("accident_location"),
            ocr.get("extracted_fields"),
        ]
    )
    if ocr_text:
        parts.append(f"[OCR 단서] {ocr_text}")

    claim_text = compact_text(
        [
            insurer_claim.get("claimed_ratio"),
            insurer_claim.get("reason_text"),
            insurer_claim.get("source_text"),
        ]
    )
    if claim_text:
        parts.append(f"[보험사 주장] {claim_text}")

    return "\n".join(parts)


def build_input_variants(agent_input: dict[str, Any]) -> dict[str, str]:
    query_text = compact_text(agent_input.get("query_text"))
    full_optional = build_optional_context_text(agent_input)
    return {
        "query_text": query_text,
        "full_optional_context": full_optional or query_text,
    }


def get_text_for_rerank(row: dict[str, Any]) -> str:
    return row.get("chunk_text") or row.get("search_text") or row.get("chunk_preview") or row.get("search_preview") or ""


def load_cross_encoder(model_name: str, device: str | None):
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise RuntimeError("sentence-transformers is required for local reranker scoring.") from exc
    kwargs = {"device": device} if device else {}
    return CrossEncoder(model_name, **kwargs)


def score_pairs(model: Any, pairs: list[tuple[str, str]], batch_size: int) -> list[float]:
    if not pairs:
        return []
    raw_scores = model.predict(pairs, batch_size=batch_size, show_progress_bar=True)
    return [sigmoid(float(score)) for score in raw_scores]


def normalize_result(
    *,
    case: TestCase,
    input_variant: str,
    search_query: str,
    retriever: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    score_by_retriever = {
        "pgvector_cosine": row.get("cosine_similarity"),
        "bm25_nori": row.get("bm25_score"),
        "hybrid": row.get("hybrid_score"),
    }
    score_type_by_retriever = {
        "pgvector_cosine": "cosine_similarity",
        "bm25_nori": "bm25_score",
        "hybrid": "rrf_bm25_vector_score",
    }
    chunk_text = str(row.get("chunk_text") or "")
    search_text = str(row.get("search_text") or "")
    return {
        "query_id": case.query_id,
        "message_id": case.agent_input.get("message_id"),
        "session_id": case.agent_input.get("session_id"),
        "job_id": case.agent_input.get("job_id"),
        "input_variant": input_variant,
        "query": search_query,
        "retriever": retriever,
        "rank": row.get("rank"),
        "review_case_id": row.get("review_case_id"),
        "review_no": row.get("review_no"),
        "chunk_id": row.get("chunk_id"),
        "chunk_type": row.get("chunk_type"),
        "case_title": row.get("case_title"),
        "reference_chart_key": row.get("reference_chart_key"),
        "decision_fault_ratio": row.get("decision_fault_ratio"),
        "claimant_final_ratio": row.get("claimant_final_ratio"),
        "respondent_final_ratio": row.get("respondent_final_ratio"),
        "signal_condition": row.get("signal_condition"),
        "road_feature": row.get("road_feature"),
        "standard_a_behavior": row.get("standard_a_behavior"),
        "standard_b_behavior": row.get("standard_b_behavior"),
        "retriever_score": score_by_retriever.get(retriever),
        "score_type": score_type_by_retriever.get(retriever),
        "cosine_similarity": row.get("cosine_similarity"),
        "cosine_distance": row.get("cosine_distance"),
        "bm25_rank": row.get("bm25_rank"),
        "bm25_score": row.get("bm25_score"),
        "vector_rank": row.get("vector_rank"),
        "vector_score": row.get("vector_score"),
        "hybrid_score": row.get("hybrid_score"),
        "candidate_text_char_len": len(get_text_for_rerank(row)),
        "chunk_preview": chunk_text[:500],
        "search_preview": search_text[:500],
        "highlight": row.get("highlight") or {},
    }


def append_candidate(
    *,
    rows: list[dict[str, Any]],
    reranker_pairs: list[tuple[str, str]],
    reranker_rows: list[dict[str, Any]],
    case: TestCase,
    input_variant: str,
    search_query: str,
    retriever: str,
    row: dict[str, Any],
) -> None:
    normalized = normalize_result(
        case=case,
        input_variant=input_variant,
        search_query=search_query,
        retriever=retriever,
        row=row,
    )
    rows.append(normalized)
    reranker_pairs.append((search_query, get_text_for_rerank(row)))
    reranker_rows.append(normalized)


def run_search(
    *,
    input_path: Path,
    output_dir: Path,
    report_md_path: Path,
    top_k: int,
    candidate_k: int,
    model_name: str,
    batch_size: int,
    device: str | None,
    limit: int | None,
    include_query_text: bool,
    include_full_optional_context: bool,
) -> dict[str, Any]:
    cases = load_test_cases(input_path)
    if limit is not None:
        cases = cases[:limit]

    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    reranker_pairs: list[tuple[str, str]] = []
    reranker_rows: list[dict[str, Any]] = []

    for case in cases:
        input_variants = build_input_variants(case.agent_input)
        if not include_query_text:
            input_variants.pop("query_text", None)
        if not include_full_optional_context:
            input_variants.pop("full_optional_context", None)

        for input_variant, search_query in input_variants.items():
            if not search_query:
                errors.append({"query_id": case.query_id, "input_variant": input_variant, "error": "empty query"})
                continue

            try:
                for row in search_pgvector(query=search_query, top_k=top_k):
                    append_candidate(
                        rows=rows,
                        reranker_pairs=reranker_pairs,
                        reranker_rows=reranker_rows,
                        case=case,
                        input_variant=input_variant,
                        search_query=search_query,
                        retriever="pgvector_cosine",
                        row=row,
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "query_id": case.query_id,
                        "input_variant": input_variant,
                        "retriever": "pgvector_cosine",
                        "error": repr(exc),
                    }
                )

            try:
                for row in search_bm25(query=search_query, top_k=top_k):
                    append_candidate(
                        rows=rows,
                        reranker_pairs=reranker_pairs,
                        reranker_rows=reranker_rows,
                        case=case,
                        input_variant=input_variant,
                        search_query=search_query,
                        retriever="bm25_nori",
                        row=row,
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "query_id": case.query_id,
                        "input_variant": input_variant,
                        "retriever": "bm25_nori",
                        "error": repr(exc),
                    }
                )

            try:
                for row in search_hybrid(query=search_query, top_k=top_k, candidate_k=candidate_k):
                    append_candidate(
                        rows=rows,
                        reranker_pairs=reranker_pairs,
                        reranker_rows=reranker_rows,
                        case=case,
                        input_variant=input_variant,
                        search_query=search_query,
                        retriever="hybrid",
                        row=row,
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "query_id": case.query_id,
                        "input_variant": input_variant,
                        "retriever": "hybrid",
                        "error": repr(exc),
                    }
                )

    if reranker_pairs:
        try:
            model = load_cross_encoder(model_name, device=device)
            reranker_scores = score_pairs(model, reranker_pairs, batch_size=batch_size)
            for row, score in zip(reranker_rows, reranker_scores, strict=True):
                row["common_reranker_model"] = model_name
                row["common_reranker_score"] = score
        except Exception as exc:  # noqa: BLE001
            errors.append({"stage": "common_reranker_scoring", "error": repr(exc)})

    elapsed = time.perf_counter() - started
    output_dir.mkdir(parents=True, exist_ok=True)
    report_md_path.parent.mkdir(parents=True, exist_ok=True)

    candidates_path = output_dir / "text_ml_case_search_schema_search_candidates.jsonl"
    summary_path = output_dir / "text_ml_case_search_schema_search_summary.json"

    with candidates_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = build_summary(
        rows=rows,
        errors=errors,
        input_path=input_path,
        candidates_path=candidates_path,
        report_md_path=report_md_path,
        top_k=top_k,
        candidate_k=candidate_k,
        model_name=model_name,
        elapsed_seconds=elapsed,
        reranker_pair_count=len(reranker_pairs),
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report_md_path.write_text(build_markdown_report(summary), encoding="utf-8")

    return {
        **summary,
        "summary_path": str(summary_path),
        "report_md_path": str(report_md_path),
    }


def group_by(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(key) for key in keys)].append(row)
    return grouped


def score_for_summary(row: dict[str, Any]) -> float:
    value = row.get("retriever_score")
    return float(value) if value is not None else 0.0


def reranker_score(row: dict[str, Any]) -> float | None:
    value = row.get("common_reranker_score")
    return float(value) if value is not None else None


def build_summary(
    *,
    rows: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    input_path: Path,
    candidates_path: Path,
    report_md_path: Path,
    top_k: int,
    candidate_k: int,
    model_name: str,
    elapsed_seconds: float,
    reranker_pair_count: int,
) -> dict[str, Any]:
    retriever_counts = Counter(row["retriever"] for row in rows)
    variant_counts = Counter(row["input_variant"] for row in rows)
    chunk_type_counts = Counter(row.get("chunk_type") or "" for row in rows)
    common_score_count = sum(1 for row in rows if row.get("common_reranker_score") is not None)

    group_metrics = []
    for (input_variant, retriever), group in sorted(group_by(rows, ("input_variant", "retriever")).items()):
        query_groups = group_by(group, ("query_id",))
        top1_internal_scores = []
        avg_internal_scores = []
        top1_common_scores = []
        avg_common_scores = []
        max_common_scores = []
        min_common_scores = []

        for query_rows in query_groups.values():
            sorted_rows = sorted(query_rows, key=lambda row: int(row.get("rank") or 9999))
            if sorted_rows:
                top1_internal_scores.append(score_for_summary(sorted_rows[0]))
                avg_internal_scores.append(mean(score_for_summary(row) for row in sorted_rows))
                top1_common = reranker_score(sorted_rows[0])
                if top1_common is not None:
                    top1_common_scores.append(top1_common)

            common_scores = [score for row in sorted_rows if (score := reranker_score(row)) is not None]
            if common_scores:
                avg_common_scores.append(mean(common_scores))
                max_common_scores.append(max(common_scores))
                min_common_scores.append(min(common_scores))

        group_metrics.append(
            {
                "input_variant": input_variant,
                "retriever": retriever,
                "query_count": len(query_groups),
                "candidate_count": len(group),
                "avg_top1_internal_score": mean(top1_internal_scores) if top1_internal_scores else None,
                "avg_at_5_internal_score": mean(avg_internal_scores) if avg_internal_scores else None,
                "top1_common_reranker_score": mean(top1_common_scores) if top1_common_scores else None,
                "avg_common_reranker_score": mean(avg_common_scores) if avg_common_scores else None,
                "max_common_reranker_score_at_5": mean(max_common_scores) if max_common_scores else None,
                "min_common_reranker_score_at_5": mean(min_common_scores) if min_common_scores else None,
                "chunk_type_counts": dict(Counter(row.get("chunk_type") or "" for row in group)),
            }
        )

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input_path": str(input_path),
        "candidates_path": str(candidates_path),
        "report_md_path": str(report_md_path),
        "active_test_case_count": len({row["query_id"] for row in rows}),
        "input_variant_count": len(variant_counts),
        "retriever_count": len(retriever_counts),
        "candidate_count": len(rows),
        "top_k": top_k,
        "candidate_k": candidate_k,
        "reranker_pair_count": reranker_pair_count,
        "common_reranker_score_not_null": common_score_count,
        "reranker_model": model_name,
        "elapsed_seconds": elapsed_seconds,
        "retriever_counts": dict(retriever_counts),
        "input_variant_counts": dict(variant_counts),
        "chunk_type_counts": dict(chunk_type_counts),
        "group_metrics": group_metrics,
        "error_count": len(errors),
        "errors": errors,
        "notes": [
            "JSONL lines starting with // are skipped as inactive test cases.",
            "pgvector_cosine and hybrid require query embeddings.",
            "Retriever internal scores have different scales and are for debugging only.",
            "Final comparison should use common_reranker_score because it is applied to every pgvector, BM25/Nori, and hybrid candidate.",
        ],
    }


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def build_markdown_report(summary: dict[str, Any]) -> str:
    metric_rows = [
        [
            row["input_variant"],
            row["retriever"],
            str(row["query_count"]),
            str(row["candidate_count"]),
            fmt(row["avg_top1_internal_score"]),
            fmt(row["avg_at_5_internal_score"]),
            fmt(row["top1_common_reranker_score"]),
            fmt(row["avg_common_reranker_score"]),
            fmt(row["max_common_reranker_score_at_5"]),
            json.dumps(row["chunk_type_counts"], ensure_ascii=False),
        ]
        for row in summary["group_metrics"]
    ]

    error_section = "없음"
    if summary["errors"]:
        error_section = "\n".join(
            f"- {item.get('query_id', '')} / {item.get('input_variant', '')} / {item.get('retriever', item.get('stage', ''))}: {item.get('error')}"
            for item in summary["errors"][:30]
        )

    return "\n\n".join(
        [
            "# 심의사례 스키마 검색 테스트 결과 스코어 및 보고서",
            f"생성일시: {summary['created_at']}",
            "## 1. 목적",
            "\n".join(
                [
                    "`text_ml_case_search` Agent 입력 JSONL을 기준으로 RAG 검색 입력이 정상 처리되는지 확인한다.",
                    "`//`로 시작하는 JSONL 라인은 비활성 테스트 케이스로 보고 건너뛴다.",
                    "비교 대상은 pgvector, BM25+Nori, Elasticsearch hybrid다.",
                    "검색기별 내부 점수는 스케일이 다르므로 최종 비교는 공통 로컬 reranker 점수로 수행한다.",
                ]
            ),
            "## 2. 실행 요약",
            "\n".join(
                [
                    f"- active_test_case_count: {summary['active_test_case_count']}",
                    f"- input_variant_count: {summary['input_variant_count']}",
                    f"- retriever_count: {summary['retriever_count']}",
                    f"- candidate_count: {summary['candidate_count']}",
                    f"- top_k: {summary['top_k']}",
                    f"- candidate_k: {summary['candidate_k']}",
                    f"- reranker_pair_count: {summary['reranker_pair_count']}",
                    f"- common_reranker_score_not_null: {summary['common_reranker_score_not_null']}",
                    f"- reranker_model: `{summary['reranker_model']}`",
                    f"- elapsed_seconds: {summary['elapsed_seconds']:.2f}",
                    f"- error_count: {summary['error_count']}",
                ]
            ),
            "## 3. 입력 Variant와 검색 방식별 점수",
            md_table(
                [
                    "Input Variant",
                    "Retriever",
                    "Query Count",
                    "Candidate Count",
                    "Avg Top1 Internal",
                    "Avg@5 Internal",
                    "Top1 Common",
                    "Avg Common@5",
                    "Max Common@5",
                    "Chunk Type Counts",
                ],
                metric_rows,
            ),
            "## 4. 점수 해석 기준",
            "\n".join(
                [
                    "BM25 점수, cosine similarity, hybrid RRF 점수는 서로 계산 방식과 범위가 다르다.",
                    "따라서 `retriever_score`는 같은 검색기 내부의 순위 확인과 디버깅에만 사용한다.",
                    "`common_reranker_score`는 동일한 로컬 CrossEncoder가 모든 후보를 다시 채점한 값이므로 검색 방식 간 비교에 사용한다.",
                    "이번 테스트에서 `common_reranker_score_not_null`이 `candidate_count`와 같아야 세 검색 방식이 공정하게 비교된 상태다.",
                ]
            ),
            "## 5. 오류 및 예외 사항",
            error_section,
            "## 6. 산출물",
            "\n".join(
                [
                    f"- candidates: `{summary['candidates_path']}`",
                    "- summary: `etl/fault_cases/artifacts/review_case_output/schema_search_test/text_ml_case_search_schema_search_summary.json`",
                    f"- report: `{summary['report_md_path']}`",
                ]
            ),
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run schema-based review_case RAG search tests.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD_PATH)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--candidate-k", type=int, default=DEFAULT_CANDIDATE_K)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only-query-text", action="store_true")
    parser.add_argument("--only-full-optional-context", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    include_query_text = not args.only_full_optional_context
    include_full_optional_context = not args.only_query_text
    summary = run_search(
        input_path=args.input,
        output_dir=args.output_dir,
        report_md_path=args.report_md,
        top_k=args.top_k,
        candidate_k=args.candidate_k,
        model_name=args.model,
        batch_size=args.batch_size,
        device=args.device,
        limit=args.limit,
        include_query_text=include_query_text,
        include_full_optional_context=include_full_optional_context,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
