"""인정기준 PDF 판례번호 추출 및 국가법령정보센터 수집 CLI."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from .io_utils import (
    append_jsonl,
    load_dotenv,
    write_json,
    write_jsonl,
)
from .law_api import LawGoKrClient
from .pdf_extract import (
    build_unique_targets,
    extract_pdf_citations,
)

WORKSPACE_ROOT = Path.cwd()
DATA_ROOT = WORKSPACE_ROOT / "outputs" / "traffic_precedents"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "인정기준 PDF에서 판례번호를 추출하고 LAW_GO_KR_OC로 "
            "국가법령정보센터 판례 원문을 수집합니다."
        )
    )
    parser.add_argument(
        "--pdf",
        action="append",
        default=[],
        help="입력 PDF 경로. 여러 번 지정할 수 있습니다.",
    )
    parser.add_argument(
        "--pdf-dir",
        default=str(DATA_ROOT / "01_input" / "pdfs"),
        help="--pdf 미지정 시 PDF를 찾을 폴더",
    )
    parser.add_argument(
        "--out-dir",
        help=(
            "출력 폴더. 기본은 "
            "outputs/traffic_precedents/03_output/01_seed_precedents/run_YYYYMMDD_HHMMSS"
        ),
    )
    parser.add_argument(
        "--expected-count",
        type=int,
        default=250,
        help="고유 사건번호 예상값. 불일치해도 실행은 계속됩니다.",
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="PDF 사건번호 추출까지만 실행합니다.",
    )
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--sleep", type=float, default=0.25)
    return parser.parse_args()


def resolve_pdfs(args: argparse.Namespace) -> list[Path]:
    if args.pdf:
        return [Path(value).expanduser().resolve() for value in args.pdf]
    pdf_dir = Path(args.pdf_dir).expanduser().resolve()
    return sorted(pdf_dir.glob("*.pdf")) if pdf_dir.exists() else []


def main() -> int:
    args = parse_args()
    load_dotenv(WORKSPACE_ROOT / "90_config" / ".env")
    load_dotenv(WORKSPACE_ROOT / ".env")
    load_dotenv(WORKSPACE_ROOT.parents[2] / ".env")

    pdf_paths = resolve_pdfs(args)
    if not pdf_paths:
        print(
            "입력 PDF가 없습니다. "
            "outputs/traffic_precedents/01_input/pdfs/에 PDF 4종을 넣거나 "
            "--pdf 옵션으로 지정하세요.",
            file=sys.stderr,
        )
        return 2

    run_name = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    out_dir = (
        Path(args.out_dir).expanduser().resolve()
        if args.out_dir
        else DATA_ROOT / "03_output" / "01_seed_precedents" / run_name
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    occurrences, warnings = extract_pdf_citations(pdf_paths)
    targets = build_unique_targets(occurrences)

    paths = {
        "occurrences": out_dir / "01_pdf_citations_raw.jsonl",
        "targets": out_dir / "02_case_numbers_unique.jsonl",
        "collected": out_dir / "03_precedents_collected.jsonl",
        "not_found": out_dir / "04_precedents_not_found.jsonl",
        "ambiguous": out_dir / "05_precedents_ambiguous.jsonl",
        "errors": out_dir / "06_errors.jsonl",
        "report": out_dir / "07_run_report.json",
    }
    write_jsonl(paths["occurrences"], occurrences)
    write_jsonl(paths["targets"], targets)
    write_jsonl(paths["errors"], warnings)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pdf_files": [str(path) for path in pdf_paths],
        "pdf_count": len(pdf_paths),
        "citation_occurrence_count": len(occurrences),
        "unique_case_number_count": len(targets),
        "expected_unique_case_number_count": args.expected_count,
        "expected_count_matches": len(targets) == args.expected_count,
        "pdf_warning_count": len(warnings),
        "extract_only": args.extract_only,
        "collected": 0,
        "not_found": 0,
        "ambiguous": 0,
        "api_errors": 0,
    }

    if args.extract_only:
        write_json(paths["report"], report)
        print(
            f"추출 완료: occurrences={len(occurrences)}, "
            f"unique={len(targets)}, out={out_dir}"
        )
        return 0

    oc = os.getenv("LAW_GO_KR_OC", "").strip()
    if not oc:
        write_json(paths["report"], report)
        print(
            "LAW_GO_KR_OC가 설정되지 않았습니다. 사건번호 추출 결과는 "
            f"저장했습니다: {out_dir}",
            file=sys.stderr,
        )
        return 3

    client = LawGoKrClient(
        oc=oc,
        timeout=args.timeout,
        sleep_seconds=args.sleep,
    )
    for index, target in enumerate(targets, 1):
        outcome = client.collect_target(target)
        if outcome.status == "collected":
            append_jsonl(paths["collected"], outcome.detail or {})
            report["collected"] += 1
        elif outcome.status == "not_found":
            append_jsonl(
                paths["not_found"],
                {
                    **target,
                    "collection_status": "not_found",
                },
            )
            report["not_found"] += 1
        elif outcome.status == "ambiguous":
            append_jsonl(
                paths["ambiguous"],
                {
                    **target,
                    "collection_status": "ambiguous",
                    "candidates": outcome.candidates or [],
                },
            )
            report["ambiguous"] += 1
        else:
            append_jsonl(
                paths["errors"],
                {
                    "stage": "law_api",
                    "case_number": target["case_number"],
                    "error": outcome.error,
                },
            )
            report["api_errors"] += 1

        if index % 20 == 0 or index == len(targets):
            print(f"API 수집 진행: {index}/{len(targets)}")

    write_json(paths["report"], report)
    print(
        "수집 완료: "
        f"collected={report['collected']}, "
        f"not_found={report['not_found']}, "
        f"ambiguous={report['ambiguous']}, "
        f"errors={report['api_errors']}, "
        f"out={out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
