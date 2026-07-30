from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..contracts import read_jsonl
from .validate import validate_collected_records


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate collected precedents.")
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [row for path in args.input for row in read_jsonl(path.resolve())]
    report = validate_collected_records(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
