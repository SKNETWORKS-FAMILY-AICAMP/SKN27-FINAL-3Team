"""로드된 원천 데이터와 로더 설정을 점검하는 검증 스크립트."""

from __future__ import annotations

import csv
from pathlib import Path

from app.config import Settings, get_settings
from loaders.load_protection_zones import load_sgg_codes


def validate_required_urls(settings: Settings) -> list[str]:
    """공공데이터 4종 API URL 설정이 모두 채워졌는지 검사한다."""
    errors: list[str] = []
    required_urls = {
        "ROAD_SIGNS_API_URL": settings.road_signs_api_url,
        "TRAFFIC_SIGNALS_API_URL": settings.traffic_signals_api_url,
        "CROSSWALKS_API_URL": settings.crosswalks_api_url,
        "PROTECTION_ZONES_API_URL": settings.protection_zones_api_url,
    }
    for name, value in required_urls.items():
        if not value:
            errors.append(f"{name} 값이 비어 있습니다.")
    return errors


def validate_sgg_codes_csv(settings: Settings) -> list[str]:
    """보호구역 전국 수집에 필요한 시군구 코드 CSV를 검사한다."""
    errors: list[str] = []
    csv_path = Path(settings.protection_zone_sgg_codes_csv)
    if settings.protection_zone_sgg_code_list:
        return errors
    if not csv_path.exists():
        return [f"시군구 코드 CSV가 없습니다: {csv_path}"]

    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required_columns = {"sgg_cd", "sido_name", "sigungu_name", "enabled"}
        missing = required_columns.difference(reader.fieldnames or [])
        if missing:
            errors.append(f"시군구 코드 CSV 필수 컬럼 누락: {sorted(missing)}")
    return errors


def validate_loader_settings() -> list[str]:
    """로더 실행 전에 필요한 환경설정 전체를 검사한다."""
    settings = get_settings()
    errors = []
    errors.extend(validate_required_urls(settings))
    errors.extend(validate_sgg_codes_csv(settings))
    try:
        codes = load_sgg_codes(settings)
        if not codes:
            errors.append("활성화된 보호구역 시군구 코드가 없습니다.")
    except RuntimeError as exc:
        errors.append(str(exc))
    return errors


def main() -> None:
    """검증 결과를 콘솔에 출력하고 실패 시 종료 코드를 발생시킨다."""
    errors = validate_loader_settings()
    if errors:
        print("로더 설정 검증 실패:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("로더 설정 검증 통과")


if __name__ == "__main__":
    main()
