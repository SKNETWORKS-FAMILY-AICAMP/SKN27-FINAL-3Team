from __future__ import annotations

import argparse
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..config import EXPECTED_RAG_BLOCKS, EXPECTED_RAG_CASES
from .loader import load_bootstrap_pair, load_records


@contextmanager
def connect(dsn: str) -> Iterator[Any]:
    import psycopg

    with psycopg.connect(dsn) as connection:
        yield connection


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load the tracked precedent embedding pair into pgvector."
    )
    parser.add_argument("--embeddings", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--dsn", default=os.getenv("PRECEDENT_NEWPLUSPLUS_DSN", ""))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, vectors = load_bootstrap_pair(
        args.embeddings.resolve(), args.metadata.resolve()
    )
    if not args.apply:
        print(
            f"dry-run passed: blocks={len(records)}, "
            f"cases={len({row['record_id'] for row in records})}"
        )
        return 0
    if not args.dsn:
        raise ValueError("--dsn or PRECEDENT_NEWPLUSPLUS_DSN is required with --apply")
    count = load_records(
        records,
        vectors,
        connection_factory=lambda: connect(args.dsn),
        expected_blocks=EXPECTED_RAG_BLOCKS,
        expected_cases=EXPECTED_RAG_CASES,
    )
    print(f"loaded={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
