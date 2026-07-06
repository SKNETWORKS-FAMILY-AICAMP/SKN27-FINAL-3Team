# -*- coding: utf-8 -*-
"""경로와 실행 설정을 관리합니다."""

from pathlib import Path

from ...config import get_preprocessed_dir, get_raw_source_dir


# 전처리 버전입니다. 결과 JSON/JSONL에 기록됩니다.
PREPROCESSING_VERSION = "nontypical_2020_v2.3"

RULEBOOK_ID = "nontypical_2020"
RULE_ID_PREFIX = "nontypical_2020_no"
SOURCE_SUBTYPE = "nontypical_2020"
DOCUMENT_TITLE = "2020년 비정형사고 과실비율 기준"
SECTION_TITLE = "비정형사고 과실비율 기준"
RULE_TYPE = "nontypical_vehicle_accident"
PUBLISHED_YEAR = 2020
PUBLISHED_DATE = "2021-01-07"
SOURCE_RELIABILITY = "official_standard"

# 찾을 PDF 파일명의 핵심 키워드입니다.
PDF_NAME_KEYWORDS = ["210107", "비정형"]

# 기준서 구조 설정값입니다. 코드 내부에 숫자를 박지 않고 parser가 참조합니다.
EXPECTED_RULE_COUNT = 23
RULE_NO_MIN = 1
RULE_NO_MAX = EXPECTED_RULE_COUNT


def find_project_root(start: Path) -> Path:
    """현재 fault_cases 프로젝트 루트를 반환합니다."""

    return get_raw_source_dir().parents[2]


def find_input_pdf(input_dir: Path) -> Path:
    """data/traffic_ratio_stand 폴더에서 2020 비정형 PDF를 찾습니다."""

    # 입력 폴더의 PDF 목록을 정렬해서 가져옵니다.
    pdf_files = sorted(input_dir.glob("*.pdf"))

    # 210107 + 비정형 키워드가 모두 들어간 파일을 우선 찾습니다.
    for pdf_path in pdf_files:
        if all(keyword in pdf_path.name for keyword in PDF_NAME_KEYWORDS):
            return pdf_path

    # 못 찾으면 비정형이라는 말이 들어간 PDF라도 찾습니다.
    for pdf_path in pdf_files:
        if "비정형" in pdf_path.name:
            return pdf_path

    # 끝까지 못 찾으면 명확하게 에러를 냅니다.
    raise FileNotFoundError(f"2020 비정형사고 PDF를 찾지 못했습니다: {input_dir}")


def build_paths() -> dict:
    """입력/출력 경로를 한 번에 계산해서 반환합니다."""

    # 이 파일의 위치입니다.
    script_dir = Path(__file__).resolve().parent

    # 프로젝트 루트를 찾습니다.
    project_root = find_project_root(script_dir)

    # 입력 PDF 폴더입니다.
    input_dir = get_raw_source_dir()

    # 출력 루트 폴더입니다.
    output_root = get_preprocessed_dir()

    # 비정형 기준서 전용 출력 폴더입니다.
    rulebook_dir = output_root / "2020_nontypical_accident_rulebook"

    # 결과 폴더들을 묶어서 반환합니다.
    return {
        "project_root": project_root,
        "input_dir": input_dir,
        "output_root": output_root,
        "rulebook_dir": rulebook_dir,
        "manifest_dir": rulebook_dir / "00_manifest",
        "summary_dir": rulebook_dir / "01_summary_table",
        "rule_dir": rulebook_dir / "02_detailed_fault_ratio_standards",
        "table_dir": rulebook_dir / "99_tables_for_db",
    }
