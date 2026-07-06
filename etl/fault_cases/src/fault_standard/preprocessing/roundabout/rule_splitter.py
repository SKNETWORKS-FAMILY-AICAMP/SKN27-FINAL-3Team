# -*- coding: utf-8 -*-
"""회전-1 ~ 회전-15 rule section을 분리합니다."""

import re
from typing import Any, Dict, List, Optional

from .cleaners import clean_pdf_text, structure_rule_text
from .file_utils import safe_filename
from .models import PageText
from .config import ROUND_NO_MIN, ROUND_NO_MAX


def split_roundabout_rules(pages: List[PageText]) -> List[Dict[str, Any]]:
    """상세 본문을 회전-1~회전-15 rule section으로 분리합니다."""

    # 최종 rule section 목록입니다.
    sections: List[Dict[str, Any]] = []

    # 현재 누적 중인 section입니다.
    current: Optional[Dict[str, Any]] = None

    # 회전 코드가 먼저 나오고 제목을 기다리는 상태입니다.
    pending_code: Optional[Dict[str, Any]] = None

    # 제목이 먼저 나오고 회전 코드를 기다리는 상태입니다.
    pending_title: Optional[Dict[str, Any]] = None

    # 상세 기준 시작 페이지는 회전 코드가 처음 나타나는 페이지로 동적으로 찾습니다.
    start_page_no = find_first_round_rule_page(pages)
    for page in [p for p in pages if p.page_no >= start_page_no]:
        # 현재 페이지 번호입니다.
        page_no = page.page_no

        # 페이지 텍스트를 줄 단위로 읽습니다.
        for raw_line in page.clean_text.splitlines():
            # 줄 앞뒤 공백을 제거합니다.
            line = raw_line.strip()

            # 빈 줄은 현재 section에만 보존합니다.
            if not line:
                if current:
                    current["lines"].append("")
                continue

            # 제목 후보가 "사고"만 다음 줄로 끊긴 경우를 처리합니다.
            if pending_title and line == "사고":
                pending_title["title"] = f"{pending_title['title']} 사고"
                continue

            # 회전 코드가 단독 또는 같은 줄에 붙은 형태인지 확인합니다.
            code_info = parse_round_code_line(line)

            # 제목 후보 직후 회전 코드가 나오면 새 rule로 확정합니다.
            if pending_title and code_info:
                # 기존 section이 있으면 먼저 마감합니다.
                if current:
                    sections.append(finalize_rule_section(current))

                # 새 section을 시작합니다.
                current = start_section_from_code_and_title(
                    code_info=code_info,
                    title=pending_title["title"],
                    page_start=page_no,
                    first_extra_line=code_info.get("extra_text"),
                )

                # 제목 후보를 해제합니다.
                pending_title = None

                # 코드 대기 상태도 해제합니다.
                pending_code = None
                continue

            # 제목 후보가 있었지만 회전 코드가 아니면 이전 rule 본문으로 되돌립니다.
            if pending_title and not code_info:
                if current:
                    current["lines"].append(pending_title["title"])
                pending_title = None

            # 이번 줄이 회전 코드인 경우입니다.
            if code_info:
                # 기존 section을 먼저 마감합니다. 코드 단독이어도 여기서 마감해야 이전 rule이 사라지지 않습니다.
                if current:
                    sections.append(finalize_rule_section(current))
                    current = None

                # 코드 뒤에 제목이 붙어 있고 당사자 줄이 아니면 그 extra를 제목으로 사용합니다.
                if code_info.get("extra_text") and not is_party_line(code_info["extra_text"]):
                    current = start_section_from_code_and_title(
                        code_info=code_info,
                        title=code_info["extra_text"],
                        page_start=page_no,
                        first_extra_line=None,
                    )
                    pending_code = None
                    continue

                # 코드 뒤에 레드(A) 같은 본문이 붙어 있으면 임시 제목으로 시작합니다.
                if code_info.get("extra_text") and is_party_line(code_info["extra_text"]):
                    current = start_section_from_code_and_title(
                        code_info=code_info,
                        title=code_info["round_code"],
                        page_start=page_no,
                        first_extra_line=code_info["extra_text"],
                    )
                    pending_code = None
                    continue

                # 코드만 있으면 다음 줄 제목을 기다립니다.
                pending_code = {
                    "round_no": code_info["round_no"],
                    "round_code": code_info["round_code"],
                    "page_start": page_no,
                }
                continue

            # 코드가 먼저 나온 뒤 다음 줄 제목을 받는 경우입니다.
            if pending_code:
                # 당사자 줄이 아니라면 제목으로 사용합니다.
                if not is_party_line(line):
                    current = {
                        "round_no": pending_code["round_no"],
                        "round_code": pending_code["round_code"],
                        "rule_title": line,
                        "page_start": pending_code["page_start"],
                        "page_end": page_no,
                        "lines": [pending_code["round_code"], line],
                    }
                    pending_code = None
                    continue

                # 당사자 줄이 바로 나오면 임시 제목으로 시작합니다.
                current = {
                    "round_no": pending_code["round_no"],
                    "round_code": pending_code["round_code"],
                    "rule_title": pending_code["round_code"],
                    "page_start": pending_code["page_start"],
                    "page_end": page_no,
                    "lines": [pending_code["round_code"], pending_code["round_code"], line],
                }
                pending_code = None
                continue

            # 현재 줄이 rule 제목처럼 보이면 다음 줄이 회전 코드인지 확인하기 위해 보류합니다.
            # 회전-1처럼 첫 rule도 제목이 먼저 나오므로 current가 없어도 보류합니다.
            if looks_like_round_title(line):
                pending_title = {
                    "title": line,
                    "page_no": page_no,
                }
                continue

            # 일반 줄은 현재 section에 누적합니다.
            if current:
                current["lines"].append(line)
                current["page_end"] = page_no

    # 제목 후보가 끝까지 남으면 마지막 section 본문으로 되돌립니다.
    if pending_title and current:
        current["lines"].append(pending_title["title"])

    # 마지막 section을 마감합니다.
    if current:
        sections.append(finalize_rule_section(current))

    # 중복을 제거하고 번호 순서로 정렬합니다.
    sections = dedupe_sections_by_round_no(sections)

    # section 목록을 반환합니다.
    return sections



