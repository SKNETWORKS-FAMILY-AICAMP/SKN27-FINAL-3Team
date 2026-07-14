from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


JsonDict = dict[str, Any]


def ensure_dir(path: str | Path) -> Path:
    """Create a directory if needed and return it as a Path."""

    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def read_jsonl_iter(path: str | Path) -> Iterable[JsonDict]:
    """
    Yield JSONL rows one by one.

    Invalid JSON lines are yielded as invalid rows so the pipeline can report
    them instead of silently dropping data.
    """

    source = Path(path)

    with source.open("r", encoding="utf-8") as file:
        for line_no, line in enumerate(file, 1):
            line = line.strip()

            if not line:
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                row = {
                    "_input_line_no": line_no,
                    "_json_decode_error": repr(error),
                    "_raw_line_preview": line[:500],
                }
            else:
                if isinstance(row, dict):
                    row["_input_line_no"] = line_no
                else:
                    row = {
                        "_input_line_no": line_no,
                        "_json_decode_error": "JSON value is not an object",
                        "_raw_line_preview": line[:500],
                    }

            yield row


def load_jsonl(path: str | Path) -> list[JsonDict]:
    """Load a JSONL file into memory."""

    return list(read_jsonl_iter(path))


def write_jsonl(path: str | Path, rows: Iterable[JsonDict]) -> None:
    """Write rows to JSONL, replacing the file if it already exists."""

    target = Path(path)
    ensure_dir(target.parent)

    with target.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: str | Path, data: Any) -> None:
    """Write JSON with stable UTF-8 formatting."""

    target = Path(path)
    ensure_dir(target.parent)

    with target.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def prepare_output_dir(path: str | Path) -> Path:
    """
    Prepare the preprocessing output directory.

    This does not delete existing outputs. The run script can decide later
    whether to add a --fresh option.
    """

    output_dir = ensure_dir(path)
    ensure_dir(output_dir / "debug")
    return output_dir


def build_output_paths(output_dir: str | Path) -> dict[str, Path]:
    """Return standard output paths for the preprocessing pipeline."""

    base = prepare_output_dir(output_dir)

    return {
        "report": base / "00_preprocess_report.json",
        "invalid": base / "01_invalid_cases.jsonl",
        "duplicate_removed": base / "02_duplicate_removed_cases.jsonl",
        "preprocessed": base / "03_cases_preprocessed.jsonl",
        "fault_ratio_debug": base / "debug" / "fault_ratio_candidates_sample.jsonl",
        "section_debug": base / "debug" / "section_extraction_failed_sample.jsonl",
        "duplicate_debug": base / "debug" / "duplicate_groups_sample.jsonl",
    }
