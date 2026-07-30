#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
traffic_fault_ratio_stage2_classifier_commented.py

1차 분류 결과를 2차 전 검증한 교통사고 판례 후보를 입력으로 받아,
과실비율/과실상계/책임비율 판단에 사용할 수 있는 판례인지 2차 분류하는 코드입니다.

입력:
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass_verified/01_confirmed_traffic_cases.jsonl

출력:
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio/

생성 파일:
00_fault_ratio_classification_report.json
01_fault_ratio_confirmed_cases.jsonl
02_fault_ratio_possible_review.jsonl
03_traffic_but_no_fault_ratio_cases.jsonl
04_fault_ratio_classified_all.jsonl

실행:
python traffic_fault_ratio_stage2_classifier_commented.py --fresh
"""

from __future__ import annotations

# argparse는 터미널에서 --input, --out-dir, --fresh 옵션을 받기 위해 사용합니다.
import argparse

# json은 JSONL 파일을 읽고 쓰기 위해 사용합니다.
import json

# re는 정규식 기반 비율/문맥 탐지에 사용합니다.
import re

# shutil은 --fresh 옵션 실행 시 기존 출력 폴더 삭제에 사용합니다.
import shutil

# Counter는 라벨, 이유, 키워드 빈도 집계에 사용합니다.
from collections import Counter

# dataclass는 실행 통계를 구조화하기 위해 사용합니다.
from dataclasses import asdict, dataclass, field

# Path는 파일 경로를 안전하게 다루기 위해 사용합니다.
from pathlib import Path

# 타입 힌트는 함수 입력/출력 의미를 명확히 하기 위해 사용합니다.
from typing import Any, Dict, Iterable, List, Tuple


# ============================================================
# 1. 기본 경로
# ============================================================

# 2차 분류의 기본 입력은 reclass 검증/정리 후 확정된 confirmed_traffic 파일입니다.
DEFAULT_INPUT_PATH = "etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass_verified/01_confirmed_traffic_cases.jsonl"

# 2차 분류 결과 저장 폴더입니다.
DEFAULT_OUTPUT_DIR = "etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio"


# ============================================================
# 2. 분류 기준값
# ============================================================

# fault_ratio_confirmed가 되기 위한 최소 점수입니다.
FAULT_RATIO_CONFIRMED_SCORE_THRESHOLD = 10

# fault_ratio_possible_review가 되기 위한 참고 점수입니다.
FAULT_RATIO_REVIEW_SCORE_THRESHOLD = 5

# confirmed가 되기 위한 최소 근거 묶음 수입니다.
MIN_CONFIRMED_SIGNAL_GROUPS = 2

# 과실/책임 단어와 숫자 비율 사이를 몇 글자까지 볼지 정합니다.
NEAR_WINDOW = 100

# 너무 긴 판례 본문을 전부 검색하면 느려질 수 있어 앞부분과 끝부분만 사용합니다.
MAX_RECLASS_BODY_CHARS = 10000

# 긴 본문을 자를 때 끝부분에서 보존할 글자 수입니다.
RECLASS_BODY_TAIL_CHARS = 2500


# ============================================================
# 3. 키워드 사전
# ============================================================

# 과실비율/과실상계 판단을 직접적으로 보여주는 표현입니다.
EXPLICIT_FAULT_RATIO_TERMS = [
    "과실비율",
    "과실 비율",
    "책임비율",
    "책임 비율",
    "과실상계",
    "과실 상계",
    "쌍방과실",
    "쌍방 과실",
    "과실을 참작",
    "과실을 고려",
    "과실 정도",
    "과실의 정도",
]

# 당사자별 과실 판단을 보여줄 수 있는 표현입니다.
# "과실" 단독은 너무 넓기 때문에 당사자 표현과 결합해서 봅니다.
PARTY_FAULT_TERMS = [
    "원고의 과실",
    "피고의 과실",
    "피해자의 과실",
    "가해자의 과실",
    "망인의 과실",
    "운전자의 과실",
    "운전자로서의 과실",
    "피보험자의 과실",
    "상대방의 과실",
    "공동불법행위",
    "공동 불법행위",
]

# 손해배상/보험/구상금/손해액 산정 문맥입니다.
DAMAGE_OR_INSURANCE_CONTEXT_TERMS = [
    "손해배상(자)",
    "손해배상",
    "손해배상책임",
    "손해액",
    "손해액 산정",
    "일실수입",
    "위자료",
    "치료비",
    "향후치료비",
    "개호비",
    "장례비",
    "구상금",
    "보험금",
    "자동차보험",
    "책임보험",
    "종합보험",
    "대인배상",
    "대물배상",
    "운행자책임",
    "보험자대위",
    "구상권",
]

# 교통사고 과실 판단에 자주 등장하는 의무/위반 문맥입니다.
TRAFFIC_DUTY_CONTEXT_TERMS = [
    "전방주시의무",
    "전방 주시의무",
    "안전운전의무",
    "안전 운전의무",
    "주의의무",
    "주의 의무",
    "서행의무",
    "양보의무",
    "진로양보의무",
    "신호위반",
    "중앙선 침범",
    "안전거리",
    "안전거리 확보",
    "차로 변경",
    "진로 변경",
    "끼어들기",
    "무단횡단",
    "횡단보도",
    "전방주시",
    "주시의무",
]

# 과실비율 판단용으로 보기 어려운 문맥입니다.
# 단, 이 단어가 있다고 무조건 제외하지 않고, strong fault ratio context가 없을 때 제외 쪽으로 작동합니다.
NO_FAULT_RATIO_CONTEXT_TERMS = [
    "운전면허취소",
    "운전면허정지",
    "도로교통법위반",
    "음주운전",
    "무면허운전",
    "측정거부",
    "벌점",
    "교통사고처리특례법위반",
    "도주치상",
    "도주차량",
    "위험운전치상",
    "업무상과실치상",
    "업무상과실치사",
    "요양급여",
    "요양불승인",
    "유족급여",
    "장의비",
    "산업재해보상보험법",
    "부당해고",
    "자동차보험진료수가",
    "의료법위반",
    "사기",
]

# 숫자 비율 표현입니다.
# 과실/책임 단어 주변에 이런 표현이 있으면 강한 근거가 됩니다.
RATIO_NUMBER_PATTERNS = [
    r"\d{1,3}\s*%",
    r"\d{1,3}\s*:\s*\d{1,3}",
    r"\d{1,3}\s*대\s*\d{1,3}",
    r"\d{1,2}\s*할",
]


# ============================================================
# 4. 실행 통계 구조
# ============================================================

@dataclass
class FaultRatioStats:
    """
    2차 분류 실행 통계를 저장하기 위한 구조입니다.
    """

    # 입력 row 전체 개수입니다.
    input_rows: int = 0

    # JSON 파싱 실패 등으로 정상 처리하지 못한 row 개수입니다.
    skipped_unusable_rows: int = 0

    # 과실비율 후보로 확정된 row 개수입니다.
    fault_ratio_confirmed: int = 0

    # 과실비율 후보 가능성이 있어 검토가 필요한 row 개수입니다.
    fault_ratio_possible_review: int = 0

    # 교통사고 관련은 맞지만 과실비율용은 아닌 row 개수입니다.
    traffic_but_no_fault_ratio: int = 0

    # 라벨별 개수입니다.
    label_counts: Dict[str, int] = field(default_factory=dict)

    # 분류 이유별 개수입니다.
    reason_counts: Dict[str, int] = field(default_factory=dict)

    # 근거 키워드별 빈도입니다.
    evidence_term_counts: Dict[str, int] = field(default_factory=dict)


# ============================================================
# 5. 파일 경로 준비
# ============================================================

def remove_dir_if_exists(path: Path) -> None:
    """
    지정한 폴더가 있으면 삭제합니다.

    역할:
    - --fresh 옵션으로 새로 실행할 때 기존 결과를 지우기 위해 사용합니다.
    """

    # 폴더가 존재하는 경우에만 삭제합니다.
    if path.exists():
        # 폴더와 내부 파일을 모두 삭제합니다.
        shutil.rmtree(path)


def prepare_output_paths(out_dir: Path, fresh: bool) -> Dict[str, Path]:
    """
    출력 폴더와 결과 파일 경로를 준비합니다.
    """

    # fresh 옵션이 있으면 기존 출력 폴더를 삭제합니다.
    if fresh:
        remove_dir_if_exists(out_dir)

    # 출력 폴더가 없으면 생성합니다.
    out_dir.mkdir(parents=True, exist_ok=True)

    # 이후 코드에서 사용할 파일 경로를 dict로 반환합니다.
    return {
        "report": out_dir / "00_fault_ratio_classification_report.json",
        "confirmed": out_dir / "01_fault_ratio_confirmed_cases.jsonl",
        "review": out_dir / "02_fault_ratio_possible_review.jsonl",
        "no_fault_ratio": out_dir / "03_traffic_but_no_fault_ratio_cases.jsonl",
        "all": out_dir / "04_fault_ratio_classified_all.jsonl",
    }


# ============================================================
# 6. 공통 유틸 함수
# ============================================================

def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    """
    JSONL 파일을 한 줄씩 읽어서 dict로 반환합니다.
    """

    # UTF-8로 입력 파일을 엽니다.
    with path.open("r", encoding="utf-8") as file:
        # line_no는 오류 추적용 원본 줄 번호입니다.
        for line_no, line in enumerate(file, 1):
            # 줄 앞뒤 공백과 개행 문자를 제거합니다.
            line = line.strip()

            # 빈 줄은 건너뜁니다.
            if not line:
                continue

            try:
                # JSON 문자열을 dict로 변환합니다.
                row = json.loads(line)

                # 입력 줄 번호를 추적용으로 저장합니다.
                row["_fault_ratio_input_line_no"] = line_no

                # 정상 row를 반환합니다.
                yield row

            except json.JSONDecodeError:
                # JSON 파싱 실패 시에도 전체 실행이 멈추지 않도록 에러 row를 반환합니다.
                yield {
                    "_fault_ratio_input_line_no": line_no,
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
    연속 공백을 하나의 공백으로 정리합니다.
    """

    # None이면 빈 문자열로 처리합니다.
    if text is None:
        return ""

    # split/join 방식으로 빠르게 공백을 정리합니다.
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
    """

    # None이면 빈 문자열을 반환합니다.
    if text is None:
        return ""

    # 문자열로 변환합니다.
    value = str(text)

    # 기준 길이 이하이면 그대로 반환합니다.
    if len(value) <= MAX_RECLASS_BODY_CHARS:
        return value

    # 앞부분에서 보존할 길이를 계산합니다.
    head_len = MAX_RECLASS_BODY_CHARS - RECLASS_BODY_TAIL_CHARS

    # 앞부분을 자릅니다.
    head = value[:head_len]

    # 끝부분을 자릅니다.
    tail = value[-RECLASS_BODY_TAIL_CHARS:]

    # 중간 생략 표시를 넣어 반환합니다.
    return head + "\n[FAULT_RATIO_RECLASS_TEXT_MIDDLE_OMITTED]\n" + tail


def build_fault_ratio_text(row: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    2차 분류에 사용할 텍스트를 만듭니다.

    반환:
    - title_text: 사건명/사건번호/법원명 등 메타 텍스트
    - body_text: 판시사항/판결요지/본문/참조조문
    - all_text: title_text + body_text
    """

    # 사건명/사건번호/법원명/사건종류 등 짧은 메타 정보를 모읍니다.
    title_parts = [
        first_value(row, "사건명", "case_name"),
        first_value(row, "사건번호", "case_number"),
        first_value(row, "법원명", "court_name"),
        first_value(row, "사건종류명", "case_category"),
        first_value(row, "judgment_type"),
    ]

    # main_text를 우선 사용하고, 없으면 full_text를 사용합니다.
    raw_main_body = first_value(row, "판례내용", "main_text", "full_text")

    # 너무 긴 본문은 앞부분과 끝부분만 남깁니다.
    main_body = trim_reclass_body_text(raw_main_body)

    # 본문 판단에 사용할 필드를 모읍니다.
    body_parts = [
        first_value(row, "판시사항", "holding"),
        first_value(row, "판결요지", "summary"),
        first_value(row, "주문"),
        first_value(row, "이유"),
        first_value(row, "과실비율"),
        main_body,
        first_value(row, "참조조문", "referenced_laws"),
        first_value(row, "참조판례", "referenced_cases"),
    ]

    # 제목/메타 텍스트를 만듭니다.
    title_text = normalize_space(" ".join(str(x) for x in title_parts if x))

    # 본문 텍스트를 만듭니다.
    body_text = " ".join(str(x) for x in body_parts if x)

    # 전체 판단 텍스트를 만듭니다.
    all_text = title_text + " " + body_text

    # 세 가지 텍스트를 반환합니다.
    return title_text, body_text, all_text


