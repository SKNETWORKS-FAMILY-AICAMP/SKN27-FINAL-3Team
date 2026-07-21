"""Review case pipeline controller.

Supported stages:
- crawl: collect the review case PDF.
- preprocess: build preprocessing artifacts and pre-embedding chunks.
- schema: create/apply the PostgreSQL review_case schema.
- load: load preprocessed artifacts into PostgreSQL.
- all: run crawl -> preprocess -> schema -> load.

Embedding is intentionally not part of this controller because this pipeline is
for the pre-embedding handoff point.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


STAGES = ("crawl", "preprocess", "schema", "load", "all")


def parse_stage_args() -> tuple[str, list[str]]:
    parser = argparse.ArgumentParser(description="Run the review_case pre-embedding pipeline.")
    parser.add_argument("--stage", choices=STAGES, default="crawl")
    args, remaining = parser.parse_known_args()
    return args.stage, remaining


def run_crawl(args: list[str]) -> None:
    sys.argv = [sys.argv[0], *args]
    from .crawling.one_click_collect import main as crawl_main

    crawl_main()


def run_preprocess(args: list[str]) -> None:
    sys.argv = [sys.argv[0], *args]
    from .preprocessing.preprocess_runner import main as preprocess_main

    preprocess_main()


def run_schema() -> None:
    from .db_loading.schema_manager import apply_schema

    report = apply_schema(create_db=True, apply_schema_sql=True)
    print(f"[review_case schema] db={report['db_name']} created={report['database_created']}")


def run_load(args: list[str]) -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--preprocessed-dir", type=Path, default=None)
    parser.add_argument("--no-reset", action="store_true")
    parsed, _ = parser.parse_known_args(args)

    from .db_loading.db_config import PREPROCESSED_DIR
    from .db_loading.run_db_load import run_load as load_preprocessed_artifacts

    report = load_preprocessed_artifacts(
        parsed.preprocessed_dir or PREPROCESSED_DIR,
        reset=not parsed.no_reset,
    )
    print(f"[review_case load] run_id={report['run_id']}")
    print(f"[review_case load] loaded_counts={report['loaded_counts']}")


def main() -> None:
    stage, remaining = parse_stage_args()

    if stage == "crawl":
        run_crawl(remaining)
        return

    if stage == "preprocess":
        run_preprocess(remaining)
        return

    if stage == "schema":
        run_schema()
        return

    if stage == "load":
        run_load(remaining)
        return

    if stage == "all":
        run_crawl(remaining)
        run_preprocess([])
        run_schema()
        run_load([])
        return

    raise SystemExit(f"Unsupported stage: {stage}")


if __name__ == "__main__":
    main()
