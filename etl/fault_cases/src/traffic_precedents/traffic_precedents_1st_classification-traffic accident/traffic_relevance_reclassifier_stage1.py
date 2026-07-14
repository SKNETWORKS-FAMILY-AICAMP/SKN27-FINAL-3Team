#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
traffic_relevance_reclassifier_stage1_final_commented.py

전처리 최종 파일인 traffic_prec_pre/03_cases_preprocessed.jsonl을 입력으로 받아
판례가 "교통사고 관련 판례인지 아닌지"를 1차로 재분류하는 코드입니다.

이번 수정의 핵심은 precision-first 최종 기준입니다.
즉, confirmed_traffic은 다음 단계에서 바로 사용할 수 있어야 하므로
애매한 판례를 confirmed로 올리지 않고 possible_traffic_review로 보냅니다.

confirmed_traffic 조건:
1. 점수 기준 충족
2. 근거 묶음 2개 이상
3. 교통 관련 키워드 총 3개 이상
4. 사고 핵심 문맥 존재
5. 일반 예시 문구가 아님
6. 세무/특허/가사처럼 비교통 성격이 강한 사건종류가 아님

기본 입력:
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_pre/03_cases_preprocessed.jsonl

기본 출력:
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass/

생성 파일:
00_traffic_reclass_report.json
01_confirmed_traffic_cases.jsonl
02_possible_traffic_review.jsonl
03_non_traffic_cases.jsonl
04_traffic_reclassified_all.jsonl