def find_terms(text: str, terms: List[str]) -> List[str]:
    """
    text 안에 포함된 키워드를 찾습니다.
    """

    # 결과 리스트입니다.
    found = []

    # 대소문자 영향을 줄이기 위해 소문자로 변환합니다.
    lower_text = text.lower()

    # 키워드 목록을 하나씩 확인합니다.
    for term in terms:
        # 키워드가 포함되어 있으면 결과에 추가합니다.
        if term.lower() in lower_text:
            found.append(term)

    # 중복 제거 후 정렬하여 반환합니다.
    return sorted(set(found))


def regex_search(pattern: str, text: str) -> bool:
    """
    정규식 패턴이 text 안에 있는지 확인합니다.
    """

    # re.I는 대소문자 무시, re.S는 줄바꿈 포함 검색입니다.
    return re.search(pattern, text, flags=re.I | re.S) is not None


def collect_regex_examples(patterns: List[str], text: str, max_examples: int = 5) -> List[str]:
    """
    정규식 패턴에 걸린 문구 일부를 예시로 추출합니다.
    """

    # 예시 문구 리스트입니다.
    examples = []

    # 패턴을 하나씩 검사합니다.
    for pattern in patterns:
        # 패턴에 맞는 모든 구간을 찾습니다.
        for match in re.finditer(pattern, text, flags=re.I | re.S):
            # 매칭된 문구를 공백 정리합니다.
            snippet = normalize_space(match.group(0))

            # 비어 있지 않고 중복이 아니면 저장합니다.
            if snippet and snippet not in examples:
                examples.append(snippet[:200])

            # 최대 예시 개수에 도달하면 반환합니다.
            if len(examples) >= max_examples:
                return examples

    # 수집된 예시를 반환합니다.
    return examples


