#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
preprocess_traffic_precedents_final_all_raw_maintext_clean.py

교통사고 판례 후보 raw 파일을 전처리하고,
사건명+사건번호+법원명+선고일자가 같은 중복 후보 중
본문 유사도 0.90 이상인 것은 대표 1개만 남기는 코드입니다.

기본 입력:
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_api/all_prec_candidates_raw.jsonl

주의:
이 코드는 traffic_cases_raw + skipped_non_traffic을 합친 test.jsonl이 아니라,
수집 단계에서 split 없이 저장한 all_prec_candidates_raw.jsonl을 기본 입력으로 사용합니다.

기본 출력:
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_preprocessed/

생성 파일:
00_preprocess_report.json
01_invalid_detail_cases.jsonl
02_all_cases_cleaned.jsonl
03_duplicate_candidate_groups.jsonl
04_duplicate_removed_cases.jsonl
05_all_cases_deduped.jsonl
06_all_cases_quality_checked.jsonl

실행:
python preprocess_traffic_precedents_final_all_raw_maintext_clean.py --fresh
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import html
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


# ============================================================
# 기본 경로 / 기준값
# ============================================================

# 현재 프로젝트 구조 기준 입력 파일
DEFAULT_INPUT_PATH = "etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_api/all_prec_candidates_raw.jsonl"

# 전처리 결과 저장 폴더
DEFAULT_OUTPUT_DIR = "etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_preprocessed"

# 본문 길이 품질 기준
MAIN_TEXT_MIN_LENGTH = 300

# full_text 길이 품질 기준
FULL_TEXT_MIN_LENGTH = 500

# 중복 판단 유사도 기준
# 같은 사건명+사건번호+법원명+선고일자 그룹 안에서
# 판시사항+판결요지+판례내용 유사도가 0.90 이상이면 같은 판례 중복으로 봅니다.
DUPLICATE_SIMILARITY_THRESHOLD = 0.90

# 표/숫자 깨짐 artifact 판단 기준입니다.
# 국가법령정보센터 API에서 표가 일반 텍스트로 납작하게 들어오면
# 날짜, 금액, 비율, 호프만계수 등이 셀 구분 없이 붙어서 긴 숫자 덩어리처럼 보일 수 있습니다.
NUMERIC_DENSE_DIGIT_RATIO = 0.35
NUMERIC_DENSE_MIN_LENGTH = 120


# ============================================================
# 실행 통계
# ============================================================

@dataclass
class PreprocessStats:
    input_rows: int = 0
    valid_detail_rows: int = 0
    invalid_detail_rows: int = 0

    cleaned_rows: int = 0

    same_case_key_duplicate_groups: int = 0
    same_case_key_duplicate_rows: int = 0
    duplicate_candidate_groups_written: int = 0
    duplicate_removed_rows: int = 0
    duplicate_kept_representatives: int = 0
    deduped_rows: int = 0

    quality_checked_rows: int = 0
    usable_for_reclassification: int = 0
    unusable_for_reclassification: int = 0

    source_bucket_counts: Dict[str, int] = field(default_factory=dict)
    invalid_reason_counts: Dict[str, int] = field(default_factory=dict)
    duplicate_status_counts: Dict[str, int] = field(default_factory=dict)
    quality_flag_counts: Dict[str, int] = field(default_factory=dict)
    missing_field_counts: Dict[str, int] = field(default_factory=dict)


# ============================================================
# 파일 경로 준비
# ============================================================

def remove_dir_if_exists(path: Path) -> None:
    """
    --fresh 옵션이 있을 때 기존 출력 폴더를 삭제합니다.
    """

    if path.exists():
        shutil.rmtree(path)


def prepare_output_paths(out_dir: Path, fresh: bool) -> Dict[str, Path]:
    """
    전처리 결과 파일 저장 위치를 한 곳에서 지정합니다.

    traffic_precedents_output/traffic_prec_preprocessed 폴더가 없으면 자동 생성합니다.
    """

    if fresh:
        remove_dir_if_exists(out_dir)

    out_dir.mkdir(parents=True, exist_ok=True)

    return {
        "report": out_dir / "00_preprocess_report.json",
        "invalid": out_dir / "01_invalid_detail_cases.jsonl",
        "cleaned": out_dir / "02_all_cases_cleaned.jsonl",
        "duplicate_candidates": out_dir / "03_duplicate_candidate_groups.jsonl",
        "duplicate_removed": out_dir / "04_duplicate_removed_cases.jsonl",
        "deduped": out_dir / "05_all_cases_deduped.jsonl",
        "quality": out_dir / "06_all_cases_quality_checked.jsonl",
    }


# ============================================================
# 공통 유틸
# ============================================================

def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    """
    JSONL 파일을 한 줄씩 읽습니다.
    """

    with path.open("r", encoding="utf-8") as file:
        for line_no, line in enumerate(file, 1):
            line = line.strip()

            if not line:
                continue

            try:
                row = json.loads(line)
                row["_input_line_no"] = line_no
                yield row

            except json.JSONDecodeError as error:
                yield {
                    "_input_line_no": line_no,
                    "_json_decode_error": repr(error),
                    "_raw_line_preview": line[:500],
                }