실행:
python traffic_relevance_reclassifier_stage1_final_commented.py --fresh
"""

from __future__ import annotations

# argparse는 터미널에서 --input, --out-dir, --fresh 같은 실행 옵션을 받기 위해 사용합니다.
import argparse

# json은 JSONL 파일을 한 줄씩 읽고 쓰기 위해 사용합니다.
import json

# re는 정규식 검색과 근접 문맥 탐지를 위해 사용합니다.
import re

# shutil은 --fresh 옵션 실행 시 기존 출력 폴더를 삭제하기 위해 사용합니다.
import shutil

# Counter는 라벨별 개수, 근거별 개수, 키워드별 개수를 세기 위해 사용합니다.
from collections import Counter

# dataclass는 실행 통계를 구조화된 형태로 저장하기 위해 사용합니다.
from dataclasses import asdict, dataclass, field

# Path는 파일 경로를 안전하게 다루기 위해 사용합니다.
from pathlib import Path

# 타입 힌트는 함수 입력/출력 의미를 명확히 하기 위해 사용합니다.
from typing import Any, Dict, Iterable, List, Tuple


# ============================================================
# 1. 기본 경로
# ============================================================

# 전처리 최종 결과 파일입니다.
# invalid 분리, 중복 제거, 품질 플래그 생성이 끝난 파일을 입력으로 받습니다.
DEFAULT_INPUT_PATH = "etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_pre/03_cases_preprocessed.jsonl"

# 교통사고 관련성 1차 재분류 결과를 저장할 기본 폴더입니다.
DEFAULT_OUTPUT_DIR = "etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass"


# ============================================================
# 2. 재분류 기준값
# ============================================================

# confirmed_traffic이 되기 위한 최소 점수입니다.
# 점수만 높다고 confirmed가 되는 것은 아니며, 아래 조건들도 함께 만족해야 합니다.
CONFIRMED_SCORE_THRESHOLD = 8

# possible_traffic_review로 보낼 최소 참고 점수입니다.
# confirmed 조건은 부족하지만 교통 관련 단서가 있으면 review로 보냅니다.
REVIEW_SCORE_THRESHOLD = 4

# confirmed_traffic이 되기 위한 최소 근거 묶음 개수입니다.
# 예: 직접 사고 표현 + 교통사고 법령/보험 문맥
MIN_CONFIRMED_SIGNAL_GROUPS = 2

# confirmed_traffic이 되기 위한 최소 교통 관련 키워드 개수입니다.
# 예: 교통사고, 차량, 충돌처럼 전체 텍스트에서 3개 이상 잡혀야 합니다.
MIN_CONFIRMED_TRAFFIC_TERM_COUNT = 3

# 근접 문맥을 볼 때 두 키워드 사이를 몇 글자까지 허용할지 정합니다.
# 예: "차량이 ... 충돌하였다"에서 차량과 충돌 사이의 허용 거리입니다.
NEAR_WINDOW = 80


# 재분류에 사용할 본문 최대 길이입니다.
# 판례 본문 전체가 매우 긴 경우 모든 글자를 매번 검색하면 속도가 급격히 느려집니다.
# 교통사고 관련성 판단은 사건명, 판시사항, 판결요지, 본문 앞부분에 핵심 단서가 나오는 경우가 많습니다.
# 그래서 본문이 너무 길면 앞부분과 끝부분만 남겨 처리합니다.
MAX_RECLASS_BODY_CHARS = 8000

# 긴 본문을 자를 때 뒤쪽에서 추가로 보존할 글자 수입니다.
# 참조조문, 결론부, 주문 근처에 단서가 있을 수 있어서 끝부분 일부를 남깁니다.
RECLASS_BODY_TAIL_CHARS = 2000

# confirmed_traffic에는 사고 핵심 문맥이 반드시 필요합니다.
# True이면 직접 사고 표현 또는 강한 사고 근접 문맥 없이는 confirmed가 될 수 없습니다.
REQUIRE_CORE_ACCIDENT_CONTEXT_FOR_CONFIRMED = True


# ============================================================
# 3. 키워드 사전
# ============================================================

# 직접적으로 교통사고 판례임을 보여주는 표현입니다.
# 단, "천재지변, 화재, 교통사고" 같은 일반 예시 문구는 아래 패턴에서 다시 제외합니다.
DIRECT_TRAFFIC_ACCIDENT_TERMS = [
    "교통사고",
    "자동차 사고",
    "차량 사고",
    "차량 충돌",
    "자동차 충돌",
    "접촉사고",
    "추돌사고",
    "후미추돌",
    "보행자 사고",
    "횡단보도 사고",
    "자전거 사고",
    "이륜차 사고",
    "오토바이 사고",
    "전동킥보드 사고",
    "개인형 이동장치 사고",
    "PM 사고",
    "사고차량",
    "가해차량",
    "피해차량",
    "피보험차량",
    "사고 차량",
    "가해 차량",
    "피해 차량",
    "피보험 차량",
]

# 교통사고 관련 법령, 보험, 사건명 표현입니다.
# 이 단어들은 중요한 힌트지만 단독으로 confirmed를 주지는 않습니다.
TRAFFIC_LEGAL_TERMS = [
    "교통사고처리특례법",
    "자동차손해배상 보장법",
    "자동차손해배상보장법",
    "자동차손해배상",
    "손해배상(자)",
    "자동차보험",
    "책임보험",
    "종합보험",
    "대인배상",
    "대물배상",
    "운행자책임",
    "보험자대위",
    "구상금",
]

# 넓은 의미의 도로/차량/사람 관련 단어입니다.
# 참고용 근접 문맥에는 사용하지만 confirmed 핵심 근거로는 직접 사용하지 않습니다.
ROAD_ACTOR_TERMS = [
    "자동차",
    "차량",
    "승용차",
    "승합차",
    "화물차",
    "버스",
    "택시",
    "덤프트럭",
    "트럭",
    "오토바이",
    "이륜차",
    "이륜자동차",
    "원동기장치자전거",
    "자전거",
    "전동킥보드",
    "개인형 이동장치",
    "보행자",
    "운전자",
    "탑승자",
    "동승자",
    "횡단보도",
    "교차로",
    "차로",
    "차선",
    "중앙선",
    "신호등",
    "도로",
    "주차장",
]

# 넓은 의미의 사고 행위/결과 단어입니다.
# 참고용으로는 사용하지만 confirmed 핵심 근거로는 직접 사용하지 않습니다.
ACCIDENT_ACTION_TERMS = [
    "사고",
    "충돌",
    "추돌",
    "들이받",
    "부딪",
    "치어",
    "치여",
    "충격",
    "전복",
    "전도",
    "넘어져",
    "사망",
    "상해",
    "상해를 입",
    "부상",
    "치상",
    "치사",
    "도주치상",
    "도주치사",
    "위험운전치상",
    "위험운전치사",
]

# confirmed_traffic 판단에 사용할 실제 사고 주체입니다.
# 도로, 신호등, 주차장, 차로처럼 배경에 가까운 단어는 제외했습니다.
CORE_ACCIDENT_ACTOR_TERMS = [
    "자동차",
    "차량",
    "승용차",
    "승합차",
    "화물차",
    "버스",
    "택시",
    "덤프트럭",
    "트럭",
    "오토바이",
    "이륜차",
    "이륜자동차",
    "원동기장치자전거",
    "자전거",
    "전동킥보드",
    "개인형 이동장치",
    "보행자",
    "운전자",
    "탑승자",
    "동승자",
]

# confirmed_traffic 판단에 사용할 강한 사고 행위입니다.
# 사고, 상해, 사망, 부상, 충격처럼 다른 분야에서도 흔한 단어는 제외했습니다.
CORE_ACCIDENT_ACTION_TERMS = [
    "충돌",
    "추돌",
    "들이받",
    "부딪",
    "치어",
    "치여",
    "전복",
    "전도",
    "치상",
    "치사",
    "도주치상",
    "도주치사",
    "위험운전치상",
    "위험운전치사",
]

# 구체적인 교통사고 상황을 보여주는 단어입니다.
TRAFFIC_SITUATION_TERMS = [
    "신호위반",
    "중앙선 침범",
    "안전거리",
    "진로 변경",
    "차로 변경",
    "끼어들기",
    "좌회전",
    "우회전",
    "유턴",
    "회전교차로",
    "어린이보호구역",
    "스쿨존",
    "개문",
    "문을 열",
    "무단횡단",
    "보행신호",
    "적색신호",
    "녹색신호",
]

# 과실/책임 판단과 관련된 표현입니다.
# 단독으로 교통사고 근거가 아니라, 다른 교통사고 근거와 함께 있을 때 보조 근거로 사용합니다.
FAULT_CONTEXT_TERMS = [
    "과실비율",
    "과실 비율",
    "과실상계",
    "과실 상계",
    "책임비율",
    "책임 비율",
    "주의의무",
    "안전운전의무",
    "전방주시의무",
    "주의를 게을리",
    "손해배상책임",
    "손해액",
]

# 교통사고가 아닐 가능성이 큰 도메인 단어입니다.
# 이 단어가 있어도 교통사고 핵심 근거가 충분하면 바로 non_traffic으로 보내지는 않습니다.
NON_TRAFFIC_DOMAIN_TERMS = [
    "공직선거법",
    "선거운동",
    "후보자",
    "정당",
    "투표",
    "개표",
    "조세",
    "법인세",
    "부가가치세",
    "소득세",
    "상속세",
    "증여세",
    "종합부동산세",
    "양도소득세",
    "근로기준법",
    "부당해고",
    "임금",
    "퇴직금",
    "산업재해보상보험법",
    "장애인차별금지법",
    "특허",
    "상표",
    "디자인보호법",
    "저작권",
    "의료법",
    "마약류",
    "성폭력",
    "아동·청소년",
    "건축허가",
    "도시정비",
    "정보공개",
    "국가보안법",
    "출입국관리법",
    "관세법",
]

# 교통 법규 단어이지만 사고가 없을 수 있는 표현입니다.
# 이런 단어만 있으면 confirmed_traffic이 아니라 possible 또는 non으로 보냅니다.
TRAFFIC_BUT_NOT_ACCIDENT_ALONE_TERMS = [
    "음주운전",
    "무면허운전",
    "운전면허취소",
    "운전면허정지",
    "자동차운전면허취소",
    "도로교통법위반",
    "도로교통법 위반",
    "주취운전",
    "측정거부",
    "벌점",
]

# 실제 교통사고 사실관계가 아니라 일반 예시나 법령 설명으로 등장하는 패턴입니다.
# 이런 패턴이 있으면 confirmed_traffic을 막는 방향으로 사용합니다.
GENERIC_TRAFFIC_REFERENCE_PATTERNS = [
    r"천재지변.{0,20}화재.{0,20}교통사고",
    r"화재.{0,20}교통사고.{0,20}도난",
    r"사고나\s*질병",
    r"질병\s*또는\s*사고",
    r"안전사고\s*예방",
    r"교통소통.{0,20}원활",
    r"질서유지",
]


# confirmed_traffic으로 바로 보내지 않을 사건종류입니다.
# 이건 특정 판례 ID를 찍는 하드코딩이 아니라, 도메인 단위 안전장치입니다.
# 세무/특허/가사는 실제 교통사고 분쟁이라기보다 세금, 지식재산, 가족관계 쟁점일 가능성이 높습니다.
# 따라서 교통 관련 단어가 있어도 바로 confirmed가 아니라 possible_traffic_review로 보냅니다.
DISALLOW_CONFIRMED_CASE_CATEGORIES = [
    "세무",
    "특허",
    "가사",
]


# ============================================================
# 4. 실행 통계 구조
# ============================================================

@dataclass
class ReclassStats:
    """
    재분류 실행 결과를 report JSON에 저장하기 위한 통계 구조입니다.
    """

    # 입력 row 전체 개수입니다.
    input_rows: int = 0

    # JSON 파싱 실패 등으로 정상 처리하지 못한 row 개수입니다.
    skipped_unusable_rows: int = 0

    # confirmed_traffic으로 분류된 row 개수입니다.
    confirmed_traffic: int = 0

    # possible_traffic_review로 분류된 row 개수입니다.
    possible_traffic_review: int = 0

    # non_traffic으로 분류된 row 개수입니다.
    non_traffic: int = 0

    # 라벨별 개수를 저장합니다.
    label_counts: Dict[str, int] = field(default_factory=dict)

    # 분류 이유별 개수를 저장합니다.
    reason_counts: Dict[str, int] = field(default_factory=dict)

    # 근거 키워드별 빈도를 저장합니다.
    evidence_term_counts: Dict[str, int] = field(default_factory=dict)

    # 비교통 도메인 키워드별 빈도를 저장합니다.
    non_traffic_domain_counts: Dict[str, int] = field(default_factory=dict)


# ============================================================
# 5. 파일 경로 준비 함수
# ============================================================

def remove_dir_if_exists(path: Path) -> None:
    """
    지정한 폴더가 존재하면 삭제합니다.

    역할:
    - --fresh 옵션을 사용할 때 기존 결과 폴더를 깨끗하게 비웁니다.
    """

    # path가 실제로 존재하는지 확인합니다.
    if path.exists():
        # 폴더와 내부 파일을 모두 삭제합니다.
        shutil.rmtree(path)


def prepare_output_paths(out_dir: Path, fresh: bool) -> Dict[str, Path]:
    """
    출력 폴더와 결과 파일 경로를 준비합니다.

    반환:
    - report: 실행 요약 JSON
    - confirmed: confirmed_traffic JSONL
    - review: possible_traffic_review JSONL
    - non_traffic: non_traffic JSONL
    - all: 전체 row에 traffic_label을 붙인 JSONL
    """

    # fresh 옵션이 있으면 기존 출력 폴더를 삭제합니다.
    if fresh:
        remove_dir_if_exists(out_dir)

    # 출력 폴더가 없으면 생성합니다.
    out_dir.mkdir(parents=True, exist_ok=True)

    # 결과 파일 경로를 dict로 묶어서 반환합니다.
    return {
        "report": out_dir / "00_traffic_reclass_report.json",
        "confirmed": out_dir / "01_confirmed_traffic_cases.jsonl",
        "review": out_dir / "02_possible_traffic_review.jsonl",
        "non_traffic": out_dir / "03_non_traffic_cases.jsonl",
        "all": out_dir / "04_traffic_reclassified_all.jsonl",
    }


# ============================================================
# 6. 공통 유틸 함수
# ============================================================

def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    """
    JSONL 파일을 한 줄씩 읽어서 dict로 반환합니다.
    """

    # UTF-8 인코딩으로 입력 파일을 엽니다.
    with path.open("r", encoding="utf-8") as file:
        # line_no는 오류 추적을 위한 원본 줄 번호입니다.
        for line_no, line in enumerate(file, 1):
            # 줄 앞뒤 공백과 개행 문자를 제거합니다.
            line = line.strip()

            # 빈 줄이면 건너뜁니다.
            if not line:
                continue

            try:
                # JSON 문자열 한 줄을 dict로 변환합니다.
                row = json.loads(line)

                # 나중에 추적할 수 있도록 입력 줄 번호를 저장합니다.
                row["_reclass_input_line_no"] = line_no

                # 정상 row를 호출한 쪽으로 반환합니다.
                yield row

            except json.JSONDecodeError:
                # JSON 파싱 실패 시에도 전체 실행이 멈추지 않도록 에러 row를 반환합니다.
                yield {
                    "_reclass_input_line_no": line_no,
                    "_json_decode_error": True,
                    "_raw_line_preview": line[:500],
                }


def write_jsonl(path: Path, row: Dict[str, Any]) -> None:
    """
    dict 한 건을 JSONL 파일에 append 저장합니다.
    """

    # append 모드로 파일을 엽니다.
    with path.open("a", encoding="utf-8") as file:
        # 한글이 깨지지 않도록 ensure_ascii=False를 사용합니다.
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_space(text: Any) -> str:
    """
    텍스트 안의 연속 공백을 하나의 공백으로 정리합니다.

    긴 판례 본문을 빠르게 처리하기 위해 정규식 대신 split/join을 사용합니다.
    """

    # 값이 None이면 빈 문자열로 처리합니다.
    if text is None:
        return ""

    # 문자열로 바꾼 뒤 공백 기준으로 쪼개고 다시 하나의 공백으로 합칩니다.
    return " ".join(str(text).split())


def first_value(row: Dict[str, Any], *keys: str) -> str:
    """
    새 한글 전처리 필드와 기존 영문 필드를 함께 지원합니다.
    """

    for key in keys:
        value = row.get(key)
        if value not in (None, "", []):
            return str(value)
    return ""


def trim_reclass_body_text(text: Any) -> str:
    """
    재분류용 긴 본문을 적당한 길이로 줄입니다.

    역할:
    - 너무 긴 판례 본문 때문에 분류 속도가 느려지는 문제를 줄입니다.
    - 앞부분은 그대로 보존합니다.
    - 끝부분도 일부 보존합니다.
    - 중간 생략 표식을 넣어, 나중에 잘린 텍스트임을 알 수 있게 합니다.
    """

    # None이면 빈 문자열을 반환합니다.
    if text is None:
        return ""

    # 입력값을 문자열로 변환합니다.
    value = str(text)

    # 본문이 기준 길이 이하이면 그대로 반환합니다.
    if len(value) <= MAX_RECLASS_BODY_CHARS:
        return value

    # 앞부분에서 보존할 길이를 계산합니다.
    head_len = MAX_RECLASS_BODY_CHARS - RECLASS_BODY_TAIL_CHARS

    # 앞부분을 자릅니다.
    head = value[:head_len]

    # 끝부분을 자릅니다.
    tail = value[-RECLASS_BODY_TAIL_CHARS:]

    # 중간 생략 표식을 넣어 반환합니다.
    return head + "\n[RECLASS_TEXT_MIDDLE_OMITTED]\n" + tail


def build_reclass_text(row: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    재분류에 사용할 텍스트를 만듭니다.

    반환:
    - title_text: 사건명/사건번호/법원명/사건종류 등 메타 정보
    - body_text: 판시사항/판결요지/full_text/main_text/참조조문 중심 본문
    - all_text: title_text와 body_text를 합친 전체 텍스트
    """

    # 사건명, 사건번호, 법원명 등 짧은 메타 정보를 모읍니다.
    title_parts = [
        first_value(row, "사건명", "case_name"),
        first_value(row, "사건번호", "case_number"),
        first_value(row, "법원명", "court_name"),
        first_value(row, "사건종류명", "case_category"),
        first_value(row, "judgment_type"),
    ]

    # 본문 판단에 사용할 긴 텍스트 필드를 모읍니다.
    # full_text는 case_name, holding, summary, main_text가 합쳐져 있어 중복이 생길 수 있습니다.
    # 그래서 가능하면 main_text를 우선 사용하고, main_text가 없을 때만 full_text를 사용합니다.
    raw_main_body_text = first_value(row, "판례내용", "main_text", "full_text")

    # 너무 긴 본문은 앞부분과 끝부분만 남겨 처리 속도를 높입니다.
    main_body_text = trim_reclass_body_text(raw_main_body_text)

    body_parts = [
        first_value(row, "판시사항", "holding"),
        first_value(row, "판결요지", "summary"),
        first_value(row, "주문"),
        first_value(row, "이유"),
        main_body_text,
        first_value(row, "참조조문", "referenced_laws"),
        first_value(row, "참조판례", "referenced_cases"),
    ]

    # title_parts 중 비어 있지 않은 값만 이어 붙입니다.
    # 제목 영역은 짧기 때문에 공백 정리를 적용합니다.
    title_text = normalize_space(" ".join(str(x) for x in title_parts if x))

    # body_parts 중 비어 있지 않은 값만 이어 붙입니다.
    # 긴 본문은 반복적인 정규식 공백 정리를 피해서 처리 속도를 높입니다.
    body_text = " ".join(str(x) for x in body_parts if x)

    # 제목/메타 텍스트와 본문 텍스트를 합쳐 전체 검색 텍스트를 만듭니다.
    # 여기서도 긴 본문 전체에 다시 공백 정리를 걸지 않습니다.
    all_text = title_text + " " + body_text

    # 세 가지 텍스트를 반환합니다.
    return title_text, body_text, all_text


