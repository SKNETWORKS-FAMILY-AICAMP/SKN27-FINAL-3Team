# -*- coding: utf-8 -*-
"""보/차/거 기준 코드를 중심으로 rule section을 분리합니다."""

import re
from typing import Any, Dict, List, Optional

from .cleaners import clean_pdf_text, structure_rule_text
from .file_utils import safe_filename
from .models import PageText

try:
    from .config import MAX_REASONABLE_RULE_PAGE_SPAN
except Exception:
    MAX_REASONABLE_RULE_PAGE_SPAN = 6


def split_official_rules(pages: List[PageText]) -> List[Dict[str, Any]]:
    """상세 본문을 보/차/거 rule code 단위로 분리합니다."""

    # 상세 기준은 물리 페이지 39부터 시작됩니다.
    detail_text = build_detail_text(pages)

    # rule code header 후보를 찾습니다.
    headers = find_rule_code_headers(detail_text)

    # 같은 code가 중복되면 앞쪽 header를 우선합니다.
    headers = dedupe_headers(headers)

    # 결과 section 목록입니다.
    sections: List[Dict[str, Any]] = []

    # code별로 텍스트 범위를 자릅니다.
    for idx, header in enumerate(headers):
        # 현재 rule 시작 위치입니다.
        start = header["offset"]

        # 다음 rule code 전까지를 현재 rule 범위로 봅니다.
        end = headers[idx + 1]["offset"] if idx + 1 < len(headers) else len(detail_text)

        # rule block입니다.
        block_text = detail_text[start:end].strip()

        # 시작 page marker가 slice 밖에 있으면 보강합니다.
        if header.get("page_no") and "__PAGE_START__" not in block_text[:80]:
            block_text = f"__PAGE_START__ {header['page_no']}\n" + block_text

        # section을 생성합니다.
        sections.append(finalize_rule_section(header, block_text))

    # rule code 기준으로 중복을 제거합니다.
    sections = dedupe_sections_by_rule_code(sections)

    # 거43처럼 한 도표 안에 거43-1, 거43-2, 거43-3이 묶인 rule을 개별 rule로 확장합니다.
    sections = expand_combined_rule_groups(sections)

    # 확장 중 중복된 child section이 생길 수 있으므로 다시 한 번 중복을 정리합니다.
    sections = dedupe_sections_by_rule_code(sections)

    # 여러 기준이 한 도표/해설을 공유하는 경우 code별 해설을 보강합니다.
    sections = attach_shared_explanations_by_code(sections)

    # rule code 등장 순서대로 반환합니다.
    return sections



