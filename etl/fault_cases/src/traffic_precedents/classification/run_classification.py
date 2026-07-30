"""C 판례와 D 의미 블록을 E~I로 분류하고 J 독립 검증을 수행합니다."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .classifier import CLASSIFIER_VERSION, classify_case


DATA_ROOT = Path.cwd() / "outputs" / "traffic_precedents"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="C 대표 판례와 D 의미 블록으로 E~I 분류를 실행합니다."
    )
    parser.add_argument("--cases-input", required=True)
    parser.add_argument("--blocks-input", required=True)
    parser.add_argument("--out-dir")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def file_info(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def record_id_of(case: dict[str, Any]) -> str:
    return str(
        case.get("판례정보일련번호")
        or case.get("판례일련번호")
        or case.get("_case_id")
        or ""
    )


def load_blocks(path: Path) -> tuple[dict[str, list[dict[str, Any]]], Counter]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    counts = Counter()
    seen_block_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            record_id = str(row.get("record_id") or "")
            block_id = str(row.get("block_id") or "")
            if not record_id or not block_id:
                raise ValueError(f"D 블록 필수 ID 누락: line={line_number}")
            if block_id in seen_block_ids:
                raise ValueError(f"D 블록 ID 중복: {block_id}")
            seen_block_ids.add(block_id)
            grouped[record_id].append(row)
            counts["input_block_count"] += 1
            if row.get("is_valid_evidence") is True:
                counts["valid_evidence_block_count"] += 1
    counts["block_record_count"] = len(grouped)
    return grouped, counts


def main() -> int:
    args = parse_args()
    cases_path = Path(args.cases_input).expanduser().resolve()
    blocks_path = Path(args.blocks_input).expanduser().resolve()
    for path in (cases_path, blocks_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    run_name = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    out_dir = (
        Path(args.out_dir).expanduser().resolve()
        if args.out_dir
        else DATA_ROOT / "03_output" / "05_classification_validation" / run_name
    )
    out_dir.mkdir(parents=True, exist_ok=False)
    results_path = out_dir / "01_classification_candidates.jsonl"
    grade_manifest_path = out_dir / "02_grade_manifest.json"
    report_path = out_dir / "03_classification_report.json"
    run_manifest_path = out_dir / "04_run_manifest.json"

    started_at = datetime.now().isoformat(timespec="seconds")
    inputs = {
        "cases": file_info(cases_path),
        "blocks": file_info(blocks_path),
    }
    manifest: dict[str, Any] = {
        "run_id": out_dir.name,
        "stage": "05_classification",
        "classifier_version": CLASSIFIER_VERSION,
        "started_at": started_at,
        "completed_at": None,
        "status": "RUNNING",
        "inputs": inputs,
        "outputs": {},
    }
    run_manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    try:
        blocks_by_record, block_counts = load_blocks(blocks_path)
        counts = Counter(block_counts)
        grade_counts = Counter()
        main_issue_counts = Counter()
        gate_pass_counts = Counter()
        grade_record_ids: dict[str, list[str]] = defaultdict(list)
        case_ids: set[str] = set()

        with (
            cases_path.open("r", encoding="utf-8") as source,
            results_path.open("w", encoding="utf-8", newline="\n") as output,
        ):
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                case = json.loads(line)
                record_id = record_id_of(case)
                if not record_id:
                    raise ValueError(f"C 판례 필수 ID 누락: line={line_number}")
                if record_id in case_ids:
                    raise ValueError(f"C 판례 ID 중복: {record_id}")
                case_ids.add(record_id)
                case_blocks = blocks_by_record.get(record_id, [])
                if not case_blocks:
                    counts["case_without_blocks_count"] += 1

                result = classify_case(case, case_blocks)
                output.write(json.dumps(result, ensure_ascii=False) + "\n")

                counts["input_case_count"] += 1
                counts["classified_case_count"] += 1
                grade = result["internal_grade"]
                grade_counts[grade] += 1
                main_issue_counts[result["main_issue"]] += 1
                grade_record_ids[grade].append(record_id)
                for gate, passed in result["gates"].items():
                    if passed:
                        gate_pass_counts[gate] += 1

        orphan_block_ids = sorted(set(blocks_by_record) - case_ids)
        missing_block_case_ids = sorted(case_ids - set(blocks_by_record))
        counts["orphan_block_record_count"] = len(orphan_block_ids)
        counts["missing_block_case_count"] = len(missing_block_case_ids)
        counts["seed_ready_count"] = grade_counts["SEED_READY"]

        expected_grades = {
            "SEED_READY",
            "GENERAL_READY_DIRECT",
            "GENERAL_READY_LEGAL_SUPPORT",
            "GENERAL_QUARANTINE",
            "GENERAL_EXCLUDED",
        }
        unknown_grades = sorted(set(grade_counts) - expected_grades)
        accounting_passed = (
            counts["input_case_count"] == counts["classified_case_count"]
            == sum(grade_counts.values())
            and counts["case_without_blocks_count"] == 0
            and counts["orphan_block_record_count"] == 0
            and counts["missing_block_case_count"] == 0
            and not unknown_grades
        )
        completed_at = datetime.now().isoformat(timespec="seconds")

        grade_manifest = {
            "generated_at": completed_at,
            "classifier_version": CLASSIFIER_VERSION,
            "grade_counts": dict(grade_counts),
            "grade_record_ids": dict(grade_record_ids),
        }
        grade_manifest_path.write_text(
            json.dumps(grade_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        report = {
            "generated_at": completed_at,
            "classifier_version": CLASSIFIER_VERSION,
            "inputs": inputs,
            "counts": dict(counts),
            "grade_counts": dict(grade_counts),
            "main_issue_counts": dict(main_issue_counts),
            "gate_pass_counts": dict(gate_pass_counts),
            "unknown_grades": unknown_grades,
            "orphan_block_record_ids": orphan_block_ids[:100],
            "missing_block_case_ids": missing_block_case_ids[:100],
            "accounting_passed": accounting_passed,
            "output_directory": str(out_dir),
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest.update(
            {
                "completed_at": completed_at,
                "status": "COMPLETED" if accounting_passed else "FAILED",
                "counts": dict(counts),
                "grade_counts": dict(grade_counts),
                "accounting_passed": accounting_passed,
                "outputs": {
                    "classification_results": file_info(results_path),
                    "grade_manifest": file_info(grade_manifest_path),
                    "report": file_info(report_path),
                },
            }
        )
        run_manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if not accounting_passed:
            raise RuntimeError("E~I 분류 정산 실패")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        manifest["completed_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["status"] = "FAILED"
        run_manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
