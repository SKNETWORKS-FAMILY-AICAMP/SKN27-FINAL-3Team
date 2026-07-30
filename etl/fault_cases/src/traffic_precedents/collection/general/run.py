"""일반 판례 수집 (B1 목록 수집, B2 시드 사전 대조, B3 상세 수집) 실행 CLI."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from .collector import (
    collect_b1_candidate_lists,
    fetch_b3_details,
    filter_b2_with_seed_registry,
)
from ..seed.io_utils import (
    load_dotenv,
    read_jsonl,
    write_json,
    write_jsonl,
)
from ..seed.law_api import LawGoKrClient

WORKSPACE_ROOT = Path.cwd()
DATA_ROOT = WORKSPACE_ROOT / "outputs" / "traffic_precedents"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="국가법령정보센터에서 일반 과실비율 판례 후보를 수집합니다."
    )
    parser.add_argument(
        "--display-per-query",
        type=int,
        default=100,
        help="질의당 수집할 후보 목록 개수 (기본 100)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="질의당 수집할 최대 페이지 수 (0 지정 시 API 결과가 없을 때까지 제한 없이 무제한 전수 수집)",
    )
    parser.add_argument(
        "--out-dir",
        help="출력 폴더 경로",
    )
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--sleep", type=float, default=0.25)
    return parser.parse_args()


def load_seed_case_numbers() -> set[str]:
    """1단계에서 확보한 시드 판례 고유 사건번호 세트를 로드합니다."""
    output_base = DATA_ROOT / "03_output" / "01_seed_precedents"
    if not output_base.exists():
        return set()

    # 가장 최근 실행 결과 폴더 찾기
    run_dirs = sorted(output_base.glob("run_*"))
    if not run_dirs:
        return set()

    latest_dir = run_dirs[-1]
    unique_file = latest_dir / "02_case_numbers_unique.jsonl"
    if not unique_file.exists():
        return set()

    rows = read_jsonl(unique_file)
    return {row["case_number"] for row in rows if "case_number" in row}


def main() -> int:
    args = parse_args()
    load_dotenv(WORKSPACE_ROOT / "90_config" / ".env")
    load_dotenv(WORKSPACE_ROOT / ".env")
    load_dotenv(WORKSPACE_ROOT.parents[2] / ".env")

    oc = os.getenv("LAW_GO_KR_OC", "").strip()
    if not oc:
        print("LAW_GO_KR_OC가 설정되지 않았습니다.", file=sys.stderr)
        return 1

    run_name = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    out_dir = (
        Path(args.out_dir).expanduser().resolve()
        if args.out_dir
        else DATA_ROOT / "03_output" / "02_general_precedents" / run_name
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    print("B1: 질의별 일반 판례 목록 수집 시작...")
    client = LawGoKrClient(oc=oc, timeout=args.timeout, sleep_seconds=args.sleep)
    b1_candidates = collect_b1_candidate_lists(
        client=client,
        display_per_query=args.display_per_query,
        max_pages=args.max_pages,
    )
    print(f"B1 수집 완료: 총 고유 후보 {len(b1_candidates)}건 목록 확보")

    # B2: 시드 사전 대조
    seed_numbers = load_seed_case_numbers()
    to_fetch, skipped_seeds = filter_b2_with_seed_registry(b1_candidates, seed_numbers)
    print(
        f"B2 시드 대조 완료: 상세 수집 대상 {len(to_fetch)}건, "
        f"시드 중복 스킵 {len(skipped_seeds)}건"
    )

    print("B3: 알짜 일반 후보 상세 원문 수집 시작...")
    collected_details, errors = fetch_b3_details(client, to_fetch)
    print(f"B3 상세 수집 완료: 성공 {len(collected_details)}건, 에러 {len(errors)}건")

    # 산출물 저장
    write_jsonl(
        out_dir / "01_general_candidates_b1_list.jsonl",
        [
            {
                "case_id": item.case_id,
                "case_number": item.case_number,
                "normalized_case_number": item.normalized_case_number,
                "case_name": item.case_name,
                "court_name": item.court_name,
                "decision_date": item.decision_date,
                "collection_provenance": item.collection_provenance,
            }
            for item in b1_candidates
        ],
    )
    write_jsonl(
        out_dir / "02_skipped_seed_candidates.jsonl",
        [
            {
                "case_id": item.case_id,
                "case_number": item.case_number,
                "normalized_case_number": item.normalized_case_number,
            }
            for item in skipped_seeds
        ],
    )
    write_jsonl(out_dir / "03_general_precedents_collected.jsonl", collected_details)
    write_jsonl(out_dir / "04_errors.jsonl", errors)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "b1_total_candidates": len(b1_candidates),
        "b2_seed_skipped_count": len(skipped_seeds),
        "b3_to_fetch_count": len(to_fetch),
        "b3_collected_count": len(collected_details),
        "b3_error_count": len(errors),
        "output_directory": str(out_dir),
    }
    write_json(out_dir / "05_run_report.json", report)
    print(f"B단계 일반 판례 수집 최종 완료! 결과 저장: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
