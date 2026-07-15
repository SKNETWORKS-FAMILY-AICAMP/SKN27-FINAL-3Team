"""로드된 원천 데이터와 로더 설정을 점검하는 검증 스크립트."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from loaders.common import find_record_list, find_total_count, is_no_data_response
from loaders.load_protection_zones import load_sgg_codes


@dataclass
class ValidationReport:
    """검증 결과 메시지를 심각도별로 모아 최종 종료 코드를 결정한다."""

    errors: list[str]
    warnings: list[str]
    infos: list[str]

    def error(self, message: str) -> None:
        """실패로 판단해야 하는 검증 오류를 추가한다."""
        self.errors.append(message)

    def warn(self, message: str) -> None:
        """실패는 아니지만 확인이 필요한 경고를 추가한다."""
        self.warnings.append(message)

    def info(self, message: str) -> None:
        """검증 과정에서 확인한 정상 정보를 추가한다."""
        self.infos.append(message)


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


def validate_loader_settings(settings: Settings, report: ValidationReport) -> list[str]:
    """로더 실행 전에 필요한 환경설정 전체를 검사하고 보호구역 코드를 반환한다."""
    for error in validate_required_urls(settings):
        report.error(error)
    for error in validate_sgg_codes_csv(settings):
        report.error(error)

    try:
        codes = load_sgg_codes(settings)
    except RuntimeError as exc:
        report.error(str(exc))
        return []

    if not codes:
        report.error("활성화된 보호구역 시군구 코드가 없습니다.")
    else:
        report.info(f"보호구역 enabled 시군구 코드 수: {len(codes)}")
    return codes


def dated_source_dir(settings: Settings, source_name: str) -> Path:
    """오늘 날짜가 붙은 공공데이터 snapshot 폴더 경로를 만든다."""
    suffix = datetime.now().strftime("%y%m%d")
    return Path(settings.road_data_dir) / "snapshots" / f"{source_name}_{suffix}"


def read_json_file(path: Path, report: ValidationReport) -> dict[str, Any] | None:
    """JSON 파일을 읽고 파싱 실패나 빈 파일을 검증 오류로 기록한다."""
    if not path.exists():
        report.error(f"JSON 파일이 없습니다: {path}")
        return None
    if path.stat().st_size == 0:
        report.error(f"JSON 파일 크기가 0 byte입니다: {path}")
        return None
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError as exc:
        report.error(f"JSON 파싱 실패: {path} ({exc})")
        return None
    if not isinstance(payload, dict):
        report.error(f"JSON 최상위 구조가 object가 아닙니다: {path}")
        return None
    return payload


def page_number(path: Path) -> int | None:
    """page_00001.json 파일명에서 페이지 번호를 추출한다."""
    match = re.fullmatch(r"page_(\d+)\.json", path.name)
    if not match:
        return None
    return int(match.group(1))


def validate_page_sequence(source_name: str, page_files: list[Path], report: ValidationReport) -> None:
    """페이지 파일 번호가 1부터 마지막까지 빠짐없이 이어지는지 검사한다."""
    numbers = [number for path in page_files if (number := page_number(path)) is not None]
    if len(numbers) != len(page_files):
        report.error(f"{source_name}: page_00001.json 형식이 아닌 파일명이 있습니다.")
        return
    if not numbers:
        report.error(f"{source_name}: 페이지 파일이 없습니다.")
        return

    expected = set(range(1, max(numbers) + 1))
    missing = sorted(expected.difference(numbers))
    if missing:
        preview = ", ".join(str(number) for number in missing[:10])
        report.error(f"{source_name}: 누락된 페이지가 있습니다. missing={preview}")


def validate_public_source(
    settings: Settings,
    source_name: str,
    report: ValidationReport,
) -> None:
    """도로안내표지·신호등·횡단보도 snapshot JSON의 기본 무결성을 검사한다."""
    source_dir = dated_source_dir(settings, source_name)
    if not source_dir.exists():
        report.error(f"{source_name}: snapshot 폴더가 없습니다: {source_dir}")
        return

    page_files = sorted(source_dir.glob("page_*.json"))
    validate_page_sequence(source_name, page_files, report)
    if not page_files:
        return

    total_count: int | None = None
    total_records = 0
    rows_per_page = settings.public_data_default_num_of_rows
    for path in page_files:
        payload = read_json_file(path, report)
        if payload is None:
            continue
        if total_count is None:
            total_count = find_total_count(payload)
        records = find_record_list(payload)
        if records is None:
            report.error(f"{source_name}: records 목록을 찾지 못했습니다: {path}")
            continue
        total_records += len(records)

    if total_count is None:
        report.error(f"{source_name}: totalCount를 찾지 못했습니다.")
        return

    expected_pages = math.ceil(total_count / rows_per_page) if total_count else 0
    if expected_pages != len(page_files):
        report.error(
            f"{source_name}: 페이지 수 불일치. expected={expected_pages}, actual={len(page_files)}, totalCount={total_count}"
        )
    if total_records != total_count:
        report.warn(f"{source_name}: records 합계와 totalCount가 다릅니다. records={total_records}, totalCount={total_count}")
    report.info(f"{source_name}: pages={len(page_files)}, records={total_records}, totalCount={total_count}")


def validate_protection_sgg_dir(sgg_cd: str, sgg_dir: Path, report: ValidationReport) -> bool:
    """보호구역 특정 시군구 폴더의 JSON 파일과 페이지 연속성을 검사한다."""
    page_files = sorted(sgg_dir.glob("page_*.json"))
    validate_page_sequence(f"protection_zones/{sgg_cd}", page_files, report)
    if not page_files:
        return False

    first_payload = read_json_file(page_files[0], report)
    if first_payload is None:
        return False
    if is_no_data_response(first_payload):
        if len(page_files) > 1:
            report.error(
                f"protection_zones/{sgg_cd}: 0건 응답인데 페이지가 여러 개 저장되어 있습니다. "
                f"pages={len(page_files)}"
            )
            return False
        report.info(f"protection_zones/{sgg_cd}: 조회 결과 0건")
        return True

    total_count: int | None = None
    total_records = 0
    for path in page_files:
        payload = first_payload if path == page_files[0] else read_json_file(path, report)
        if payload is None:
            return False
        if total_count is None:
            total_count = find_total_count(payload)
        records = find_record_list(payload)
        if records is None:
            report.error(f"protection_zones/{sgg_cd}: records 목록을 찾지 못했습니다: {path}")
            return False
        total_records += len(records)

    if total_count is None:
        report.error(f"protection_zones/{sgg_cd}: totalCount를 찾지 못했습니다.")
        return False
    if total_records != total_count:
        report.warn(
            f"protection_zones/{sgg_cd}: records 합계와 totalCount가 다릅니다. "
            f"records={total_records}, totalCount={total_count}"
        )
    return True


def validate_protection_zones(
    settings: Settings,
    expected_sgg_codes: list[str],
    clean_resolved_rejected: bool,
    report: ValidationReport,
) -> None:
    """보호구역 snapshot과 rejected 재시도 큐 상태를 검사한다."""
    source_dir = dated_source_dir(settings, "protection_zones")
    rejected_dir = Path(settings.road_data_dir) / "rejected" / "protection_zones"
    if not source_dir.exists():
        report.error(f"protection_zones: snapshot 폴더가 없습니다: {source_dir}")
        return

    success_codes: set[str] = set()
    for sgg_dir in sorted(path for path in source_dir.iterdir() if path.is_dir()):
        sgg_cd = sgg_dir.name
        if validate_protection_sgg_dir(sgg_cd, sgg_dir, report):
            success_codes.add(sgg_cd)

    rejected_codes: set[str] = set()
    if rejected_dir.exists():
        for error_path in sorted(rejected_dir.glob("*_error.json")):
            sgg_cd = error_path.stem.removesuffix("_error")
            if sgg_cd in success_codes and clean_resolved_rejected:
                error_path.unlink()
                report.info(f"해결된 보호구역 rejected 삭제: {error_path}")
            elif sgg_cd in success_codes:
                report.warn(f"보호구역 snapshot은 있으나 rejected도 남아 있습니다: {error_path}")
                rejected_codes.add(sgg_cd)
            else:
                rejected_codes.add(sgg_cd)

    expected_codes = set(expected_sgg_codes)
    unknown_success = sorted(success_codes.difference(expected_codes))
    if unknown_success:
        report.warn(f"CSV에 없는 보호구역 성공 코드가 있습니다: {unknown_success[:10]}")

    covered_codes = success_codes.union(rejected_codes)
    missing_codes = sorted(expected_codes.difference(covered_codes))
    if missing_codes:
        report.error(f"보호구역 성공/실패 어디에도 없는 시군구 코드가 있습니다: {missing_codes[:10]}")

    report.info(
        "protection_zones: "
        f"expected={len(expected_codes)}, success={len(success_codes)}, rejected={len(rejected_codes)}"
    )
    if rejected_codes:
        report.warn(f"보호구역 rejected 남음: {len(rejected_codes)}개")


def validate_osm_pbf(settings: Settings, report: ValidationReport) -> None:
    """OSM PBF 파일 존재, 파일명, 크기 등 기본 무결성을 검사한다."""
    osm_dir = Path(settings.road_data_dir) / "raw" / "osm"
    if not osm_dir.exists():
        report.error(f"OSM 폴더가 없습니다: {osm_dir}")
        return

    pbf_files = sorted(osm_dir.glob("south-korea-*.osm.pbf"))
    if not pbf_files:
        report.error(f"OSM PBF 파일이 없습니다: {osm_dir}")
        return

    latest_file = max(pbf_files, key=lambda path: path.stat().st_mtime)
    if not re.fullmatch(r"south-korea-\d{6}\.osm\.pbf", latest_file.name):
        report.warn(f"OSM PBF 파일명이 날짜 형식이 아닙니다: {latest_file.name}")
    size = latest_file.stat().st_size
    minimum_size = 100 * 1024 * 1024
    if size < minimum_size:
        report.error(f"OSM PBF 파일 크기가 비정상적으로 작습니다: {latest_file} ({size} bytes)")
    else:
        report.info(f"OSM PBF 확인: {latest_file.name}, size={size} bytes")

    if len(pbf_files) > 1:
        report.warn(f"OSM PBF 파일이 여러 개 있습니다. 최신 파일 기준으로 검증했습니다: {latest_file.name}")


def parse_args() -> argparse.Namespace:
    """명령행 옵션을 해석한다."""
    parser = argparse.ArgumentParser(description="Road MCP 원본 데이터 무결성 검증")
    parser.add_argument(
        "--clean-resolved-rejected",
        action="store_true",
        help="snapshot이 정상인 보호구역 코드의 rejected error json을 삭제합니다.",
    )
    return parser.parse_args()


def print_report(report: ValidationReport) -> None:
    """검증 결과를 콘솔에 출력한다."""
    for message in report.infos:
        print(f"[OK] {message}")
    for message in report.warnings:
        print(f"[WARN] {message}")
    for message in report.errors:
        print(f"[ERROR] {message}")


def main() -> None:
    """설정, 공공데이터 JSON, 보호구역 rejected, OSM PBF를 검증한다."""
    args = parse_args()
    settings = get_settings()
    report = ValidationReport(errors=[], warnings=[], infos=[])

    expected_sgg_codes = validate_loader_settings(settings, report)
    for source_name in ("road_signs", "traffic_signals", "crosswalks"):
        validate_public_source(settings, source_name, report)
    validate_protection_zones(settings, expected_sgg_codes, args.clean_resolved_rejected, report)
    validate_osm_pbf(settings, report)

    print_report(report)
    if report.errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