def write_jsonl(path: Path, row: Dict[str, Any]) -> None:
    """
    dict 한 건을 JSONL로 append 저장합니다.
    """

    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def basic_clean_text(value: Any) -> str:
    """
    가장 기본적인 텍스트 정리 함수입니다.

    이 함수는 표/숫자 덩어리를 제거하지 않습니다.
    먼저 API 응답을 일반 텍스트 형태로 정리하는 역할만 합니다.

    처리 내용:
    - None -> 빈 문자열
    - HTML 엔티티 해제
    - HTML 태그 제거
    - 유니코드 정규화
    - 제로폭 문자/깨진 문자 제거
    - 연속 공백 정리
    """

    if value is None:
        return ""

    text = str(value)

    # HTML 엔티티를 실제 문자로 변환합니다.
    # 예: &amp; -> &, &lt; -> <
    text = html.unescape(text)

    # 유니코드 정규화입니다.
    # 전각 숫자/문자, 특수 기호를 최대한 일반 형태로 맞춥니다.
    text = unicodedata.normalize("NFKC", text)

    # <br>, <br/>, <br />는 공백으로 바꿉니다.
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)

    # 나머지 HTML 태그를 제거합니다.
    text = re.sub(r"<[^>]+>", " ", text)

    # 눈에 보이지 않는 제어 문자, 제로폭 문자, BOM 등을 제거합니다.
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]", "", text)

    # 깨진 문자 replacement character 제거
    text = text.replace("\ufffd", "")

    # 특수 공백을 일반 공백으로 변환
    text = text.replace("\u00a0", " ")

    # 연속 공백 정리
    text = re.sub(r"\s+", " ", text).strip()

    return text


def remove_suspicious_question_marks(text: str) -> str:
    """
    표가 깨지면서 들어온 물음표(?) artifact를 제거합니다.

    중요한 점:
    - 모든 ?를 무조건 지우지 않습니다.
    - 표 머리글이나 숫자 근처에서 구분자처럼 들어온 ?만 제거합니다.
    - 일반 문장부호일 수 있는 ?는 최대한 남깁니다.

    예:
    - '산정 ?기간초일기간 말일...' -> '산정 기간초일기간 말일...'
    - '326,000? 통상임금...' -> '326,000 통상임금...'
    """

    if not text:
        return ""

    table_words = (
        "기간", "초일", "말일", "노임", "노임단가", "일수", "월소득", "상실률",
        "호프만", "일실수입", "손해액", "보험급여", "지급액", "합계",
        "통상임금", "근무일수", "최저임금", "요양급여", "휴업급여", "장해급여"
    )
    table_word_pattern = "|".join(table_words)

    # 표 머리글 앞에 붙은 ? 제거
    text = re.sub(rf"\s+\?(?=\s*(?:{table_word_pattern}))", " ", text)
    text = re.sub(rf"(?<=[가-힣])\?(?=\s*(?:{table_word_pattern}))", " ", text)

    # 숫자 뒤에 붙은 ? 제거
    text = re.sub(r"(?<=[0-9,])\?\s*(?=[가-힣A-Za-z])", " ", text)

    # 단독 구분자처럼 남은 ? 제거
    text = re.sub(r"\s+\?\s+", " ", text)

    return re.sub(r"\s+", " ", text).strip()


def count_numeric_dense_tokens(text: str) -> int:
    """
    숫자/쉼표/소수점/별표/퍼센트가 길게 이어진 덩어리 개수를 셉니다.

    이런 덩어리가 많으면 판례 원문 안의 표가 텍스트로 깨졌을 가능성이 높습니다.
    """

    if not text:
        return 0

    return len(re.findall(r"[0-9][0-9,.\-*%]{8,}", text))


def numeric_digit_ratio(text: str) -> float:
    """
    텍스트에서 숫자가 차지하는 비율을 계산합니다.
    숫자 비율이 지나치게 높으면 계산표가 한 줄로 붙은 artifact일 가능성이 있습니다.
    """

    compact = re.sub(r"\s+", "", text or "")

    if not compact:
        return 0.0

    digits = sum(1 for ch in compact if ch.isdigit())
    return digits / len(compact)


def has_table_header_words(text: str) -> bool:
    """
    손해액/일실수입/호프만계수 등 표에서 자주 나오는 머리글이 있는지 확인합니다.
    """

    table_headers = [
        "기간초일", "기간 말일", "노임단가", "월소득", "상실률",
        "호프만", "일실수입", "치료기간 중 손해액", "치료종결 후 손해액",
        "보험급여지급액", "구상 가능 금액", "요양급여", "휴업급여", "장해급여",
        "통상임금", "근무일수", "일용노임"
    ]

    compact = re.sub(r"\s+", "", text or "")
    return any(header.replace(" ", "") in compact for header in table_headers)


def detect_table_artifact(text: str) -> Dict[str, Any]:
    """
    표가 깨져서 들어온 흔적을 탐지합니다.

    이 함수는 데이터를 삭제하지 않습니다.
    나중에 quality_flags에 경고를 붙이기 위한 근거를 만듭니다.
    """

    text = text or ""

    digit_ratio = numeric_digit_ratio(text)
    dense_count = count_numeric_dense_tokens(text)
    question_count = text.count("?")
    has_headers = has_table_header_words(text)

    numeric_dense = (
        len(text) >= NUMERIC_DENSE_MIN_LENGTH
        and (
            digit_ratio >= NUMERIC_DENSE_DIGIT_RATIO
            or dense_count >= 8
        )
    )

    table_artifact = has_headers and (numeric_dense or dense_count >= 3 or question_count >= 1)

    return {
        "table_artifact_detected": bool(table_artifact),
        "numeric_dense_text_detected": bool(numeric_dense),
        "question_mark_count": question_count,
        "numeric_dense_token_count": dense_count,
        "digit_ratio": round(digit_ratio, 4),
        "has_table_header_words": bool(has_headers),
    }


