from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from etl.common.utils import read_jsonl, batched, normalize_l2, load_env_file



DEFAULT_MODEL_ID = "text-embedding-3-large"
DEFAULT_DIMENSIONS = 1024
DEFAULT_BATCH_SIZE = 128
DEFAULT_MAX_RETRIES = 5


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env_file(Path(args.env_file))
    generate_embeddings(
        input_path=Path(args.input),
        output_path=Path(args.output),
        report_path=Path(args.report),
        model_id=args.model_id,
        dimensions=args.dimensions,
        batch_size=args.batch_size,
        limit=args.limit,
        offset=args.offset,
        normalize=not args.no_normalize,
        max_retries=args.max_retries,
        progress_every=args.progress_every,
    )
    return 0


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default="output/law_ingestion/embeddings/embedding_inputs.jsonl",
    )
    parser.add_argument(
        "--output",
        default="output/law_ingestion/embeddings/law_embeddings_openai_3_large_1024.jsonl",
    )
    parser.add_argument(
        "--report",
        default="output/law_ingestion/reports/embedding_report_openai_3_large_1024.json",
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--dimensions", type=int, default=DEFAULT_DIMENSIONS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=0, help="Embed only N rows. Use 0 for all rows.")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--no-normalize", action="store_true")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    parser.add_argument(
        "--progress-every",
        type=int,
        default=1000,
        help="Print progress every N embedded rows. Use 0 to disable.",
    )
    return parser.parse_args(argv)


def generate_embeddings(
    *,
    input_path: Path,
    output_path: Path,
    report_path: Path,
    model_id: str = DEFAULT_MODEL_ID,
    dimensions: int = DEFAULT_DIMENSIONS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int = 0,
    offset: int = 0,
    normalize: bool = True,
    max_retries: int = DEFAULT_MAX_RETRIES,
    progress_every: int = 1000,
) -> dict:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0")
    if dimensions <= 0:
        raise ValueError("dimensions must be greater than 0")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0")
    if limit < 0:
        raise ValueError("limit must be greater than or equal to 0")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required. Put it in .env or the environment.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the openai package from requirements.txt.") from exc

    started_at = datetime.now(timezone.utc).isoformat()
    rows = read_jsonl(input_path)
    selected_rows = rows[offset : offset + limit if limit else None]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output_path = output_path.with_name(output_path.name + ".tmp")

    client = OpenAI()
    embedded_count = 0
    total_prompt_tokens = 0
    embedding_dimensions = 0

    with temp_output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for batch in batched(selected_rows, batch_size):
            texts = [row.get("embedding_text") or "" for row in batch]
            response = create_embeddings_with_retry(
                client=client,
                model_id=model_id,
                dimensions=dimensions,
                texts=texts,
                max_retries=max_retries,
            )
            vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
            usage = getattr(response, "usage", None)
            total_prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            if vectors and not embedding_dimensions:
                embedding_dimensions = len(vectors[0])

            for row, vector in zip(batch, vectors, strict=True):
                if normalize:
                    vector = normalize_l2(vector)
                embedded = {
                    **row,
                    "embedding_provider": "openai",
                    "embedding_model": model_id,
                    "embedding_version": "openai-embeddings-api",
                    "embedding_dimensions": len(vector),
                    "embedding_vector": vector,
                    "status": "embedded",
                    "embedded_at": datetime.now(timezone.utc).isoformat(),
                }
                handle.write(json.dumps(embedded, ensure_ascii=False, sort_keys=True) + "\n")
                embedded_count += 1
                if progress_every and embedded_count % progress_every == 0:
                    print(f"embedded {embedded_count}/{len(selected_rows)}", flush=True)

    temp_output_path.replace(output_path)

    report = {
        "status": "success",
        "embedding_provider": "openai",
        "embedding_model": model_id,
        "embedding_version": "openai-embeddings-api",
        "embedding_dimensions": embedding_dimensions,
        "requested_dimensions": dimensions,
        "normalized": normalize,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "total_inputs": len(rows),
        "offset": offset,
        "limit": limit,
        "embedded_count": embedded_count,
        "failed_count": 0,
        "prompt_tokens": total_prompt_tokens,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "limitations": [],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def create_embeddings_with_retry(
    *,
    client,
    model_id: str,
    dimensions: int,
    texts: list[str],
    max_retries: int,
):
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return client.embeddings.create(
                model=model_id,
                input=texts,
                dimensions=dimensions,
                encoding_format="float",
            )
        except Exception as exc:  # OpenAI SDK exposes several retryable exception classes.
            last_error = exc
            if attempt >= max_retries:
                break
            time.sleep(min(2**attempt, 30))
    raise RuntimeError(f"OpenAI embedding request failed after {max_retries + 1} attempts") from last_error





if __name__ == "__main__":
    raise SystemExit(main())