def find_terms(text: str, terms: List[str]) -> List[str]:
    """
    text 안에 포함된 키워드를 찾아 중복 없이 반환합니다.
    """

    # 매칭된 키워드를 저장할 리스트입니다.
    found = []

    # 대소문자 차이를 줄이기 위해 전체 텍스트를 소문자로 바꿉니다.
    lower = text.lower()

    # 키워드 목록을 하나씩 확인합니다.
    for term in terms:
        # 키워드도 소문자로 바꿔 포함 여부를 확인합니다.
        if term.lower() in lower:
            # 포함되어 있으면 결과 리스트에 추가합니다.
            found.append(term)

    # 중복 제거 후 정렬하여 반환합니다.
    return sorted(set(found))


def regex_search(pattern: str, text: str) -> bool:
    """
    정규식 패턴이 text 안에 존재하는지 확인합니다.
    """

    # re.I는 대소문자 무시, re.S는 줄바꿈 포함 검색입니다.
    return re.search(pattern, text, flags=re.I | re.S) is not None


def has_near_pair(
    text: str,
    left_terms: List[str],
    right_terms: List[str],
    window: int = NEAR_WINDOW,
) -> bool:
    """
    left_terms 중 하나와 right_terms 중 하나가 가까운 거리 안에 같이 나오는지 확인합니다.

    정규식 OR 패턴으로 전체 본문을 반복 검색하면 긴 판례에서 느려질 수 있습니다.
    그래서 여기서는 문자열 find 방식으로 단어 주변 window만 확인합니다.

    예:
    - 차량 ... 충돌
    - 보행자 ... 치어
    - 오토바이 ... 추돌
    """

    # 전체 텍스트를 소문자로 바꿔 대소문자 차이를 줄입니다.
    lower_text = text.lower()

    # 왼쪽 키워드도 소문자로 준비합니다.
    left_pairs = [(term, term.lower()) for term in left_terms]

    # 오른쪽 키워드도 소문자로 준비합니다.
    right_lowers = [term.lower() for term in right_terms]

    # 왼쪽 키워드를 하나씩 기준점으로 삼습니다.
    for original_left, left in left_pairs:
        # find 검색 시작 위치입니다.
        start_pos = 0

        # 같은 단어가 여러 번 나올 수 있으므로 반복해서 찾습니다.
        while True:
            # 현재 시작 위치 이후에서 왼쪽 키워드를 찾습니다.
            idx = lower_text.find(left, start_pos)

            # 더 이상 없으면 다음 왼쪽 키워드로 넘어갑니다.
            if idx == -1:
                break

            # 왼쪽 키워드 주변 window 범위를 계산합니다.
            window_start = max(0, idx - window)

            # 왼쪽 키워드 끝에서 window만큼 뒤까지 봅니다.
            window_end = min(len(lower_text), idx + len(left) + window)

            # 주변 문맥만 잘라냅니다.
            nearby_text = lower_text[window_start:window_end]

            # 주변 문맥 안에 오른쪽 키워드 중 하나라도 있으면 근접쌍으로 봅니다.
            if any(right in nearby_text for right in right_lowers):
                return True

            # 다음 검색 시작 위치를 현재 키워드 뒤로 옮깁니다.
            start_pos = idx + len(left)

    # 끝까지 찾지 못하면 근접쌍이 없는 것입니다.
    return False