def attach_shared_explanations_by_code(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """공통 해설 페이지에 여러 rule code가 함께 적힌 경우 각 section에 해설을 보강합니다."""

    by_code = {section["rule_code"]: section for section in sections}

    for section in sections:
        code = section["rule_code"]

        # 이미 본문 해설에서 자신의 code가 설명되면 그대로 둡니다.
        if f"⊙{code}" in section.get("raw_text", ""):
            continue

        # 기본과실이 본문 안에서 명확히 추출될 수 있으면 보강하지 않습니다.
        if re.search(r"보행자의?\s*기본\s*과실비율을\s*\d{1,3}\s*%", section.get("raw_text", "")):
            continue

        shared_text = find_shared_explanation_text(code, sections)
        if not shared_text:
            continue

        rebuilt = rebuild_section_from_raw(
            section,
            f"{section['raw_text'].strip()}\n\n__SHARED_EXPLANATION__ {code}\n{shared_text.strip()}".strip(),
        )
        by_code[code] = rebuilt

    return [by_code[section["rule_code"]] for section in sections]


def find_shared_explanation_text(rule_code: str, sections: List[Dict[str, Any]]) -> Optional[str]:
    """다른 section에서 특정 rule code가 포함된 공통 해설을 찾습니다."""

    marker = f"⊙{rule_code}"
    for other in sections:
        raw = other.get("raw_text", "")
        if marker not in raw:
            continue
        start = raw.find(marker)
        # 공통 해설은 뒤쪽에 관련 법규까지 포함되어도 원문 보존과 비율 추출에 유리합니다.
        return raw[start:]
    return None

def build_detail_text(pages: List[PageText]) -> str:
    """상세 기준 텍스트를 하나로 합칩니다."""

    start_page_no = find_first_official_rule_page(pages)
    end_page_no = find_detail_end_page(pages, start_page_no)

    selected = [page for page in pages if start_page_no <= page.page_no <= end_page_no]

    parts = []
    for page in selected:
        parts.append(f"\n__PAGE_START__ {page.page_no}\n{page.clean_text}")

    return "\n".join(parts)


def find_first_official_rule_page(pages: List[PageText]) -> int:
    """보/차/거 rule code가 처음 등장하는 페이지를 찾습니다."""

    for page in pages:
        for line in page.clean_text.splitlines():
            if parse_rule_code_line(line.strip()):
                return page.page_no
    return pages[0].page_no if pages else 1


def find_detail_end_page(pages: List[PageText], start_page_no: int) -> int:
    """상세 기준의 끝 페이지를 별첨 변경대비표 직전으로 찾습니다."""

    end_page_no = pages[-1].page_no if pages else start_page_no
    for page in pages:
        if page.page_no <= start_page_no:
            continue
        if "변경대비표" in page.clean_text and "별첨" in page.clean_text:
            return max(start_page_no, page.page_no - 1)
    return end_page_no


def find_rule_code_headers(detail_text: str) -> List[Dict[str, Any]]:
    """상세 텍스트에서 보1, 차1-1, 거7-2 같은 code header를 찾습니다.

    PyMuPDF 추출 결과는 아래처럼 다양합니다.
    - 보1
    - 차1-1
    - 거43-1 자전거 전용도로 통행 자전거 대 진로변경 자동차
    - 거43 / -1 처럼 표 내부에서 깨진 code

    실제 rule header와 표 내부 code를 구분하기 위해 주변 줄을 함께 봅니다.
    """

    lines_with_offsets: List[Dict[str, Any]] = []
    offset = 0
    current_page = 0
    previous_lines: List[str] = []

    for raw_line in detail_text.splitlines(keepends=True):
        line = raw_line.strip()
        page_match = re.match(r"__PAGE_START__\s+(\d+)", line)
        if page_match:
            current_page = int(page_match.group(1))
        lines_with_offsets.append({
            "raw_line": raw_line,
            "line": line,
            "offset": offset,
            "page_no": current_page,
            "previous_lines": list(previous_lines),
        })
        if line:
            previous_lines.append(line)
            previous_lines = previous_lines[-8:]
        offset += len(raw_line)

    headers: List[Dict[str, Any]] = []
    skip_child_parent: Optional[str] = None

    for idx, item in enumerate(lines_with_offsets):
        line = item["line"]
        if not line or line.startswith("__PAGE_START__"):
            continue

        next_lines = [x["line"] for x in lines_with_offsets[idx + 1: idx + 5] if x["line"] and not x["line"].startswith("__PAGE_START__")]
        prev_lines = [x["line"] for x in lines_with_offsets[max(0, idx - 4): idx] if x["line"] and not x["line"].startswith("__PAGE_START__")]

        parsed = parse_rule_header_line(line, next_lines, prev_lines)
        if not parsed:
            continue

        # 거43-1/거43-2/거43-3처럼 제목 목록이 연속으로 나온 경우,
        # 첫 child만 header로 잡고 나머지는 같은 group 본문 안에 남깁니다.
        parent_code = get_parent_code(parsed["rule_code"]) if "-" in parsed["rule_number"] else None
        if parent_code and skip_child_parent == parent_code:
            continue
        if parent_code and is_start_of_child_header_group(idx, lines_with_offsets, parent_code):
            skip_child_parent = parent_code
        elif not parent_code:
            skip_child_parent = None

        parsed["offset"] = item["offset"]
        parsed["page_no"] = item["page_no"]
        if not parsed.get("rule_title"):
            parsed["rule_title"] = infer_title_from_previous_lines(item["previous_lines"])
        headers.append(parsed)

    return headers


def parse_rule_header_line(line: str, next_lines: List[str] | None = None, prev_lines: List[str] | None = None) -> Optional[Dict[str, Any]]:
    """주변 줄을 참고해 rule header를 파싱합니다."""

    next_lines = next_lines or []
    prev_lines = prev_lines or []

    # code + title 한 줄형입니다. 예: 거43-1 자전거 전용도로...
    inline = re.match(r"^(?P<prefix>보|차|거)(?P<number>\d+(?:-\d+)?)\s+(?P<title>.+)$", line)
    if inline:
        title = clean_title(inline.group("title"))
        if title and not is_noise_title_line(title):
            return {
                "rule_code": f"{inline.group('prefix')}{inline.group('number')}",
                "rule_prefix": inline.group("prefix"),
                "rule_number": inline.group("number"),
                "rule_title": title,
            }

    # code 단독형입니다. 단, 바로 다음 줄이 '-1'이면 표 내부에서 깨진 code라 header로 보지 않습니다.
    solo = re.fullmatch(r"(?P<prefix>보|차|거)(?P<number>\d+(?:-\d+)?)", line)
    if solo:
        if next_lines and re.fullmatch(r"-\s*\d+", next_lines[0]):
            return None
        return {
            "rule_code": f"{solo.group('prefix')}{solo.group('number')}",
            "rule_prefix": solo.group("prefix"),
            "rule_number": solo.group("number"),
            "rule_title": "",
        }

    return None


def is_start_of_child_header_group(idx: int, lines_with_offsets: List[Dict[str, Any]], parent_code: str) -> bool:
    """연속 child header 목록의 첫 줄인지 확인합니다."""

    current = lines_with_offsets[idx]["line"]
    if not current.startswith(parent_code + "-"):
        return False
    following = [x["line"] for x in lines_with_offsets[idx + 1: idx + 4] if x["line"] and not x["line"].startswith("__PAGE_START__")]
    return any(line.startswith(parent_code + "-") for line in following)


def parse_rule_code_line(line: str) -> Optional[Dict[str, Any]]:
    """한 줄이 rule code인지 판단합니다."""

    # 보1, 차1-1, 거7-2 같은 코드만 인정합니다.
    match = re.fullmatch(r"(?P<prefix>보|차|거)(?P<number>\d+(?:-\d+)?)", line)

    # 매칭되지 않으면 None입니다.
    if not match:
        return None

    # prefix입니다.
    prefix = match.group("prefix")

    # 번호 부분입니다.
    number = match.group("number")

    # rule code입니다.
    rule_code = f"{prefix}{number}"

    # 결과를 반환합니다.
    return {
        "rule_code": rule_code,
        "rule_prefix": prefix,
        "rule_number": number,
    }


def infer_title_from_previous_lines(previous_lines: List[str]) -> str:
    """rule code 바로 위쪽 줄에서 rule 제목을 추정합니다."""

    # 뒤에서부터 적합한 제목 후보를 찾습니다.
    for line in reversed(previous_lines):
        # 제목이 될 수 없는 줄은 건너뜁니다.
        if is_noise_title_line(line):
            continue

        # code 줄과 목차 줄은 제목이 아닙니다.
        if parse_rule_code_line(line):
            continue

        # 적합한 줄을 제목으로 반환합니다.
        return clean_title(line)

    # 못 찾으면 빈 제목을 반환합니다.
    return ""


def is_noise_title_line(line: str) -> bool:
    """제목 후보에서 제외할 줄인지 판단합니다."""

    # page marker는 제외합니다.
    if line.startswith("__PAGE_START__"):
        return True

    # 짧은 한자/방향 표기는 제외합니다.
    if line in {"내", "후", "전", "대", "기준"}:
        return True

    # 장/절 번호만 있는 줄은 제외합니다.
    if re.fullmatch(r"\d+\)|\(\d+\)|[가-하]\.", line):
        return True

    # 기본 과실비율이나 당사자 줄은 제목이 아닙니다.
    if any(token in line for token in ["기본 과실비율", "과실비율", "(A)", "(B)", "(보)", "(차)", "※"]):
        return True

    # 수정요소 줄은 제목이 아닙니다.
    if re.search(r"[+-]\s*\d{1,2}|비적용", line):
        return True

    # 헤더성 문구는 제외합니다.
    if "세부유형별 과실비율 적용기준" in line:
        return True

    # 기본값은 제목 후보로 봅니다.
    return False


def clean_title(title: str) -> str:
    """추정한 제목을 파일명/JSON에 넣기 좋게 정리합니다."""

    # 對가 정규화된 대(대)를 대로 바꿉니다.
    title = title.replace("대(대)", "대")

    # 중복 공백을 줄입니다.
    title = re.sub(r"\s+", " ", title)

    # 앞뒤 공백을 제거합니다.
    return title.strip()



def infer_title_from_block_after_code(raw_text: str, rule_code: str) -> str:
    """rule code 다음 줄에서 제목을 다시 추정합니다."""

    # 줄 목록을 만듭니다.
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    # rule code 위치를 찾습니다.
    try:
        code_index = lines.index(rule_code)
    except ValueError:
        return ""

    # code 이후 몇 줄만 확인합니다.
    for line in lines[code_index + 1: code_index + 6]:
        # 제목 후보가 아니면 건너뜁니다.
        if is_noise_title_line(line):
            continue

        # 다른 rule code면 건너뜁니다.
        if parse_rule_code_line(line):
            continue

        # 제목처럼 보이면 반환합니다.
        return clean_title(line)

    # 못 찾으면 빈 문자열입니다.
    return ""



def expand_combined_rule_groups(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """거43처럼 하나의 도표 안에 여러 세부 rule이 있는 section을 개별 rule로 확장합니다."""

    # 확장 후 section을 저장합니다.
    expanded: List[Dict[str, Any]] = []

    # 인덱스로 순회해서 다음 section과 결합할 수 있게 합니다.
    idx = 0

    # section을 순서대로 확인합니다.
    while idx < len(sections):
        # 현재 section입니다.
        section = sections[idx]

        # 현재 section 안에서 child rule header를 찾습니다.
        child_headers = find_child_rule_headers(section["raw_text"])

        # child header가 2개 이상이면 묶음형 rule 후보입니다.
        if len(child_headers) >= 2:
            # child code의 parent code입니다. 예: 거43-1 -> 거43
            parent_code = get_parent_code(child_headers[0]["rule_code"])

            # child header가 시작되는 지점 전/후로 현재 section을 나눕니다.
            before_text, child_header_text = split_raw_at_first_child_header(section["raw_text"])

            # 현재 section이 parent가 아니라면 앞부분은 기존 rule로 보존합니다.
            if section["rule_code"] != parent_code and before_text.strip():
                expanded.append(rebuild_section_from_raw(section, before_text))

            # 다음 section이 parent code라면 child header와 parent body를 결합합니다.
            next_section = sections[idx + 1] if idx + 1 < len(sections) else None
            if next_section and next_section["rule_code"] == parent_code:
                group_raw_text = f"{child_header_text.strip()}\n{next_section['raw_text'].strip()}".strip()
                group_page_start = min(section["page_end"], next_section["page_start"])
                group_page_end = next_section["page_end"]
                idx += 1
            else:
                group_raw_text = section["raw_text"]
                group_page_start = section["page_start"]
                group_page_end = section["page_end"]

            # child rule별로 section을 만듭니다.
            for child in child_headers:
                expanded.append(
                    build_child_section_from_group(
                        child=child,
                        parent_code=parent_code,
                        combined_codes=[item["rule_code"] for item in child_headers],
                        group_raw_text=group_raw_text,
                        page_start=group_page_start,
                        page_end=group_page_end,
                    )
                )

            # 다음 section으로 넘어갑니다.
            idx += 1
            continue

        # child header가 없으면 일반 section으로 보존합니다.
        expanded.append(section)

        # 다음 section으로 넘어갑니다.
        idx += 1

    # 혹시 남은 parent base section이 있으면 제거합니다.
    expanded = remove_parent_only_combined_sections(expanded)

    # 확장 결과를 반환합니다.
    return expanded


def find_child_rule_headers(raw_text: str) -> List[Dict[str, str]]:
    """section 내부의 child rule header를 찾습니다.

    다음 두 형태를 모두 지원합니다.
    - 거43-1 자전거 전용도로 통행 자전거 대 진로변경 자동차
    - 거43 / -1 처럼 표 안에서 깨진 code
    """

    headers: List[Dict[str, str]] = []
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    idx = 0
    while idx < len(lines):
        line = lines[idx]

        match = re.match(r"^(?P<prefix>보|차|거)(?P<number>\d+-\d+)\s+(?P<title>.+)$", line)
        if match:
            title = clean_title(match.group("title"))
            if title and not is_noise_title_line(title):
                headers.append({
                    "rule_code": f"{match.group('prefix')}{match.group('number')}",
                    "rule_prefix": match.group("prefix"),
                    "rule_number": match.group("number"),
                    "rule_title": title,
                })
            idx += 1
            continue

        # 거43 / -1 분리형. 제목은 같은 section 앞쪽의 child title 목록에서 이미 확보되는 경우가 많으므로,
        # 여기서는 title이 없을 때만 fallback title로 code를 사용합니다.
        split_parent = re.fullmatch(r"(?P<prefix>보|차|거)(?P<base>\d+)", line)
        if split_parent and idx + 1 < len(lines):
            split_child = re.fullmatch(r"-\s*(?P<child>\d+)", lines[idx + 1])
            if split_child:
                code = f"{split_parent.group('prefix')}{split_parent.group('base')}-{split_child.group('child')}"
                headers.append({
                    "rule_code": code,
                    "rule_prefix": split_parent.group("prefix"),
                    "rule_number": f"{split_parent.group('base')}-{split_child.group('child')}",
                    "rule_title": code,
                })
                idx += 2
                continue

        idx += 1

    # 같은 code가 title형과 split형으로 동시에 잡히면 title형을 우선합니다.
    by_code: Dict[str, Dict[str, str]] = {}
    for header in headers:
        code = header["rule_code"]
        old = by_code.get(code)
        if old is None or old.get("rule_title") == code:
            by_code[code] = header

    return list(by_code.values())

def get_parent_code(rule_code: str) -> str:
    """거43-1 같은 child code에서 parent code 거43을 반환합니다."""

    # 하이픈 앞까지를 parent code로 봅니다.
    return rule_code.split("-")[0]


def split_raw_at_first_child_header(raw_text: str) -> tuple[str, str]:
    """raw_text를 첫 child rule header 기준으로 앞/뒤로 나눕니다."""

    # 전체 줄입니다.
    lines = raw_text.splitlines()

    # 첫 child header index입니다.
    first_idx = None

    # 줄을 순서대로 확인합니다.
    for idx, line in enumerate(lines):
        if re.match(r"^\s*(보|차|거)\d+-\d+\s+.+", line.strip()) or (re.fullmatch(r"(보|차|거)\d+", line.strip()) and idx + 1 < len(lines) and re.fullmatch(r"-\s*\d+", lines[idx + 1].strip())):
            first_idx = idx
            break

    # child header가 없으면 전체를 앞쪽으로 반환합니다.
    if first_idx is None:
        return raw_text, ""

    # 앞쪽 텍스트입니다.
    before = "\n".join(lines[:first_idx]).strip()

    # child header부터 끝까지입니다.
    after = "\n".join(lines[first_idx:]).strip()

    # 둘을 반환합니다.
    return before, after


def rebuild_section_from_raw(section: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
    """기존 section의 raw_text가 잘렸을 때 clean/structured를 다시 계산합니다."""

    # 복사본을 만듭니다.
    copied = dict(section)

    # raw_text를 교체합니다.
    copied["raw_text"] = truncate_spillover_text(raw_text.strip(), section["rule_prefix"])

    # clean_text를 다시 계산합니다.
    copied["clean_text"] = clean_pdf_text(copied["raw_text"])

    # structured_text를 다시 계산합니다.
    copied["structured_text"] = structure_rule_text(copied["clean_text"])

    # 반환합니다.
    return copied


def build_child_section_from_group(
    child: Dict[str, str],
    parent_code: str,
    combined_codes: List[str],
    group_raw_text: str,
    page_start: int,
    page_end: int,
) -> Dict[str, Any]:
    """묶음형 group raw_text에서 child rule section을 만듭니다."""

    # child title을 앞에 보강한 raw_text입니다.
    raw_text = truncate_spillover_text(f"{child['rule_title']}\n{group_raw_text}".strip(), child["rule_prefix"])

    # clean_text를 계산합니다.
    clean_text = clean_pdf_text(raw_text)

    # structured_text를 계산합니다.
    structured_text = structure_rule_text(clean_text)

    # child section을 반환합니다.
    return {
        "rule_code": child["rule_code"],
        "rule_prefix": child["rule_prefix"],
        "rule_number": child["rule_number"],
        "rule_title": child["rule_title"],
        "page_start": page_start,
        "page_end": page_end,
        "raw_text": raw_text,
        "clean_text": clean_text,
        "structured_text": structured_text,
        "file_title": safe_filename(f"{child['rule_code']}_{child['rule_title']}"),
        "combined_parent_code": parent_code,
        "combined_rule_codes": combined_codes,
    }


def remove_parent_only_combined_sections(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """child rule로 확장된 parent base section을 제거합니다."""

    # child가 가진 parent code 목록입니다.
    parent_codes = {
        section.get("combined_parent_code")
        for section in sections
        if section.get("combined_parent_code")
    }

    # None은 제거합니다.
    parent_codes.discard(None)

    # parent code 자체 section은 제거합니다.
    return [
        section
        for section in sections
        if not (section["rule_code"] in parent_codes and "-" not in section["rule_number"])
    ]


def dedupe_headers(headers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """같은 rule code가 여러 번 잡힌 경우 앞쪽 header를 우선합니다."""

    # code별 header 저장소입니다.
    by_code: Dict[str, Dict[str, Any]] = {}

    # header를 순서대로 확인합니다.
    for header in headers:
        # rule code입니다.
        code = header["rule_code"]

        # 처음 잡힌 header만 사용합니다.
        if code not in by_code:
            by_code[code] = header

    # 원래 등장 순서를 유지합니다.
    return [header for header in headers if by_code.get(header["rule_code"]) is header]


def extract_page_range(text: str) -> tuple[int, int]:
    """rule block 안의 page marker로 시작/끝 페이지를 추정합니다."""

    # page marker를 모두 찾습니다.
    pages = [int(n) for n in re.findall(r"__PAGE_START__\s+(\d+)", text)]

    # marker가 없으면 0으로 반환합니다.
    if not pages:
        return 0, 0

    # 시작/끝 페이지를 반환합니다.
    return min(pages), max(pages)


def remove_page_markers(text: str) -> str:
    """rule block에서 page marker를 제거합니다."""

    # page marker 줄을 제거합니다.
    text = re.sub(r"\n?__PAGE_START__\s+\d+\n?", "\n", text)

    # 앞뒤 공백을 제거합니다.
    return text.strip()


def finalize_rule_section(header: Dict[str, Any], block_text: str) -> Dict[str, Any]:
    """rule section의 raw/clean/structured 텍스트를 완성합니다."""

    # 다음 rule code가 나오지 않는 장의 마지막 도표는 다음 장 본문까지 포함될 수 있습니다.
    # 페이지 수 제한 전에 문서의 장 표지 문법으로 실제 경계를 먼저 확정합니다.
    _, header_slice_page_end = extract_page_range(block_text)
    block_text, chapter_boundary_truncated = truncate_at_next_chapter_boundary(block_text, header["rule_prefix"])

    # 구조 경계를 적용한 뒤 page marker로 실제 도표 페이지 범위를 추정합니다.
    page_start, original_page_end = extract_page_range(block_text)

    # 비정상적으로 긴 rule section은 우선 합리적 페이지 범위 안쪽으로 제한합니다.
    block_text = limit_block_page_span(block_text, page_start, MAX_REASONABLE_RULE_PAGE_SPAN)
    page_start, page_end = extract_page_range(block_text)

    # page marker와 반복 footer/header를 제거하되, 법규/판례가 다음 페이지에 이어지는 경우는 보존합니다.
    before_spillover = remove_page_markers(strip_layout_noise_lines(block_text))
    raw_text = truncate_spillover_text(before_spillover, header["rule_prefix"])

    # PyMuPDF는 rule code 다음 줄에 제목이 오는 경우가 많으므로 block 내부에서도 제목을 다시 추정합니다.
    block_title = infer_title_from_block_after_code(raw_text, header["rule_code"])

    # block 내부 제목이 더 구체적이면 그 제목을 사용합니다.
    if block_title:
        header["rule_title"] = block_title

    # rule title을 앞에 보강합니다.
    if header.get("rule_title") and not raw_text.startswith(header["rule_title"]):
        raw_text = f"{header['rule_title']}\n{raw_text}"

    # 기본 클리닝을 적용합니다.
    clean_text = clean_pdf_text(raw_text)

    # 파싱하기 좋은 구조로 정리합니다.
    structured_text = structure_rule_text(clean_text)

    # section을 반환합니다.
    return {
        "rule_code": header["rule_code"],
        "rule_prefix": header["rule_prefix"],
        "rule_number": header["rule_number"],
        "rule_title": header.get("rule_title") or header["rule_code"],
        "page_start": page_start,
        "page_end": page_end,
        "raw_text": raw_text,
        "clean_text": clean_text,
        "structured_text": structured_text,
        "boundary_quality": {
            "page_span_limited": bool(original_page_end and page_end and original_page_end > page_end),
            "original_page_end": original_page_end,
            "limited_page_end": page_end,
            "header_slice_page_end": header_slice_page_end,
            "chapter_boundary_truncated": chapter_boundary_truncated,
            "spillover_truncated": chapter_boundary_truncated or len(raw_text) < len(before_spillover.strip()),
        },
        "file_title": safe_filename(f"{header['rule_code']}_{header.get('rule_title') or header['rule_code']}"),
    }


def truncate_at_next_chapter_boundary(block_text: str, rule_prefix: str) -> tuple[str, bool]:
    """현재 도표 뒤에 이어진 다른 사고 주체 장의 본문을 제거합니다.

    특정 rule code나 페이지 번호를 사용하지 않고, PDF에 반복되는
    ``과실비율 적용기준(사고유형별) / 제N장 / 1. 적용 범위`` 장 표지를 인식합니다.
    같은 장의 반복 머리말은 보존하고 현재 prefix와 다른 장 표지만 경계로 사용합니다.
    """

    chapter_prefix_by_no = {"1": "보", "2": "차", "3": "거"}
    lines = block_text.splitlines()

    for idx, raw_line in enumerate(lines):
        chapter_match = re.fullmatch(r"제\s*([123])\s*장\.?(?:\s*.*)?", raw_line.strip())
        if not chapter_match:
            continue

        window_start = max(0, idx - 6)
        window_end = min(len(lines), idx + 6)
        window = " ".join(line.strip() for line in lines[window_start:window_end] if line.strip())
        compact_window = re.sub(r"\s+", "", window)
        if "과실비율적용기준(사고유형별)" not in compact_window or "1.적용범위" not in compact_window:
            continue

        next_prefix = chapter_prefix_by_no.get(chapter_match.group(1))
        if not next_prefix or next_prefix == rule_prefix:
            continue

        # 장 번호 앞의 분할 표지(예: 자동차 / (이륜차 포함)의 / 과실비율...)까지 함께 제거합니다.
        boundary_idx = idx
        for back_idx in range(idx - 1, window_start - 1, -1):
            stripped = lines[back_idx].strip()
            if re.fullmatch(r"__PAGE_START__\s+\d+", stripped):
                boundary_idx = back_idx
                break
            if not stripped:
                boundary_idx = back_idx + 1
                break
            boundary_idx = back_idx

        return "\n".join(lines[:boundary_idx]).strip(), True

    return block_text, False


def limit_block_page_span(block_text: str, page_start: int, max_span: int) -> str:
    """rule section이 다음 장까지 길게 번진 경우 page marker 기준으로 1차 제한합니다."""

    if not page_start or max_span <= 0:
        return block_text

    max_page = page_start + max_span - 1
    lines = block_text.splitlines()
    kept: List[str] = []
    current_page = page_start
    for line in lines:
        page_match = re.match(r"__PAGE_START__\s+(\d+)", line.strip())
        if page_match:
            current_page = int(page_match.group(1))
            if current_page > max_page:
                break
        kept.append(line)
    return "\n".join(kept).strip()


def strip_layout_noise_lines(text: str) -> str:
    """PDF 페이지마다 반복되는 장 제목/목차 footer를 제거합니다."""

    lines = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped in {"목차", "목 차"}:
            continue
        if stripped in {
            "제1장. 자동차와 보행자의 사고",
            "제2장. 자동차와 자동차(이륜차 포함)의 사고",
            "제3장. 자동차와 자전거(농기계 포함)의 사고",
        }:
            continue
        lines.append(raw_line)
    return "\n".join(lines)


def truncate_spillover_text(raw_text: str, rule_prefix: str) -> str:
    """다음 장/목차가 rule 본문에 번져 들어온 경우 잘라냅니다."""

    lines = raw_text.splitlines()
    kept: List[str] = []

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if idx > 0 and is_spillover_marker(stripped, rule_prefix):
            break
        kept.append(line)

    return "\n".join(kept).strip()


def is_spillover_marker(line: str, rule_prefix: str) -> bool:
    """현재 rule 이후의 명확한 별첨/다음 자료 marker인지 판단합니다."""

    # 반복 footer/header는 strip_layout_noise_lines에서 제거하므로 여기서 잘라내지 않습니다.
    if "변경대비표" in line and "별첨" in line:
        return True

# rule code 단독 줄은 표 내부에서 깨진 code일 수 있으므로 여기서 자르지 않습니다.
    return False


def dedupe_sections_by_rule_code(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """같은 rule code가 중복될 경우 하나만 남깁니다."""

    # code별 section 저장소입니다.
    by_code: Dict[str, Dict[str, Any]] = {}

    # section을 순서대로 확인합니다.
    for section in sections:
        # rule code입니다.
        code = section["rule_code"]

        # 처음 나온 code는 저장합니다.
        if code not in by_code:
            by_code[code] = section
            continue

        # 더 긴 텍스트를 가진 section을 우선합니다.
        old_len = len(by_code[code].get("structured_text", ""))
        new_len = len(section.get("structured_text", ""))

        # 새 section이 더 길면 교체합니다.
        if new_len > old_len:
            by_code[code] = section

    # 처음 등장 순서를 유지합니다.
    return [by_code[section["rule_code"]] for section in sections if by_code.get(section["rule_code"]) is section]
