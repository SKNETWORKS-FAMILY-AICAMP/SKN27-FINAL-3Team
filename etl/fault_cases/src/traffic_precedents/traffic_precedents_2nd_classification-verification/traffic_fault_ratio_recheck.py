#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
traffic_fault_ratio_recheck.py

2차 과실비율 분류 결과(Confirmed, Possible, No Fault)를 검증하고 재정리하여,
RAG 데이터베이스에 적재할 수 있는 깨끗한 '과실비율 판단용 판례'만 최종 선별하는 코드입니다.

입력:
- etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio/01_fault_ratio_confirmed_cases.jsonl
- etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio/02_fault_ratio_possible_review.jsonl
- etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio/03_traffic_but_no_fault_ratio_cases.jsonl

출력:
- etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio_verified/

생성 파일:
- 00_fault_ratio_verification_report.json (검증 요약 보고서)
- 01_fault_ratio_confirmed_cases.jsonl (최종 확정 판례 - RAG 대상)
- 02_traffic_but_no_fault_ratio_cases.jsonl (최종 제외 판례)
- 03_fault_ratio_verified_all.jsonl (전체 데이터 매핑 결과 - 감사용)
- 04_demoted_from_fault_confirmed_to_no_fault_ratio.jsonl (강등 대상 판례)
- 05_promoted_from_possible_to_fault_confirmed.jsonl (승격 대상 판례)
- 06_possible_to_no_fault_ratio.jsonl (possible에서 탈락한 판례)
"""

from __future__ import annotations

# 터미널 매개변수 처리를 위한 라이브러리
import argparse
# JSON 객체 읽기/쓰기를 위한 라이브러리
import json
# 기존 디렉터리 삭제(fresh 옵션)를 위한 라이브러리
import shutil
# 빈도수 집계를 위한 Counter 클래스
from collections import Counter
# 구조화된 통계 저장을 위한 데이터클래스 데코레이터 및 함수
from dataclasses import asdict, dataclass, field
# 파일 및 디렉터리 경로를 안전하게 제어하기 위한 라이브러리
from pathlib import Path
# 타입 힌팅을 위한 도구
from typing import Any, Dict, Iterable, List, Tuple


# ============================================================
# 1. 기본 경로 정의
# ============================================================

# 2차 분류의 원본 결과물이 들어있는 디렉터리 경로
DEFAULT_FAULT_RATIO_DIR = "etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio"
# 검증을 마친 최종 결과물을 저장할 디렉터리 경로
DEFAULT_OUT_DIR = "etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio_verified"

# 2차 분류에서 확정되었던 파일명
CONFIRMED_FILE = "01_fault_ratio_confirmed_cases.jsonl"
# 2차 분류에서 보류되었던 파일명
POSSIBLE_FILE = "02_fault_ratio_possible_review.jsonl"
# 2차 분류에서 제외되었던 파일명
NO_FAULT_RATIO_FILE = "03_traffic_but_no_fault_ratio_cases.jsonl"


# ============================================================
# 2. 실행 통계 구조화
# ============================================================

@dataclass
class VerificationStats:
    """
    검증 과정 전체의 처리 수량을 기록하기 위한 통계 데이터 클래스입니다.
    """
    # 2차 분류 Confirmed 입력 건수
    fault_confirmed_input_rows: int = 0
    # Confirmed에서 최종 검증을 통과하여 유지된 건수
    fault_confirmed_verified_rows: int = 0
    # Confirmed에서 비과실비율로 강등된 건수
    fault_confirmed_demoted_to_no_fault_rows: int = 0
    
    # 2차 분류 Possible 입력 건수
    possible_input_rows: int = 0
    # Possible에서 최종 Confirmed로 승격된 건수
    possible_promoted_to_fault_confirmed_rows: int = 0
    # Possible에서 비과실비율로 확정 탈락된 건수
    possible_to_no_fault_rows: int = 0
    
    # 2차 분류 No Fault 입력 건수
    no_fault_input_rows: int = 0
    
    # 최종 확정된 과실비율 판례 건수 (RAG 대상)
    final_fault_ratio_confirmed_rows: int = 0
    # 최종 제외된 판례 건수
    final_no_fault_ratio_rows: int = 0
    # 전체 입력 대비 처리 완료 건수
    final_all_rows: int = 0
    
    # 세부 결정 사유별 통계
    decision_reason_counts: Dict[str, int] = field(default_factory=dict)


# ============================================================
# 3. 파일 입출력 및 디렉터리 생성 유틸
# ============================================================

def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    """
    지정한 경로의 JSONL 파일을 열어 한 줄씩 JSON 객체(Dict)로 파싱하여 반환합니다.
    """
    # UTF-8 인코딩으로 텍스트 파일을 엽니다.
    with path.open("r", encoding="utf-8") as file:
        # 각 행을 순회하며 파싱합니다.
        for line_no, line in enumerate(file, start=1):
            # 행 앞뒤의 공백을 제거합니다.
            line = line.strip()
            # 빈 줄은 건너뜁니다.
            if not line:
                continue
            # JSON 파싱을 수행합니다.
            row = json.loads(line)
            # 디버깅 및 추적을 위해 입력 줄 번호를 임시로 보관합니다.
            row["_recheck_input_line_no"] = line_no
            # 제너레이터 형태로 row 객체를 반환합니다.
            yield row


def write_jsonl(path: Path, row: Dict[str, Any]) -> None:
    """
    dict 형태의 데이터 한 건을 JSON 문자열로 변환하여 파일 끝에 append 합니다.
    """
    # 추가(append) 모드로 파일을 엽니다. 한글 깨짐 방지를 위해 UTF-8을 사용합니다.
    with path.open("a", encoding="utf-8") as file:
        # 한글 깨짐 방지 옵션(ensure_ascii=False)을 지정하여 저장하고 개행을 추가합니다.
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def prepare_output_paths(out_dir: Path, fresh: bool) -> Dict[str, Path]:
    """
    검증 결과가 저장될 디렉터리를 만들고, 출력될 각 파일의 경로 객체를 정의하여 딕셔너리로 반환합니다.
    """
    # fresh 옵션이 켜져 있고 기존 폴더가 존재하는 경우 디렉터리 전체를 삭제합니다.
    if fresh and out_dir.exists():
        # 디렉터리와 내부 파일 전체를 삭제합니다.
        shutil.rmtree(out_dir)
        
    # 출력 경로 폴더가 없다면 부모 디렉터리까지 함께 만듭니다.
    out_dir.mkdir(parents=True, exist_ok=True)

    # 출력할 각 파일들의 경로를 정의합니다.
    paths = {
        "report": out_dir / "00_fault_ratio_verification_report.json",
        "confirmed": out_dir / "01_fault_ratio_confirmed_cases.jsonl",
        "no_fault_ratio": out_dir / "02_traffic_but_no_fault_ratio_cases.jsonl",
        "all": out_dir / "03_fault_ratio_verified_all.jsonl",
        "demoted": out_dir / "04_demoted_from_fault_confirmed_to_no_fault_ratio.jsonl",
        "promoted": out_dir / "05_promoted_from_possible_to_fault_confirmed.jsonl",
        "possible_to_no_fault": out_dir / "06_possible_to_no_fault_ratio.jsonl",
    }

    # fresh 옵션이 없는 경우, 기존에 남아있던 잔여 파일들을 제거하여 데이터를 초기화합니다.
    if not fresh:
        for path in paths.values():
            if path.exists():
                path.unlink()

    # 준비된 파일 경로 딕셔너리를 반환합니다.
    return paths


# ============================================================
# 4. 정밀 검증 필터 로직
# ============================================================

def check_spurious_signals(row: Dict[str, Any]) -> Tuple[bool, str]:
    """
    숫자 비율(%)이 존재하지만, 과실비율이 아니라 '지연손해금(이자율)'이나 '장해율'을 오탐한 것인지 정밀 판단합니다.
    
    반환값:
    - (True, '이유'): 오탐(지연손해금/장해율 등)으로 판단됨
    - (False, ''): 정상이거나 다른 핵심 근거가 존재함
    """
    # 2차 분류에서 수집된 숫자 비율 매칭 구절 리스트를 가져옵니다.
    number_examples = row.get("fault_ratio_number_examples", [])
    # 2차 분류에서 수집된 과실비율 직접적인 키워드 리스트를 가져옵니다.
    explicit_terms = row.get("fault_ratio_explicit_terms", [])
    
    # 1) 과실비율/과실상계 직접 키워드가 문서에 확실히 존재하면 오탐이 아닐 가능성이 높으므로 정상 처리합니다.
    if explicit_terms:
        # 정상 판례로 반환합니다.
        return False, ""
        
    # 2) 직접 키워드는 없는데, 매칭된 숫자 비율 예시가 존재하는 경우 오탐 여부를 체크합니다.
    if number_examples:
        # 모든 매칭 예시가 오탐 패턴에 해당할 경우에만 오탐으로 확정하기 위해 플래그를 True로 초기화합니다.
        all_spurious = True
        # 감지된 상세 오탐 이유를 보관할 변수입니다.
        spurious_reason = ""
        
        # 각 숫자 매칭 예시들을 순회합니다. (예: "연 20%의 비율", "장해율 30%")
        for ex in number_examples:
            # 예시 문구에 지연손해금/이자율 관련 노이즈 키워드가 포함되었는지 확인합니다.
            is_interest = any(x in ex for x in ["연", "지연손해금", "지연이자", "법정이율", "소송촉진", "이율", "지연"])
            # 예시 문구에 장해율/노동능력상실률 관련 노이즈 키워드가 포함되었는지 확인합니다.
            is_disability = any(x in ex for x in ["장해율", "상실률", "노동능력", "장해"])
            
            # 오탐 키워드가 있어도, 진짜 과실상계/책임제한 단어가 함께 결합해 있는지 확인합니다.
            has_real_context = any(x in ex for x in ["과실비율", "과실상계", "책임제한", "책임비율"]) or (
                # 과실, 책임, 분담 등의 단어가 있으면서 지연손해금이나 장해 단어가 동시에 묶여있지 않은 순수 구절인지 체크합니다.
                any(x in ex for x in ["과실", "책임", "분담"]) and not any(x in ex for x in ["지연손해", "장해", "노동능력", "이자", "연 "])
            )
            
            # 진짜 과실 관련 의미로 쓰인 구절이 단 하나라도 있다면 오탐에서 제외합니다.
            if has_real_context:
                # 하나라도 유효한 비율이 있으므로 오탐 플래그를 내리고 순회를 중단합니다.
                all_spurious = False
                break
                
            # 유효하지 않고 지연이자인 경우
            if is_interest:
                # 이자율 오탐으로 이유를 마크합니다.
                spurious_reason = "interest_rate_only"
            # 유효하지 않고 장해율인 경우
            elif is_disability:
                # 장해율 오탐으로 이유를 마크합니다.
                spurious_reason = "disability_rate_only"
            # 그 외의 의미 없는 숫자 매칭인 경우
            else:
                # 확인되지 않는 패턴이 섞여있다면 확실한 오탐으로 단정 짓지 않습니다.
                all_spurious = False
                break
                
        # 모든 예시가 지연이자/장해율 오탐으로 판정되었을 때
        if all_spurious:
            # 오탐이 확실하다고 반환합니다.
            return True, spurious_reason
            
    # 기본값은 오탐이 아님으로 처리합니다.
    return False, ""


def first_value(row: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", []):
            return str(value)
    return ""


def check_case_type(row: Dict[str, Any]) -> Tuple[bool, str]:
    """
    사건분류, 사건번호, 사건명을 복합 분석하여 형사책임, 행정처분, 산재보험 등
    민사상 과실비율과 관계없는 다른 도메인의 사건인지 판단합니다.
    
    반환값:
    - (True, '도메인명'): 비과실 민사 도메인으로 제외 대상임
    - (False, ''): 정상 민사/구상금 사건 영역임
    """
    # 사건 종류 메타데이터를 문자열로 가져옵니다.
    case_category = first_value(row, "사건종류명", "case_category")
    # 사건 번호를 문자열로 가져옵니다. (예: "2020다12345")
    case_number = first_value(row, "사건번호", "case_number")
    # 사건명을 문자열로 가져옵니다. (예: "손해배상(자)")
    case_name = first_value(row, "사건명", "case_name")
    
    # 1) 형사사건 여부 판단 (사건번호에 고단, 고합, 노, 도 등 형사 기호가 들어갔는지 확인)
    is_criminal_no = any(x in case_number for x in ["고단", "고합", "노", "도", "초"])
    # 2) 행정/산재소송 여부 판단 (사건번호에 구, 누, 두 등 행정 기호가 들어갔는지 확인)
    is_admin_no = any(x in case_number for x in ["구", "누", "두"])
    
    # 사건종류 텍스트에 형사가 명시되어 있는지 확인합니다.
    is_criminal_cat = "형사" in case_category
    # 사건종류 텍스트에 행정/특허가 명시되어 있는지 확인합니다.
    is_admin_cat = "행정" in case_category or "특허" in case_category
    
    # 사건명에 형사 위반 법규명이 포함되어 있는지 확인합니다.
    is_criminal_name = any(x in case_name for x in ["도로교통법", "교통사고처리특례법", "특례법위반", "도주치상", "위험운전", "음주운전", "무면허운전", "도주차량"])
    # 사건명에 행정처분 및 산재보험 관련 명이 포함되어 있는지 확인합니다.
    is_admin_name = any(x in case_name for x in ["면허취소", "면허정지", "요양급여", "유족급여", "요양불승인", "해고", "징계", "진료수가"])
    
    # 형사사건의 범주에 해당하는 경우 (명시적인 민사 사건 카테고리가 아닐 때)
    if is_criminal_no or is_criminal_cat or (is_criminal_name and "민사" not in case_category):
        # 형사책임 사건으로 오탐 처리합니다.
        return True, "criminal_case"
        
    # 행정/산재/노동사건의 범주에 해당하는 경우
    if is_admin_no or is_admin_cat or (is_admin_name and "민사" not in case_category):
        # 행정/산재처분 사건으로 오탐 처리합니다.
        return True, "administrative_or_labor_case"
        
    # 정상 민사소송 범위로 판단합니다.
    return False, ""


def verify_row(row: Dict[str, Any]) -> Tuple[str, List[str]]:
    """
    개별 판례 데이터를 검증 기준에 맞추어 최종 라벨을 판정하고 세부 판정 근거 리스트를 반환합니다.
    
    반환값:
    - (최종 라벨, 결정 사유 리스트)
      최종 라벨은 'fault_ratio_confirmed' 또는 'traffic_but_no_fault_ratio' 중 하나입니다.
    """
    # 최종 판정 이유들을 모을 리스트입니다.
    decision_reasons: List[str] = []
    
    # 2차 분류에서 추출해 두었던 문맥 플래그와 통계값을 가져옵니다.
    has_core = row.get("has_core_fault_ratio_context", False)
    has_damage = row.get("has_damage_or_insurance_context", False)
    signal_group_count = row.get("fault_ratio_signal_group_count", 0)
    no_fault_without_core = row.get("no_fault_context_without_core", False)
    
    # 1) 지연손해금, 이자율, 장해율 오탐 여부를 검사합니다.
    is_spurious, spurious_reason = check_spurious_signals(row)
    # 오탐이 감지되었다면
    if is_spurious:
        # 사유 리스트에 추가합니다.
        decision_reasons.append(f"spurious_ratio_apportionment_{spurious_reason}")
        # 핵심 과실비율 문맥이 없는 것으로 플래그를 정정합니다.
        has_core = False
        # 핵심 문맥이 실종되었으므로, 노이즈 키워드가 있을 경우 제외 대상으로 묶습니다.
        if row.get("fault_ratio_no_fault_terms", []):
            no_fault_without_core = True
            
    # 2) 형사책임 및 행정/산재 사건 도메인 여부를 검사합니다.
    is_non_civil, non_civil_reason = check_case_type(row)
    # 민사 과실비율 소송이 아니라면
    if is_non_civil:
        # 사유 리스트에 추가합니다.
        decision_reasons.append(f"non_civil_case_type_{non_civil_reason}")
        
    # 3) 손해액(치료비, 위자료, 일실수입 등) 산정 계산만 중심이고 과실비율 판단이 결여되었는지 검사합니다.
    # 손해액 관련 단어가 등장했는지 여부
    has_damage_terms = bool(row.get("fault_ratio_damage_terms", []))
    # 과실상계/비율 직접 표현이 명시되었는지 여부
    has_explicit = bool(row.get("fault_ratio_explicit_terms", []))
    # 유효한 숫자 비율 판시 예시가 존재하는지 여부
    has_numerical = bool(row.get("fault_ratio_number_examples", [])) and not is_spurious
    
    # 이 두 가지가 없고 손해액 항목만 존재한다면 단순 금액 다툼 사건입니다.
    is_damage_only = has_damage_terms and not has_explicit and not has_numerical
    # 단순 손해액 산정으로 판명 시
    if is_damage_only:
        # 사유 리스트에 추가합니다.
        decision_reasons.append("damage_calculation_only_without_fault_ratio")
        
    # 4) 최종 확정 조건 충족 여부를 평가합니다.
    # 숫자 비율 매칭이 오탐인 경우 근거 그룹 개수에서 제외하여 가중치 개수를 보정합니다.
    adjusted_signal_groups = max(0, signal_group_count - 1) if is_spurious else signal_group_count
    
    # 6개 확정 요건을 대조합니다.
    meets_confirmed_criteria = (
        # 1. 핵심 과실비율 문맥이 유효한가
        has_core
        # 2. 손해배상 및 보험 관련 맥락이 존재하는가
        and has_damage
        # 3. 근거가 되는 시그널 묶음이 2개 이상인가
        and adjusted_signal_groups >= 2
        # 4. 핵심 문맥 결여 상태에서 노이즈가 지배적이지 않은가
        and not no_fault_without_core
        # 5. 형사 및 행정/산재 사건이 아닌가
        and not is_non_civil
        # 6. 단순 손해액 산정 위주의 판례가 아닌가
        and not is_damage_only
    )
    
    # 모든 조건을 만족할 때
    if meets_confirmed_criteria:
        # 만약 누적된 거부 사유가 없다면 기본 사유를 기록합니다.
        if not decision_reasons:
            decision_reasons.append("verified_fault_ratio_confirmed")
        # 최종 confirmed 라벨을 부여합니다.
        return "fault_ratio_confirmed", decision_reasons
    # 하나라도 어긋날 때
    else:
        # 거부 사유가 마크되지 않았다면 기본 미달 이유를 기록합니다.
        if not decision_reasons:
            decision_reasons.append("insufficient_fault_ratio_evidence")
        # 최종 제외 라벨을 부여합니다.
        return "traffic_but_no_fault_ratio", decision_reasons


def attach_verification_fields(
    row: Dict[str, Any],
    source_label: str,
    final_label: str,
    decision_reasons: List[str],
) -> Dict[str, Any]:
    """
    기존 판례 객체(row)의 사본을 만들고, 검증 이력 추적이 가능하도록
    검증 전 라벨, 소스 라벨, 최종 결정 라벨 및 결정 사유 리스트를 주입하여 반환합니다.
    """
    # 얕은 복사를 통해 원본 데이터를 보존하며 복사본을 생성합니다.
    row = dict(row)
    # 검증 수행 전의 원본 2차 분류 라벨을 기록해둡니다.
    row["fault_ratio_label_before_verification"] = row.get("fault_ratio_label")
    # 원본 파일 출처(confirmed 인지 possible 인지)를 저장합니다.
    row["fault_ratio_verification_source_label"] = source_label
    # 정밀 검증 후 최종 판정된 라벨을 대입합니다.
    row["fault_ratio_verification_final_label"] = final_label
    # 2차 분류 라벨 필드도 최종 라벨로 통일 및 갱신해줍니다.
    row["fault_ratio_label"] = final_label
    # 최종 판정 이유 리스트를 알파벳 순으로 정렬하여 저장합니다.
    row["fault_ratio_verification_decision_reasons"] = sorted(decision_reasons)
    # 결과 객체를 반환합니다.
    return row


# ============================================================
# 5. 검증 실행 엔진
# ============================================================

def run_verification(args: argparse.Namespace) -> None:
    """
    2차 분류 결과 파일들을 각각 읽어와 정밀 검증을 순차적으로 수행하고,
    승격/강등 처리 후 최종 묶음으로 통합 분류하여 디렉터리에 저장합니다.
    """
    # 입력 폴더 경로 객체화
    fault_ratio_dir = Path(args.fault_ratio_dir)
    # 출력 폴더 경로 객체화
    out_dir = Path(args.out_dir)
    
    # 2차 분류 입력 파일 경로들이 실제로 존재하는지 체크합니다.
    confirmed_path = fault_ratio_dir / CONFIRMED_FILE
    possible_path = fault_ratio_dir / POSSIBLE_FILE
    no_fault_path = fault_ratio_dir / NO_FAULT_RATIO_FILE
    
    # 필수 파일들이 누락된 경우 즉시 중단합니다.
    if not (confirmed_path.exists() and possible_path.exists() and no_fault_path.exists()):
        raise FileNotFoundError(f"필수 입력 파일들이 {fault_ratio_dir} 내에 존재하지 않습니다.")
        
    # 결과가 저장될 디렉터리 및 개별 경로들을 초기화하며 생성합니다.
    paths = prepare_output_paths(out_dir, fresh=args.fresh)
    
    # 통계 기록용 객체 생성
    stats = VerificationStats()
    # 결정 이유 수량 집계를 위한 카운터
    decision_counter = Counter()
    
    # ------------------------------------------------------------
    # A. 01_confirmed_cases.jsonl 검증 처리 (유지 또는 강등)
    # ------------------------------------------------------------
    for row in read_jsonl(confirmed_path):
        # Confirmed 입력 개수를 늘립니다.
        stats.fault_confirmed_input_rows += 1
        
        # 6대 요건을 기준으로 정밀 평가를 돌립니다.
        final_label, decision_reasons = verify_row(row)
        # 통계 집계를 위해 판정 사유를 누적합니다.
        decision_counter.update(decision_reasons)
        # 이력 추적 필드를 객체에 덧붙입니다.
        verified_row = attach_verification_fields(row, "fault_ratio_confirmed", final_label, decision_reasons)
        
        # 검증을 통과하여 Confirmed 상태를 유지한 경우
        if final_label == "fault_ratio_confirmed":
            # 유지 수량을 늘립니다.
            stats.fault_confirmed_verified_rows += 1
            # 최종 과실비율 판례 수량을 늘립니다.
            stats.final_fault_ratio_confirmed_rows += 1
            # 최종 확정 파일에 저장합니다.
            write_jsonl(paths["confirmed"], verified_row)
        # 요건 미달로 강등된 경우
        else:
            # 강등 수량을 늘립니다.
            stats.fault_confirmed_demoted_to_no_fault_rows += 1
            # 최종 제외 판례 수량을 늘립니다.
            stats.final_no_fault_ratio_rows += 1
            # 최종 제외 파일에 저장합니다.
            write_jsonl(paths["no_fault_ratio"], verified_row)
            # 강등 이력 파일에도 개별 저장합니다.
            write_jsonl(paths["demoted"], verified_row)
            
        # 감사용 통합 파일에 저장합니다.
        stats.final_all_rows += 1
        write_jsonl(paths["all"], verified_row)
        
    # ------------------------------------------------------------
    # B. 02_possible_review.jsonl 검증 처리 (승격 또는 제외 유지)
    # ------------------------------------------------------------
    for row in read_jsonl(possible_path):
        # Possible 입력 개수를 늘립니다.
        stats.possible_input_rows += 1
        
        # 6대 요건을 기준으로 승격 가능 여부를 평가합니다.
        final_label, decision_reasons = verify_row(row)
        # 통계 집계를 위해 판정 사유를 누적합니다.
        decision_counter.update(decision_reasons)
        # 이력 추적 필드를 객체에 덧붙입는다.
        verified_row = attach_verification_fields(row, "fault_ratio_possible_review", final_label, decision_reasons)
        
        # 조건을 만족하여 최종 Confirmed로 승격 판정을 받은 경우
        if final_label == "fault_ratio_confirmed":
            # 승격 수량을 늘립니다.
            stats.possible_promoted_to_fault_confirmed_rows += 1
            # 최종 과실비율 판례 수량을 늘립니다.
            stats.final_fault_ratio_confirmed_rows += 1
            # 최종 확정 파일에 저장합니다.
            write_jsonl(paths["confirmed"], verified_row)
            # 승격 이력 파일에도 개별 저장합니다.
            write_jsonl(paths["promoted"], verified_row)
        # 승격되지 못하고 비과실비율로 강등(탈락)된 경우
        else:
            # 탈락 수량을 늘립니다.
            stats.possible_to_no_fault_rows += 1
            # 최종 제외 판례 수량을 늘립니다.
            stats.final_no_fault_ratio_rows += 1
            # 최종 제외 파일에 저장합니다.
            write_jsonl(paths["no_fault_ratio"], verified_row)
            # possible 탈락 이력 파일에도 개별 저장합니다.
            write_jsonl(paths["possible_to_no_fault"], verified_row)
            
        # 감사용 통합 파일에 저장합니다.
        stats.final_all_rows += 1
        write_jsonl(paths["all"], verified_row)
        
    # ------------------------------------------------------------
    # C. 03_no_fault_cases.jsonl 제외 처리 유지 (별도 재검토 없음)
    # ------------------------------------------------------------
    for row in read_jsonl(no_fault_path):
        # 기존 No Fault 입력 개수를 늘립니다.
        stats.no_fault_input_rows += 1
        
        # 원본 유지 정책에 따라 별도 검증 없이 비과실비율 판례로 보존합니다.
        final_label = "traffic_but_no_fault_ratio"
        # 사유에 원본 유지 사유를 대입합니다.
        decision_reasons = ["kept_original_no_fault_ratio"]
        # 결정 이유 누적
        decision_counter.update(decision_reasons)
        # 이력 추적 필드를 객체에 덧붙입니다.
        verified_row = attach_verification_fields(row, "traffic_but_no_fault_ratio", final_label, decision_reasons)
        
        # 최종 제외 수량 증가
        stats.final_no_fault_ratio_rows += 1
        # 최종 제외 파일에 저장합니다.
        write_jsonl(paths["no_fault_ratio"], verified_row)
        
        # 감사용 통합 파일에 저장합니다.
        stats.final_all_rows += 1
        write_jsonl(paths["all"], verified_row)
        
    # ------------------------------------------------------------
    # D. 리포트 생성 및 저장
    # ------------------------------------------------------------
    # 수집한 사유별 건수를 딕셔너리로 마크합니다.
    stats.decision_reason_counts = dict(decision_counter.most_common())
    
    # 00_report 파일에 들어갈 구조화 데이터를 준비합니다.
    report = {
        "verification_goal": "2차 과실비율 분류 결과 검증 및 최종 RAG 적재 후보 정제",
        "input_dir": str(fault_ratio_dir),
        "output_dir": str(out_dir),
        "outputs": {key: str(path) for key, path in paths.items()},
        "policy": [
            "1. has_core_fault_ratio_context가 유효하고, has_damage_or_insurance_context가 존재하며, 가중치 근거 그룹이 2개 이상일 때만 confirmed 처리합니다.",
            "2. 지연손해금(이자율), 노동능력상실률(장해율)에 의한 숫자 비율 오탐을 차단합니다.",
            "3. 사건 메타데이터를 추적하여 형사책임 위주 또는 행정처분, 산재보험 중심 판례를 confirmed에서 배제합니다.",
            "4. 과실비율 산정 내용 없이 손해액 연산(일실수입 등)만 나열된 판례를 제외합니다.",
            "5. 기존 possible_review 중 확정 요건을 넘은 판례만 confirmed로 끌어올리고, 미달은 모두 no_fault_ratio로 강등합니다.",
            "6. 기존 no_fault_ratio는 그대로 보존하여 precision을 극대화합니다."
        ],
        "stats": asdict(stats)
    }
    
    # JSON 파일로 저장합니다. 한글 인코딩을 적용합니다.
    with paths["report"].open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        
    # 콘솔 완료 로그 출력
    print("\n[성공] 2차 과실비율 검증 및 재정리 완료")
    print(json.dumps(report["stats"], ensure_ascii=False, indent=2))


# ============================================================
# 6. CLI 터미널 진입부
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    터미널 명령어 인수를 정의합니다.
    """
    # 인수 파서 정의
    parser = argparse.ArgumentParser(
        description="2차 과실비율 분류 판례 데이터를 정밀 검증 및 재분류하여 최종 Confirmed/No Fault로 정제합니다."
    )
    # 2차 분류 결과 폴더 옵션
    parser.add_argument(
        "--fault-ratio-dir",
        default=DEFAULT_FAULT_RATIO_DIR,
        help=f"2차 분류 결과 폴더. 기본값: {DEFAULT_FAULT_RATIO_DIR}",
    )
    # 검증 결과 출력 폴더 옵션
    parser.add_argument(
        "--out-dir",
        default=DEFAULT_OUT_DIR,
        help=f"출력될 검증 결과 폴더. 기본값: {DEFAULT_OUT_DIR}",
    )
    # 기존 결과 폴더 지우기 옵션
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="출력 디렉터리가 이미 존재할 시 삭제 후 새로 작성합니다.",
    )
    # 파싱 결과 반환
    return parser.parse_args()


# 파일 직접 실행 시 run_verification을 구동합니다.
if __name__ == "__main__":
    run_verification(parse_args())