def find_fault_ratio_number_examples(text: str) -> List[str]:
    """
    과실/책임/비율 단어 주변에 숫자 비율 표현이 있는지 찾습니다.
    """

    # 숫자 비율 표현을 하나의 OR 패턴으로 만듭니다.
    ratio_pattern = "|".join(f"(?:{p})" for p in RATIO_NUMBER_PATTERNS)

    # 과실/책임/상계 단어 뒤쪽에 숫자 비율이 나오는 패턴입니다.
    pattern_1 = rf"(과실|책임|비율|상계).{{0,{NEAR_WINDOW}}}({ratio_pattern})"

    # 숫자 비율 뒤쪽에 과실/책임/상계 단어가 나오는 패턴입니다.
    pattern_2 = rf"({ratio_pattern}).{{0,{NEAR_WINDOW}}}(과실|책임|비율|상계)"

    # 두 방향의 예시를 추출합니다.
    return collect_regex_examples([pattern_1, pattern_2], text)


# ============================================================
# 7. 과실비율 관련성 판정
# ============================================================

def classify_fault_ratio_relevance(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    교통사고 판례 한 건이 과실비율 판단용으로 적합한지 분류합니다.

    역할:
    - 과실비율/과실상계/책임비율 표현을 찾습니다.
    - 손해배상/보험/구상금/손해액 문맥을 찾습니다.
    - 과실/책임 단어 주변에 숫자 비율이 있는지 찾습니다.
    - confirmed / possible / no_fault_ratio 라벨을 결정합니다.
    """

    # row에서 2차 분류용 텍스트를 생성합니다.
    title_text, body_text, all_text = build_fault_ratio_text(row)

    # 과실비율/과실상계 직접 표현을 찾습니다.
    explicit_fault_terms = find_terms(all_text, EXPLICIT_FAULT_RATIO_TERMS)

    # 당사자별 과실 판단 표현을 찾습니다.
    party_fault_terms = find_terms(all_text, PARTY_FAULT_TERMS)

    # 손해배상/보험/구상금/손해액 문맥을 찾습니다.
    damage_terms = find_terms(all_text, DAMAGE_OR_INSURANCE_CONTEXT_TERMS)

    # 교통사고 책임 판단에 쓰이는 의무/위반 문맥을 찾습니다.
    duty_terms = find_terms(all_text, TRAFFIC_DUTY_CONTEXT_TERMS)

    # 과실비율용으로 보기 어려운 문맥을 찾습니다.
    no_fault_terms = find_terms(all_text, NO_FAULT_RATIO_CONTEXT_TERMS)

    # 과실/책임 단어 주변에 숫자 비율 표현이 있는지 찾습니다.
    ratio_number_examples = find_fault_ratio_number_examples(all_text)

    # 전처리 단계에서 high confidence로 추출한 과실비율 필드입니다.
    preprocessed_fault_ratio = first_value(row, "과실비율", "fault_ratio")

    # 점수 초기값입니다.
    score = 0

    # 분류 이유 리스트입니다.
    reasons = []

    # 사람이 검토할 근거 표현 리스트입니다.
    evidence_terms = []

    # confirmed 판단용 근거 묶음 리스트입니다.
    signal_groups = []

    # ------------------------------------------------------------
    # 1. 과실비율/과실상계 직접 표현
    # ------------------------------------------------------------

    # 직접 표현이 있으면 강한 근거입니다.
    if explicit_fault_terms:
        score += 7
        reasons.append("explicit_fault_ratio_terms")
        evidence_terms.extend(explicit_fault_terms)
        signal_groups.append("explicit_fault_ratio_expression")

    # 전처리에서 이미 확인한 과실비율은 강한 보조 신호로 사용합니다.
    if preprocessed_fault_ratio:
        score += 6
        reasons.append("preprocessed_fault_ratio_field")
        evidence_terms.append(preprocessed_fault_ratio)
        signal_groups.append("preprocessed_fault_ratio")

    # ------------------------------------------------------------
    # 2. 숫자 비율 + 과실/책임 근접 문맥
    # ------------------------------------------------------------

    # 과실/책임 단어 근처에 30%, 70:30 같은 표현이 있으면 매우 강한 근거입니다.
    if ratio_number_examples:
        score += 7
        reasons.append("numerical_fault_apportionment_near_fault_terms")
        evidence_terms.extend(ratio_number_examples)
        signal_groups.append("numerical_fault_apportionment")

    # ------------------------------------------------------------
    # 3. 당사자별 과실 판단
    # ------------------------------------------------------------

    # 원고의 과실, 피고의 과실 등은 과실 판단 근거입니다.
    if party_fault_terms:
        score += min(5, 2 + len(party_fault_terms))
        reasons.append("party_fault_judgment_terms")
        evidence_terms.extend(party_fault_terms)
        signal_groups.append("party_fault_judgment")

    # ------------------------------------------------------------
    # 4. 손해배상/보험/구상금/손해액 문맥
    # ------------------------------------------------------------

    # 과실비율 판단은 보통 손해배상/보험/구상금/손해액 산정과 연결됩니다.
    if damage_terms:
        score += min(5, 2 + len(damage_terms))
        reasons.append("damage_or_insurance_context_terms")
        evidence_terms.extend(damage_terms)
        signal_groups.append("damage_or_insurance_context")

    # ------------------------------------------------------------
    # 5. 교통사고 의무/위반 문맥
    # ------------------------------------------------------------

    # 전방주시의무, 신호위반 등은 과실 판단의 보조 근거입니다.
    if duty_terms:
        score += min(4, len(duty_terms))
        reasons.append("traffic_duty_context_terms")
        evidence_terms.extend(duty_terms)
        signal_groups.append("traffic_duty_context")

    # ------------------------------------------------------------
    # 6. 과실비율용으로 약한 문맥
    # ------------------------------------------------------------

    # 형사/면허/산재/의료법/사기 문맥은 no_fault_ratio 쪽 신호입니다.
    if no_fault_terms:
        reasons.append("possible_no_fault_ratio_context_terms")
        evidence_terms.extend(no_fault_terms)

    # ------------------------------------------------------------
    # 7. 근거 묶음 계산
    # ------------------------------------------------------------

    # 근거 묶음은 중복 제거 후 정렬합니다.
    signal_groups = sorted(set(signal_groups))

    # 근거 묶음 개수를 계산합니다.
    signal_group_count = len(signal_groups)

    # 과실비율 핵심 문맥이 있는지 확인합니다.
    has_core_fault_ratio_context = bool(
        explicit_fault_terms
        or preprocessed_fault_ratio
        or ratio_number_examples
        or (party_fault_terms and damage_terms)
    )

    # 손해배상/보험/손해액 문맥이 있는지 확인합니다.
    has_damage_or_insurance_context = bool(damage_terms)

    # confirmed 기준을 만족하는지 확인합니다.
    enough_confirmed_signals = signal_group_count >= MIN_CONFIRMED_SIGNAL_GROUPS

    # no_fault 문맥이 강한데 과실비율 핵심 문맥이 없으면 confirmed를 막습니다.
    no_fault_context_without_core = bool(no_fault_terms and not has_core_fault_ratio_context)

    # ------------------------------------------------------------
    # 8. 최종 라벨 결정
    # ------------------------------------------------------------

    # 과실비율 confirmed는 엄격하게 판단합니다.
    if (
        score >= FAULT_RATIO_CONFIRMED_SCORE_THRESHOLD
        and enough_confirmed_signals
        and has_core_fault_ratio_context
        and has_damage_or_insurance_context
        and not no_fault_context_without_core
    ):
        label = "fault_ratio_confirmed"

    # confirmed는 아니지만 과실/책임/손해배상 단서가 있으면 review로 보냅니다.
    elif (
        score >= FAULT_RATIO_REVIEW_SCORE_THRESHOLD
        or explicit_fault_terms
        or party_fault_terms
        or (damage_terms and duty_terms)
        or ratio_number_examples
    ):
        label = "fault_ratio_possible_review"

    # 교통사고 관련은 맞지만 과실비율 판단용 근거가 부족하면 제외 라벨로 보냅니다.
    else:
        label = "traffic_but_no_fault_ratio"

    # 근거 표현을 중복 제거하고 정리합니다.
    evidence_terms = sorted(set(normalize_space(x) for x in evidence_terms if normalize_space(x)))

    # 최종 결과와 검토용 필드를 반환합니다.
    return {
        "fault_ratio_label": label,
        "fault_ratio_score": score,
        "fault_ratio_reclass_reasons": sorted(set(reasons)),
        "fault_ratio_evidence_terms": evidence_terms,
        "fault_ratio_signal_groups": signal_groups,
        "fault_ratio_signal_group_count": signal_group_count,
        "has_core_fault_ratio_context": has_core_fault_ratio_context,
        "has_damage_or_insurance_context": has_damage_or_insurance_context,
        "no_fault_context_without_core": no_fault_context_without_core,
        "fault_ratio_explicit_terms": explicit_fault_terms,
        "fault_ratio_party_fault_terms": party_fault_terms,
        "fault_ratio_damage_terms": damage_terms,
        "fault_ratio_duty_terms": duty_terms,
        "fault_ratio_no_fault_terms": no_fault_terms,
        "fault_ratio_number_examples": ratio_number_examples,
        "preprocessed_fault_ratio": preprocessed_fault_ratio,
        "min_confirmed_signal_groups": MIN_CONFIRMED_SIGNAL_GROUPS,
    }


# ============================================================
# 8. 메인 실행
# ============================================================

def classify_file(args: argparse.Namespace) -> None:
    """
    입력 JSONL 전체에 대해 2차 과실비율 후보 분류를 실행합니다.
    """

    # 입력 파일 경로를 Path 객체로 변환합니다.
    input_path = Path(args.input)

    # 출력 폴더 경로를 Path 객체로 변환합니다.
    out_dir = Path(args.out_dir)

    # 입력 파일이 없으면 오류를 발생시킵니다.
    if not input_path.exists():
        raise FileNotFoundError(f"input file not found: {input_path}")

    # 출력 경로들을 준비합니다.
    paths = prepare_output_paths(out_dir, fresh=args.fresh)

    # 실행 통계 객체를 생성합니다.
    stats = FaultRatioStats()

    # 라벨별 개수 카운터입니다.
    label_counter = Counter()

    # 분류 이유별 개수 카운터입니다.
    reason_counter = Counter()

    # 근거 키워드별 빈도 카운터입니다.
    evidence_counter = Counter()

    # 입력 JSONL을 한 줄씩 처리합니다.
    for row in read_jsonl(input_path):
        # 입력 row 수를 증가시킵니다.
        stats.input_rows += 1

        # JSON 파싱 실패 row는 전체 파일에만 남깁니다.
        if row.get("_json_decode_error"):
            row["fault_ratio_label"] = "unusable_input_error"
            row["fault_ratio_reclass_reasons"] = ["json_decode_error"]
            stats.skipped_unusable_rows += 1
            write_jsonl(paths["all"], row)
            continue

        # 정상 row는 2차 분류 함수를 적용합니다.
        result = classify_fault_ratio_relevance(row)

        # 원본 row에 2차 분류 결과를 추가합니다.
        row.update(result)

        # 최종 라벨을 가져옵니다.
        label = row["fault_ratio_label"]

        # 라벨 카운터를 증가시킵니다.
        label_counter[label] += 1

        # reason 카운터를 증가시킵니다.
        for reason in row.get("fault_ratio_reclass_reasons", []) or []:
            reason_counter[reason] += 1

        # evidence term 카운터를 증가시킵니다.
        for term in row.get("fault_ratio_evidence_terms", []) or []:
            evidence_counter[term] += 1

        # 전체 추적용 파일에 저장합니다.
        write_jsonl(paths["all"], row)

        # confirmed 라벨이면 confirmed 파일에 저장합니다.
        if label == "fault_ratio_confirmed":
            stats.fault_ratio_confirmed += 1
            write_jsonl(paths["confirmed"], row)

        # possible review 라벨이면 review 파일에 저장합니다.
        elif label == "fault_ratio_possible_review":
            stats.fault_ratio_possible_review += 1
            write_jsonl(paths["review"], row)

        # 나머지는 traffic_but_no_fault_ratio 파일에 저장합니다.
        else:
            stats.traffic_but_no_fault_ratio += 1
            write_jsonl(paths["no_fault_ratio"], row)

    # 통계 객체에 라벨별 개수를 저장합니다.
    stats.label_counts = dict(label_counter)

    # 통계 객체에 reason별 개수를 저장합니다.
    stats.reason_counts = dict(reason_counter)

    # 통계 객체에 evidence term 상위 100개를 저장합니다.
    stats.evidence_term_counts = dict(evidence_counter.most_common(100))

    # report JSON을 구성합니다.
    report = {
        "input_file": str(input_path),
        "output_dir": str(out_dir),
        "classification_goal": "교통사고 confirmed 판례 중 과실비율/과실상계 판단용 판례 선별",
        "labels": {
            "fault_ratio_confirmed": "과실비율/과실상계/책임비율 판단에 바로 사용할 수 있는 판례",
            "fault_ratio_possible_review": "과실/책임/손해배상 단서는 있으나 확정이 필요한 판례",
            "traffic_but_no_fault_ratio": "교통사고 관련은 맞지만 과실비율 판단용은 아닌 판례",
        },
        "important_policy": [
            "과실이라는 단어 하나만으로 confirmed 처리하지 않습니다.",
            "업무상과실치상/형사사건의 과실과 민사 과실비율 판단을 구분합니다.",
            "fault_ratio_confirmed에는 과실비율 핵심 문맥과 손해배상/보험 문맥이 함께 있어야 합니다.",
            "애매한 것은 traffic_but_no_fault_ratio로 바로 버리지 않고 fault_ratio_possible_review로 보냅니다.",
        ],
        "thresholds": {
            "FAULT_RATIO_CONFIRMED_SCORE_THRESHOLD": FAULT_RATIO_CONFIRMED_SCORE_THRESHOLD,
            "FAULT_RATIO_REVIEW_SCORE_THRESHOLD": FAULT_RATIO_REVIEW_SCORE_THRESHOLD,
            "MIN_CONFIRMED_SIGNAL_GROUPS": MIN_CONFIRMED_SIGNAL_GROUPS,
            "NEAR_WINDOW": NEAR_WINDOW,
            "MAX_RECLASS_BODY_CHARS": MAX_RECLASS_BODY_CHARS,
            "RECLASS_BODY_TAIL_CHARS": RECLASS_BODY_TAIL_CHARS,
        },
        "outputs": {key: str(value) for key, value in paths.items()},
        "stats": asdict(stats),
    }

    # report JSON을 저장합니다.
    paths["report"].write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 터미널에 완료 메시지를 출력합니다.
    print("\n과실비율 2차 분류 완료")

    # 터미널에 통계를 출력합니다.
    print(json.dumps(report["stats"], ensure_ascii=False, indent=2))

    # 저장 위치를 출력합니다.
    print(f"\n저장 위치: {out_dir.resolve()}")

    # 생성 파일 목록을 출력합니다.
    for name, path in paths.items():
        print(f"- {name}: {path}")


# ============================================================
# 9. CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    터미널 실행 옵션을 정의합니다.
    """

    # ArgumentParser 객체를 만듭니다.
    parser = argparse.ArgumentParser(
        description="1차 confirmed_traffic 판례를 과실비율 후보/검토/비후보로 2차 분류합니다."
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

    # 파싱한 옵션을 반환합니다.
    return parser.parse_args()


# 이 파일을 직접 실행했을 때만 classify_file을 실행합니다.
if __name__ == "__main__":
    classify_file(parse_args())
