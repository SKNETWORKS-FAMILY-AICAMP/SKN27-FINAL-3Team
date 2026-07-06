"""CLI entry point for collecting and validating fault standard PDFs."""

from __future__ import annotations

import argparse

from ..config import PipelineConfig
from .collection_validator import validate_collection
from .crawler import run_collect
from .setup_browser import ensure_chromium_installed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect fault standard PDFs.")
    parser.add_argument("--seed-url", help="Source list URL. Defaults to FAULT_CASES_SEED_URL or crawling_settings.json.")
    parser.add_argument("--headed", action="store_true", help="Run browser with a visible window.")
    parser.add_argument("--quiet", action="store_true", help="Disable progress logs.")
    parser.add_argument("--force", action="store_true", help="Download even if manifest already has the target document type.")
    parser.add_argument("--keep-duplicates", action="store_true", help="Keep duplicate PDF files on disk.")
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    parser.add_argument("--validate", action="store_true", help="Run collection quality validation after downloading.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = PipelineConfig(
        seed_url=args.seed_url or PipelineConfig().seed_url,
        headless=not args.headed,
        verbose=not args.quiet,
        force_download=args.force,
        keep_duplicate_files=args.keep_duplicates,
        timeout_ms=args.timeout_ms,
    )
    ensure_chromium_installed()
    rows = run_collect(config)
    print(f"collection rows added: {len(rows)}")
    print(f"manifest: {config.manifest_path}")
    print(f"raw source files: {config.raw_source_dir}")
    if args.validate:
        reports = validate_collection(config)
        print(f"quality reports: {len(reports)}")
        print(f"quality report: {config.quality_report_path}")


if __name__ == "__main__":
    main()