def reduce_table_artifacts(text: str) -> str:
    """
    깨진 계산표/숫자표 구간을 줄입니다.

    중요한 점:
    - 판례 row 자체를 삭제하지 않습니다.
    - main_text 컬럼 안에서 깨진 표 구간만 [계산표_생략], [숫자표_생략]으로 줄입니다.
    - 원본은 입력 파일 all_prec_candidates_raw.jsonl에 그대로 남아 있습니다.
    """

    text = remove_suspicious_question_marks(basic_clean_text(text))

    if not text:
        return ""

    table_start_pattern = (
        r"(?:산정\s*)?"
        r"(?:기간초일|기간\s*초일|노임단가|월소득|상실률|호프만|일실수입|"
        r"보험급여지급액|구상\s*가능\s*금액|요양급여|휴업급여|장해급여)"
    )

    # 『 ... 』 안에 계산표가 들어간 경우, 그 인용 구간을 계산표 생략으로 줄입니다.
    text = re.sub(
        rf"『([^』]{{0,80}}{table_start_pattern}[^』]{{80,8000}})』",
        " [계산표_생략] ",
        text,
        flags=re.I,
    )

    # 셀 구분 없이 붙은 긴 숫자 덩어리를 줄입니다.
    text = re.sub(
        r"(?:[0-9][0-9,.\-*%]{6,}\s*){6,}",
        " [숫자표_생략] ",
        text,
    )

    # 대표적인 손해액 산정표 머리글이 통째로 붙은 경우를 줄입니다.
    text = re.sub(
        r"기간초일기간말일노임단가일수월소득상실률m1호프만1m2호프만2m1-2적용호프만기간일실수입",
        " [손해액_산정표_생략] ",
        text,
        flags=re.I,
    )

    # 생략 토큰이 반복되면 하나로 줄입니다.
    text = re.sub(
        r"(?:\s*\[(?:계산표|숫자표|손해액_산정표)_생략\]\s*){2,}",
        " [계산표_생략] ",
        text,
    )

    return re.sub(r"\s+", " ", text).strip()


def clean_text(value: Any) -> str:
    """
    최종 저장용 클린 텍스트를 만듭니다.

    여기서 만든 결과가 그대로 표준 컬럼에 들어갑니다.
    즉, 별도의 main_text_for_classification 컬럼을 만들지 않고,
    main_text 자체를 클린 텍스트로 사용합니다.

    처리:
    - 기본 클리닝
    - 의심스러운 ? artifact 제거
    - 깨진 계산표/숫자표 구간 축약
    """

    return reduce_table_artifacts(value)


def normalize_date(value: Any) -> Tuple[str, bool]:
    """
    선고일자를 YYYY-MM-DD로 정규화합니다.
    """

    text = clean_text(value)

    if not text:
        return "", False

    digits = re.sub(r"\D", "", text)

    if len(digits) == 8:
        try:
            dt = datetime.strptime(digits, "%Y%m%d")
            return dt.strftime("%Y-%m-%d"), True
        except ValueError:
            return text, False

    return text, False


def ensure_list(value: Any) -> List[Any]:
    """
    리스트가 아닌 값을 리스트로 바꿉니다.
    """

    if value is None or value == "":
        return []

    if isinstance(value, list):
        return value

    return [value]


def unique_keep_order(values: Iterable[Any]) -> List[Any]:
    """
    순서를 유지하면서 중복 제거합니다.
    """

    seen = set()
    result = []

    for value in values:
        if value is None or value == "":
            continue

        key = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value)

        if key not in seen:
            seen.add(key)
            result.append(value)

    return result


def get_raw_case_id(row: Dict[str, Any]) -> str:
    """
    수집 과정의 내부 ID를 가져옵니다.
    """

    for key in ("_case_id", "_merge_case_id", "판례일련번호", "판례정보일련번호", "ID", "id"):
        value = row.get(key)

        if value:
            return str(value).strip()

    return ""


def get_official_case_id(row: Dict[str, Any]) -> str:
    """
    정상 판례의 공식 ID를 가져옵니다.

    우선순위:
    1. 판례정보일련번호
    2. 판례일련번호
    """

    for key in ("판례정보일련번호", "판례일련번호"):
        value = row.get(key)

        if value:
            return str(value).strip()

    return ""


def extract_matched_keywords(row: Dict[str, Any]) -> List[str]:
    """
    어떤 검색 키워드로 잡혔는지 추출합니다.
    """

    keywords = []

    keywords.extend(ensure_list(row.get("_matched_keywords")))

    list_row = row.get("_list_row", {}) or {}
    if list_row.get("_matched_keyword"):
        keywords.append(list_row.get("_matched_keyword"))

    return unique_keep_order(clean_text(keyword) for keyword in keywords)


def extract_raw_topic_labels(row: Dict[str, Any]) -> List[str]:
    """
    기존 수집 코드가 붙인 topic_labels를 참고용으로 추출합니다.
    """

    return unique_keep_order(clean_text(label) for label in ensure_list(row.get("topic_labels")))


