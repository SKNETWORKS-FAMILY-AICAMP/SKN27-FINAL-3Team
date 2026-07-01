# -*- coding: utf-8 -*-
"""2021 PM 대 자동차 과실비율 비정형 기준 전처리 실행 파일입니다."""

from .builder import apply_shared_rule_groups, build_rule_package, flatten_packages_to_tables
from .config import (
    EXPECTED_RULE_COUNT,
    PUBLISHED_YEAR,
    PREPROCESSING_VERSION,
    RULEBOOK_ID,
    SOURCE_RELIABILITY,
    SOURCE_SUBTYPE,
    build_paths,
    find_input_pdf,
    get_rule_group_key,
)
from .file_utils import ensure_dir, now_iso, sha256_file, safe_filename, write_json, write_jsonl
from .pdf_loader import build_page_coverage, load_pdf_pages
from .rule_splitter import split_pm_auto_rules
from .section_parser import build_explanatory_sections


def run() -> None:
    """2021 PM 대 자동차 과실비율 기준 전처리를 실행합니다."""

    # 경로 정보를 계산합니다.
    paths = build_paths()

    # 출력 폴더를 미리 생성합니다.
    for key in [
        "manifest_dir",
        "overview_dir",
        "scope_dir",
        "terms_dir",
        "adjustment_dir",
        "signal_dir",
        "unsignalized_dir",
        "one_way_dir",
        "turning_dir",
        "crossing_dir",
        "centerline_dir",
        "lane_rear_dir",
        "bicycle_sidewalk_door_dir",
        "table_dir",
    ]:
        ensure_dir(paths[key])

    # 입력 PDF 파일을 찾습니다.
    pdf_path = find_input_pdf(paths["input_dir"])

    # 원본 PDF 해시를 계산합니다.
    file_hash = sha256_file(pdf_path)

    # PDF 전체 페이지를 읽습니다.
    pages, loader_report = load_pdf_pages(pdf_path)

    # 페이지 누락 여부를 검증합니다.
    page_coverage = build_page_coverage(pages, loader_report["expected_page_count"])

    # 개요/적용범위/용어/수정요소 section을 생성합니다.
    sections = build_explanatory_sections(pages)

    # 도표1~도표38 rule을 분리합니다.
    detail_sections = split_pm_auto_rules(pages)

    # 최종 rule package 목록입니다.
    packages = []

    # 상세 rule을 하나씩 처리합니다.
    for section in detail_sections:
        # rule JSON package를 생성합니다.
        package = build_rule_package(section, pdf_path, file_hash, page_coverage)

        # package 목록에 추가합니다.
        packages.append(package)

    # 공통 해설/법규를 공유하는 도표 묶음을 연결합니다.
    apply_shared_rule_groups(packages)

    # 보정이 끝난 rule JSON을 저장합니다.
    for package, section in zip(packages, detail_sections):
        # 제목 기반 파일명을 만듭니다.
        file_name = f"{section['chart_code']}_{safe_filename(section['rule_title'])}.json"

        # 도표 번호에 따라 저장 폴더를 결정합니다.
        target_dir = paths[get_rule_group_key(section["chart_no"])]

        # rule JSON을 저장합니다.
        write_json(target_dir / file_name, package)

    # 설명 section을 개별 폴더에도 저장합니다.
    write_json(paths["overview_dir"] / "overview.json", sections[0])
    write_json(paths["scope_dir"] / "scope.json", sections[1])
    write_json(paths["terms_dir"] / "terms.json", sections[2])
    write_json(paths["adjustment_dir"] / "adjustment_factor_explanation.json", sections[3])

    # DB 적재용 table row를 생성합니다.
    tables = flatten_packages_to_tables(packages, sections)

    # rulebook 메타 row를 추가합니다.
    tables["rulebooks"].append(
        {
            "rulebook_id": RULEBOOK_ID,
            "source_file": pdf_path.name,
            "source_type": "fault_standard",
            "source_subtype": SOURCE_SUBTYPE,
            "source_reliability": SOURCE_RELIABILITY,
            "published_year": PUBLISHED_YEAR,
            "file_hash": file_hash,
            "expected_page_count": page_coverage["expected_page_count"],
            "read_page_count": page_coverage["read_page_count"],
            "missing_pages": page_coverage["missing_pages"],
            "preprocessing_version": PREPROCESSING_VERSION,
            "created_at": now_iso(),
        }
    )

    # 페이지 커버리지 결과를 저장합니다.
    write_json(paths["manifest_dir"] / "page_coverage.json", page_coverage)

    # Loader 실행 리포트를 저장합니다.
    write_json(paths["manifest_dir"] / "loader_report.json", loader_report)

    # 전체 실행 요약을 저장합니다.
    write_json(
        paths["manifest_dir"] / "run_summary.json",
        {
            "source_file": pdf_path.name,
            "rule_json_count": len(packages),
            "expected_rule_count": EXPECTED_RULE_COUNT,
            "output_rule_root_dir": str(paths["rule_root_dir"]),
            "created_at": now_iso(),
        },
    )

    # table별 JSONL을 저장합니다.
    for table_name, rows in tables.items():
        write_jsonl(paths["table_dir"] / f"{table_name}.jsonl", rows)

    # 현재 범위는 텍스트 전처리이므로 이미지/diagram 산출물은 남아 있으면 제거합니다.
    stale_diagram_table = paths["table_dir"] / "diagrams.jsonl"
    if stale_diagram_table.exists():
        stale_diagram_table.unlink()

    # 완료 메시지를 출력합니다.
    print(f"[완료] PDF: {pdf_path.name}")
    print(f"[완료] PM 도표 rule JSON: {len(packages)}개")
    print(f"[완료] 출력 폴더: {paths['rulebook_dir']}")


if __name__ == "__main__":
    run()
