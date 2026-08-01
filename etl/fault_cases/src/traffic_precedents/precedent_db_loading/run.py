from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .loader import load_bootstrap_pair
from .seed_integrity import compute_seed_identity, promote_seed, stage_seed


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
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--expected-active-seed-version")
    args = parser.parse_args()
    embeddings_path = args.embeddings.resolve()
    metadata_path = args.metadata.resolve()
    if not args.apply:
        if args.promote:
            parser.error("--promote requires --apply")
        records, vectors = load_bootstrap_pair(embeddings_path, metadata_path)
        identity = compute_seed_identity()
        print(json.dumps({
            "contract_version": "precedent_newplusplus_seed.v1",
            "status": "validated",
            "external_writes": False,
            "seed_version": identity.seed_version,
            "block_count": len(records),
            "case_count": len({row["record_id"] for row in records}),
            "embedding_dimension": int(vectors.shape[1]),
        }, ensure_ascii=False, sort_keys=True))
        return 0
    if not args.dsn:
        raise ValueError("--dsn or PRECEDENT_NEWPLUSPLUS_DSN is required with --apply")
    connection_factory = lambda: connect(args.dsn)
    staged = stage_seed(
        embeddings_path=embeddings_path,
        metadata_path=metadata_path,
        connection_factory=connection_factory,
    )
    result: dict[str, Any] = {"stage": staged}
    if args.promote:
        if args.expected_active_seed_version is None:
            parser.error("--promote requires --expected-active-seed-version")
        expected = args.expected_active_seed_version.strip()
        expected_active = None if expected.lower() == "none" else expected
        result["promotion"] = promote_seed(
            seed_version=staged["seed_version"],
            expected_active_seed_version=expected_active,
            connection_factory=connection_factory,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