def collect_near_pair_examples(
    text: str,
    left_terms: List[str],
    right_terms: List[str],
    window: int = NEAR_WINDOW,
    max_examples: int = 5,
) -> List[str]:
    """
    가까운 거리에서 잡힌 키워드 조합의 실제 문구 일부를 추출합니다.

    has_near_pair와 같은 방식으로 문자열 find를 사용합니다.
    """

    # 추출한 예시 문구를 담을 리스트입니다.
    examples = []

    # 전체 텍스트를 소문자로 바꿔 검색합니다.
    lower_text = text.lower()

    # 왼쪽 키워드 원문과 소문자 버전을 함께 보관합니다.
    left_pairs = [(term, term.lower()) for term in left_terms]

    # 오른쪽 키워드도 원문과 소문자 버전을 함께 보관합니다.
    right_pairs = [(term, term.lower()) for term in right_terms]

    # 왼쪽 키워드를 하나씩 기준점으로 삼습니다.
    for original_left, left in left_pairs:
        # find 검색 시작 위치입니다.
        start_pos = 0

        # 같은 키워드가 여러 번 나올 수 있으므로 반복합니다.
        while True:
            # 현재 위치 이후에서 왼쪽 키워드를 찾습니다.
            idx = lower_text.find(left, start_pos)

            # 더 이상 없으면 다음 왼쪽 키워드로 넘어갑니다.
            if idx == -1:
                break

            # 주변 문맥 범위의 시작점을 계산합니다.
            window_start = max(0, idx - window)

            # 주변 문맥 범위의 끝점을 계산합니다.
            window_end = min(len(lower_text), idx + len(left) + window)

            # 주변 문맥의 소문자 버전입니다.
            nearby_lower = lower_text[window_start:window_end]

            # 주변 문맥의 원문 버전입니다.
            nearby_original = text[window_start:window_end]

            # 오른쪽 키워드가 주변 문맥 안에 있는지 확인합니다.
            if any(right in nearby_lower for _, right in right_pairs):
                # 공백을 정리한 예시 문구를 만듭니다.
                snippet = normalize_space(nearby_original)

                # 비어 있지 않고 중복이 아니면 추가합니다.
                if snippet and snippet not in examples:
                    examples.append(snippet[:200])

                # 최대 예시 개수에 도달하면 바로 반환합니다.
                if len(examples) >= max_examples:
                    return examples

            # 다음 검색 시작 위치를 현재 키워드 뒤로 옮깁니다.
            start_pos = idx + len(left)

    # 모은 예시 문구를 반환합니다.
    return examples

