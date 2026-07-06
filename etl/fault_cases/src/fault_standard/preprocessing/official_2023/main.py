# -*- coding: utf-8 -*-
"""2023 자동차사고 과실비율 인정기준 전처리 실행 파일입니다."""

from .builder import build_rule_package, flatten_packages_to_tables
from .config import PREPROCESSING_VERSION, EXPECTED_RULE_COUNT, build_paths, find_input_pdf, get_rule_target_dir_key
from .file_utils import ensure_dir, now_iso, sha256_file, write_json, write_jsonl
from .pdf_loader import build_page_coverage, load_pdf_pages
from .rule_splitter import split_official_rules
from .section_parser import build_explanatory_sections


def run() -> None:
    """2023 공식 자동차사고 과실비율 인정기준 전처리를 실행합니다."""

    # 경로 정보를 계산합니다.
    paths = build_paths()

    # 출력 폴더를 미리 생성합니다.
    for key in [
        "manifest_dir",
        "preface_dir",
        "revision_dir",
        "general_dir",
        "pedestrian_rule_dir",
        "vehicle_rule_dir",
        "bicycle_rule_dir",
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

    # 발간사/개정경과/총설 section을 생성합니다.
    sections = build_explanatory_sections(pages)

    # 보/차/거 rule을 분리합니다.
    detail_sections = split_official_rules(pages)

    # 최종 rule package 목록입니다.
    packages = []

    # 상세 rule을 하나씩 처리합니다.
    for section in detail_sections:
        # rule JSON package를 생성합니다.
        package = build_rule_package(section, pdf_path, file_hash, page_coverage)

        # package 목록에 추가합니다.
        packages.append(package)

        # 제목 기반 파일명을 만듭니다.
        file_name = f"{section['file_title']}.json"

        # rule prefix에 따라 저장 폴더를 결정합니다.
        target_dir = paths[get_rule_target_dir_key(section["rule_prefix"])]

        # rule JSON을 저장합니다.
        write_json(target_dir / file_name, package)

    # 설명 section을 개별 폴더에도 저장합니다.
    write_json(paths["preface_dir"] / "preface.json", sections[0])
    write_json(paths["revision_dir"] / "revision_history.json", sections[1])
    write_json(paths["general_dir"] / "general_theory.json", sections[2])

    # DB 적재용 table row를 생성합니다.
    tables = flatten_packages_to_tables(packages, sections)

    # rulebook 메타 row를 추가합니다.
    tables["rulebooks"].append(
        {
            "rulebook_id": "official_2023",
            "source_file": pdf_path.name,
            "source_type": "fault_standard",
            "source_subtype": "official_2023",
            "source_reliability": "official_standard",
            "published_year": 2023,
            "published_month": 6,
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

    # diagram image crop 단계는 아직 수행하지 않으므로 예전 diagrams.jsonl이 남아 있으면 제거합니다.
    stale_diagram_table = paths["table_dir"] / "diagrams.jsonl"
    if stale_diagram_table.exists():
        stale_diagram_table.unlink()

    # 완료 메시지를 출력합니다.
    print(f"[완료] PDF: {pdf_path.name}")
    print(f"[완료] 공식 rule JSON: {len(packages)}개")
    print(f"[완료] 출력 폴더: {paths['rulebook_dir']}")


if __name__ == "__main__":
    run()
