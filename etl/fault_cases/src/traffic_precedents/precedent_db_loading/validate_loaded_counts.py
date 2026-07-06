from __future__ import annotations

import json
from datetime import datetime

from .config import DATASET_CONFIGS, POSTGRES_EXPORT_ROOT
from .db import count_rows


def count_jsonl_rows(path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def validate_loaded_counts() -> dict:
    results = {}
    all_match = True

    for dataset, config in DATASET_CONFIGS.items():
        jsonl_rows = count_jsonl_rows(config["input_path"])
        db_rows = count_rows(config["db_name"], config["table"])
        matches = jsonl_rows == db_rows
        all_match = all_match and matches
        results[dataset] = {
            "input_path": str(config["input_path"]),
            "db_name": config["db_name"],
            "table": config["table"],
            "expected_rows_source": "input_jsonl_row_count",
            "jsonl_rows": jsonl_rows,
            "db_rows": db_rows,
            "matches": matches,
        }

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "all_match": all_match,
        "results": results,
    }
    report_path = POSTGRES_EXPORT_ROOT / "precedent_loaded_count_validation_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    print(json.dumps(validate_loaded_counts(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