def find_generic_traffic_reference_patterns(text: str) -> List[str]:
    """
    실제 교통사고 사실관계가 아니라 일반 예시 문구로 보이는 패턴을 찾습니다.
    """

    # 매칭된 일반 예시 패턴을 저장할 리스트입니다.
    matched_patterns = []

    # 일반 예시 패턴 목록을 하나씩 검사합니다.
    for pattern in GENERIC_TRAFFIC_REFERENCE_PATTERNS:
        # 패턴이 전체 텍스트 안에 있으면 기록합니다.
        if regex_search(pattern, text):
            matched_patterns.append(pattern)

    # 중복 제거 후 정렬해서 반환합니다.
    return sorted(set(matched_patterns))


def find_direct_traffic_accident_terms(text: str) -> List[str]:
    """
    직접 교통사고 표현을 찾습니다.

    일반 find_terms를 그대로 쓰지 않는 이유:
    - "교통사고처리특례법" 안의 "교통사고"가 direct 사고 표현으로 잡히는 것을 막기 위해서입니다.
    - 법령명 안의 교통사고는 TRAFFIC_LEGAL_TERMS에서 따로 잡습니다.
    """

    # 매칭된 직접 사고 표현을 저장할 리스트입니다.
    found = []

    # 같은 텍스트를 여러 번 lower 처리하지 않도록 한 번만 소문자로 바꿉니다.
    lower_text = text.lower()

    # 직접 사고 표현 목록을 하나씩 확인합니다.
    for term in DIRECT_TRAFFIC_ACCIDENT_TERMS:
        # "교통사고" 단어는 법령명 내부 매칭을 제외해서 봅니다.
        if term == "교통사고":
            # 교통사고 뒤에 처리특례법이 바로 이어지는 경우는 직접 사고 표현으로 보지 않습니다.
            if regex_search(r"교통사고(?!\s*처리\s*특례법)", text):
                found.append(term)

        # 나머지 직접 표현은 일반 포함 여부로 확인합니다.
        elif term.lower() in lower_text:
            found.append(term)

    # 중복 제거 후 정렬해서 반환합니다.
    return sorted(set(found))


def is_case_category_disallowed_for_confirmed(case_category: Any) -> bool:
    """
    사건종류가 confirmed_traffic으로 바로 가면 위험한 도메인인지 확인합니다.

    예:
    - 세무
    - 특허
    - 가사
    """

    # 사건종류를 문자열로 변환하고 공백을 정리합니다.
    category = normalize_space(case_category)

    # 금지 목록에 있으면 True를 반환합니다.
    return category in DISALLOW_CONFIRMED_CASE_CATEGORIES


# ============================================================
# 7. 교통사고 관련성 판정 함수
# ============================================================

