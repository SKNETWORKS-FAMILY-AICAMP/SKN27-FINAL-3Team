"""명시적 C단계 입력으로 D 문맥 의미 블록을 스트리밍 생성합니다."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from .parser import PARSER_VERSION, parse_semantic_blocks

DATA_ROOT = Path.cwd() / "outputs" / "traffic_precedents"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="검증된 C단계 대표 판례에서 문맥 의미 블록을 만듭니다."
    )
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--out-dir")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_file).expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    run_name = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    out_dir = (
        Path(args.out_dir).expanduser().resolve()
        if args.out_dir
        else DATA_ROOT / "03_output" / "04_semantic_blocks" / run_name
    )
    out_dir.mkdir(parents=True, exist_ok=False)
    block_path = out_dir / "01_semantic_blocks.jsonl"
    case_summary_path = out_dir / "02_case_block_summary.jsonl"
    report_path = out_dir / "03_semantic_block_report.json"
    manifest_path = out_dir / "04_run_manifest.json"
    started_at = datetime.now().isoformat(timespec="seconds")
    input_info = {
        "path": str(input_path),
        "bytes": input_path.stat().st_size,
        "sha256": sha256_file(input_path),
    }
    counts = Counter()
    role_counts = Counter()
    section_counts = Counter()
    manifest = {
        "run_id": out_dir.name,
        "stage": "04_semantic_blocks",
        "parser_version": PARSER_VERSION,
        "started_at": started_at,
        "completed_at": None,
        "status": "RUNNING",
        "input": input_info,
        "outputs": {},
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    try:
        with (
            input_path.open("r", encoding="utf-8") as source,
            block_path.open("w", encoding="utf-8", newline="\n") as block_out,
            case_summary_path.open(
                "w", encoding="utf-8", newline="\n"
            ) as summary_out,
        ):
            for line in source:
                if not line.strip():
                    continue
                record = json.loads(line)
                counts["input_case_count"] += 1
                blocks = parse_semantic_blocks(record)
                record_id = str(
                    record.get("판례정보일련번호")
                    or record.get("판례일련번호")
                    or record.get("_case_id")
                    or ""
                )
                if not blocks:
                    counts["zero_block_case_count"] += 1
                case_roles = Counter()
                for block in blocks:
                    row = block.to_dict()
                    block_out.write(json.dumps(row, ensure_ascii=False) + "\n")
                    counts["total_block_count"] += 1
                    role_counts[block.semantic_role] += 1
                    section_counts[block.section_name] += 1
                    case_roles[block.semantic_role] += 1
                    if block.is_valid_evidence:
                        counts["valid_evidence_block_count"] += 1
                    else:
                        counts["invalid_evidence_block_count"] += 1
                summary_out.write(
                    json.dumps(
                        {
                            "record_id": record_id,
                            "internal_grade": record.get("internal_grade"),
                            "block_count": len(blocks),
                            "role_counts": dict(case_roles),
                            "parser_version": PARSER_VERSION,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        accounting_passed = (
            counts["total_block_count"]
            == counts["valid_evidence_block_count"]
            + counts["invalid_evidence_block_count"]
            and counts["zero_block_case_count"] == 0
            and role_counts.get("ACCIDENT_FACT", 0)
            + role_counts.get("FAULT_DECISION", 0)
            + role_counts.get("PARTY_ARGUMENT", 0)
            + role_counts.get("INSURANCE_DAMAGE_PROCEDURE", 0)
            + role_counts.get("GENERAL_LEGAL_PRINCIPLE", 0)
            + role_counts.get("INLINE_CITATION", 0)
            + role_counts.get("OTHER", 0)
            == counts["total_block_count"]
        )
        completed_at = datetime.now().isoformat(timespec="seconds")
        report = {
            "generated_at": completed_at,
            "parser_version": PARSER_VERSION,
            "input": input_info,
            "counts": dict(counts),
            "role_counts": dict(role_counts),
            "section_counts": dict(section_counts),
            "accounting_passed": accounting_passed,
            "output_directory": str(out_dir),
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest["completed_at"] = completed_at
        manifest["status"] = "COMPLETED" if accounting_passed else "FAILED"
        manifest["counts"] = dict(counts)
        manifest["accounting_passed"] = accounting_passed
        manifest["outputs"] = {
            "blocks": {
                "path": str(block_path),
                "bytes": block_path.stat().st_size,
                "sha256": sha256_file(block_path),
            },
            "case_summary": {
                "path": str(case_summary_path),
                "bytes": case_summary_path.stat().st_size,
                "sha256": sha256_file(case_summary_path),
            },
            "report": {
                "path": str(report_path),
                "bytes": report_path.stat().st_size,
                "sha256": sha256_file(report_path),
            },
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if not accounting_passed:
            raise RuntimeError("D단계 블록 정산 또는 zero-block 검증 실패")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        manifest["completed_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["status"] = "FAILED"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
