# -*- coding: utf-8 -*-
"""2025 2차로형 회전교차로 과실비율 기준 전처리 실행 파일입니다."""

from .builder import build_rule_package, flatten_packages_to_tables
from .config import PREPROCESSING_VERSION, EXPECTED_RULE_COUNT, build_paths, find_input_pdf, get_round_group
from .file_utils import ensure_dir, now_iso, sha256_file, safe_filename, write_json, write_jsonl
from .pdf_loader import build_page_coverage, load_pdf_pages
from .rule_splitter import split_roundabout_rules
from .section_parser import build_driving_method_section, build_preface_section


def run() -> None:
    """2025 2차로형 회전교차로 기준 전처리를 실행합니다."""

    # 경로 정보를 계산합니다.
    paths = build_paths()

    # 출력 폴더를 미리 생성합니다.
    for key in ["manifest_dir", "preface_dir", "driving_method_dir", "entry_vs_entry_dir", "entry_vs_circulating_dir", "table_dir"]:
        ensure_dir(paths[key])

    # 입력 PDF 파일을 찾습니다.
    pdf_path = find_input_pdf(paths["input_dir"])

    # 원본 PDF 해시를 계산합니다.
    file_hash = sha256_file(pdf_path)

    # PDF 전체 페이지를 읽습니다.
    pages, loader_report = load_pdf_pages(pdf_path)

    # 페이지 누락 여부를 검증합니다.
    page_coverage = build_page_coverage(pages, loader_report["expected_page_count"])

    # 머리말 section을 생성합니다.
    preface_section = build_preface_section(pages)

    # 올바른 통행방법 section을 생성합니다.
    driving_method_section = build_driving_method_section(pages)

    # 회전-1~회전-15 rule을 분리합니다.
    detail_sections = split_roundabout_rules(pages)

    # 최종 rule package 목록입니다.
    packages = []

    # 상세 rule을 하나씩 처리합니다.
    for section in detail_sections:
        # rule JSON package를 생성합니다.
        package = build_rule_package(section, pdf_path, file_hash, page_coverage)

        # package 목록에 추가합니다.
        packages.append(package)

        # 제목 기반 파일명을 만듭니다.
        file_name = f"{section['round_code']}_{safe_filename(section['rule_title'])}.json"

        # 회전-1~8과 회전-9~15의 저장 폴더를 나눕니다.
        target_dir = paths[get_round_group(section["round_no"])["dir_key"]]

        # rule JSON을 저장합니다.
        write_json(target_dir / file_name, package)

    # section JSON을 저장합니다.
    write_json(paths["preface_dir"] / "preface.json", preface_section)
    write_json(paths["driving_method_dir"] / "correct_roundabout_driving_method.json", driving_method_section)

    # DB 적재용 section row입니다.
    section_rows = [preface_section, driving_method_section]

    # DB 적재용 table row를 생성합니다.
    tables = flatten_packages_to_tables(packages, section_rows)

    # rulebook 메타 row를 추가합니다.
    tables["rulebooks"].append(
        {
            "rulebook_id": "roundabout_2025",
            "source_file": pdf_path.name,
            "source_type": "fault_standard",
            "source_subtype": "roundabout_2025",
            "source_reliability": "official_standard",
            "published_year": 2025,
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
    print(f"[완료] 회전 rule JSON: {len(packages)}개")
    print(f"[완료] 출력 폴더: {paths['rulebook_dir']}")


if __name__ == "__main__":
    run()
