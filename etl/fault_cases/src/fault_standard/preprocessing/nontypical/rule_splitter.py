# -*- coding: utf-8 -*-
"""상세 본문을 No별 rule section으로 분리합니다."""

import re
from typing import Any, Dict, List, Optional

from .cleaners import clean_pdf_text, structure_rule_text
from .file_utils import safe_filename
from .models import PageText
from .config import RULE_NO_MIN, RULE_NO_MAX



def find_first_detail_page(pages: List[PageText]) -> int:
    """첫 상세 rule 페이지를 텍스트 앵커로 찾습니다."""

    for page in pages:
        if re.search(r"^\s*1\.\s+.+사고", page.clean_text, re.MULTILINE) and "기본과실" in page.clean_text:
            return page.page_no
    for page in pages:
        if re.search(r"^\s*1\.\s+", page.clean_text, re.MULTILINE):
            return page.page_no
    return pages[0].page_no if pages else 1

def split_detail_rules(pages: List[PageText]) -> List[Dict[str, Any]]:
    """상세 본문을 No별 rule section으로 분리합니다."""

    # 최종 section 목록입니다.
    sections: List[Dict[str, Any]] = []

    # 현재 누적 중인 section입니다.
    current: Optional[Dict[str, Any]] = None

    # 여러 줄로 깨진 rule 제목을 임시 저장합니다.
    pending_header: Optional[Dict[str, Any]] = None

    # 마지막으로 확정한 rule 번호입니다.
    last_rule_no = 0

    # 상세 본문 시작 페이지는 rule header와 기본과실 앵커로 찾습니다.
    first_detail_page = find_first_detail_page(pages)
    for page in pages:
        if page.page_no < first_detail_page:
            continue
        # 현재 페이지 번호입니다.
        page_no = page.page_no

        # 페이지 텍스트를 줄 단위로 읽습니다.
        for line in page.clean_text.splitlines():
            # 줄 앞뒤 공백을 제거합니다.
            line = line.strip()

            # 빈 줄은 현재 section에만 보존합니다.
            if not line:
                if current:
                    current["lines"].append("")
                continue

            # 직전 줄에서 "23. 긴 제목"처럼 제목이 끊겼다면 다음 줄을 이어붙입니다.
            if pending_header:
                # 제목 조각을 추가합니다.
                pending_header["title_parts"].append(line)

                # 합친 제목입니다.
                joined_title = " ".join(pending_header["title_parts"]).strip()

                # 제목에 사고가 들어오면 rule header로 확정합니다.
                if "사고" in joined_title:
                    # 기존 section이 있으면 먼저 마감합니다.
                    if current:
                        sections.append(finalize_rule_section(current))

                    # 새 rule 번호입니다.
                    rule_no = pending_header["rule_no"]

                    # 새 section을 시작합니다.
                    current = {
                        "rule_no": rule_no,
                        "rule_code": f"No.{rule_no}",
                        "rule_title": joined_title,
                        "page_start": pending_header["page_start"],
                        "page_end": page_no,
                        "lines": [f"{rule_no}. {joined_title}"],
                    }

                    # 마지막 rule 번호를 갱신합니다.
                    last_rule_no = rule_no

                    # pending 상태를 해제합니다.
                    pending_header = None
                    continue

                # 아직 사고라는 단어가 없으면 제목 조각을 더 기다립니다.
                continue

            # 상세 rule 헤더인지 확인합니다.
            header = parse_detail_header(line, last_rule_no)

            # 새 rule 헤더 후보를 찾은 경우입니다.
            if header:
                # 제목이 한 줄에서 완성된 경우입니다.
                if header["is_complete"]:
                    # 기존 section이 있으면 먼저 마감합니다.
                    if current:
                        sections.append(finalize_rule_section(current))

                    # 새 section을 시작합니다.
                    current = {
                        "rule_no": header["rule_no"],
                        "rule_code": f"No.{header['rule_no']}",
                        "rule_title": header["rule_title"],
                        "page_start": page_no,
                        "page_end": page_no,
                        "lines": [line],
                    }

                    # 마지막 rule 번호를 갱신합니다.
                    last_rule_no = header["rule_no"]
                    continue

                # 제목이 다음 줄로 이어지는 경우입니다.
                pending_header = {
                    "rule_no": header["rule_no"],
                    "title_parts": [header["rule_title"]],
                    "page_start": page_no,
                }
                continue

            # 일반 줄은 현재 section에 누적합니다.
            if current:
                current["lines"].append(line)
                current["page_end"] = page_no

    # pending header가 끝까지 완성되지 않은 경우도 로그 손실을 막기 위해 section으로 저장합니다.
    if pending_header:
        if current:
            sections.append(finalize_rule_section(current))

        rule_no = pending_header["rule_no"]
        joined_title = " ".join(pending_header["title_parts"]).strip()

        current = {
            "rule_no": rule_no,
            "rule_code": f"No.{rule_no}",
            "rule_title": joined_title,
            "page_start": pending_header["page_start"],
            "page_end": pending_header["page_start"],
            "lines": [f"{rule_no}. {joined_title}"],
        }

    # 마지막 section을 마감합니다.
    if current:
        sections.append(finalize_rule_section(current))

    # 같은 rule 번호가 중복으로 들어간 경우 뒤쪽을 우선하여 정리합니다.
    sections = dedupe_sections_by_rule_no(sections)

    # section 목록을 반환합니다.
    return sections