def build_source_reference(row: Dict[str, Any], case_id: str, raw_case_id: str) -> str:
    """
    source_reference가 없으면 case_id로 API reference를 만듭니다.
    """

    source_reference = clean_text(row.get("source_reference"))

    if source_reference:
        return source_reference

    reference_id = case_id or raw_case_id

    if not reference_id:
        return ""

    return f"https://www.law.go.kr/DRF/lawService.do?target=prec&ID={reference_id}&type=XML"


# ============================================================
# invalid / cleaned 생성
# ============================================================

def is_valid_detail_row(row: Dict[str, Any]) -> bool:
    """
    정상 상세 판례인지 판단합니다.

    정상 조건:
    - 판례정보일련번호 또는 판례일련번호 있음
    - 사건명 있음
    - 판례내용 있음
    - Law 오류 메시지 없음
    """

    if clean_text(row.get("Law")):
        return False

    if not get_official_case_id(row):
        return False

    if not clean_text(row.get("사건명")):
        return False

    if not clean_text(row.get("판례내용")):
        return False

    return True


def build_invalid_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    invalid_detail_cases.jsonl에 저장할 row를 만듭니다.
    """

    raw_case_id = get_raw_case_id(row)
    law_message = clean_text(row.get("Law"))

    invalid_reasons = []

    if row.get("_json_decode_error"):
        invalid_reasons.append("json_decode_error")

    if law_message:
        invalid_reasons.append("law_message_detail_not_found")

    if not get_official_case_id(row):
        invalid_reasons.append("missing_precedent_id")

    if not clean_text(row.get("사건명")):
        invalid_reasons.append("missing_case_name")

    if not clean_text(row.get("판례내용")):
        invalid_reasons.append("missing_main_text")

    return {
        "case_id": None,
        "raw_case_id": raw_case_id,
        "is_valid_detail": False,
        "invalid_reasons": unique_keep_order(invalid_reasons),
        "law_message": law_message,
        "matched_keywords": extract_matched_keywords(row),
        "raw_topic_labels": extract_raw_topic_labels(row),
        "source_bucket": clean_text(row.get("source_bucket")),
        "source_reference": build_source_reference(row, "", raw_case_id),
        "list_row": row.get("_list_row", {}) or {},
        "input_line_no": row.get("_input_line_no"),
        "raw_error": row.get("_json_decode_error", ""),
        "raw_line_preview": row.get("_raw_line_preview", ""),
    }


def build_cleaned_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    정상 상세 판례를 표준 컬럼으로 변환합니다.

    핵심:
    - 따로 main_text_for_classification을 만들지 않습니다.
    - main_text 컬럼 자체에 클리닝된 본문을 넣습니다.
    - 표/숫자 깨짐 여부는 main_text_artifact_info에 기록합니다.
    - full_text도 클리닝된 main_text를 기준으로 생성합니다.

    원본 확인:
    - 원본은 all_prec_candidates_raw.jsonl에 그대로 남아 있습니다.
    - 따라서 전처리 결과 파일에서는 main_text를 바로 실사용 가능한 클린 텍스트로 두는 것이 더 단순합니다.
    """

    case_id = get_official_case_id(row)
    raw_case_id = get_raw_case_id(row)

    decision_date, decision_date_ok = normalize_date(row.get("선고일자"))

    case_name = clean_text(row.get("사건명"))
    case_number = clean_text(row.get("사건번호"))
    court_name = clean_text(row.get("법원명"))

    holding = clean_text(row.get("판시사항"))
    summary = clean_text(row.get("판결요지"))

    # artifact 탐지는 클리닝 전의 기본 정리 텍스트를 기준으로 합니다.
    # 그래야 ?나 숫자표 깨짐 흔적을 품질 플래그로 기록할 수 있습니다.
    main_text_before_table_cleanup = basic_clean_text(row.get("판례내용"))
    main_text_artifact_info = detect_table_artifact(main_text_before_table_cleanup)

    # 실제 표준 컬럼에 저장할 본문입니다.
    # 이 main_text가 곧 클리닝된 본문이며, 후속 분류/RAG에서 사용할 본문입니다.
    main_text = clean_text(row.get("판례내용"))

    referenced_laws = clean_text(row.get("참조조문"))
    referenced_cases = clean_text(row.get("참조판례"))

    # 참조판례는 다른 사건 내용이 섞일 수 있어서 full_text에는 넣지 않습니다.
    # full_text는 클리닝된 main_text를 기준으로 생성합니다.
    full_text = clean_text("\n\n".join(
        part for part in [case_name, holding, summary, main_text, referenced_laws] if part
    ))

    # 같은 사건 후보를 묶기 위한 키입니다.
    same_case_key = "|".join([case_name, case_number, court_name, decision_date])

    return {
        "case_id": case_id,
        "raw_case_id": raw_case_id,

        "case_name": case_name,
        "case_number": case_number,
        "decision_date": decision_date,
        "decision_date_raw": clean_text(row.get("선고일자")),
        "decision_date_parse_ok": decision_date_ok,
        "decision_label": clean_text(row.get("선고")),

        "court_name": court_name,
        "court_type_code": clean_text(row.get("법원종류코드")),

        "case_category": clean_text(row.get("사건종류명")),
        "case_category_code": clean_text(row.get("사건종류코드")),
        "judgment_type": clean_text(row.get("판결유형")),

        "holding": holding,
        "summary": summary,
        "main_text": main_text,
        "main_text_artifact_info": main_text_artifact_info,

        "referenced_laws": referenced_laws,
        "referenced_cases": referenced_cases,

        "full_text": full_text,
        "text_length": len(full_text),
        "main_text_length": len(main_text),
        "summary_length": len(summary),
        "holding_length": len(holding),
        "referenced_laws_length": len(referenced_laws),
        "referenced_cases_length": len(referenced_cases),

        "matched_keywords": extract_matched_keywords(row),
        "raw_topic_labels": extract_raw_topic_labels(row),
        "source_bucket": clean_text(row.get("source_bucket")),
        "source_type": clean_text(row.get("source_type")) or "precedent",
        "source_provider": clean_text(row.get("source_provider")) or "국가법령정보센터 Open API",
        "source_reference": build_source_reference(row, case_id, raw_case_id),

        "same_case_key": same_case_key,
        "list_row": row.get("_list_row", {}) or {},
        "input_line_no": row.get("_input_line_no"),
        "is_valid_detail": True,
    }


