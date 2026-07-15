"""대한민국 OSM PBF 다운로드와 osm2pgsql 적재 준비 로더."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import httpx

from app.config import get_settings
from loaders.common import data_path, ensure_data_dirs, require_value


async def download_osm_pbf(force: bool = False) -> Path:
    """Geofabrik 대한민국 OSM PBF 파일을 data/raw/osm 아래로 다운로드한다."""
    settings = get_settings()
    ensure_data_dirs(settings)
    url = require_value(settings.osm_pbf_url, "OSM_PBF_URL")
    output_dir = data_path("raw", "osm", settings=settings)
    output_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            if str(response.url) != url:
                print(f"Redirected OSM PBF URL: {response.url}")
            output_filename = Path(response.url.path).name or "south-korea-latest.osm.pbf"
            output_path = output_dir / output_filename
            if output_path.exists() and not force:
                print(f"OSM PBF already exists: {output_path}")
                return output_path
            with output_path.open("wb") as file:
                async for chunk in response.aiter_bytes():
                    file.write(chunk)

    print(f"Downloaded OSM PBF: {output_path}")
    return output_path


def print_osm2pgsql_next_step(pbf_path: Path) -> None:
    """다운로드 후 실행해야 할 osm2pgsql 명령 예시를 출력한다."""
    print("다음 단계는 osm2pgsql Flex 적재입니다.")
    print("예시:")
    print(
        "osm2pgsql --create --slim --database \"$ROAD_DB_NAME\" "
        f"--style loaders/osm2pgsql_flex.lua --output flex \"{pbf_path}\""
    )


def parse_args() -> argparse.Namespace:
    """명령행 옵션을 해석한다."""
    parser = argparse.ArgumentParser(description="대한민국 OSM PBF 로더")
    parser.add_argument("--download", action="store_true", help="OSM PBF를 다운로드합니다.")
    parser.add_argument("--force", action="store_true", help="기존 PBF가 있어도 다시 받습니다.")
    return parser.parse_args()


def main() -> None:
    """스크립트 진입점으로 다운로드 여부에 따라 OSM 준비 작업을 실행한다."""
    args = parse_args()
    if args.download:
        pbf_path = asyncio.run(download_osm_pbf(force=args.force))
        print_osm2pgsql_next_step(pbf_path)
    else:
        ensure_data_dirs()
        print("OSM 로더 준비 완료. 다운로드하려면 --download 옵션을 사용하세요.")


if __name__ == "__main__":
    main()
