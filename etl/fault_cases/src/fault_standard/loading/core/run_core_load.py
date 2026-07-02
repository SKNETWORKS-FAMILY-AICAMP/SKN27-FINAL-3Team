"""Command line entry point for promoting staging data into core tables."""

from __future__ import annotations

import argparse
import sys

from ..db import connect_postgres
from ..run_staging_pipeline import (
    DEFAULT_BATCH_NAME,
    DEFAULT_FAULT_STANDARD_DB,
    configure_target_database,
    ensure_database_exists,
    start_postgres_service,
)
from .loader import promote_staging_to_core
from .schema import create_core_schema


def parse_args() -> argparse.Namespace:
    """Parse PowerShell-friendly core loading options."""
    parser = argparse.ArgumentParser(
        description="Create PostgreSQL core schema and promote one validated fault-standard staging batch."
    )
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
    parser.add_argument("--batch-id", type=int, default=None, help="Exact staging batch_id to promote.")
    parser.add_argument("--batch-name", default=DEFAULT_BATCH_NAME, help="Staging batch_name to promote.")
    parser.add_argument("--description", default="fault standard core promotion", help="Core load description.")
    parser.add_argument("--mode", choices=("replace-core",), default="replace-core", help="Replace active core tables.")
    parser.add_argument("--create-schema-only", action="store_true", help="Create core schema and tables only.")
    parser.add_argument("--allow-validation-issues", action="store_true", help="Promote even if validation fails.")
    parser.add_argument("--skip-create-db", action="store_true", help="Skip target database creation check.")
    parser.add_argument("--skip-docker-up", action="store_true", help="Skip automatic 'docker compose up -d postgres'.")
    return parser.parse_args()


def print_result(result: dict) -> None:
    """Print the core promotion summary in a compact form."""
    print(f"[core] load_id={result['load_id']} batch_id={result['batch_id']} batch_name={result['batch_name']}")
    print(f"[core] mode={result['mode']}")
    print("[core] validation:")
    for key, value in sorted(result["validation"].items()):
        print(f"  - {key}: {value}")
    print("[core] table counts:")
    for table_name, count in sorted(result["core_counts"].items()):
        print(f"  - {table_name}: {count}")


def main() -> int:
    """Run database setup and core promotion."""
    args = parse_args()
    target_db = configure_target_database(args.env_file, args.database)
    print(f"[core] target_database={target_db}")

    try:
        if not args.skip_docker_up:
            start_postgres_service()
        if not args.skip_create_db:
            ensure_database_exists(args.env_file, target_db, args.admin_database)

        conn = connect_postgres(args.env_file)
    except Exception as exc:
        print(f"[core] database setup failed: {exc}", file=sys.stderr)
        return 1

    conn.autocommit = False
    try:
        if args.create_schema_only:
            create_core_schema(conn)
            conn.commit()
            print("[core] schema ready")
            return 0

        result = promote_staging_to_core(
            conn=conn,
            batch_id=args.batch_id,
            batch_name=args.batch_name,
            mode=args.mode,
            description=args.description,
            allow_validation_issues=args.allow_validation_issues,
        )
    except Exception as exc:
        conn.rollback()
        print(f"[core] load failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
