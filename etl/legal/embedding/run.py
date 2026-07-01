from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_BATCH_SIZE = 32
DEFAULT_MODEL_ID = "intfloat/multilingual-e5-large"
import json
import time
from datetime import datetime, timezone
from etl.common.utils import read_jsonl_iter, batched

DEFAULT_PROVIDER = "sentence-transformers"
FALLBACK_PROVIDER = "sentence-transformers"
PROVIDER_CHOICES = ["auto", "sentence-transformers", "openai"]
DEFAULT_DIMENSIONS = 1024
DEFAULT_OUTPUTS = {
    "sentence-transformers": (
        "output/law_ingestion/embeddings/law_embeddings_e5_large.jsonl",
        "output/law_ingestion/reports/embedding_report_e5_large.json",
    ),
    "openai": (
        "output/law_ingestion/embeddings/law_embeddings_openai_3_large_1024.jsonl",
        "output/law_ingestion/reports/embedding_report_openai_3_large_1024.json",
    ),
}



def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    provider = resolve_provider(args.provider)
    output_path, report_path = resolve_output_paths(args.output, args.report, provider)
    generate_embeddings(
        input_path=Path(args.input),
        output_path=output_path,
        report_path=report_path,
        provider=provider,
        model_id=args.model_id,
        dimensions=args.dimensions,
        batch_size=args.batch_size,
        max_length=args.max_length,
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
        default=None,
        help="Embedding JSONL output. Defaults to the adopted E5 path for sentence-transformers.",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Embedding report JSON output. Defaults to the adopted E5 report for sentence-transformers.",
    )
    parser.add_argument("--dimensions", type=int, default=DEFAULT_DIMENSIONS)
    parser.add_argument(
        "--provider",
        choices=PROVIDER_CHOICES,
        default=DEFAULT_PROVIDER,
        help=(
            "Embedding provider. Use 'auto' to choose interactively in a terminal, "
            "or fall back to sentence-transformers in non-interactive runs."
        ),
    )
    parser.add_argument(
        "--model-id",
        default=DEFAULT_MODEL_ID,
        help="Model id for the selected provider. Defaults to the adopted E5-large model.",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument(
        "--progress-every",
        type=int,
        default=1000,
        help="Print progress every N embedded rows. Use 0 to disable.",
    )
    return parser.parse_args(argv)


def resolve_provider(provider: str) -> str:
    if provider != "auto":
        return provider
    if not sys.stdin.isatty():
        print(f"No interactive terminal detected. Using default provider: {FALLBACK_PROVIDER}")
        return FALLBACK_PROVIDER

    options = [
        ("sentence-transformers", "Adopted E5-large embedding path"),
        ("openai", "OpenAI embeddings API for comparison or re-evaluation"),
    ]
    print("\nSelect embedding provider:")
    for index, (name, description) in enumerate(options, 1):
        print(f"  {index}. {name} - {description}")

    while True:
        try:
            selected = input(f"Provider [1-{len(options)}, default 1]: ").strip()
        except EOFError:
            print(f"\nNo provider selected. Using default provider: {FALLBACK_PROVIDER}")
            return FALLBACK_PROVIDER
        if not selected:
            return options[0][0]
        if selected.isdigit() and 1 <= int(selected) <= len(options):
            return options[int(selected) - 1][0]
        matching = [name for name, _ in options if name == selected]
        if matching:
            return matching[0]
        print("Invalid selection. Choose a number or provider name.")


def resolve_output_paths(output: str | None, report: str | None, provider: str) -> tuple[Path, Path]:
    default_output, default_report = DEFAULT_OUTPUTS[provider]
    return Path(output or default_output), Path(report or default_report)


def generate_embeddings(
    *,
    input_path: Path,
    output_path: Path,
    report_path: Path,
    provider: str = DEFAULT_PROVIDER,
    model_id: str = DEFAULT_MODEL_ID,
    dimensions: int = DEFAULT_DIMENSIONS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_length: int = 512,
    progress_every: int = 1000,
) -> dict:
    if provider == "openai":
        from .run_openai import DEFAULT_MODEL_ID as OPENAI_DEFAULT_MODEL_ID
        from .run_openai import generate_embeddings as openai_generate_embeddings

        selected_model_id = OPENAI_DEFAULT_MODEL_ID if model_id == DEFAULT_MODEL_ID else model_id
        return openai_generate_embeddings(
            input_path=input_path,
            output_path=output_path,
            report_path=report_path,
            model_id=selected_model_id,
            dimensions=dimensions,
            batch_size=batch_size,
            progress_every=progress_every,
        )

    if provider == "sentence-transformers":
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("sentence-transformers package is required for this provider.") from exc

        print(f"Loading local SentenceTransformer model: {model_id} ...")
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = SentenceTransformer(model_id, device=device)

        doc_prefix = "passage: " if "e5" in model_id.lower() else ""
        started_at = datetime.now(timezone.utc).isoformat()
        
        # Read input items
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")
        
        items = list(read_jsonl_iter(input_path))
        print(f"Embedding {len(items)} items using {model_id} on {device}...")
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)

        embedded_count = 0
        t0 = time.time()

        with output_path.open("w", encoding="utf-8", newline="\n") as out_handle:
            for batch in batched(items, batch_size):
                texts = [doc_prefix + row["embedding_text"] for row in batch]
                embeddings = model.encode(
                    texts,
                    batch_size=len(texts),
                    show_progress_bar=False,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                )
                
                for row, emb in zip(batch, embeddings):
                    out_row = {
                        "chunk_id": row["chunk_id"],
                        "embedded_at": datetime.now(timezone.utc).isoformat(),
                        "embedding_dimensions": len(emb),
                        "embedding_model": model_id,
                        "embedding_provider": "sentence-transformers",
                        "embedding_text": row["embedding_text"],
                        "embedding_text_hash": row["embedding_text_hash"],
                        "embedding_vector": [float(v) for v in emb],
                        "embedding_version": "sentence-transformers",
                        "status": "embedded",
                    }
                    out_handle.write(json.dumps(out_row, ensure_ascii=False) + "\n")
                
                embedded_count += len(batch)
                if progress_every > 0 and embedded_count % progress_every == 0:
                    print(f"  Embedded {embedded_count}/{len(items)} chunks...")

        elapsed = time.time() - t0
        report = {
            "model_id": model_id,
            "provider": "sentence-transformers",
            "total_items": len(items),
            "embedded_items": embedded_count,
            "elapsed_seconds": round(elapsed, 2),
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        with report_path.open("w", encoding="utf-8") as rep_handle:
            json.dump(report, rep_handle, indent=2)

        print(f"Embedding generation completed: {embedded_count} chunks in {elapsed:.2f}s")
        return report

    raise ValueError(f"Unsupported embedding provider: {provider}")





if __name__ == "__main__":
    raise SystemExit(main())
