"""전국 도로안내표지 공공데이터 로더."""

from __future__ import annotations

import argparse
import asyncio

from app.config import get_settings
from loaders.common import latest_snapshot_page, iter_public_data_pages, preview_public_data_api, save_json, snapshot_path

SOURCE_NAME = "road_signs"


def build_extra_params() -> dict[str, str]:
    """도로안내표지 API에 추가로 넘길 파라미터를 만든다."""
    return {"type": "json"}


async def preview() -> dict:
    """도로안내표지 API를 1건 호출하고 응답 샘플을 저장한다."""
    settings = get_settings()
    return await preview_public_data_api(
        source_name=SOURCE_NAME,
        api_url=settings.road_signs_api_url,
        extra_params=build_extra_params(),
        settings=settings,
    )


async def collect_raw_pages(max_pages: int | None = None, start_page: int = 1) -> None:
    """도로안내표지 API 원본 응답을 페이지별 스냅샷으로 저장한다."""
    settings = get_settings()
    async for page_no, payload in iter_public_data_pages(
        api_url=settings.road_signs_api_url,
        extra_params=build_extra_params(),
        max_pages=max_pages,
        start_page=start_page,
        settings=settings,
    ):
        path = save_json(payload, snapshot_path(SOURCE_NAME, page_no))
        print(f"[{SOURCE_NAME}] saved page {page_no}: {path}")


def parse_args() -> argparse.Namespace:
    """명령행 옵션을 해석한다."""
    parser = argparse.ArgumentParser(description="전국 도로안내표지 데이터 로더")
    parser.add_argument("--collect", action="store_true", help="전체 페이지 원본을 수집합니다.")
    parser.add_argument("--max-pages", type=int, default=None, help="테스트용 최대 페이지 수")
    parser.add_argument("--start-page", type=int, default=1, help="수집을 시작할 pageNo")
    parser.add_argument("--resume", action="store_true", help="오늘 저장된 마지막 페이지 다음부터 이어받습니다.")
    return parser.parse_args()


def main() -> None:
    """스크립트 진입점으로 preview 또는 collect 모드를 실행한다."""
    args = parse_args()
    if args.collect:
        start_page = args.start_page
        if args.resume:
            last_page = latest_snapshot_page(SOURCE_NAME)
            start_page = (last_page or 0) + 1
            print(f"[{SOURCE_NAME}] resume from page {start_page}")
        asyncio.run(collect_raw_pages(max_pages=args.max_pages, start_page=start_page))
    else:
        asyncio.run(preview())


if __name__ == "__main__":
    main()
