from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..config import EXPECTED_RAG_BLOCKS, EXPECTED_RAG_CASES
from ..contracts import read_jsonl, write_jsonl
from .builder import build_rag_records
from .validator import validate_rag_records


def main() -> int:
    parser = argparse.ArgumentParser(description="Build fixed precedent RAG records.")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--blocks", type=Path, required=True)
    parser.add_argument("--classifications", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-blocks", type=int, default=EXPECTED_RAG_BLOCKS)
    parser.add_argument("--expected-cases", type=int, default=EXPECTED_RAG_CASES)
    args = parser.parse_args()
    rows = build_rag_records(
        read_jsonl(args.cases.resolve()),
        read_jsonl(args.blocks.resolve()),
        read_jsonl(args.classifications.resolve()),
    )
    report = validate_rag_records(
        rows,
        expected_blocks=args.expected_blocks,
        expected_cases=args.expected_cases,
    )
    write_jsonl(args.output.resolve(), rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
