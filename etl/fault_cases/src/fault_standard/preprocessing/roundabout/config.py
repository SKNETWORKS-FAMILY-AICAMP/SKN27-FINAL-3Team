# -*- coding: utf-8 -*-
"""경로와 실행 설정을 관리합니다."""

from pathlib import Path

from ...config import get_preprocessed_dir, get_raw_source_dir


# 전처리 버전입니다. 결과 JSON/JSONL에 기록됩니다.
PREPROCESSING_VERSION = "roundabout_2025_v1.0"

# 찾을 PDF 파일명의 핵심 키워드입니다.
PDF_NAME_KEYWORDS = ["250624", "2차로형", "회전교차로"]

# 기준서 구조 설정값입니다. parser가 참조하며 코드 본문에 범위를 박지 않습니다.
EXPECTED_RULE_COUNT = 15
ROUND_NO_MIN = 1
ROUND_NO_MAX = EXPECTED_RULE_COUNT

ROUND_GROUP_RANGES = [
    (1, 8, "entry_vs_entry_dir", "entry_vs_entry", "진입차량 간 사고", "1", "진입차량 간 사고"),
    (9, 15, "entry_vs_circulating_dir", "entry_vs_circulating", "진입차량과 회전차량 간 사고", "2", "진입차량과 회전차량 간 사고"),
]

def get_round_group(round_no: int) -> dict:
    """회전 번호에 해당하는 그룹 정보를 반환합니다."""

    for start_no, end_no, dir_key, major_group, major_group_title, major_group_no, major_title in ROUND_GROUP_RANGES:
        if start_no <= round_no <= end_no:
            return {
                "dir_key": dir_key,
                "major_group": major_group,
                "major_group_title": major_group_title,
                "major_group_no": major_group_no,
                "major_title": major_title,
            }

    raise ValueError(f"지원하지 않는 회전 번호입니다: {round_no}")


def find_project_root(start: Path) -> Path:
    """현재 fault_cases 프로젝트 루트를 반환합니다."""

    return get_raw_source_dir().parents[2]


def find_input_pdf(input_dir: Path) -> Path:
    """data/traffic_ratio_stand 폴더에서 2025 회전교차로 PDF를 찾습니다."""

    # 입력 폴더의 PDF 목록을 가져옵니다.
    pdf_files = sorted(input_dir.glob("*.pdf"))

    # 핵심 키워드가 모두 들어간 PDF를 우선 찾습니다.
    for pdf_path in pdf_files:
        if all(keyword in pdf_path.name for keyword in PDF_NAME_KEYWORDS):
            return pdf_path

    # 못 찾으면 회전교차로라는 말이 들어간 PDF라도 찾습니다.
    for pdf_path in pdf_files:
        if "회전교차로" in pdf_path.name:
            return pdf_path

    # 끝까지 못 찾으면 명확하게 에러를 냅니다.
    raise FileNotFoundError(f"2025 2차로형 회전교차로 PDF를 찾지 못했습니다: {input_dir}")


def build_paths() -> dict:
    """입력/출력 경로를 한 번에 계산해서 반환합니다."""

    # 이 파일이 들어있는 roundabout 폴더입니다.
    script_dir = Path(__file__).resolve().parent

    # 프로젝트 루트를 찾습니다.
    project_root = find_project_root(script_dir)

    # 입력 PDF 폴더입니다.
    input_dir = get_raw_source_dir()

    # 출력 루트 폴더입니다.
    output_root = get_preprocessed_dir()

    # 회전교차로 기준서 전용 출력 폴더입니다.
    rulebook_dir = output_root / "2025_two_lane_roundabout_rulebook"

    # 결과 폴더들을 묶어서 반환합니다.
    return {
        "project_root": project_root,
        "input_dir": input_dir,
        "output_root": output_root,
        "rulebook_dir": rulebook_dir,
        "manifest_dir": rulebook_dir / "00_manifest",
        "preface_dir": rulebook_dir / "01_preface",
        "driving_method_dir": rulebook_dir / "02_correct_roundabout_driving_method",
        "rule_root_dir": rulebook_dir / "03_two_lane_roundabout_fault_ratio_standard",
        "entry_vs_entry_dir": rulebook_dir / "03_two_lane_roundabout_fault_ratio_standard" / "01_entry_vehicle_vs_entry_vehicle",
        "entry_vs_circulating_dir": rulebook_dir / "03_two_lane_roundabout_fault_ratio_standard" / "02_entry_vehicle_vs_circulating_vehicle",
        "table_dir": rulebook_dir / "99_tables_for_db",
    }
