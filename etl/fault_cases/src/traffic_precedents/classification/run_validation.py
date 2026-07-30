from __future__ import annotations

import argparse
from pathlib import Path

from ..contracts import read_jsonl, write_jsonl
from .validator import validate_classification


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Independently validate precedent classifications."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    released = []
    failed = 0
    for source in read_jsonl(args.input.resolve()):
        row = dict(source)
        row["validation"] = validate_classification(row)
        released.append(row)
        failed += row["validation"]["status"] != "PASSED"
    write_jsonl(args.output.resolve(), released)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
