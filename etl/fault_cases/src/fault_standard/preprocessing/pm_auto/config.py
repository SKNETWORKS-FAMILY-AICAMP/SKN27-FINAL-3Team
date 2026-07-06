# -*- coding: utf-8 -*-
"""경로와 실행 설정을 관리합니다."""

from pathlib import Path

from ...config import get_preprocessed_dir, get_raw_source_dir


# 전처리 버전입니다. 결과 JSON/JSONL에 기록됩니다.
PREPROCESSING_VERSION = "pm_auto_2021_v1.0"

RULEBOOK_ID = "pm_auto_2021"
RULE_ID_PREFIX = "pm_auto_2021"
SECTION_ID_PREFIX = "pm_auto_2021"
SHARED_GROUP_ID_PREFIX = "pm_auto_2021_shared"
SOURCE_SUBTYPE = "pm_auto_2021"
DOCUMENT_TITLE = "PM 대 자동차 사고 과실비율 비정형 기준"
SECTION_NO = "5"
SECTION_TITLE = "세부유형별 과실비율 적용기준"
RULE_TYPE = "pm_vs_vehicle"
PUBLISHED_YEAR = 2021
SOURCE_RELIABILITY = "official_standard"

# 찾을 PDF 파일명의 핵심 키워드입니다.
PDF_NAME_KEYWORDS = ["PM", "자동차", "과실비율"]

# 기준서 구조 설정값입니다. parser가 참조하며 코드 본문에 범위를 박지 않습니다.
EXPECTED_RULE_COUNT = 38
CHART_NO_MIN = 1
CHART_NO_MAX = EXPECTED_RULE_COUNT

RULE_GROUP_RANGES = [
    (1, 5, "signal_dir"),
    (6, 9, "unsignalized_dir"),
    (10, 11, "one_way_dir"),
    (12, 17, "turning_dir"),
    (18, 27, "crossing_dir"),
    (28, 30, "centerline_dir"),
    (31, 34, "lane_rear_dir"),
    (35, 38, "bicycle_sidewalk_door_dir"),
]

PM_CATEGORY_METADATA = {
    "signal_dir": {"category_no": "01", "category_title": "신호위반 사고", "chart_group": "signal_violation"},
    "unsignalized_dir": {"category_no": "02", "category_title": "신호기 없는 교차로 사고", "chart_group": "unsignalized_intersection"},
    "one_way_dir": {"category_no": "03", "category_title": "일방통행 위반 사고", "chart_group": "one_way_violation"},
    "turning_dir": {"category_no": "04", "category_title": "직진·좌회전·우회전 사고", "chart_group": "straight_left_right_turn"},
    "crossing_dir": {"category_no": "05", "category_title": "횡단 및 보도 관련 사고", "chart_group": "crossing_and_sidewalk"},
    "centerline_dir": {"category_no": "06", "category_title": "중앙선 침범 및 차도 진입 사고", "chart_group": "centerline_and_road_entry"},
    "lane_rear_dir": {"category_no": "07", "category_title": "진로변경 및 추돌 사고", "chart_group": "lane_change_and_rear_end"},
    "bicycle_sidewalk_door_dir": {"category_no": "08", "category_title": "자전거도로·보도·개문 사고", "chart_group": "bicycle_road_sidewalk_door_opening"},
}


def find_project_root(start: Path) -> Path:
    """현재 fault_cases 프로젝트 루트를 반환합니다."""

    return get_raw_source_dir().parents[2]


def find_input_pdf(input_dir: Path) -> Path:
    """data/traffic_ratio_stand 폴더에서 PM 대 자동차 PDF를 찾습니다."""

    # 입력 폴더의 PDF 목록을 정렬해서 가져옵니다.
    pdf_files = sorted(input_dir.glob("*.pdf"))

    # PM + 자동차 + 과실비율 키워드가 모두 들어간 파일을 우선 찾습니다.
    for pdf_path in pdf_files:
        if all(keyword in pdf_path.name for keyword in PDF_NAME_KEYWORDS):
            return pdf_path

    # 못 찾으면 PM과 자동차가 들어간 PDF라도 찾습니다.
    for pdf_path in pdf_files:
        if "PM" in pdf_path.name and "자동차" in pdf_path.name:
            return pdf_path

    # 끝까지 못 찾으면 명확하게 에러를 냅니다.
    raise FileNotFoundError(f"PM 대 자동차 과실비율 PDF를 찾지 못했습니다: {input_dir}")


def build_paths() -> dict:
    """입력/출력 경로를 한 번에 계산해서 반환합니다."""

    # 이 파일이 들어있는 pm_auto 폴더입니다.
    script_dir = Path(__file__).resolve().parent

    # 프로젝트 루트를 찾습니다.
    project_root = find_project_root(script_dir)

    # 입력 PDF 폴더입니다.
    input_dir = get_raw_source_dir()

    # 출력 루트 폴더입니다.
    output_root = get_preprocessed_dir()

    # PM 기준서 전용 출력 폴더입니다.
    rulebook_dir = output_root / "2021_pm_vs_auto_nontypical_rulebook"

    # 결과 폴더들을 묶어서 반환합니다.
    return {
        "project_root": project_root,
        "input_dir": input_dir,
        "output_root": output_root,
        "rulebook_dir": rulebook_dir,
        "manifest_dir": rulebook_dir / "00_manifest",
        "overview_dir": rulebook_dir / "01_overview",
        "scope_dir": rulebook_dir / "02_scope",
        "terms_dir": rulebook_dir / "03_terms",
        "adjustment_dir": rulebook_dir / "04_adjustment_factor_explanation",
        "rule_root_dir": rulebook_dir / "05_detailed_fault_ratio_standards",
        "signal_dir": rulebook_dir / "05_detailed_fault_ratio_standards" / "01_signal_violation",
        "unsignalized_dir": rulebook_dir / "05_detailed_fault_ratio_standards" / "02_unsignalized_intersection",
        "one_way_dir": rulebook_dir / "05_detailed_fault_ratio_standards" / "03_one_way_violation",
        "turning_dir": rulebook_dir / "05_detailed_fault_ratio_standards" / "04_straight_left_right_turn",
        "crossing_dir": rulebook_dir / "05_detailed_fault_ratio_standards" / "05_crossing_and_sidewalk",
        "centerline_dir": rulebook_dir / "05_detailed_fault_ratio_standards" / "06_centerline_and_road_entry",
        "lane_rear_dir": rulebook_dir / "05_detailed_fault_ratio_standards" / "07_lane_change_and_rear_end",
        "bicycle_sidewalk_door_dir": rulebook_dir / "05_detailed_fault_ratio_standards" / "08_bicycle_road_sidewalk_door_opening",
        "table_dir": rulebook_dir / "99_tables_for_db",
    }


def get_rule_group_key(chart_no: int) -> str:
    """도표 번호를 저장 폴더 그룹 key로 변환합니다."""

    for start_no, end_no, dir_key in RULE_GROUP_RANGES:
        if start_no <= chart_no <= end_no:
            return dir_key

    raise ValueError(f"지원하지 않는 도표 번호입니다: {chart_no}")
