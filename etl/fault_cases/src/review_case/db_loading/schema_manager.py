from __future__ import annotations

import argparse
import json
from datetime import datetime

from .db_config import POSTGRES_EXPORT_ROOT, SCHEMA_PATH, SETTINGS
from .db_connection import apply_sql_file, create_database_if_missing


def apply_schema(create_db: bool = True, apply_schema_sql: bool = True) -> dict:
    created = False
    if create_db:
        created = create_database_if_missing(SETTINGS.review_case_db)

    if apply_schema_sql:
        apply_sql_file(SETTINGS.review_case_db, SCHEMA_PATH.read_text(encoding="utf-8"))

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "db_name": SETTINGS.review_case_db,
        "schema_path": str(SCHEMA_PATH),
        "database_created": created,
        "schema_applied": apply_schema_sql,
    }
    report_path = POSTGRES_EXPORT_ROOT / "schema_load_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create review_case_db and apply schema.")
    parser.add_argument("--create-db", action="store_true", help="Create REVIEW_CASE_DB if it does not exist.")
    parser.add_argument("--apply-schema", action="store_true", help="Apply storage/schemas/review_case_db_schema.sql.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    should_create = args.create_db or not args.apply_schema
    should_apply = args.apply_schema or not args.create_db
    report = apply_schema(create_db=should_create, apply_schema_sql=should_apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

