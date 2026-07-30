from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import DATASET_CONFIGS
from .db import count_rows
from .loader_common import TRAFFIC_COLUMNS, read_jsonl, upsert_rows, write_report


def count_jsonl_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def load_traffic_precedents(input_path: Path | None = None) -> dict:
    config = DATASET_CONFIGS["traffic"]
    source_path = input_path or config["input_path"]
    inserted_or_updated = upsert_rows(
        db_name=config["db_name"],
        table_name=config["table"],
        columns=TRAFFIC_COLUMNS,
        rows=read_jsonl(source_path),
        dataset="traffic",
    )
    db_rows = count_rows(config["db_name"], config["table"])
    input_rows = count_jsonl_rows(source_path)
    report = {
        "dataset": "traffic",
        "input_path": str(source_path),
        "target_db": config["db_name"],
        "target_table": config["table"],
        "expected_rows_source": "input_jsonl_row_count",
        "input_rows": input_rows,
        "inserted_or_updated_rows": inserted_or_updated,
        "db_rows": db_rows,
        "row_count_matches_expected": db_rows == input_rows,
    }
    write_report(config["report_path"], report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load confirmed traffic precedents into PostgreSQL.")
    parser.add_argument("--input", type=Path, default=None, help="Override input JSONL path.")
    return parser.parse_args()


def main() -> None:
    report = load_traffic_precedents(parse_args().input)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
