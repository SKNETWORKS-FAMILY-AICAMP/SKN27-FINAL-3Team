"""Validate legal ingestion run evidence against an operator-approved age limit."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


EXPECTED_SUMMARY_CONTRACT_VERSION = "legal_ingestion_run_summary.v2"
VALIDATION_CONTRACT_VERSION = "legal_run_summary_validation.v1"


def evaluate_run_summary(
    summary: dict[str, Any],
    *,
    now: datetime,
    max_age_hours: int,
    required_sources: list[str],
) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("now must include timezone information")
    if max_age_hours <= 0:
        raise ValueError("max_age_hours must be greater than zero")

    checked_at = now.astimezone(timezone.utc)
    required = sorted(
        {
            source_id.strip()
            for source_id in required_sources
            if source_id and source_id.strip()
        }
    )
    source_rows = summary.get("source_summaries")
    source_rows = source_rows if isinstance(source_rows, list) else []
    sources_by_id = {
        str(row.get("source_id") or ""): row
        for row in source_rows
        if isinstance(row, dict) and row.get("source_id")
    }
    if not required:
        required = sorted(sources_by_id)

    errors = []
    if summary.get("contract_version") != EXPECTED_SUMMARY_CONTRACT_VERSION:
        errors.append("unsupported_contract_version")
    if not required:
        errors.append("no_sources_to_validate")

    missing_sources = [
        source_id for source_id in required if source_id not in sources_by_id
    ]
    failed_sources = []
    stale_sources = []
    oldest_allowed = checked_at - timedelta(hours=max_age_hours)

    for source_id in required:
        source = sources_by_id.get(source_id)
        if source is None:
            continue
        if source.get("status") != "success":
            failed_sources.append(source_id)
            continue
        verified_at = _parse_timestamp(source.get("last_verified_at"))
        if verified_at is None:
            failed_sources.append(source_id)
            continue
        if verified_at < oldest_allowed:
            stale_sources.append(source_id)

    status = (
        "failed"
        if errors or missing_sources or failed_sources or stale_sources
        else "success"
    )
    return {
        "contract_version": VALIDATION_CONTRACT_VERSION,
        "status": status,
        "checked_at": checked_at.isoformat(),
        "max_age_hours": max_age_hours,
        "run_id": summary.get("run_id"),
        "dataset_version": summary.get("dataset_version"),
        "required_sources": required,
        "missing_sources": missing_sources,
        "failed_sources": failed_sources,
        "stale_sources": stale_sources,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True, help="v2 run_summary.json path")
    parser.add_argument("--max-age-hours", required=True, type=int)
    parser.add_argument(
        "--required-source",
        action="append",
        default=[],
        help="Required source_id; repeat for each required source",
    )
    parser.add_argument("--output", help="Optional validation JSON output path")
    parser.add_argument(
        "--now",
        help="UTC ISO 8601 check time override for reproducible verification",
    )
    args = parser.parse_args(argv)

    summary_path = Path(args.summary)
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    now = _parse_timestamp(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        parser.error("--now must be a timezone-aware ISO 8601 timestamp")

    result = evaluate_run_summary(
        summary,
        now=now,
        max_age_hours=args.max_age_hours,
        required_sources=args.required_source,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered)
    return 0 if result["status"] == "success" else 1


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