# ============================================================
# 내용 유사도 기반 중복 제거
# ============================================================

def normalize_for_similarity(text: str) -> str:
    """
    내용 비교를 위해 텍스트를 정규화합니다.

    처리:
    - 공백 제거
    - 따옴표 모양 통일
    - 콜론 모양 통일
    """

    text = clean_text(text)
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = text.replace("：", ":")
    text = re.sub(r"\s+", "", text)

    return text


def content_for_duplicate_compare(row: Dict[str, Any]) -> str:
    """
    중복 내용 비교에 사용할 텍스트를 만듭니다.

    비교 대상:
    - 판시사항
    - 판결요지
    - 판례내용

    참조조문/참조판례는 제외합니다.
    """

    return "\n".join([
        row.get("holding", ""),
        row.get("summary", ""),
        row.get("main_text", ""),
    ])


def content_hash(row: Dict[str, Any]) -> str:
    """
    정규화된 비교 텍스트의 해시를 만듭니다.
    """

    text = normalize_for_similarity(content_for_duplicate_compare(row))
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def similarity(a: str, b: str) -> float:
    """
    두 텍스트의 유사도를 계산합니다.
    """

    a = normalize_for_similarity(a)
    b = normalize_for_similarity(b)

    if a == b:
        return 1.0

    # 너무 긴 판례는 앞 80,000자를 기준으로 비교합니다.
    # 같은 판례 중복 여부 판단에는 충분합니다.
    return difflib.SequenceMatcher(None, a[:80000], b[:80000], autojunk=False).ratio()


def min_pairwise_similarity(rows: List[Dict[str, Any]]) -> float:
    """
    그룹 내부 모든 row 쌍의 최소 유사도를 구합니다.
    """

    if len(rows) <= 1:
        return 1.0

    sims = []

    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            sims.append(similarity(
                content_for_duplicate_compare(rows[i]),
                content_for_duplicate_compare(rows[j]),
            ))

    return min(sims) if sims else 1.0


def duplicate_status(rows: List[Dict[str, Any]], min_sim: float) -> str:
    """
    중복 그룹의 상태를 정합니다.
    """

    hashes = {content_hash(row) for row in rows}

    if len(hashes) == 1:
        return "exact_same_content"

    if min_sim >= 0.995:
        return "near_same_content"

    if min_sim >= 0.98:
        return "very_similar_content"

    if min_sim >= DUPLICATE_SIMILARITY_THRESHOLD:
        return "similar_same_content"

    return "not_removed_similarity_below_threshold"


def representative_score(row: Dict[str, Any]) -> Tuple[int, int, int, int, str]:
    """
    중복 그룹에서 대표 row를 고르는 기준입니다.

    우선순위:
    1. full_text 길이가 긴 것
    2. main_text 길이가 긴 것
    3. summary 길이가 긴 것
    4. holding 길이가 긴 것
    5. case_id 문자열이 작은 것
    """

    return (
        row.get("text_length", 0),
        row.get("main_text_length", 0),
        row.get("summary_length", 0),
        row.get("holding_length", 0),
        str(row.get("case_id", "")),
    )


def merge_metadata_to_representative(rep: Dict[str, Any], rows: List[Dict[str, Any]], status: str, min_sim: float) -> Dict[str, Any]:
    """
    대표 row에 중복 그룹 정보를 보존합니다.
    """

    duplicate_case_ids = [row["case_id"] for row in rows if row["case_id"] != rep["case_id"]]

    rep["duplicate_group_status"] = status
    rep["duplicate_similarity_min"] = round(min_sim, 6)
    rep["duplicate_removed_count"] = len(duplicate_case_ids)
    rep["duplicate_case_ids"] = duplicate_case_ids

    all_keywords = []
    all_labels = []
    all_buckets = []
    all_source_refs = []

    for row in rows:
        all_keywords.extend(ensure_list(row.get("matched_keywords")))
        all_labels.extend(ensure_list(row.get("raw_topic_labels")))
        all_buckets.append(row.get("source_bucket"))
        all_source_refs.append(row.get("source_reference"))

    rep["matched_keywords"] = unique_keep_order(all_keywords)
    rep["raw_topic_labels"] = unique_keep_order(all_labels)
    rep["source_buckets"] = unique_keep_order(all_buckets)
    rep["duplicate_source_references"] = unique_keep_order(all_source_refs)

    return rep


