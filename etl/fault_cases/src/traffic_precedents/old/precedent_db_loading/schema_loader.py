from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .config import POSTGRES_EXPORT_ROOT, SCHEMA_PATH, SETTINGS
from .db import apply_sql_file, create_database_if_missing


SECTION_PATTERN = re.compile(
    r"-- BEGIN (?P<name>[A-Z_]+)\s+(?P<body>.*?)\s+-- END (?P=name)",
    re.DOTALL,
)


def extract_sections(sql_text: str) -> dict[str, str]:
    sections = {match.group("name"): match.group("body").strip() for match in SECTION_PATTERN.finditer(sql_text)}
    required = {"COMMON_SCHEMA", "TRAFFIC_SCHEMA", "TRAFFIC_INDEXES", "FAULT_RATIO_SCHEMA", "FAULT_RATIO_INDEXES"}
    missing = sorted(required - sections.keys())
    if missing:
        raise ValueError(f"Missing schema sections in {SCHEMA_PATH}: {missing}")
    return sections


def dataset_sql(db_name: str, sections: dict[str, str]) -> str:
    if db_name == SETTINGS.traffic_db:
        names = ["COMMON_SCHEMA", "TRAFFIC_SCHEMA", "TRAFFIC_INDEXES"]
    elif db_name == SETTINGS.fault_ratio_db:
        names = ["COMMON_SCHEMA", "FAULT_RATIO_SCHEMA", "FAULT_RATIO_INDEXES"]
    else:
        raise ValueError(
            f"Unknown precedent database '{db_name}'. "
            f"Expected {SETTINGS.traffic_db} or {SETTINGS.fault_ratio_db}."
        )
    return "\n\n".join(sections[name] for name in names)


def load_schema(databases: Iterable[str]) -> dict:
    sql_text = SCHEMA_PATH.read_text(encoding="utf-8")
    sections = extract_sections(sql_text)
    created = []
    applied = []

    for db_name in databases:
        if create_database_if_missing(db_name):
            created.append(db_name)
        apply_sql_file(db_name, dataset_sql(db_name, sections))
        applied.append(db_name)

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "schema_path": str(SCHEMA_PATH),
        "created_databases": created,
        "schema_applied_databases": applied,
    }

    report_path = POSTGRES_EXPORT_ROOT / "schema_load_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create precedent databases and apply schema.")
    parser.add_argument(
        "--databases",
        nargs="*",
        default=[SETTINGS.traffic_db, SETTINGS.fault_ratio_db],
        help="Database names to create and apply storage/schemas/precedent_db_schema.sql to.",
    )
    return parser.parse_args()


def main() -> None:
    report = load_schema(parse_args().databases)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
