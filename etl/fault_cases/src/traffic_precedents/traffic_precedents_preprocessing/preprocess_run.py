from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from modules.duplicate_detector import remove_duplicates
from modules.fault_ratio_extractor import extract_fault_ratio_rows
from modules.io_utils import build_output_paths, load_jsonl, write_json, write_jsonl
from modules.normalizer import TARGET_FIELDS, normalize_cases, split_valid_invalid_cases
from modules.report_builder import build_preprocess_report
from modules.section_extractor import extract_order_and_reason_many
from modules.table_compactor import compact_numeric_table_rows
from modules.text_cleaner import clean_text_rows


JsonDict = dict[str, Any]


DEFAULT_INPUT = Path(
    "etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_api/all_prec_candidates_raw.jsonl"
)
DEFAULT_OUTPUT_DIR = Path(
    "etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_pre"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preprocess raw traffic precedent API JSONL for fault-ratio RAG."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--duplicate-threshold", type=float, default=0.90)
    parser.add_argument("--debug-sample-size", type=int, default=200)
    return parser.parse_args()


def strip_internal_fields(row: JsonDict) -> JsonDict:
    """Keep only final target fields for the Agent/RAG output JSONL."""

    return {field: row.get(field) for field in TARGET_FIELDS}


def build_fault_ratio_debug_rows(rows: list[JsonDict], limit: int) -> list[JsonDict]:
    """Build a bounded debug sample for fault-ratio extraction."""

    debug_rows: list[JsonDict] = []

    for row in rows:
        candidates = row.get("_fault_ratio_candidates") or []

        if not candidates:
            continue

        debug_rows.append(
            {
                "_case_id": row.get("_case_id"),
                "사건명": row.get("사건명"),
                "과실비율": row.get("과실비율"),
                "candidate_count": len(candidates),
                "candidates": candidates[:20],
            }
        )

        if len(debug_rows) >= limit:
            break

    return debug_rows


def run_pipeline(
    input_path: Path,
    output_dir: Path,
    duplicate_threshold: float,
    debug_sample_size: int,
) -> dict[str, Any]:
    output_paths = build_output_paths(output_dir)

    raw_rows = load_jsonl(input_path)
    valid_rows, invalid_rows = split_valid_invalid_cases(raw_rows)

    rows = normalize_cases(valid_rows)
    rows = extract_order_and_reason_many(rows)

    deduped_rows, duplicate_removed_rows, duplicate_group_summaries = remove_duplicates(
        rows,
        similarity_threshold=duplicate_threshold,
    )

    rows = clean_text_rows(deduped_rows)
    rows, numeric_table_compaction_count = compact_numeric_table_rows(rows)
    rows = extract_fault_ratio_rows(rows)

    final_rows = [strip_internal_fields(row) for row in rows]
    fault_ratio_debug_rows = build_fault_ratio_debug_rows(rows, debug_sample_size)

    report = build_preprocess_report(
        raw_count=len(raw_rows),
        valid_count=len(valid_rows),
        invalid_rows=invalid_rows,
        duplicate_removed_rows=duplicate_removed_rows,
        final_rows=rows,
        extra_stats={
            "input_path": str(input_path),
            "output_dir": str(output_dir),
            "duplicate_threshold": duplicate_threshold,
            "numeric_table_compaction_count": numeric_table_compaction_count,
            "duplicate_group_count": len(duplicate_group_summaries),
        },
    )

    write_json(output_paths["report"], report)
    write_jsonl(output_paths["invalid"], invalid_rows)
    write_jsonl(output_paths["duplicate_removed"], duplicate_removed_rows)
    write_jsonl(output_paths["preprocessed"], final_rows)
    write_jsonl(output_paths["fault_ratio_debug"], fault_ratio_debug_rows)
    write_jsonl(output_paths["duplicate_debug"], duplicate_group_summaries[:debug_sample_size])

    return report


def main() -> None:
    args = parse_args()
    report = run_pipeline(
        input_path=args.input,
        output_dir=args.output_dir,
        duplicate_threshold=args.duplicate_threshold,
        debug_sample_size=args.debug_sample_size,
    )
    print(
        "preprocess complete: "
        f"raw={report['row_counts']['raw']} "
        f"final={report['row_counts']['final']} "
        f"output_dir={args.output_dir}"
    )


if __name__ == "__main__":
    main()