def build_duplicate_candidate_groups(
    cleaned_rows: List[Dict[str, Any]],
    duplicate_candidates_path: Path,
) -> Dict[str, int]:
    """
    중복 후보 그룹만 따로 모은 JSONL을 먼저 만듭니다.

    이 단계에서는 최종 데이터를 바로 삭제하지 않습니다.
    먼저 03_duplicate_candidate_groups.jsonl에 다음 정보를 저장합니다.

    - 같은 사건 키
    - 그룹 안의 모든 case_id
    - 대표로 남길 case_id
    - 제거할 case_id 목록
    - 내용 유사도
    - 그룹 안 row 전체

    즉, 나중에 삭제는 이 JSONL에 적힌 remove_case_ids를 기준으로 진행합니다.
    """

    grouped = defaultdict(list)

    for row in cleaned_rows:
        grouped[row["same_case_key"]].append(row)

    stats = Counter()
    group_no = 0

    with duplicate_candidates_path.open("w", encoding="utf-8") as file:
        for same_key, rows in grouped.items():
            if len(rows) <= 1:
                continue

            group_no += 1
            stats["same_case_key_duplicate_groups"] += 1
            stats["same_case_key_duplicate_rows"] += len(rows)

            min_sim = min_pairwise_similarity(rows)
            status = duplicate_status(rows, min_sim)
            stats[status] += 1

            representative = max(rows, key=representative_score)
            representative_case_id = representative["case_id"]

            if min_sim >= DUPLICATE_SIMILARITY_THRESHOLD:
                action = "remove_duplicates"
                remove_case_ids = [
                    row["case_id"]
                    for row in rows
                    if row["case_id"] != representative_case_id
                ]
            else:
                # 기준 미만이면 삭제하지 않고 검토용으로만 기록합니다.
                action = "review_keep_all"
                remove_case_ids = []

            candidate_group = {
                "group_no": group_no,
                "action": action,
                "same_case_key": same_key,
                "case_name": rows[0].get("case_name"),
                "case_number": rows[0].get("case_number"),
                "court_name": rows[0].get("court_name"),
                "decision_date": rows[0].get("decision_date"),
                "duplicate_group_status": status,
                "duplicate_similarity_min": round(min_sim, 6),
                "threshold": DUPLICATE_SIMILARITY_THRESHOLD,
                "row_count": len(rows),
                "all_case_ids": [row["case_id"] for row in rows],
                "representative_case_id": representative_case_id,
                "remove_case_ids": remove_case_ids,
                "representative_rule": "full_text 길이가 가장 긴 row 우선",
                "rows": rows,
            }

            file.write(json.dumps(candidate_group, ensure_ascii=False) + "\n")
            stats["duplicate_candidate_groups_written"] += 1
            stats["duplicate_removed_rows"] += len(remove_case_ids)

    return dict(stats)


