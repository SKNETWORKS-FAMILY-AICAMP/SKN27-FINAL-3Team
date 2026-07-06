"""
review_case 패키지 실행 컨트롤러.

지원 stage:
- crawl: 심의사례 PDF 수집
- preprocess: 현재 reset 상태. 나중에 preprocessing/preprocess_runner.py를 새로 만들면 실행된다.
"""

from __future__ import annotations

import argparse
import sys


def parse_stage_args() -> tuple[str, list[str]]:
    """stage 인자와 나머지 인자를 분리한다."""

    parser = argparse.ArgumentParser(description="과실비율 심의사례 파이프라인 실행 컨트롤러")
    parser.add_argument("--stage", choices=["crawl", "preprocess"], default="crawl")
    args, remaining = parser.parse_known_args()
    return args.stage, remaining


def main() -> None:
    """선택한 stage를 실행한다."""

    stage, remaining = parse_stage_args()
    sys.argv = [sys.argv[0], *remaining]

    if stage == "crawl":
        from .crawling.one_click_collect import main as crawl_main

        crawl_main()
        return

    if stage == "preprocess":
        try:
            from .preprocessing.preprocess_runner import main as preprocess_main
        except ImportError as error:
            raise SystemExit(
                "심의사례 전처리 코드는 현재 reset 상태입니다. "
                "새 전처리 구현을 etl/fault_cases/src/review_case/preprocessing/"
                "preprocess_runner.py에 만든 뒤 다시 실행해 주세요."
            ) from error

        preprocess_main()
        return

    raise SystemExit(f"지원하지 않는 stage입니다: {stage}")


if __name__ == "__main__":
    main()
