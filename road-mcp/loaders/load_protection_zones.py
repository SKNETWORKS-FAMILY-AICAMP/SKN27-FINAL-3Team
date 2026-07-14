"""경찰청 전국 보호구역 현황 공공데이터 로더."""

from __future__ import annotations

import argparse
import asyncio
import csv
from datetime import datetime
from pathlib import Path

from app.config import Settings, get_settings
from loaders.common import (
    PublicDataApiError,
    data_path,
    iter_public_data_pages,
    preview_public_data_api,
    require_value,
    save_json,
    snapshot_path,
)

SOURCE_NAME = "protection_zones"


def load_sgg_codes(settings: Settings) -> list[str]:
    """보호구역 API 호출에 사용할 시군구 코드를 환경변수 또는 CSV에서 읽는다."""
    env_codes = settings.protection_zone_sgg_code_list
    if env_codes:
        return env_codes

    csv_path = Path(settings.protection_zone_sgg_codes_csv)
    if not csv_path.exists():
        raise RuntimeError(
            "보호구역 시군구 코드가 없습니다. PROTECTION_ZONE_SGG_CODES를 설정하거나 "
            "PROTECTION_ZONE_SGG_CODES_CSV 파일을 생성하세요."
        )

    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        codes = [
            row["sgg_cd"].strip()
            for row in reader
            if row.get("sgg_cd", "").strip() and row.get("enabled", "").strip().lower() == "true"
        ]

    if not codes:
        raise RuntimeError(f"활성화된 시군구 코드가 없습니다: {csv_path}")
    return codes


def build_extra_params(settings: Settings, sgg_cd: str) -> dict[str, str]:
    """보호구역 API에 필요한 추가 파라미터를 만든다."""
    params = {"sggCd": require_value(sgg_cd, "sggCd")}
    if settings.protection_zone_assign_type:
        params["assignType"] = settings.protection_zone_assign_type
    if settings.protection_zone_call_date:
        params["callDate"] = settings.protection_zone_call_date
    return params


async def preview() -> dict:
    """첫 번째 시군구 코드로 보호구역 API를 1건 호출하고 샘플을 저장한다."""
    settings = get_settings()
    sgg_cd = load_sgg_codes(settings)[0]
    return await preview_public_data_api(
        source_name=f"{SOURCE_NAME}_{sgg_cd}",
        api_url=settings.protection_zones_api_url,
        extra_params=build_extra_params(settings, sgg_cd),
        settings=settings,
    )


async def collect_raw_pages(max_pages_per_sgg: int | None = None) -> None:
    """활성화된 모든 시군구 코드에 대해 보호구역 원본 응답을 수집한다."""
    settings = get_settings()
    sgg_codes = load_sgg_codes(settings)
    for sgg_cd in sgg_codes:
        source_key = f"{SOURCE_NAME}_{sgg_cd}"
        try:
            async for page_no, payload in iter_public_data_pages(
                api_url=settings.protection_zones_api_url,
                extra_params=build_extra_params(settings, sgg_cd),
                max_pages=max_pages_per_sgg,
                settings=settings,
            ):
                path = save_json(payload, snapshot_path(source_key, page_no))
                print(f"[{source_key}] saved page {page_no}: {path}")
        except PublicDataApiError as exc:
            today = datetime.now().strftime("%Y%m%d")
            error_path = data_path("rejected", SOURCE_NAME, today, f"{sgg_cd}_error.json", settings=settings)
            save_json(
                {
                    "source": SOURCE_NAME,
                    "sggCd": sgg_cd,
                    "error": str(exc),
                    "message": "보호구역 API가 해당 시군구 코드에서 오류를 반환해 다음 코드로 넘어갑니다.",
                },
                error_path,
            )
            print(f"[{source_key}] failed and logged: {error_path}")


def parse_args() -> argparse.Namespace:
    """명령행 옵션을 해석한다."""
    parser = argparse.ArgumentParser(description="경찰청 전국 보호구역 현황 데이터 로더")
    parser.add_argument("--collect", action="store_true", help="전체 시군구 원본을 수집합니다.")
    parser.add_argument("--max-pages", type=int, default=None, help="시군구별 테스트용 최대 페이지 수")
    return parser.parse_args()


def main() -> None:
    """스크립트 진입점으로 preview 또는 collect 모드를 실행한다."""
    args = parse_args()
    try:
        if args.collect:
            asyncio.run(collect_raw_pages(max_pages_per_sgg=args.max_pages))
        else:
            asyncio.run(preview())
    except PublicDataApiError as exc:
        raise SystemExit(f"[{SOURCE_NAME}] API 오류: {exc}") from None


if __name__ == "__main__":
    main()