def find_first_round_rule_page(pages: List[PageText]) -> int:
    """회전 rule이 처음 등장하는 페이지를 찾습니다."""

    for page in pages:
        for line in page.clean_text.splitlines():
            if parse_round_code_line(line.strip()):
                return page.page_no
    return pages[0].page_no if pages else 1

def parse_round_code_line(line: str) -> Optional[Dict[str, Any]]:
    """회전-1 또는 회전-12 레드(A) 같은 줄을 파싱합니다."""

    # 회전 코드와 뒤쪽 나머지 문자열을 분리합니다.
    match = re.match(r"^회전-(?P<no>\d{1,2})(?:\s+(?P<extra>.+))?$", line)

    # 회전 코드가 아니면 None입니다.
    if not match:
        return None

    # 회전 번호입니다.
    round_no = int(match.group("no"))

    # 회전-1~회전-15만 인정합니다.
    if round_no < ROUND_NO_MIN or round_no > ROUND_NO_MAX:
        return None

    # 뒤쪽 텍스트입니다.
    extra = match.group("extra")

    # 결과를 반환합니다.
    return {
        "round_no": round_no,
        "round_code": f"회전-{round_no}",
        "extra_text": extra.strip() if extra else None,
    }


def start_section_from_code_and_title(
    code_info: Dict[str, Any],
    title: str,
    page_start: int,
    first_extra_line: Optional[str],
) -> Dict[str, Any]:
    """회전 코드와 제목으로 새 section을 시작합니다."""

    # 기본 lines입니다.
    lines = [code_info["round_code"], title]

    # 같은 줄에 레드(A) 같은 본문이 붙어 있으면 추가합니다.
    if first_extra_line:
        lines.append(first_extra_line)

    # 새 section을 반환합니다.
    return {
        "round_no": code_info["round_no"],
        "round_code": code_info["round_code"],
        "rule_title": title,
        "page_start": page_start,
        "page_end": page_start,
        "lines": lines,
    }


def looks_like_round_title(line: str) -> bool:
    """회전교차로 rule 제목처럼 보이는지 판단합니다."""

    # 문서 제목/헤더는 제외합니다.
    if "과실비율 비정형 기준" in line:
        return False

    # 당사자 줄은 제목이 아닙니다.
    if is_party_line(line):
        return False

    # 판례 본문의 이 사건 사고 같은 문장은 제외합니다.
    if "이 사건 사고" in line:
        return False

    # 회전 rule 제목에 자주 나오는 단어입니다.
    positive_keywords = ["진입", "회전", "진출", "차량", "차로변경"]

    # "사고"가 있으면 확실한 제목 후보입니다.
    if "사고" in line and any(keyword in line for keyword in positive_keywords):
        return True

    # 15번처럼 "사고"가 다음 줄로 끊긴 제목 조각도 후보로 인정합니다.
    if "차량 간" in line and any(keyword in line for keyword in positive_keywords):
        return True

    # 기본값은 False입니다.
    return False