def classify_traffic_relevance(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    판례 한 건이 교통사고 관련인지 1차 재분류합니다.

    역할:
    - 한 row의 텍스트를 읽습니다.
    - 키워드와 근접 문맥을 찾습니다.
    - confirmed / possible / non 라벨을 결정합니다.
    - 사람이 검토할 수 있도록 근거 필드를 함께 반환합니다.
    """

    # row에서 재분류용 텍스트를 생성합니다.
    title_text, body_text, all_text = build_reclass_text(row)

    # 직접 교통사고 표현을 찾습니다.
    # 교통사고처리특례법 안의 교통사고는 direct가 아니라 legal로만 봅니다.
    direct_terms = find_direct_traffic_accident_terms(all_text)

    # 교통사고 관련 법령/보험 표현을 찾습니다.
    legal_terms = find_terms(all_text, TRAFFIC_LEGAL_TERMS)

    # 넓은 도로/차량/사람 표현을 찾습니다.
    actor_terms = find_terms(all_text, ROAD_ACTOR_TERMS)

    # 넓은 사고 행위/결과 표현을 찾습니다.
    action_terms = find_terms(all_text, ACCIDENT_ACTION_TERMS)

    # 구체적 사고 상황 표현을 찾습니다.
    situation_terms = find_terms(all_text, TRAFFIC_SITUATION_TERMS)

    # 과실/책임 문맥 표현을 찾습니다.
    fault_terms = find_terms(all_text, FAULT_CONTEXT_TERMS)

    # 비교통 도메인 표현을 찾습니다.
    non_traffic_terms = find_terms(all_text, NON_TRAFFIC_DOMAIN_TERMS)

    # 교통 법규이지만 사고가 없을 수 있는 표현을 찾습니다.
    traffic_law_only_terms = find_terms(all_text, TRAFFIC_BUT_NOT_ACCIDENT_ALONE_TERMS)

    # 넓은 의미의 차량/도로 주체 + 사고 행위 근접 문맥을 확인합니다.
    near_actor_action = has_near_pair(all_text, ROAD_ACTOR_TERMS, ACCIDENT_ACTION_TERMS)

    # 넓은 근접 문맥이 있을 때만 예시 문구를 추출합니다.
    # 없는데도 예시 추출을 돌리면 긴 판례에서 불필요하게 느려집니다.
    near_examples = (
        collect_near_pair_examples(all_text, ROAD_ACTOR_TERMS, ACCIDENT_ACTION_TERMS)
        if near_actor_action
        else []
    )

    # confirmed 판단용 강한 사고 주체 + 강한 사고 행위 근접 문맥을 확인합니다.
    core_actor_action = has_near_pair(
        all_text,
        CORE_ACCIDENT_ACTOR_TERMS,
        CORE_ACCIDENT_ACTION_TERMS,
    )

    # 강한 근접 문맥이 있을 때만 예시 문구를 추출합니다.
    core_actor_action_examples = (
        collect_near_pair_examples(
            all_text,
            CORE_ACCIDENT_ACTOR_TERMS,
            CORE_ACCIDENT_ACTION_TERMS,
        )
        if core_actor_action
        else []
    )

    # 일반 예시 문구로 보이는 패턴을 찾습니다.
    generic_reference_patterns = find_generic_traffic_reference_patterns(all_text)

    # 사건종류가 confirmed로 바로 보내기 위험한 도메인인지 확인합니다.
    case_category_disallowed_for_confirmed = is_case_category_disallowed_for_confirmed(
        first_value(row, "사건종류명", "case_category")
    )

    # 분류 점수 초기값입니다.
    score = 0

    # 분류 이유를 저장할 리스트입니다.
    reasons = []

    # 사람이 검토할 근거 표현을 저장할 리스트입니다.
    evidence_terms = []

    # confirmed 판단에 사용할 근거 묶음 리스트입니다.
    signal_groups = []

    # 직접 교통사고 표현이 있으면 강한 근거로 점수를 부여합니다.
    if direct_terms:
        score += 8
        reasons.append("direct_traffic_accident_terms")
        evidence_terms.extend(direct_terms)
        signal_groups.append("direct_accident_expression")

    # 넓은 근접 문맥은 참고 근거로만 사용합니다.
    # 기존에는 confirmed 근거 묶음에 들어갔지만, 노이즈가 있어 약화했습니다.
    if near_actor_action:
        score += 4
        reasons.append("road_actor_and_accident_action_nearby")
        evidence_terms.extend(near_examples)

    # 강한 근접 문맥은 confirmed 판단에 사용할 핵심 근거로 인정합니다.
    if core_actor_action:
        score += 7
        reasons.append("core_actor_and_strong_accident_action_nearby")
        evidence_terms.extend(core_actor_action_examples)
        signal_groups.append("core_actor_action_nearby")

    # 교통사고 관련 법령/보험 표현이 있으면 점수를 부여합니다.
    if legal_terms:
        score += min(6, 2 + len(legal_terms))
        reasons.append("traffic_legal_or_insurance_terms")
        evidence_terms.extend(legal_terms)
        signal_groups.append("traffic_legal_or_insurance_context")

    # 사고 상황 표현이 있으면 보조 근거로 점수를 부여합니다.
    if situation_terms:
        score += min(4, len(situation_terms))
        reasons.append("traffic_situation_terms")
        evidence_terms.extend(situation_terms)
        signal_groups.append("traffic_situation_context")

    # 과실/책임 문맥은 교통 관련 근거가 있을 때만 보조 근거로 인정합니다.
    if fault_terms and (direct_terms or core_actor_action or legal_terms or situation_terms):
        score += min(3, len(fault_terms))
        reasons.append("fault_context_with_traffic_evidence")
        evidence_terms.extend(fault_terms)
        signal_groups.append("fault_or_liability_context")

    # 사고 없는 교통 법규 단어만 있으면 confirmed로 보내지 않습니다.
    if traffic_law_only_terms and not (direct_terms or core_actor_action):
        score += 1
        reasons.append("traffic_law_terms_without_accident_context")
        evidence_terms.extend(traffic_law_only_terms)

    # 비교통 도메인 단어가 있으면 이유에 기록합니다.
    if non_traffic_terms:
        reasons.append("non_traffic_domain_terms_found")

    # 일반 예시 문구가 있으면 이유에 기록합니다.
    if generic_reference_patterns:
        reasons.append("generic_traffic_reference_pattern_found")

    # 사건종류상 confirmed로 바로 보내기 위험하면 이유에 기록합니다.
    if case_category_disallowed_for_confirmed:
        reasons.append("case_category_disallowed_for_confirmed")

    # 근거 묶음은 중복 제거 후 정렬합니다.
    signal_groups = sorted(set(signal_groups))

    # 근거 묶음 개수를 계산합니다.
    signal_group_count = len(signal_groups)

    # 교통 관련 키워드 개수 계산용 리스트를 만듭니다.
    traffic_terms_for_count = []

    # 직접 교통사고 표현을 키워드 개수 계산에 포함합니다.
    traffic_terms_for_count.extend(direct_terms)

    # 교통 법령/보험 표현을 키워드 개수 계산에 포함합니다.
    traffic_terms_for_count.extend(legal_terms)

    # 넓은 도로/차량/사람 표현을 키워드 개수 계산에 포함합니다.
    traffic_terms_for_count.extend(actor_terms)

    # 넓은 사고 행위/결과 표현을 키워드 개수 계산에 포함합니다.
    traffic_terms_for_count.extend(action_terms)

    # 사고 상황 표현을 키워드 개수 계산에 포함합니다.
    traffic_terms_for_count.extend(situation_terms)

    # 과실/책임 표현을 키워드 개수 계산에 포함합니다.
    traffic_terms_for_count.extend(fault_terms)

    # 키워드를 공백 정리하고 중복 제거합니다.
    traffic_terms_for_count = sorted(set(
        normalize_space(term)
        for term in traffic_terms_for_count
        if normalize_space(term)
    ))

    # 교통 관련 키워드 총 개수를 계산합니다.
    traffic_term_count = len(traffic_terms_for_count)

    # 사고 핵심 문맥 여부를 계산합니다.
    # 직접 사고 표현 또는 강한 사고 근접 문맥이 있으면 True입니다.
    has_core_accident_context = bool(direct_terms or core_actor_action)

    # 교통 법령/보험 문맥이 사고 문맥 또는 사고 상황과 결합되는지 확인합니다.
    has_traffic_legal_plus_accident_context = bool(
        legal_terms
        and (
            has_core_accident_context
            or situation_terms
        )
    )

    # 근거 묶음 개수가 confirmed 기준을 만족하는지 확인합니다.
    enough_confirmed_signals = signal_group_count >= MIN_CONFIRMED_SIGNAL_GROUPS

    # 교통 관련 키워드 개수가 confirmed 기준을 만족하는지 확인합니다.
    enough_confirmed_terms = traffic_term_count >= MIN_CONFIRMED_TRAFFIC_TERM_COUNT

    # 일반 예시 문구가 없는지 확인합니다.
    no_generic_reference = not generic_reference_patterns

    # confirmed_traffic은 가장 엄격하게 판단합니다.
    # 핵심 수정:
    # - 법령/보험 + 사고상황만으로는 confirmed를 주지 않습니다.
    # - confirmed에는 반드시 has_core_accident_context=True가 필요합니다.
    # - 일반 예시 문구가 있으면 confirmed를 주지 않습니다.
    # - 세무/특허/가사 사건종류는 confirmed를 주지 않습니다.
    if (
        score >= CONFIRMED_SCORE_THRESHOLD
        and enough_confirmed_signals
        and enough_confirmed_terms
        and has_core_accident_context
        and no_generic_reference
        and not case_category_disallowed_for_confirmed
    ):
        label = "confirmed_traffic"

    # confirmed는 아니지만 교통 관련 단서가 있으면 review로 보냅니다.
    elif (
        score >= REVIEW_SCORE_THRESHOLD
        or signal_group_count >= 1
        or legal_terms
        or traffic_law_only_terms
        or direct_terms
        or core_actor_action
    ):
        label = "possible_traffic_review"

    # 교통사고 관련 근거가 부족하면 non_traffic으로 보냅니다.
    else:
        label = "non_traffic"

    # 비교통 도메인 단어가 있고 교통사고 핵심 근거가 부족하면 non_traffic으로 강화합니다.
    if non_traffic_terms and signal_group_count < MIN_CONFIRMED_SIGNAL_GROUPS:
        if not has_core_accident_context and not has_traffic_legal_plus_accident_context:
            label = "non_traffic"
            reasons.append("non_traffic_domain_without_enough_traffic_accident_signals")

    # 근거 표현은 공백 정리, 빈 값 제거, 중복 제거 후 정렬합니다.
    evidence_terms = sorted(set(normalize_space(x) for x in evidence_terms if normalize_space(x)))

    # 최종 분류 결과와 검토용 메타데이터를 반환합니다.
    return {
        "traffic_label": label,
        "traffic_relevance_score": score,
        "traffic_reclass_reasons": sorted(set(reasons)),
        "traffic_evidence_terms": evidence_terms,
        "traffic_signal_groups": signal_groups,
        "traffic_signal_group_count": signal_group_count,
        "min_confirmed_signal_groups": MIN_CONFIRMED_SIGNAL_GROUPS,
        "traffic_term_count": traffic_term_count,
        "min_confirmed_traffic_term_count": MIN_CONFIRMED_TRAFFIC_TERM_COUNT,
        "traffic_terms_for_count": traffic_terms_for_count[:50],
        "traffic_direct_terms": direct_terms,
        "traffic_legal_terms": legal_terms,
        "traffic_actor_terms": actor_terms[:30],
        "traffic_action_terms": action_terms,
        "traffic_situation_terms": situation_terms,
        "traffic_fault_terms": fault_terms,
        "traffic_law_only_terms": traffic_law_only_terms,
        "non_traffic_domain_terms": non_traffic_terms,
        "near_actor_action_examples": near_examples,
        "core_actor_action_examples": core_actor_action_examples,
        "has_core_accident_context": has_core_accident_context,
        "has_traffic_legal_plus_accident_context": has_traffic_legal_plus_accident_context,
        "generic_traffic_reference_patterns": generic_reference_patterns,
        "case_category_disallowed_for_confirmed": case_category_disallowed_for_confirmed,
        "disallow_confirmed_case_categories": DISALLOW_CONFIRMED_CASE_CATEGORIES,
        "require_core_accident_context_for_confirmed": REQUIRE_CORE_ACCIDENT_CONTEXT_FOR_CONFIRMED,
    }


# ============================================================
# 8. 메인 실행 함수
# ============================================================

def reclassify(args: argparse.Namespace) -> None:
    """
    교통사고 관련성 1차 재분류를 실행합니다.

    역할:
    - 입력 JSONL을 읽습니다.
    - 각 row를 confirmed / possible / non으로 분류합니다.
    - 라벨별 JSONL 파일을 저장합니다.
    - 실행 통계 report를 저장합니다.
    """

    # 입력 파일 경로를 Path 객체로 변환합니다.
    input_path = Path(args.input)

    # 출력 폴더 경로를 Path 객체로 변환합니다.
    out_dir = Path(args.out_dir)

    # 입력 파일이 없으면 오류를 발생시킵니다.
    if not input_path.exists():
        raise FileNotFoundError(f"input file not found: {input_path}")

    # 출력 파일 경로들을 준비합니다.
    paths = prepare_output_paths(out_dir, fresh=args.fresh)

    # 실행 통계 객체를 생성합니다.
    stats = ReclassStats()

    # 라벨별 개수를 세는 Counter입니다.
    label_counter = Counter()

    # 분류 이유별 개수를 세는 Counter입니다.
    reason_counter = Counter()

    # evidence term별 빈도를 세는 Counter입니다.
    evidence_counter = Counter()

    # 비교통 도메인 단어별 빈도를 세는 Counter입니다.
    non_domain_counter = Counter()

    # 입력 JSONL을 한 줄씩 읽습니다.
    for row in read_jsonl(input_path):
        # 전체 입력 row 개수를 증가시킵니다.
        stats.input_rows += 1

        # JSON 파싱 에러가 있는 row는 전체 파일에만 남깁니다.
        if row.get("_json_decode_error"):
            row["traffic_label"] = "unusable_input_error"
            row["traffic_reclass_reasons"] = ["json_decode_error"]
            stats.skipped_unusable_rows += 1
            write_jsonl(paths["all"], row)
            continue

        # 전처리에서 재분류 사용 불가로 표시된 row는 review로 보냅니다.
        if row.get("is_usable_for_reclassification") is False:
            result = {
                "traffic_label": "possible_traffic_review",
                "traffic_relevance_score": 0,
                "traffic_reclass_reasons": ["unusable_for_reclassification"],
                "traffic_evidence_terms": [],
                "traffic_signal_groups": [],
                "traffic_signal_group_count": 0,
                "traffic_term_count": 0,
            }

        # 정상 row는 교통사고 관련성 분류 함수를 적용합니다.
        else:
            result = classify_traffic_relevance(row)

        # 원본 row에 분류 결과를 추가합니다.
        row.update(result)

        # 최종 라벨을 가져옵니다.
        label = row["traffic_label"]

        # 라벨별 카운터를 증가시킵니다.
        label_counter[label] += 1

        # 분류 이유별 카운터를 증가시킵니다.
        for reason in row.get("traffic_reclass_reasons", []):
            reason_counter[reason] += 1

        # evidence term별 카운터를 증가시킵니다.
        for term in row.get("traffic_evidence_terms", []):
            evidence_counter[term] += 1

        # 비교통 도메인 term별 카운터를 증가시킵니다.
        for term in row.get("non_traffic_domain_terms", []):
            non_domain_counter[term] += 1

        # 전체 결과 파일에는 모든 row를 저장합니다.
        write_jsonl(paths["all"], row)

        # confirmed_traffic이면 confirmed 파일에 저장합니다.
        if label == "confirmed_traffic":
            stats.confirmed_traffic += 1
            write_jsonl(paths["confirmed"], row)

        # possible_traffic_review이면 review 파일에 저장합니다.
        elif label == "possible_traffic_review":
            stats.possible_traffic_review += 1
            write_jsonl(paths["review"], row)

        # 그 외 라벨은 non_traffic 파일에 저장합니다.
        else:
            stats.non_traffic += 1
            write_jsonl(paths["non_traffic"], row)

    # 라벨별 개수를 stats에 저장합니다.
    stats.label_counts = dict(label_counter)

    # reason별 개수를 stats에 저장합니다.
    stats.reason_counts = dict(reason_counter)

    # evidence term 상위 100개를 stats에 저장합니다.
    stats.evidence_term_counts = dict(evidence_counter.most_common(100))

    # 비교통 도메인 단어 상위 100개를 stats에 저장합니다.
    stats.non_traffic_domain_counts = dict(non_domain_counter.most_common(100))

    # 실행 결과 리포트를 구성합니다.
    report = {
        "input_file": str(input_path),
        "output_dir": str(out_dir),
        "classification_goal": "교통사고 관련 판례인지 아닌지 1차 확실 구분 - precision-first 기준",
        "labels": {
            "confirmed_traffic": "교통사고 관련성이 충분히 확인되어 바로 다음 단계에 사용할 판례",
            "possible_traffic_review": "교통/차량/보험 단서는 있으나 사고 맥락 확정이 필요한 판례",
            "non_traffic": "교통사고 관련성이 낮은 판례",
        },
        "important_policy": [
            "confirmed_traffic은 다음 단계에서 바로 사용할 데이터이므로 precision을 우선합니다.",
            "도로교통법위반, 음주운전, 면허취소 같은 단어만으로는 confirmed_traffic으로 보내지 않습니다.",
            "confirmed_traffic은 최소 2개 이상의 근거 묶음이 있어야 합니다.",
            "confirmed_traffic은 교통 관련 키워드가 총 3개 이상 잡혀야 합니다.",
            "confirmed_traffic에는 직접 사고 표현 또는 강한 사고 근접 문맥이 반드시 있어야 합니다.",
            "일반 예시 문구의 교통사고 언급은 confirmed 근거로 쓰지 않습니다.",
            "세무/특허/가사 사건종류는 confirmed_traffic으로 바로 보내지 않습니다.",
            "애매한 것은 non_traffic으로 바로 버리지 않고 possible_traffic_review로 보냅니다.",
            "과실비율 분류는 이 다음 단계에서 수행합니다.",
        ],
        "thresholds": {
            "CONFIRMED_SCORE_THRESHOLD": CONFIRMED_SCORE_THRESHOLD,
            "REVIEW_SCORE_THRESHOLD": REVIEW_SCORE_THRESHOLD,
            "NEAR_WINDOW": NEAR_WINDOW,
            "MIN_CONFIRMED_SIGNAL_GROUPS": MIN_CONFIRMED_SIGNAL_GROUPS,
            "MIN_CONFIRMED_TRAFFIC_TERM_COUNT": MIN_CONFIRMED_TRAFFIC_TERM_COUNT,
            "REQUIRE_CORE_ACCIDENT_CONTEXT_FOR_CONFIRMED": REQUIRE_CORE_ACCIDENT_CONTEXT_FOR_CONFIRMED,
            "DISALLOW_CONFIRMED_CASE_CATEGORIES": DISALLOW_CONFIRMED_CASE_CATEGORIES,
            "MAX_RECLASS_BODY_CHARS": MAX_RECLASS_BODY_CHARS,
            "RECLASS_BODY_TAIL_CHARS": RECLASS_BODY_TAIL_CHARS,
        },
        "outputs": {key: str(value) for key, value in paths.items()},
        "stats": asdict(stats),
    }

    # 리포트를 JSON 파일로 저장합니다.
    paths["report"].write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 터미널에 완료 메시지를 출력합니다.
    print("\n교통사고 관련성 재분류 완료")

    # 터미널에 통계를 출력합니다.
    print(json.dumps(report["stats"], ensure_ascii=False, indent=2))

    # 터미널에 저장 위치를 출력합니다.
    print(f"\n저장 위치: {out_dir.resolve()}")

    # 터미널에 생성 파일 목록을 출력합니다.
    for name, path in paths.items():
        print(f"- {name}: {path}")


# ============================================================
# 9. CLI 옵션 처리
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    터미널 실행 옵션을 정의하고 파싱합니다.

    지원 옵션:
    - --input: 입력 JSONL 경로
    - --out-dir: 출력 폴더
    - --fresh: 기존 출력 폴더 삭제 후 재생성
    """

    # argparse 파서를 생성합니다.
    parser = argparse.ArgumentParser(
        description="전처리된 판례를 교통사고 관련/검토/비교통으로 재분류합니다."
    )

    # 입력 파일 경로 옵션입니다.
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT_PATH,
        help=f"입력 JSONL 파일 경로. 기본값: {DEFAULT_INPUT_PATH}",
    )

    # 출력 폴더 경로 옵션입니다.
    parser.add_argument(
        "--out-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"출력 폴더. 기본값: {DEFAULT_OUTPUT_DIR}",
    )

    # 기존 출력 폴더 삭제 여부 옵션입니다.
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="기존 출력 폴더를 삭제하고 새로 생성합니다.",
    )

    # 파싱된 실행 옵션을 반환합니다.
    return parser.parse_args()


# 이 파일을 직접 실행했을 때만 reclassify를 실행합니다.
if __name__ == "__main__":
    reclassify(parse_args())
