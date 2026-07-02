"""Command line entry point for building search documents from core tables."""

from __future__ import annotations

import argparse
import sys

from ..db import connect_postgres
from ..run_staging_pipeline import (
    DEFAULT_FAULT_STANDARD_DB,
    configure_target_database,
    ensure_database_exists,
    start_postgres_service,
)
from .loader import DEFAULT_DOCUMENT_STRATEGY, build_search_documents
from .schema import create_search_schema


def parse_args() -> argparse.Namespace:
    """Parse PowerShell-friendly search document build options."""
    parser = argparse.ArgumentParser(description="Build PostgreSQL search documents from fault-standard core tables.")
    parser.add_argument("--env-file", default=".env", help="Environment file with PostgreSQL settings.")
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
    parser.add_argument("--source-batch-id", type=int, default=None, help="Core source_batch_id to build from.")
    parser.add_argument("--source-core-load-id", type=int, default=None, help="Specific core_loads.load_id to build from.")
    parser.add_argument("--mode", choices=("replace-search",), default="replace-search", help="Replace active search documents.")
    parser.add_argument("--document-strategy", default=DEFAULT_DOCUMENT_STRATEGY, help="Search text construction strategy label.")
    parser.add_argument("--embedding-model", default=None, help="Embedding model label to store before embedding is generated.")
    parser.add_argument("--description", default="fault standard search document build", help="Search load description.")
    parser.add_argument("--create-schema-only", action="store_true", help="Create search schema and tables only.")
    parser.add_argument("--allow-validation-issues", action="store_true", help="Build even if core validation fails.")
    parser.add_argument("--skip-create-db", action="store_true", help="Skip target database creation check.")
    parser.add_argument("--skip-docker-up", action="store_true", help="Skip automatic 'docker compose up -d postgres'.")
    return parser.parse_args()


def print_result(result: dict) -> None:
    """Print the search-document build summary."""
    print(
        "[search] "
        f"search_load_id={result['search_load_id']} "
        f"source_batch_id={result['source_batch_id']} "
        f"source_core_load_id={result['source_core_load_id']}"
    )
    print(f"[search] mode={result['mode']} strategy={result['document_strategy']}")
    print("[search] validation:")
    for key, value in sorted(result["validation"].items()):
        print(f"  - {key}: {value}")
    print("[search] document counts:")
    for document_type, count in sorted(result["document_counts"].items()):
        print(f"  - {document_type}: {count}")


def main() -> int:
    """Run database setup and search document generation."""
    args = parse_args()
    target_db = configure_target_database(args.env_file, args.database)
    print(f"[search] target_database={target_db}")

    try:
        if not args.skip_docker_up:
            start_postgres_service()
        if not args.skip_create_db:
            ensure_database_exists(args.env_file, target_db, args.admin_database)
        conn = connect_postgres(args.env_file)
    except Exception as exc:
        print(f"[search] database setup failed: {exc}", file=sys.stderr)
        return 1

    conn.autocommit = False
    try:
        if args.create_schema_only:
            create_search_schema(conn)
            conn.commit()
            print("[search] schema ready")
            return 0

        result = build_search_documents(
            conn=conn,
            source_batch_id=args.source_batch_id,
            source_core_load_id=args.source_core_load_id,
            mode=args.mode,
            document_strategy=args.document_strategy,
            embedding_model=args.embedding_model,
            description=args.description,
            allow_validation_issues=args.allow_validation_issues,
        )
    except Exception as exc:
        conn.rollback()
        print(f"[search] build failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
