# -*- coding: utf-8 -*-
"""경로와 실행 설정을 관리합니다."""

from pathlib import Path

from ...config import get_preprocessed_dir, get_raw_source_dir


# 전처리 버전입니다. 결과 JSON/JSONL에 기록됩니다.
PREPROCESSING_VERSION = "official_2023_v1.1_official_patch"

# 찾을 PDF 파일명의 핵심 키워드입니다.
PDF_NAME_KEYWORDS = ["자동차사고", "과실비율", "인정기준"]

EXPECTED_RULE_COUNT = 201

# 한 rule이 비정상적으로 다음 장 본문까지 먹는 것을 막기 위한 검증 기준입니다.
# 2023 공식 기준은 일부 법규/판례가 다음 페이지까지 이어질 수 있으므로 너무 짧게 자르지 않습니다.
MAX_REASONABLE_RULE_PAGE_SPAN = 6
RULE_PREFIX_TARGET_DIR = {"보": "pedestrian_rule_dir", "차": "vehicle_rule_dir", "거": "bicycle_rule_dir"}


def find_project_root(start: Path) -> Path:
    """현재 fault_cases 프로젝트 루트를 반환합니다."""

    return get_raw_source_dir().parents[2]


def find_input_pdf(input_dir: Path) -> Path:
    """data/traffic_ratio_stand 폴더에서 2023 공식 인정기준 PDF를 찾습니다."""

    # 입력 폴더의 PDF 목록을 정렬해서 가져옵니다.
    pdf_files = sorted(input_dir.glob("*.pdf"))

    # 핵심 키워드가 모두 들어간 파일을 우선 찾습니다.
    for pdf_path in pdf_files:
        if all(keyword in pdf_path.name for keyword in PDF_NAME_KEYWORDS):
            return pdf_path

    # 못 찾으면 인정기준이 들어간 PDF라도 찾습니다.
    for pdf_path in pdf_files:
        if "인정기준" in pdf_path.name and "자동차사고" in pdf_path.name:
            return pdf_path

    # 끝까지 못 찾으면 명확하게 에러를 냅니다.
    raise FileNotFoundError(f"2023 공식 자동차사고 과실비율 인정기준 PDF를 찾지 못했습니다: {input_dir}")


def build_paths() -> dict:
    """입력/출력 경로를 한 번에 계산해서 반환합니다."""

    # 이 파일이 들어있는 official_2023 폴더입니다.
    script_dir = Path(__file__).resolve().parent

    # 프로젝트 루트를 찾습니다.
    project_root = find_project_root(script_dir)

    # 입력 PDF 폴더입니다.
    input_dir = get_raw_source_dir()

    # 출력 루트 폴더입니다.
    output_root = get_preprocessed_dir()

    # 2023 공식 인정기준 전용 출력 폴더입니다.
    rulebook_dir = output_root / "2023_official_auto_accident_rulebook"

    # 결과 폴더들을 묶어서 반환합니다.
    return {
        "project_root": project_root,
        "input_dir": input_dir,
        "output_root": output_root,
        "rulebook_dir": rulebook_dir,
        "manifest_dir": rulebook_dir / "00_manifest",
        "preface_dir": rulebook_dir / "01_preface",
        "revision_dir": rulebook_dir / "02_revision_history",
        "general_dir": rulebook_dir / "03_general_theory",
        "rule_root_dir": rulebook_dir / "04_accident_type_fault_ratio_standards",
        "pedestrian_rule_dir": rulebook_dir / "04_accident_type_fault_ratio_standards" / "01_vehicle_vs_pedestrian" / "04_detailed_rules",
        "vehicle_rule_dir": rulebook_dir / "04_accident_type_fault_ratio_standards" / "02_vehicle_vs_vehicle_motorcycle" / "04_detailed_rules",
        "bicycle_rule_dir": rulebook_dir / "04_accident_type_fault_ratio_standards" / "03_vehicle_vs_bicycle_agricultural" / "04_detailed_rules",
        "table_dir": rulebook_dir / "99_tables_for_db",
    }


def get_rule_target_dir_key(rule_prefix: str) -> str:
    """rule prefix를 저장 폴더 key로 바꿉니다."""

    try:
        return RULE_PREFIX_TARGET_DIR[rule_prefix]
    except KeyError as exc:
        raise ValueError(f"지원하지 않는 rule prefix입니다: {rule_prefix}") from exc
