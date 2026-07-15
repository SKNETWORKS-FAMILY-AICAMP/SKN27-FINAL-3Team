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
)

SOURCE_NAME = "protection_zones"


def protection_zone_snapshot_path(sgg_cd: str, page_no: int) -> Path:
    """보호구역 원본 응답을 날짜가 붙은 소스 폴더와 지역코드 폴더 아래에 저장할 경로를 만든다."""
    dated_source_name = f"{SOURCE_NAME}_{datetime.now().strftime('%y%m%d')}"
    return data_path("snapshots", dated_source_name, sgg_cd, f"page_{page_no:05d}.json")


def protection_zone_error_path(sgg_cd: str) -> Path:
    """보호구역 수집 실패 정보를 날짜 없이 지역코드 기준 파일로 저장할 경로를 만든다."""
    return data_path("rejected", SOURCE_NAME, f"{sgg_cd}_error.json")


def load_rejected_sgg_codes() -> list[str]:
    """실패 기록 폴더의 *_error.json 파일명에서 재시도할 시군구 코드를 읽는다."""
    rejected_dir = data_path("rejected", SOURCE_NAME)
    if not rejected_dir.exists():
        return []

    codes = []
    for path in sorted(rejected_dir.glob("*_error.json")):
        code = path.stem.removesuffix("_error")
        if code:
            codes.append(code)
    return codes


def clear_rejected_sgg_code(sgg_cd: str) -> None:
    """시군구 코드 재수집이 성공하면 기존 실패 기록을 삭제한다."""
    error_path = protection_zone_error_path(sgg_cd)
    if error_path.exists():
        error_path.unlink()


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


async def collect_raw_pages(max_pages_per_sgg: int | None = None, sgg_codes: list[str] | None = None) -> None:
    """지정된 시군구 코드 또는 활성화된 모든 시군구 코드의 보호구역 원본 응답을 수집한다."""
    settings = get_settings()
    target_sgg_codes = sgg_codes or load_sgg_codes(settings)
    for sgg_cd in target_sgg_codes:
        source_key = f"{SOURCE_NAME}_{sgg_cd}"
        saved_any_page = False
        try:
            async for page_no, payload in iter_public_data_pages(
                api_url=settings.protection_zones_api_url,
                extra_params=build_extra_params(settings, sgg_cd),
                max_pages=max_pages_per_sgg,
                settings=settings,
            ):
                path = save_json(payload, protection_zone_snapshot_path(sgg_cd, page_no))
                saved_any_page = True
                print(f"[{source_key}] saved page {page_no}: {path}")
            if saved_any_page:
                clear_rejected_sgg_code(sgg_cd)
        except PublicDataApiError as exc:
            error_path = protection_zone_error_path(sgg_cd)
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
    parser.add_argument("--retry-rejected", action="store_true", help="실패 기록에 남은 시군구 코드만 다시 수집합니다.")
    parser.add_argument("--max-pages", type=int, default=None, help="시군구별 테스트용 최대 페이지 수")
    return parser.parse_args()


def main() -> None:
    """스크립트 진입점으로 preview 또는 collect 모드를 실행한다."""
    args = parse_args()
    try:
        if args.collect or args.retry_rejected:
            retry_codes = load_rejected_sgg_codes() if args.retry_rejected else None
            if args.retry_rejected:
                print(f"[{SOURCE_NAME}] retry rejected sgg codes: {len(retry_codes)}")
            asyncio.run(collect_raw_pages(max_pages_per_sgg=args.max_pages, sgg_codes=retry_codes))
        else:
            asyncio.run(preview())
    except PublicDataApiError as exc:
        raise SystemExit(f"[{SOURCE_NAME}] API 오류: {exc}") from None


if __name__ == "__main__":
    main()
