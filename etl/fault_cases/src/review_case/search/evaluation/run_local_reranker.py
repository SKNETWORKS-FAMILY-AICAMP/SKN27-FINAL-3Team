from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from psycopg2.extras import RealDictCursor

from etl.fault_cases.src.review_case.db_loading.db_config import RETRIEVAL_AB_EXPORT_ROOT, SETTINGS
from etl.fault_cases.src.review_case.db_loading.db_connection import get_connection


DEFAULT_RERANKER_MODEL = "models/bge-reranker-v2-m3"
DEFAULT_INPUT_PATH = RETRIEVAL_AB_EXPORT_ROOT / "review_case_retrieval_ab_candidates.jsonl"
DEFAULT_OUTPUT_PATH = RETRIEVAL_AB_EXPORT_ROOT / "review_case_retrieval_ab_reranker_scores.jsonl"
DEFAULT_RUN_REPORT_PATH = RETRIEVAL_AB_EXPORT_ROOT / "review_case_retrieval_ab_reranker_run_report.json"


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1 / (1 + z)
    z = math.exp(value)
    return z / (1 + z)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def fetch_chunk_texts(chunk_ids: list[str]) -> dict[str, str]:
    if not chunk_ids:
        return {}
    sql = """
        SELECT chunk_id, chunk_text, search_text
        FROM review_case_chunks
        WHERE chunk_id = ANY(%s)
    """
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (chunk_ids,))
            return {
                row["chunk_id"]: row.get("chunk_text") or row.get("search_text") or ""
                for row in cur.fetchall()
            }


def enrich_chunk_texts(candidates: list[dict[str, Any]]) -> None:
    chunk_ids = sorted({row.get("chunk_id") for row in candidates if row.get("chunk_id")})
    texts = fetch_chunk_texts(chunk_ids)
    for row in candidates:
        row["chunk_text"] = texts.get(row.get("chunk_id"), row.get("chunk_preview") or "")


def build_pairs(candidates: list[dict[str, Any]], input_field: str) -> list[tuple[str, str]]:
    pairs = []
    for row in candidates:
        query = row.get("query") or ""
        text = row.get(input_field) or row.get("search_preview") or row.get("chunk_preview") or ""
        pairs.append((query, text))
    return pairs


def score_candidates(
    candidates: list[dict[str, Any]],
    model_name: str,
    input_field: str,
    batch_size: int,
    device: str | None,
) -> dict[str, Any]:
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers가 필요합니다. requirements 설치 여부를 확인하세요."
        ) from exc

    if input_field == "chunk_text":
        enrich_chunk_texts(candidates)

    model_kwargs = {"device": device} if device else {}
    model = CrossEncoder(model_name, **model_kwargs)
    pairs = build_pairs(candidates, input_field=input_field)

    started = time.perf_counter()
    raw_scores = model.predict(pairs, batch_size=batch_size, show_progress_bar=True)
    elapsed = time.perf_counter() - started

    for row, raw_score in zip(candidates, raw_scores, strict=True):
        raw_score_float = float(raw_score)
        text = row.get(input_field) or row.get("search_preview") or row.get("chunk_preview") or ""
        row["reranker_model"] = model_name
        row["reranker_input_field"] = input_field
        row["reranker_raw_score"] = raw_score_float
        row["local_reranker_score"] = sigmoid(raw_score_float)
        row["reranker_text_char_len"] = len(text)

    return {
        "candidate_count": len(candidates),
        "elapsed_seconds": elapsed,
        "avg_latency_ms_per_pair": (elapsed / len(candidates) * 1000) if candidates else 0,
    }


def run_evaluation(
    input_path: Path = DEFAULT_INPUT_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    run_report_path: Path = DEFAULT_RUN_REPORT_PATH,
    model_name: str = DEFAULT_RERANKER_MODEL,
    input_field: str = "chunk_text",
    batch_size: int = 4,
    limit: int | None = None,
    device: str | None = "cpu",
) -> dict[str, Any]:
    candidates = load_jsonl(input_path)
    if limit is not None:
        candidates = candidates[:limit]

    score_meta = score_candidates(
        candidates=candidates,
        model_name=model_name,
        input_field=input_field,
        batch_size=batch_size,
        device=device,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in candidates:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input_path": str(input_path),
        "output_path": str(output_path),
        "reranker_model": model_name,
        "reranker_input_field": input_field,
        "batch_size": batch_size,
        "limit": limit,
        "device": device,
        **score_meta,
    }
    run_report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score review_case retrieval A/B candidates with a local reranker.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--run-report", type=Path, default=DEFAULT_RUN_REPORT_PATH)
    parser.add_argument("--model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument(
        "--input-field",
        choices=["chunk_text", "search_preview", "chunk_preview"],
        default="chunk_text",
    )
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--device", default="cpu", help="Optional torch device such as cpu, cuda, or mps.")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    report = run_evaluation(
        input_path=args.input,
        output_path=args.output,
        run_report_path=args.run_report,
        model_name=args.model,
        input_field=args.input_field,
        batch_size=args.batch_size,
        limit=args.limit,
        device=args.device,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
