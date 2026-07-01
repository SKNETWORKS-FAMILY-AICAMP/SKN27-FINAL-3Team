# -*- coding: utf-8 -*-
"""요약표 No/내용/기준과실을 파싱합니다."""

import re
from typing import Any, Dict, List, Optional, Tuple

from .file_utils import safe_filename
from .models import PageText


def parse_summary_table(pages: List[PageText]) -> List[Dict[str, Any]]:
    """2페이지의 No/내용/기준과실 요약표를 파싱합니다."""

    # 페이지가 2장 미만이면 요약표를 읽을 수 없습니다.
    if len(pages) < 2:
        return []

    # 보통 2페이지에 요약표가 있으므로 index 1을 사용합니다.
    text = pages[1].clean_text

    # 빈 줄을 제외한 줄 목록입니다.
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # 파싱된 row를 저장합니다.
    rows: List[Dict[str, Any]] = []

    # 제목이 줄바꿈된 경우 임시로 저장합니다.
    pending_title_lines: List[str] = []

    # 줄 단위로 요약표를 읽습니다.
    for line in lines:
        # 헤더 줄은 건너뜁니다.
        if line.startswith("No ") or line == "No 내용 기준과실":
            continue

        # 한 줄에서 No/제목/기준과실을 파싱합니다.
        parsed = parse_summary_line(line)

        # 파싱에 성공한 경우입니다.
        if parsed:
            # 앞에 누적된 제목 줄이 있으면 붙입니다.
            if not parsed["summary_title"] and pending_title_lines:
                parsed["summary_title"] = " ".join(pending_title_lines).strip()

            # 원문 row를 보존합니다.
            parsed["summary_row_raw_text"] = " ".join([*pending_title_lines, line]).strip()

            # 결과에 추가합니다.
            rows.append(parsed)

            # 임시 제목 줄을 초기화합니다.
            pending_title_lines = []
            continue

        # 이전 row의 제목이 다음 줄로 이어진 경우입니다.
        if rows and should_append_to_previous_summary_title(line, rows[-1]):
            rows[-1]["summary_title"] = f"{rows[-1]['summary_title']} {line}".strip()
            rows[-1]["summary_row_raw_text"] = f"{rows[-1]['summary_row_raw_text']} {line}".strip()
            continue

        # 아직 어느 row인지 모르는 제목 줄로 임시 저장합니다.
        pending_title_lines.append(line)

    # row 후처리를 수행합니다.
    for row in rows:
        row["summary_title"] = normalize_summary_title(row["summary_title"])
        row["summary_title_clean"] = safe_filename(row["summary_title"])
        row["summary_no"] = int(row["summary_no"])
        row["summary_rule_ref"] = f"No.{row['summary_no']}"

    # 상세 rule title과 자동 정렬한 요약표 row 목록을 반환합니다.
    return align_summary_titles_with_detail_rules(rows, pages)


def align_summary_titles_with_detail_rules(rows: List[Dict[str, Any]], pages: List[PageText]) -> List[Dict[str, Any]]:
    """요약표 제목을 상세 rule 제목과 No 기준으로 자동 정렬합니다."""

    detail_titles = extract_detail_titles_by_no(pages)

    for row in rows:
        no = int(row.get("summary_no") or 0)
        detail_title = detail_titles.get(no)
        if not detail_title:
            continue

        original_title = row.get("summary_title", "")
        if should_use_detail_title(original_title, detail_title):
            row["summary_title_original"] = original_title
            row["summary_title"] = detail_title
            row["summary_title_clean"] = safe_filename(detail_title)
            row["summary_title_source"] = "detail_rule_title"
            row["summary_row_raw_text"] = trim_summary_raw_text(row.get("summary_row_raw_text", ""), detail_title)
        else:
            row["summary_title_source"] = "summary_table"

    return rows


def extract_detail_titles_by_no(pages: List[PageText]) -> Dict[int, str]:
    """상세 본문에서 No별 rule 제목을 추출합니다."""

    from .rule_splitter import split_detail_rules

    return {
        int(section["rule_no"]): normalize_summary_title(section["rule_title"])
        for section in split_detail_rules(pages)
        if section.get("rule_no") and section.get("rule_title")
    }


def should_use_detail_title(summary_title: str, detail_title: str) -> bool:
    """요약표 제목이 깨졌거나 상세 제목과 의미상 다른 경우 상세 제목을 사용합니다."""

    normalized_summary = normalize_title_for_compare(summary_title)
    normalized_detail = normalize_title_for_compare(detail_title)

    if not normalized_summary:
        return True

    if normalized_summary == normalized_detail:
        return False

    if normalized_detail in normalized_summary:
        return True

    if normalized_summary in normalized_detail:
        return True

    return title_similarity(normalized_summary, normalized_detail) < 0.92


def normalize_title_for_compare(title: str) -> str:
    """제목 비교용으로 조사/공백 차이를 줄입니다."""

    value = normalize_summary_title(title)
    value = value.replace("차량과 사고", "차량간 사고")
    value = value.replace("차량 간 사고", "차량간 사고")
    value = value.replace("차량간 사고", "차량간사고")
    value = value.replace("차량과", "차량간")
    value = re.sub(r"[\s·,，/]", "", value)
    return value


