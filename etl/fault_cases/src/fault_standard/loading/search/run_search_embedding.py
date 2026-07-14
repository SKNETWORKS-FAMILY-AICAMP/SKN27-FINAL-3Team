"""Command line entry point for embedding fault-standard search documents."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..db import connect_postgres
from ..run_staging_pipeline import (
    DEFAULT_FAULT_STANDARD_DB,
    configure_target_database,
    ensure_database_exists,
    start_postgres_service,
)
from .embedding import DEFAULT_REPORT_PATH, EmbeddingSettings, create_search_embeddings
from .schema import DEFAULT_EMBEDDING_API_MODEL, DEFAULT_EMBEDDING_MODEL, EMBEDDING_DIMENSION


def parse_args() -> argparse.Namespace:
    """Parse PowerShell-friendly search embedding options."""
    parser = argparse.ArgumentParser(description="Create OpenAI embeddings for fault-standard search documents.")
    parser.add_argument("--env-file", default=".env", help="Environment file with PostgreSQL and OpenAI settings.")
    parser.add_argument(
        "--database",
        default=None,
        help=f"Target database. Defaults to FAULT_STANDARD_POSTGRES_DB or {DEFAULT_FAULT_STANDARD_DB}.",
    )
    parser.add_argument(
        "--admin-database",
        default=None,
        help="Existing database used only to create the target database when missing.",
    )
    parser.add_argument("--api-model", default=DEFAULT_EMBEDDING_API_MODEL, help="OpenAI embedding API model.")
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        help="Model label stored in search.rule_search_documents.",
    )
    parser.add_argument("--dimension", type=int, default=EMBEDDING_DIMENSION, help="Embedding vector dimension.")
    parser.add_argument("--batch-size", type=int, default=64, help="OpenAI embedding batch size.")
    parser.add_argument("--max-input-chars", type=int, default=8000, help="Trim search_text to this many characters.")
    parser.add_argument("--max-retries", type=int, default=3, help="OpenAI request retry count.")
    parser.add_argument("--retry-sleep-seconds", type=float, default=2.0, help="Base retry sleep seconds.")
    parser.add_argument("--limit", type=int, default=None, help="Embed only the first N selected documents.")
    parser.add_argument("--dry-run", action="store_true", help="Count target documents without calling OpenAI.")
    parser.add_argument(
        "--reembed",
        action="store_true",
        help="Recreate embeddings even when embedding already exists for the selected model label.",
    )
    parser.add_argument("--skip-index", action="store_true", help="Skip pgvector cosine index creation.")
    parser.add_argument("--index-method", choices=("hnsw", "ivfflat"), default="hnsw", help="pgvector index method.")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH), help="Embedding load report path.")
    parser.add_argument("--skip-create-db", action="store_true", help="Skip target database creation check.")
    parser.add_argument("--skip-docker-up", action="store_true", help="Skip automatic 'docker compose up -d postgres'.")
    return parser.parse_args()


def print_result(report: dict) -> None:
    """Print a concise embedding job summary."""
    print("[embedding] completed")
    print(f"[embedding] api_model={report['embedding_api_model']} model_label={report['embedding_model']}")
    print(f"[embedding] dimension={report['embedding_dim']} dry_run={report['dry_run']}")
    print(f"[embedding] selected={report['selected_document_count']} updated={report['updated_embeddings']}")
    print(
        "[embedding] missing "
        f"before={report['missing_embedding_before']} after={report['missing_embedding_after']}"
    )
    print(f"[embedding] prompt_tokens={report['prompt_tokens']} total_tokens={report['total_tokens']}")
    print(f"[embedding] vector_index={report['vector_index_created']}")
    print(f"[embedding] report={report['report_path']}")


def main() -> int:
    """Run database setup and search embedding generation."""
    args = parse_args()
    target_db = configure_target_database(args.env_file, args.database)
    print(f"[embedding] target_database={target_db}")

    try:
        if not args.skip_docker_up:
            start_postgres_service()
        if not args.skip_create_db:
            ensure_database_exists(args.env_file, target_db, args.admin_database)
        conn = connect_postgres(args.env_file)
    except Exception as exc:
        print(f"[embedding] database setup failed: {exc}", file=sys.stderr)
        return 1

    conn.autocommit = False
    settings = EmbeddingSettings(
        api_model=args.api_model,
        stored_model_label=args.embedding_model,
        dimension=args.dimension,
        batch_size=args.batch_size,
        max_input_chars=args.max_input_chars,
        max_retries=args.max_retries,
        retry_sleep_seconds=args.retry_sleep_seconds,
    )
    try:
        report = create_search_embeddings(
            conn=conn,
            settings=settings,
            limit=args.limit,
            dry_run=args.dry_run,
            only_missing=not args.reembed,
            create_index=not args.skip_index,
            index_method=args.index_method,
            report_path=Path(args.report_path),
        )
    except Exception as exc:
        conn.rollback()
        print(f"[embedding] failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print_result(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