def parse_detail_header(line: str, last_rule_no: int = 0) -> Optional[Dict[str, Any]]:
    """상세 본문의 '1. 사고 제목' 형태를 탐지합니다."""

    # 번호. 제목 패턴을 찾습니다.
    match = re.match(r"^(?P<no>\d{1,2})\.\s+(?P<title>.+)", line)

    # 매칭되지 않으면 None입니다.
    if not match:
        return None

    # rule 번호입니다.
    rule_no = int(match.group("no"))

    # 2020 비정형 기준서는 No.1~No.23까지만 있습니다.
    if rule_no < RULE_NO_MIN or rule_no > RULE_NO_MAX:
        return None

    # 반드시 직전 rule 번호의 다음 번호만 인정합니다.
    # 예: No.22 다음에는 No.23만 인정합니다.
    # 이렇게 해야 법규 본문의 "13. 교차로란 ..." 같은 번호가 rule로 잘못 잡히지 않습니다.
    if rule_no != last_rule_no + 1:
        return None

    # 제목 문자열입니다.
    title = match.group("title").strip()

    # 법규 본문의 "2. 국가경찰공무원..." 같은 번호를 rule 제목으로 오인하지 않도록 거릅니다.
    if not looks_like_rule_title(title):
        return None

    # 제목이 한 줄에서 완성됐는지 확인합니다.
    is_complete = "사고" in title

    # rule 번호와 제목을 반환합니다.
    return {
        "rule_no": rule_no,
        "rule_title": title,
        "is_complete": is_complete,
    }



def looks_like_rule_title(title: str) -> bool:
    """상세 rule 제목처럼 보이는 문장인지 판단합니다."""

    # 사고 제목에는 대체로 차량/이륜차/횡단보도/교차로 같은 사고 핵심어가 들어갑니다.
    positive_keywords = [
        "차량",
        "이륜차",
        "자동차",
        "횡단보도",
        "교차로",
        "버스정류장",
        "이면도로",
        "주차장",
    ]

    # 법령 본문 번호를 오인하지 않기 위해 제외할 단어입니다.
    negative_keywords = [
        "국가경찰",
        "자치경찰",
        "경찰공무원",
        "경찰보조자",
        "대통령령",
        "도로교통법",
        "제1항",
        "제2항",
        "제3항",
        "정의)",
    ]

    # 제외 단어가 있으면 rule 제목으로 보지 않습니다.
    if any(word in title for word in negative_keywords):
        return False

    # 긍정 키워드가 하나라도 있으면 rule 제목 후보로 인정합니다.
    return any(word in title for word in positive_keywords)


def dedupe_sections_by_rule_no(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """같은 rule 번호가 중복될 경우 하나만 남깁니다."""

    # rule 번호별 section을 저장합니다.
    by_no: Dict[int, Dict[str, Any]] = {}

    # 앞에서부터 순회합니다.
    for section in sections:
        # rule 번호입니다.
        rule_no = int(section["rule_no"])

        # 같은 번호가 없다면 저장합니다.
        if rule_no not in by_no:
            by_no[rule_no] = section
            continue

        # 더 긴 텍스트를 가진 section을 우선합니다.
        old_len = len(by_no[rule_no].get("structured_text", ""))
        new_len = len(section.get("structured_text", ""))

        # 새 section이 더 길면 교체합니다.
        if new_len > old_len:
            by_no[rule_no] = section

    # rule 번호 순서대로 반환합니다.
    return [by_no[rule_no] for rule_no in sorted(by_no)]


def finalize_rule_section(section: Dict[str, Any]) -> Dict[str, Any]:
    """rule section의 raw/clean/structured 텍스트를 완성합니다."""

    # 누적된 줄을 원문 텍스트로 합칩니다.
    raw_text = "\n".join(section["lines"]).strip()

    # 기본 클리닝을 적용합니다.
    clean_text = clean_pdf_text(raw_text)

    # 파싱하기 좋은 구조로 정리합니다.
    structured_text = structure_rule_text(clean_text)

    # 결과를 section에 저장합니다.
    section["raw_text"] = raw_text
    section["clean_text"] = clean_text
    section["structured_text"] = structured_text
    section["file_title"] = safe_filename(f"no_{section['rule_no']:02d}_{section['rule_title']}")

    # 완성된 section을 반환합니다.
    return section