def load_duplicate_removal_plan(
    duplicate_candidates_path: Path,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    03_duplicate_candidate_groups.jsonl을 읽어서 삭제 계획을 만듭니다.

    반환:
    - remove_plan_by_case_id:
      제거할 case_id -> 제거 정보

    - representative_info_by_case_id:
      대표로 남길 case_id -> 중복 그룹 정보
    """

    remove_plan_by_case_id = {}
    representative_info_by_case_id = {}

    if not duplicate_candidates_path.exists():
        return remove_plan_by_case_id, representative_info_by_case_id

    with duplicate_candidates_path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            group = json.loads(line)

            if group.get("action") != "remove_duplicates":
                continue

            representative_case_id = group.get("representative_case_id")
            remove_case_ids = group.get("remove_case_ids", [])

            representative_info_by_case_id[representative_case_id] = {
                "duplicate_group_no": group.get("group_no"),
                "duplicate_group_status": group.get("duplicate_group_status"),
                "duplicate_similarity_min": group.get("duplicate_similarity_min"),
                "duplicate_removed_count": len(remove_case_ids),
                "duplicate_case_ids": remove_case_ids,
                "same_case_key": group.get("same_case_key"),
                "all_case_ids_in_duplicate_group": group.get("all_case_ids", []),
            }

            for remove_case_id in remove_case_ids:
                remove_plan_by_case_id[remove_case_id] = {
                    "removed_case_id": remove_case_id,
                    "representative_case_id": representative_case_id,
                    "duplicate_group_no": group.get("group_no"),
                    "same_case_key": group.get("same_case_key"),
                    "duplicate_group_status": group.get("duplicate_group_status"),
                    "duplicate_similarity_min": group.get("duplicate_similarity_min"),
                    "threshold": group.get("threshold"),
                    "all_case_ids": group.get("all_case_ids", []),
                }

    return remove_plan_by_case_id, representative_info_by_case_id


def apply_duplicate_removal_plan(
    cleaned_rows: List[Dict[str, Any]],
    duplicate_candidates_path: Path,
    duplicate_removed_path: Path,
) -> List[Dict[str, Any]]:
    """
    03_duplicate_candidate_groups.jsonl에 적힌 remove_case_ids를 기준으로
    cleaned_rows에서 중복 row를 제외합니다.

    핵심:
    - 몇 개 그룹만 보는 방식이 아닙니다.
    - 03_duplicate_candidate_groups.jsonl 전체를 읽습니다.
    - 그 안의 remove_case_ids 전체를 삭제 대상으로 사용합니다.
    - 삭제 row는 04_duplicate_removed_cases.jsonl에 보관합니다.
    """

    remove_plan_by_case_id, representative_info_by_case_id = load_duplicate_removal_plan(
        duplicate_candidates_path
    )

    deduped_rows = []

    with duplicate_removed_path.open("w", encoding="utf-8") as removed_file:
        for row in cleaned_rows:
            case_id = row.get("case_id")

            if case_id in remove_plan_by_case_id:
                removed_record = dict(remove_plan_by_case_id[case_id])
                removed_record["removed_row"] = row
                removed_file.write(json.dumps(removed_record, ensure_ascii=False) + "\n")
                continue

            if case_id in representative_info_by_case_id:
                row.update(representative_info_by_case_id[case_id])

                # 대표 row에 중복 그룹의 키워드/라벨/source 정보도 최대한 보존합니다.
                duplicate_case_ids = set(row.get("duplicate_case_ids", []))
                all_group_case_ids = set(row.get("all_case_ids_in_duplicate_group", []))

                group_keywords = []
                group_labels = []
                group_buckets = []
                group_source_refs = []

                for candidate_row in cleaned_rows:
                    if candidate_row.get("case_id") in all_group_case_ids:
                        group_keywords.extend(ensure_list(candidate_row.get("matched_keywords")))
                        group_labels.extend(ensure_list(candidate_row.get("raw_topic_labels")))
                        group_buckets.append(candidate_row.get("source_bucket"))
                        group_source_refs.append(candidate_row.get("source_reference"))

                row["matched_keywords"] = unique_keep_order(group_keywords)
                row["raw_topic_labels"] = unique_keep_order(group_labels)
                row["source_buckets"] = unique_keep_order(group_buckets)
                row["duplicate_source_references"] = unique_keep_order(group_source_refs)
            else:
                row["duplicate_group_status"] = "unique"
                row["duplicate_removed_count"] = 0
                row["duplicate_case_ids"] = []

            deduped_rows.append(row)

    return deduped_rows


# ============================================================
# 품질 플래그
# ============================================================

def build_quality_flags(row: Dict[str, Any]) -> Tuple[List[str], List[str], bool]:
    """
    품질 플래그를 생성합니다.
    """

    quality_flags = []
    missing_fields = []

    required_fields = [
        "case_id",
        "case_name",
        "case_number",
        "decision_date",
        "court_name",
        "case_category",
        "judgment_type",
        "main_text",
        "source_reference",
    ]

    for field_name in required_fields:
        if not row.get(field_name):
            missing_fields.append(field_name)
            quality_flags.append(f"missing_{field_name}")

    if not row.get("decision_date_parse_ok"):
        quality_flags.append("invalid_decision_date")

    if row.get("main_text_length", 0) < MAIN_TEXT_MIN_LENGTH:
        quality_flags.append("main_text_too_short")

    if row.get("text_length", 0) < FULL_TEXT_MIN_LENGTH:
        quality_flags.append("full_text_too_short")

    # 표/숫자 깨짐 artifact가 있었는지 기록합니다.
    # 이 플래그는 삭제 기준이 아니라 검토용 warning입니다.
    artifact_info = row.get("main_text_artifact_info", {}) or {}

    if artifact_info.get("table_artifact_detected"):
        quality_flags.append("table_artifact_detected")

    if artifact_info.get("numeric_dense_text_detected"):
        quality_flags.append("numeric_dense_text_detected")

    if artifact_info.get("question_mark_count", 0) >= 3:
        quality_flags.append("many_question_marks_remaining")

    severe_flags = {
        "missing_case_id",
        "missing_case_name",
        "missing_main_text",
        "missing_source_reference",
        "full_text_too_short",
    }

    is_usable = not any(flag in severe_flags for flag in quality_flags)

    return unique_keep_order(quality_flags), unique_keep_order(missing_fields), is_usable


# ============================================================
# 메인 전처리
# ============================================================

def preprocess(args: argparse.Namespace) -> None:
    input_path = Path(args.input)
    out_dir = Path(args.out_dir)

    if not input_path.exists():
        raise FileNotFoundError(f"input file not found: {input_path}")

    paths = prepare_output_paths(out_dir=out_dir, fresh=args.fresh)

    stats = PreprocessStats()

    source_bucket_counter = Counter()
    invalid_reason_counter = Counter()
    cleaned_rows = []

    # ------------------------------------------------------------
    # 1. invalid 분리 + cleaned 생성
    # ------------------------------------------------------------
    for row in read_jsonl(input_path):
        stats.input_rows += 1

        source_bucket = clean_text(row.get("source_bucket"))
        if source_bucket:
            source_bucket_counter[source_bucket] += 1

        if not is_valid_detail_row(row):
            invalid_row = build_invalid_row(row)

            for reason in invalid_row.get("invalid_reasons", []):
                invalid_reason_counter[reason] += 1

            write_jsonl(paths["invalid"], invalid_row)
            stats.invalid_detail_rows += 1
            continue

        cleaned = build_cleaned_row(row)
        cleaned_rows.append(cleaned)
        write_jsonl(paths["cleaned"], cleaned)

        stats.valid_detail_rows += 1
        stats.cleaned_rows += 1

    # ------------------------------------------------------------
    # 2. 중복 후보 그룹 JSONL 생성
    # ------------------------------------------------------------
    duplicate_stats = build_duplicate_candidate_groups(
        cleaned_rows=cleaned_rows,
        duplicate_candidates_path=paths["duplicate_candidates"],
    )

    stats.same_case_key_duplicate_groups = duplicate_stats.get("same_case_key_duplicate_groups", 0)
    stats.same_case_key_duplicate_rows = duplicate_stats.get("same_case_key_duplicate_rows", 0)
    stats.duplicate_candidate_groups_written = duplicate_stats.get("duplicate_candidate_groups_written", 0)
    stats.duplicate_removed_rows = duplicate_stats.get("duplicate_removed_rows", 0)
    stats.duplicate_kept_representatives = stats.same_case_key_duplicate_groups
    stats.duplicate_status_counts = {
        key: value
        for key, value in duplicate_stats.items()
        if key not in {
            "same_case_key_duplicate_groups",
            "same_case_key_duplicate_rows",
            "duplicate_candidate_groups_written",
            "duplicate_removed_rows",
        }
    }

    # ------------------------------------------------------------
    # 3. 중복 후보 JSONL의 remove_case_ids를 기준으로 실제 제거 적용
    # ------------------------------------------------------------
    deduped_rows = apply_duplicate_removal_plan(
        cleaned_rows=cleaned_rows,
        duplicate_candidates_path=paths["duplicate_candidates"],
        duplicate_removed_path=paths["duplicate_removed"],
    )

    stats.deduped_rows = len(deduped_rows)

    with paths["deduped"].open("w", encoding="utf-8") as file:
        for row in deduped_rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------
    # 4. 품질 플래그 생성
    # ------------------------------------------------------------
    quality_flag_counter = Counter()
    missing_field_counter = Counter()

    with paths["quality"].open("w", encoding="utf-8") as file:
        for row in deduped_rows:
            quality_flags, missing_fields, is_usable = build_quality_flags(row)

            row["quality_flags"] = quality_flags
            row["missing_fields"] = missing_fields
            row["is_usable_for_reclassification"] = is_usable

            for flag in quality_flags:
                quality_flag_counter[flag] += 1

            for field_name in missing_fields:
                missing_field_counter[field_name] += 1

            if is_usable:
                stats.usable_for_reclassification += 1
            else:
                stats.unusable_for_reclassification += 1

            stats.quality_checked_rows += 1

            file.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------
    # 5. 리포트 저장
    # ------------------------------------------------------------
    stats.source_bucket_counts = dict(source_bucket_counter)
    stats.invalid_reason_counts = dict(invalid_reason_counter)
    stats.quality_flag_counts = dict(quality_flag_counter)
    stats.missing_field_counts = dict(missing_field_counter)

    report = {
        "input_file": str(input_path),
        "output_dir": str(out_dir),
        "thresholds": {
            "MAIN_TEXT_MIN_LENGTH": MAIN_TEXT_MIN_LENGTH,
            "FULL_TEXT_MIN_LENGTH": FULL_TEXT_MIN_LENGTH,
            "DUPLICATE_SIMILARITY_THRESHOLD": DUPLICATE_SIMILARITY_THRESHOLD,
            "NUMERIC_DENSE_DIGIT_RATIO": NUMERIC_DENSE_DIGIT_RATIO,
            "NUMERIC_DENSE_MIN_LENGTH": NUMERIC_DENSE_MIN_LENGTH,
        },
        "dedupe_rule": {
            "same_case_key": "case_name + case_number + court_name + decision_date",
            "content_compare_fields": ["holding", "summary", "main_text"],
            "remove_if_min_pairwise_similarity_gte": DUPLICATE_SIMILARITY_THRESHOLD,
            "representative_rule": "full_text 길이가 가장 긴 row 우선",
            "important": "중복 제거는 03_duplicate_candidate_groups.jsonl에 적힌 remove_case_ids를 읽어서 적용합니다.",
        },
        "outputs": {key: str(value) for key, value in paths.items()},
        "stats": asdict(stats),
        "notes": [
            "원본 all_prec_candidates_raw.jsonl은 수정하지 않습니다.",
            "03_duplicate_candidate_groups.jsonl에 중복 후보 전체와 remove_case_ids를 먼저 저장합니다.",
            "중복 삭제는 03_duplicate_candidate_groups.jsonl을 읽어서 적용합니다.",
            "삭제는 최종 deduped/quality 파일에서 제외한다는 의미입니다.",
            "제외된 row는 04_duplicate_removed_cases.jsonl에 보관합니다.",
            "교통사고 관련성 재분류와 과실비율 분류는 아직 수행하지 않습니다.",
            "main_text 컬럼 자체에 클리닝된 본문을 저장합니다.",
            "별도의 main_text_for_classification 컬럼은 만들지 않습니다.",
            "표/숫자 깨짐 구간은 main_text 안에서 [계산표_생략], [숫자표_생략]으로 축약합니다.",
            "원본 확인은 all_prec_candidates_raw.jsonl에서 가능합니다.",
            "표 깨짐 흔적이 있으면 table_artifact_detected, numeric_dense_text_detected 플래그를 붙입니다.",
        ],
    }

    paths["report"].write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n전처리 완료")
    print(json.dumps(report["stats"], ensure_ascii=False, indent=2))
    print(f"\n저장 위치: {out_dir.resolve()}")
    for name, path in paths.items():
        print(f"- {name}: {path}")


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="교통사고 판례 후보를 전처리하고 유사도 기반 중복 제거를 수행합니다."
    )

    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT_PATH,
        help=f"입력 JSONL 파일 경로. 기본값: {DEFAULT_INPUT_PATH}",
    )

    parser.add_argument(
        "--out-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"전처리 결과 저장 폴더. 기본값: {DEFAULT_OUTPUT_DIR}",
    )

    parser.add_argument(
        "--fresh",
        action="store_true",
        help="기존 출력 폴더를 삭제하고 새로 생성",
    )

    return parser.parse_args()


if __name__ == "__main__":
    preprocess(parse_args())