def is_party_line(line: str) -> bool:
    """레드(A) 또는 블루(B) 당사자 설명 줄인지 판단합니다."""

    # 당사자 줄이면 True입니다.
    return bool(re.match(r"^(레드|블루)\s*\([AB]\)\s*:", line.strip()))


def dedupe_sections_by_round_no(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """같은 회전 번호가 중복될 경우 하나만 남깁니다."""

    # 번호별 section 저장소입니다.
    by_no: Dict[int, Dict[str, Any]] = {}

    # section을 순서대로 확인합니다.
    for section in sections:
        # 회전 번호입니다.
        round_no = int(section["round_no"])

        # 처음 나온 번호는 바로 저장합니다.
        if round_no not in by_no:
            by_no[round_no] = section
            continue

        # 더 긴 텍스트를 가진 section을 우선합니다.
        old_len = len(by_no[round_no].get("structured_text", ""))
        new_len = len(section.get("structured_text", ""))

        # 새 section이 더 길면 교체합니다.
        if new_len > old_len:
            by_no[round_no] = section

    # 번호 순서대로 반환합니다.
    return [by_no[round_no] for round_no in sorted(by_no)]


def finalize_rule_section(section: Dict[str, Any]) -> Dict[str, Any]:
    """rule section의 raw/clean/structured 텍스트를 완성합니다."""

    # 누적된 줄을 원문 텍스트로 합칩니다.
    raw_text = "\n".join(merge_broken_party_action_lines(section["lines"])).strip()

    # 기본 클리닝을 적용합니다.
    clean_text = clean_pdf_text(raw_text)

    # 파싱하기 좋은 구조로 정리합니다.
    structured_text = structure_rule_text(clean_text)

    # 결과를 section에 저장합니다.
    section["raw_text"] = raw_text
    section["clean_text"] = clean_text
    section["structured_text"] = structured_text
    section["file_title"] = safe_filename(f"{section['round_code']}_{section['rule_title']}")

    # 완성된 section을 반환합니다.
    return section


def merge_broken_party_action_lines(lines: List[str]) -> List[str]:
    """PDF 줄바꿈으로 끊긴 레드/블루 action 줄을 병합합니다."""

    result: List[str] = []
    pending: Optional[str] = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if pending:
                result.append(pending)
                pending = None
            result.append(raw_line)
            continue

        if is_party_line(line):
            if pending:
                result.append(pending)
            pending = line
            continue

        if pending and not is_party_line(line) and not is_section_marker(line) and should_merge_party_action_continuation(pending, line):
            pending = f"{pending} {line}"
            if not has_action_continuation_suffix(line):
                result.append(pending)
                pending = None
            continue

        if pending:
            result.append(pending)
            pending = None
        result.append(raw_line)

    if pending:
        result.append(pending)

    return result


def is_section_marker(line: str) -> bool:
    """party action이 끝나는 section marker인지 판단합니다."""

    return any(marker in line for marker in ["기본 과실비율", "과실비율 조정 예시", "사고 상황", "관련 법규", "참고 판례"])


def should_merge_party_action_continuation(pending: str, line: str) -> bool:
    """party action 줄의 실제 이어짐 후보만 병합합니다."""

    if has_action_continuation_suffix(pending):
        return True

    if len(line) > 80:
        return False

    return looks_like_action_continuation(line)


def looks_like_action_continuation(line: str) -> bool:
    """방향/차로/행동 표현으로 시작하는 이어진 action 줄인지 판단합니다."""

    if re.match(r"^(?:\d{1,2}시\s*방향|회전\s*[12]차로|[12]차로|진입|진출|회전|직진|좌회전|우회전|차로변경|진로변경)", line):
        return True

    return any(token in line for token in ["방향으로", "차로로", "차로에서", "차로변경", "진로변경", "진출", "회전 중"])


def has_action_continuation_suffix(line: str) -> bool:
    """다음 줄과 이어질 가능성이 높은 action 끝 표현인지 판단합니다."""

    return line.endswith(("차로로", "방향으로", "차로변경하여", "진로변경하여", "하여", "또는", "9시", "12시", "3시", "6시"))
