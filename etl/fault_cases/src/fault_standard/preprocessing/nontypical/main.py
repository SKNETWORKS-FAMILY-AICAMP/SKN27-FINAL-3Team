# -*- coding: utf-8 -*-
"""2020 비정형사고 과실비율 기준 전처리 실행 파일입니다."""

from .builder import build_rule_package, flatten_packages_to_tables
from .config import (
    EXPECTED_RULE_COUNT,
    PUBLISHED_DATE,
    PUBLISHED_YEAR,
    PREPROCESSING_VERSION,
    RULEBOOK_ID,
    SOURCE_RELIABILITY,
    SOURCE_SUBTYPE,
    build_paths,
    find_input_pdf,
)
from .file_utils import ensure_dir, now_iso, sha256_file, safe_filename, write_json, write_jsonl
from .pdf_loader import build_page_coverage, load_pdf_pages
from .rule_splitter import split_detail_rules
from .summary_parser import parse_summary_table


def run() -> None:
    """2020 비정형사고 과실비율 기준 전처리를 실행합니다."""

    # 경로 정보를 계산합니다.
    paths = build_paths()

    # 출력 폴더를 미리 생성합니다.
    for key in ["manifest_dir", "summary_dir", "rule_dir", "table_dir"]:
        ensure_dir(paths[key])

    # 입력 PDF 파일을 찾습니다.
    pdf_path = find_input_pdf(paths["input_dir"])

    # 원본 PDF 해시를 계산합니다.
    file_hash = sha256_file(pdf_path)

    # PDF 전체 페이지를 읽습니다.
    pages, loader_report = load_pdf_pages(pdf_path)

    # 페이지 누락 여부를 검증합니다.
    page_coverage = build_page_coverage(pages, loader_report["expected_page_count"])

    # 요약표를 파싱합니다.
    summary_rows = parse_summary_table(pages)

    # 상세 본문을 No별 rule로 분리합니다.
    detail_sections = split_detail_rules(pages)

    # 요약표를 No 기준으로 빠르게 찾기 위한 map입니다.
    summary_map = {row["summary_no"]: row for row in summary_rows}

    # 최종 rule package 목록입니다.
    packages = []

    # 상세 rule을 하나씩 처리합니다.
    for section in detail_sections:
        # 해당 No의 요약표 row를 찾습니다.
        summary_row = summary_map.get(section["rule_no"])

        # rule JSON package를 생성합니다.
        package = build_rule_package(section, summary_row, pdf_path, file_hash, page_coverage)

        # package 목록에 추가합니다.
        packages.append(package)

        # 제목 기반 파일명을 만듭니다.
        file_name = f"no_{section['rule_no']:02d}_{safe_filename(section['rule_title'])}.json"

        # rule JSON을 저장합니다.
        write_json(paths["rule_dir"] / file_name, package)

    # DB 적재용 table row를 생성합니다.
    tables = flatten_packages_to_tables(packages)

    # rulebook 메타 row를 추가합니다.
    tables["rulebooks"].append(
        {
            "rulebook_id": RULEBOOK_ID,
            "source_file": pdf_path.name,
            "source_type": "fault_standard",
            "source_subtype": SOURCE_SUBTYPE,
            "source_reliability": SOURCE_RELIABILITY,
            "published_year": PUBLISHED_YEAR,
            "published_date": PUBLISHED_DATE,
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
            "summary_row_count": len(summary_rows),
            "detail_rule_count": len(detail_sections),
            "expected_rule_count": EXPECTED_RULE_COUNT,
            "rule_json_count": len(packages),
            "output_rule_dir": str(paths["rule_dir"]),
            "created_at": now_iso(),
        },
    )

    # 요약표 JSON을 저장합니다.
    write_json(
        paths["summary_dir"] / "summary_table.json",
        {
            "source_file": pdf_path.name,
            "row_count": len(summary_rows),
            "rows": summary_rows,
        },
    )

    # table별 JSONL을 저장합니다.
    for table_name, rows in tables.items():
        write_jsonl(paths["table_dir"] / f"{table_name}.jsonl", rows)

    # 텍스트 전처리 범위 밖의 이미지/diagram 산출물은 남아 있으면 제거합니다.
    stale_diagram_table = paths["table_dir"] / "diagrams.jsonl"
    if stale_diagram_table.exists():
        stale_diagram_table.unlink()

    # 완료 메시지를 출력합니다.
    print(f"[완료] PDF: {pdf_path.name}")
    print(f"[완료] 요약표 row: {len(summary_rows)}개")
    print(f"[완료] 상세 rule JSON: {len(packages)}개")
    print(f"[완료] 출력 폴더: {paths['rulebook_dir']}")


if __name__ == "__main__":
    run()