def title_similarity(left: str, right: str) -> float:
    """두 제목의 문자 bigram 유사도를 계산합니다."""

    left_tokens = build_bigrams(left)
    right_tokens = build_bigrams(right)

    if not left_tokens or not right_tokens:
        return 0.0

    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def build_bigrams(text: str) -> set[str]:
    """짧은 한글 제목 비교용 bigram set을 만듭니다."""

    if len(text) < 2:
        return {text} if text else set()

    return {text[idx: idx + 2] for idx in range(len(text) - 1)}


def trim_summary_raw_text(raw_text: str, title: str) -> str:
    """보정된 제목과 비율 중심으로 summary raw text를 정리합니다."""

    ratio_match = re.search(r"A\s*\d{1,3}(?:\(\d{1,3}\))?\s*:\s*B\s*\d{1,3}(?:\(\d{1,3}\))?", raw_text)
    return f"{title} {ratio_match.group(0)}".strip() if ratio_match else title


def parse_summary_line(line: str) -> Optional[Dict[str, Any]]:
    """요약표 한 줄에서 No, 제목, 기준과실을 추출합니다."""

    # No + 제목 + A/B 기준과실 패턴입니다.
    pattern = (
        r"^(?P<no>\d{1,2})\s*"
        r"(?P<title>.*?)\s*"
        r"A\s*(?P<a>\d{1,3}(?:\(\d{1,3}\))?)\s*:\s*"
        r"B\s*(?P<b>\d{1,3}(?:\(\d{1,3}\))?)"
    )

    # 정규식 매칭을 수행합니다.
    match = re.match(pattern, line)

    # 매칭되지 않으면 None을 반환합니다.
    if not match:
        return None

    # A 비율을 기본값/괄호값으로 분리합니다.
    a_primary, a_alt = parse_ratio_number(match.group("a"))

    # B 비율을 기본값/괄호값으로 분리합니다.
    b_primary, b_alt = parse_ratio_number(match.group("b"))

    # 파싱 결과를 반환합니다.
    return {
        "summary_no": int(match.group("no")),
        "summary_title": match.group("title").strip(),
        "summary_base_ratio_raw": f"A {match.group('a')} : B {match.group('b')}",
        "summary_party_a_ratio": a_primary,
        "summary_party_b_ratio": b_primary,
        "summary_party_a_ratio_alt": a_alt,
        "summary_party_b_ratio_alt": b_alt,
        "summary_row_raw_text": line,
    }


def parse_ratio_number(value: str) -> Tuple[Optional[int], Optional[int]]:
    """40(35) 같은 비율에서 기본값과 대체값을 분리합니다."""

    # 숫자와 괄호 숫자를 읽습니다.
    match = re.match(r"(?P<main>\d{1,3})(?:\((?P<alt>\d{1,3})\))?", value.strip())

    # 매칭 실패 시 None을 반환합니다.
    if not match:
        return None, None

    # 기본 비율입니다.
    main = int(match.group("main"))

    # 괄호 안 대체 비율입니다.
    alt = int(match.group("alt")) if match.group("alt") else None

    # 기본값과 대체값을 반환합니다.
    return main, alt


def should_append_to_previous_summary_title(line: str, previous_row: Dict[str, Any]) -> bool:
    """요약표에서 다음 줄이 이전 제목의 이어진 줄인지 판단합니다."""

    # 새 번호로 시작하면 새 row이므로 이어붙이지 않습니다.
    if re.match(r"^\d{1,2}\s+", line):
        return False

    # 비율이 들어간 줄은 새 요약 row의 일부일 가능성이 높으므로 이전 제목에 붙이지 않습니다.
    if re.search(r"A\s*\d{1,3}(?:\(\d{1,3}\))?\s*:\s*B\s*\d{1,3}", line):
        return False

    # 이전 제목이 이미 완성된 상태에서 독립 사고 제목처럼 보이는 줄은 붙이지 않습니다.
    if looks_like_independent_title_line(line, previous_row.get("summary_title", "")):
        return False

    # 하이픈으로 이어지는 문장은 이전 제목의 일부일 수 있습니다.
    if line.startswith("-"):
        return True

    # 괄호가 닫히지 않은 제목은 이어질 가능성이 높습니다.
    title = previous_row.get("summary_title", "")
    if title.count("(") > title.count(")"):
        return True

    # 사고/차량간 같은 핵심어가 있으면 제목 일부로 봅니다.
    if "사고" in line or "차량간" in line:
        return True

    # 기본값은 이어붙이지 않는 것입니다.
    return False


def looks_like_independent_title_line(line: str, previous_title: str) -> bool:
    """요약표에서 현재 줄이 이전 제목의 연장이 아니라 독립 제목인지 판단합니다."""

    if not previous_title:
        return False

    previous_complete = "사고" in previous_title and previous_title.count("(") <= previous_title.count(")")
    if not previous_complete:
        return False

    current_has_title_shape = "사고" in line and line.count("(") <= line.count(")")
    if current_has_title_shape:
        return True

    return len(line) >= 12 and any(token in line for token in ["차량", "자동차", "이륜차", "교차로", "횡단보도"])


def normalize_summary_title(title: str) -> str:
    """요약표 제목의 불필요한 공백과 줄바꿈 흔적을 정리합니다."""

    # PDF 줄바꿈에서 생긴 하이픈 공백을 제거합니다.
    title = title.replace("- ", "")

    # 사고 단어가 분리된 경우를 복원합니다.
    title = title.replace(" 사 고", " 사고")

    # 반복 공백을 하나로 줄입니다.
    title = re.sub(r"\s+", " ", title)

    # 정리한 제목을 반환합니다.
    return title.strip()
