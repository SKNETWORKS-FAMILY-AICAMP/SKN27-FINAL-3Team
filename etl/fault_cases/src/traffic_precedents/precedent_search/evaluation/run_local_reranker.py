from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from psycopg2.extras import RealDictCursor

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.db import get_connection

from ..search_config import DATASET_SEARCH_CONFIGS, RETRIEVAL_AB_EXPORT_ROOT, ensure_parent


DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
DEFAULT_INPUT_PATH = RETRIEVAL_AB_EXPORT_ROOT / "retrieval_ab_candidates.jsonl"
DEFAULT_OUTPUT_PATH = RETRIEVAL_AB_EXPORT_ROOT / "retrieval_ab_reranker_scores.jsonl"


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1 / (1 + z)
    z = math.exp(value)
    return z / (1 + z)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def fetch_chunk_texts(dataset: str, chunk_ids: list[str]) -> dict[str, str]:
    if not chunk_ids:
        return {}
    config = DATASET_SEARCH_CONFIGS[dataset]
    sql = f"""
        SELECT chunk_id, chunk_text
        FROM {config["chunk_table"]}
        WHERE chunk_id = ANY(%s)
    """
    with get_connection(config["db_name"]) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (chunk_ids,))
            return {row["chunk_id"]: row.get("chunk_text") or "" for row in cur.fetchall()}


def enrich_chunk_texts(candidates: list[dict[str, Any]]) -> None:
    chunk_ids_by_dataset: dict[str, set[str]] = {}
    for row in candidates:
        dataset = row["dataset"]
        chunk_id = row.get("chunk_id")
        if chunk_id:
            chunk_ids_by_dataset.setdefault(dataset, set()).add(chunk_id)

    texts: dict[str, str] = {}
    for dataset, chunk_ids in chunk_ids_by_dataset.items():
        texts.update(fetch_chunk_texts(dataset=dataset, chunk_ids=sorted(chunk_ids)))

    for row in candidates:
        row["chunk_text"] = texts.get(row.get("chunk_id"), row.get("chunk_preview") or "")


def build_pairs(candidates: list[dict[str, Any]], input_field: str) -> list[tuple[str, str]]:
    pairs = []
    for row in candidates:
        query = row.get("query") or ""
        text = row.get(input_field) or row.get("chunk_preview") or ""
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
            "sentence-transformers is required for local reranker evaluation. "
            "Install it before running this module."
        ) from exc

    model_kwargs = {"device": device} if device else {}
    model = CrossEncoder(model_name, **model_kwargs)
    pairs = build_pairs(candidates, input_field=input_field)

    started = time.perf_counter()
    raw_scores = model.predict(pairs, batch_size=batch_size, show_progress_bar=True)
    elapsed = time.perf_counter() - started

    for row, raw_score in zip(candidates, raw_scores, strict=True):
        raw_score_float = float(raw_score)
        row["reranker_model"] = model_name
        row["reranker_input_field"] = input_field
        row["reranker_raw_score"] = raw_score_float
        row["local_reranker_score"] = sigmoid(raw_score_float)
        row["chunk_text_char_len"] = len(row.get(input_field) or "")

    return {
        "candidate_count": len(candidates),
        "elapsed_seconds": elapsed,
        "avg_latency_ms_per_pair": (elapsed / len(candidates) * 1000) if candidates else 0,
    }


def run_evaluation(
    input_path: Path = DEFAULT_INPUT_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    model_name: str = DEFAULT_RERANKER_MODEL,
    input_field: str = "chunk_text",
    batch_size: int = 8,
    limit: int | None = None,
    device: str | None = None,
) -> dict[str, Any]:
    candidates = load_jsonl(input_path)
    if limit is not None:
        candidates = candidates[:limit]

    if input_field == "chunk_text":
        enrich_chunk_texts(candidates)

    score_meta = score_candidates(
        candidates=candidates,
        model_name=model_name,
        input_field=input_field,
        batch_size=batch_size,
        device=device,
    )

    ensure_parent(output_path)
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
        **score_meta,
    }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score retrieval A/B candidates with a local reranker.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--input-field", choices=["chunk_text", "chunk_preview"], default="chunk_text")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--device", default=None, help="Optional torch device such as cpu, cuda, or mps.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_evaluation(
        input_path=args.input,
        output_path=args.output,
        model_name=args.model,
        input_field=args.input_field,
        batch_size=args.batch_size,
        limit=args.limit,
        device=args.device,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
