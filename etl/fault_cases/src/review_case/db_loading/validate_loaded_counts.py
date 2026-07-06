from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .db_config import POSTGRES_EXPORT_ROOT, PREPROCESSED_DIR, SETTINGS
from .db_connection import count_rows
from .load_common import read_jsonl


TABLE_TO_FILE = {
    "review_case_documents": "review_case_documents.jsonl",
    "review_case_source_chunks": "review_case_source_chunks.jsonl",
    "review_case_chunks": "review_case_chunks.jsonl",
    "review_case_quality_reports": "quality_report.jsonl",
    "review_case_toc_items": "toc/review_case_toc_items.jsonl",
    "review_case_toc_case_links": "toc/review_case_toc_case_links.jsonl",
}


def expected_count(preprocessed_dir: Path, rel_path: str) -> int:
    return sum(1 for _ in read_jsonl(preprocessed_dir / rel_path))


def validate(preprocessed_dir: Path) -> dict:
    table_counts = {}
    expected_counts = {}
    mismatches = {}
    for table, rel_path in TABLE_TO_FILE.items():
        table_count = count_rows(SETTINGS.review_case_db, table)
        expected = expected_count(preprocessed_dir, rel_path)
        table_counts[table] = table_count
        expected_counts[table] = expected
        if table_count != expected:
            mismatches[table] = {"expected": expected, "actual": table_count}

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "db_name": SETTINGS.review_case_db,
        "preprocessed_dir": str(preprocessed_dir),
        "expected_counts": expected_counts,
        "table_counts": table_counts,
        "is_complete": not mismatches,
        "mismatches": mismatches,
    }
    report_path = POSTGRES_EXPORT_ROOT / "review_case_loaded_counts_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate review_case_db loaded row counts.")
    parser.add_argument("--preprocessed-dir", type=Path, default=PREPROCESSED_DIR)
    return parser.parse_args()


def main() -> None:
    report = validate(parse_args().preprocessed_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
