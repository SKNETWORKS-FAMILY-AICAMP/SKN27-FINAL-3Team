"""명시적 시드·일반 입력으로 C단계 안전 전처리를 실행합니다."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .merger import (
    MERGER_VERSION,
    merge_duplicate_precedents,
)

DATA_ROOT = Path.cwd() / "outputs" / "traffic_precedents"


RUNNER_VERSION = "safe_preprocessing_runner_v2.0.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="명시적으로 고정한 시드·일반 판례를 전처리하고 중복 병합합니다."
    )
    parser.add_argument(
        "--seed-input",
        required=True,
        help="검증 통과 02_seed_ready_full_cases.jsonl",
    )
    parser.add_argument(
        "--general-input",
        required=True,
        help="검증 통과 04_valid_general_precedents_after_retry.jsonl",
    )
    parser.add_argument("--threshold", type=float, default=0.90)
    parser.add_argument("--out-dir")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError(f"{path}:{line_number} JSON 객체가 아닙니다.")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def input_info(path: Path, record_count: int) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "record_count": record_count,
    }


def main() -> int:
    args = parse_args()
    seed_path = Path(args.seed_input).expanduser().resolve()
    general_path = Path(args.general_input).expanduser().resolve()
    for label, path in (("seed", seed_path), ("general", general_path)):
        if not path.is_file():
            raise FileNotFoundError(f"{label} 입력 파일이 없습니다: {path}")

    seed_records = read_jsonl(seed_path)
    general_records = read_jsonl(general_path)
    for record in seed_records:
        record["_preprocessing_input_route"] = "SEED_READY"
        record["internal_grade"] = "SEED_READY"
        record["force_ready"] = True
    for record in general_records:
        record["_preprocessing_input_route"] = "GENERAL_VALID_DETAIL"

    raw_records = seed_records + general_records
    run_name = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    out_dir = (
        Path(args.out_dir).expanduser().resolve()
        if args.out_dir
        else DATA_ROOT / "03_output" / "03_preprocessed" / run_name
    )
    out_dir.mkdir(parents=True, exist_ok=False)
    started_at = datetime.now().isoformat(timespec="seconds")
    inputs = {
        "seed": input_info(seed_path, len(seed_records)),
        "general": input_info(general_path, len(general_records)),
    }
    manifest_path = out_dir / "05_run_manifest.json"
    manifest: dict[str, Any] = {
        "run_id": out_dir.name,
        "stage": "03_safe_preprocessing",
        "runner_version": RUNNER_VERSION,
        "merger_version": MERGER_VERSION,
        "started_at": started_at,
        "completed_at": None,
        "status": "RUNNING",
        "similarity_threshold": args.threshold,
        "inputs": inputs,
        "outputs": {},
    }
    write_json(manifest_path, manifest)

    try:
        representatives, merged = merge_duplicate_precedents(
            raw_records,
            similarity_threshold=args.threshold,
        )
        rejected: list[dict[str, Any]] = []
        valid_representatives: list[dict[str, Any]] = []
        for record in representatives:
            if str(record.get("full_text") or "").strip():
                valid_representatives.append(record)
            else:
                rejected_record = dict(record)
                rejected_record["record_status"] = "PREPROCESSING_REJECTED"
                rejected_record["preprocessing_rejection_reason_codes"] = [
                    "EMPTY_FULL_TEXT_AFTER_PREPROCESSING"
                ]
                rejected.append(rejected_record)

        status_counts = Counter(
            record.get("_preprocessing_input_route", "UNKNOWN")
            for record in valid_representatives
        )
        counts = {
            "seed_input_count": len(seed_records),
            "general_input_count": len(general_records),
            "raw_input_count": len(raw_records),
            "representative_count": len(valid_representatives),
            "merged_duplicate_count": len(merged),
            "rejected_count": len(rejected),
            "seed_representative_count": status_counts.get("SEED_READY", 0),
            "general_representative_count": status_counts.get(
                "GENERAL_VALID_DETAIL", 0
            ),
        }
        accounted_count = (
            counts["representative_count"]
            + counts["merged_duplicate_count"]
            + counts["rejected_count"]
        )
        representative_ids = [
            str(
                record.get("판례정보일련번호")
                or record.get("판례일련번호")
                or record.get("_case_id")
                or ""
            )
            for record in valid_representatives
        ]
        empty_representative_id_count = sum(
            1 for record_id in representative_ids if not record_id
        )
        duplicate_representative_id_count = (
            len(representative_ids) - len(set(representative_ids))
        )
        accounting_passed = (
            accounted_count == counts["raw_input_count"]
            and empty_representative_id_count == 0
            and duplicate_representative_id_count == 0
        )

        output_paths = {
            "representatives": out_dir / "01_representative_precedents.jsonl",
            "merged": out_dir / "02_merged_duplicate_records.jsonl",
            "rejected": out_dir / "03_rejected_preprocessing_records.jsonl",
        }
        write_jsonl(output_paths["representatives"], valid_representatives)
        write_jsonl(output_paths["merged"], merged)
        write_jsonl(output_paths["rejected"], rejected)

        completed_at = datetime.now().isoformat(timespec="seconds")
        report = {
            "generated_at": completed_at,
            "runner_version": RUNNER_VERSION,
            "merger_version": MERGER_VERSION,
            "similarity_threshold": args.threshold,
            "inputs": inputs,
            "counts": counts,
            "accounting": {
                "accounted_count": accounted_count,
                "empty_representative_id_count": (
                    empty_representative_id_count
                ),
                "duplicate_representative_id_count": (
                    duplicate_representative_id_count
                ),
                "accounting_passed": accounting_passed,
            },
            "output_directory": str(out_dir),
        }
        report_path = out_dir / "04_preprocessing_report.json"
        write_json(report_path, report)

        manifest["completed_at"] = completed_at
        manifest["status"] = "COMPLETED" if accounting_passed else "FAILED"
        manifest["counts"] = counts
        manifest["accounting_passed"] = accounting_passed
        manifest["outputs"] = {
            label: {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for label, path in output_paths.items()
        }
        manifest["outputs"]["report"] = {
            "path": str(report_path),
            "bytes": report_path.stat().st_size,
            "sha256": sha256_file(report_path),
        }
        write_json(manifest_path, manifest)
        if not accounting_passed:
            raise RuntimeError("C단계 정산식 또는 대표 ID 검증에 실패했습니다.")

        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        manifest["completed_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["status"] = "FAILED"
        write_json(manifest_path, manifest)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
