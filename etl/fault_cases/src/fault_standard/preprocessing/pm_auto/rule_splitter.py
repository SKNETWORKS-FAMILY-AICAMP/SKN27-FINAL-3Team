# -*- coding: utf-8 -*-
"""도표1 ~ 도표38 rule section을 분리합니다."""

import re
from typing import Any, Dict, List, Optional, Tuple

from .cleaners import clean_pdf_text, structure_rule_text
from .file_utils import safe_filename
from .models import PageText


from .config import CHART_NO_MIN, CHART_NO_MAX

def split_pm_auto_rules(pages: List[PageText]) -> List[Dict[str, Any]]:
    """상세 본문을 도표1~도표38 rule section으로 분리합니다."""

    # 상세 기준은 13페이지부터 시작됩니다.
    detail_text = build_detail_text(pages)

    # 줄 단위 시작 offset과 header 후보를 찾습니다.
    headers = find_chart_headers(detail_text)

    # 도표 번호 기준으로 중복 header를 정리합니다.
    headers = dedupe_headers(headers)

    # 결과 section 목록입니다.
    sections: List[Dict[str, Any]] = []

    # 도표별로 텍스트 범위를 자릅니다.
    for idx, header in enumerate(headers):
        # 현재 도표 시작 위치입니다.
        start = header["offset"]

        # 다음 도표 시작 전까지를 현재 도표 범위로 봅니다.
        end = headers[idx + 1]["offset"] if idx + 1 < len(headers) else len(detail_text)

        # 도표 텍스트입니다.
        block_text = detail_text[start:end].strip()

        # header 직전의 page marker가 slice에 포함되지 않는 경우가 있어 시작 페이지 marker를 보강합니다.
        if header.get("page_no") and "__PAGE_START__" not in block_text[:80]:
            block_text = f"__PAGE_START__ {header['page_no']}\n" + block_text

        # rule section을 생성합니다.
        sections.append(finalize_rule_section(header["chart_no"], header["title"], block_text))

    # 누락된 도표가 있으면 placeholder가 아니라 빈 section 없이 품질 리포트에서 잡히게 둡니다.
    sections = dedupe_sections_by_chart_no(sections)

    # 도표 번호 순서대로 반환합니다.
    return sections


def build_detail_text(pages: List[PageText]) -> str:
    """상세 기준 텍스트를 하나로 합칩니다."""

    # 상세 기준 시작 페이지는 도표 header 앵커로 찾습니다.
    first_detail_page = find_first_chart_page(pages)
    selected = [page for page in pages if page.page_no >= first_detail_page]

    # 페이지 경계를 남기기 위해 page marker를 넣습니다.
    parts = []

    # 페이지별 텍스트를 합칩니다.
    for page in selected:
        parts.append(f"\n__PAGE_START__ {page.page_no}\n{page.clean_text}")

    # 하나의 텍스트로 반환합니다.
    return "\n".join(parts)



def find_first_chart_page(pages: List[PageText]) -> int:
    """첫 도표가 시작되는 페이지를 텍스트 앵커로 찾습니다."""

    for page in pages:
        if re.search(r"도표\s*0?1\b", page.clean_text) and ("수정요소" in page.clean_text or re.search(r"A\s*\d{1,3}\s*:\s*B\s*\d{1,3}", page.clean_text)):
            return page.page_no
    for page in pages:
        if re.search(r"도표\s*0?1\b", page.clean_text) and "사고" in page.clean_text:
            return page.page_no
    return pages[0].page_no if pages else 1

def find_chart_headers(detail_text: str) -> List[Dict[str, Any]]:
    """상세 텍스트에서 도표 시작 header를 찾습니다."""

    # header 후보 목록입니다.
    headers: List[Dict[str, Any]] = []

    # 현재 offset입니다.
    offset = 0

    # 현재 페이지 번호입니다.
    current_page = 0

    # 줄 단위로 확인합니다.
    for raw_line in detail_text.splitlines(keepends=True):
        # 줄바꿈을 제거한 검사 대상입니다.
        line = raw_line.strip()

        # page marker를 만나면 현재 페이지를 갱신합니다.
        page_match = re.match(r"__PAGE_START__\s+(\d+)", line)
        if page_match:
            current_page = int(page_match.group(1))

        # 도표 header를 파싱합니다.
        parsed = parse_chart_header_line(line)

        # header로 인정되면 기록합니다.
        if parsed:
            parsed["offset"] = offset
            parsed["page_no"] = current_page
            headers.append(parsed)

        # 다음 줄 offset을 갱신합니다.
        offset += len(raw_line)

    # header 후보를 반환합니다.
    return headers


def parse_chart_header_line(line: str) -> Optional[Dict[str, Any]]:
    """한 줄이 도표 시작 header인지 판단합니다."""

    # 빈 줄은 header가 아닙니다.
    if not line:
        return None

    # [도표해설]은 header가 아닙니다.
    if line.startswith("[도표"):
        return None

    # 설명문 안의 "- 도표 03:" 형태는 header가 아닙니다.
    if line.startswith("-"):
        return None

    # 도표 01 자동차 신호위반 사고 / 도표 33. 자동차 추돌 사고 형태입니다.
    match = re.match(r"^도표\s*(?P<no>\d{1,2})\.?\s+(?P<title>.+)$", line)

    # 도표 header가 아니면 숫자형 header를 확인합니다.
    used_numeric_header = False
    if not match:
        match = re.match(r"^(?P<no>\d{1,2})\.\s*(?P<title>.+)$", line)
        used_numeric_header = bool(match)

    # 매칭 실패 시 None입니다.
    if not match:
        return None

    # 도표 번호입니다.
    chart_no = int(match.group("no"))

    # 도표 범위 밖이면 제외합니다.
    if chart_no < CHART_NO_MIN or chart_no > CHART_NO_MAX:
        return None

    # 제목 후보입니다.
    title_candidate = normalize_chart_title(match.group("title"))

    # 설명문 속 "도표 03 : ..."처럼 콜론으로 시작하면 제외합니다.
    if title_candidate.startswith(":"):
        return None

    # 숫자형 header는 법규 조항 번호와 혼동되므로 사고 제목일 때만 허용합니다.
    if used_numeric_header and "사고" not in title_candidate:
        return None

    # 제목 후보가 사고 도표 제목처럼 보이지 않으면 제외합니다.
    if not looks_like_chart_title(title_candidate):
        return None

    # PDF 원문에서 읽힌 제목을 사용합니다.
    title = title_candidate

    # header 정보를 반환합니다.
    return {
        "chart_no": chart_no,
        "chart_code": f"도표{chart_no:02d}",
        "title": title,
    }


def normalize_chart_title(title: str) -> str:
    """도표 제목을 정리합니다."""

    # 목차 점선 흔적을 제거합니다.
    title = re.sub(r"\.{2,}.*$", "", title)

    # 對를 대로 통일합니다.
    title = title.replace("對", "대")

    # 대(對)가 대(대)처럼 남는 경우를 대로 통일합니다.
    title = title.replace("대(대)", "대")

    # 중복 공백을 줄입니다.
    title = re.sub(r"\s+", " ", title)

    # 앞뒤 공백을 제거합니다.
    return title.strip()


def title_key(text: str) -> str:
    """제목 비교용 key를 만듭니다."""

    # 對와 대를 통일합니다.
    text = text.replace("對", "대")

    # PDF 추출에서 대(對)가 대(대)처럼 남는 경우를 대로 통일합니다.
    text = text.replace("대(대)", "대")

    # 특수 따옴표를 제거합니다.
    text = text.replace("“", "").replace("”", "").replace('"', "")

    # 공백과 점을 제거합니다.
    text = re.sub(r"[\s.·]+", "", text)

    # 괄호는 비교에 중요하므로 보존합니다.
    return text


def looks_like_chart_title(title_candidate: str) -> bool:
    """도표 제목 후보가 실제 사고유형 제목처럼 보이는지 판단합니다."""

    if not title_candidate or len(title_candidate) < 2:
        return False

    negative_words = ["목 차", "관련법규", "참고판례", "도표해설", "기본과실", "수정요소"]
    if any(word in title_candidate for word in negative_words):
        return False

    positive_words = ["사고", "차량", "자동차", "PM", "이륜차", "횡단", "추돌", "개문", "교차로", "진로변경"]
    return any(word in title_candidate for word in positive_words)

def dedupe_headers(headers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """같은 도표 번호가 여러 번 잡힌 경우 앞쪽 header를 우선합니다."""

    # 번호별 header 저장소입니다.
    by_no: Dict[int, Dict[str, Any]] = {}

    # header를 순서대로 확인합니다.
    for header in headers:
        # 도표 번호입니다.
        chart_no = header["chart_no"]

        # 처음 잡힌 header만 사용합니다.
        if chart_no not in by_no:
            by_no[chart_no] = header

    # 번호 순서대로 반환합니다.
    return [by_no[chart_no] for chart_no in sorted(by_no)]


def extract_page_range(text: str) -> tuple[int, int]:
    """도표 block 안의 page marker로 시작/끝 페이지를 추정합니다."""

    # page marker를 모두 찾습니다.
    pages = [int(n) for n in re.findall(r"__PAGE_START__\s+(\d+)", text)]

    # marker가 없으면 0으로 반환합니다.
    if not pages:
        return 0, 0

    # 시작/끝 페이지를 반환합니다.
    return min(pages), max(pages)


def remove_page_markers(text: str) -> str:
    """도표 block에서 page marker를 제거합니다."""

    # page marker 줄을 제거합니다.
    text = re.sub(r"\n?__PAGE_START__\s+\d+\n?", "\n", text)

    # 앞뒤 공백을 제거합니다.
    return text.strip()


def finalize_rule_section(chart_no: int, title: str, block_text: str) -> Dict[str, Any]:
    """도표 section의 raw/clean/structured 텍스트를 완성합니다."""

    # page marker로 페이지 범위를 추정합니다.
    page_start, page_end = extract_page_range(block_text)

    # page marker를 제거한 원문입니다.
    raw_text = remove_page_markers(block_text)

    # 기본 클리닝을 적용합니다.
    clean_text = clean_pdf_text(raw_text)

    # 파싱하기 좋은 구조로 정리합니다.
    structured_text = structure_rule_text(clean_text)

    # 제목에 다른 도표 번호가 섞인 경우 본문 당사자 행동으로 제목을 보정합니다.
    title = refine_chart_title_from_body(title, structured_text)

    # 도표 코드를 만듭니다.
    chart_code = f"도표{chart_no:02d}"

    # section을 반환합니다.
    return {
        "chart_no": chart_no,
        "chart_code": chart_code,
        "rule_title": title,
        "page_start": page_start,
        "page_end": page_end,
        "raw_text": raw_text,
        "clean_text": clean_text,
        "structured_text": structured_text,
        "file_title": safe_filename(f"{chart_code}_{title}"),
    }


def refine_chart_title_from_body(title: str, text: str) -> str:
    """PDF header가 붙어서 깨진 제목을 본문 party action 기반으로 보정합니다."""

    if not has_embedded_chart_number(title):
        return title

    rear_end_actor = infer_rear_end_actor_from_body(text)
    if rear_end_actor:
        return f"{rear_end_actor} 추돌 사고"

    return remove_embedded_chart_number(title)


def has_embedded_chart_number(title: str) -> bool:
    """제목 안에 다른 숫자형 header가 섞였는지 확인합니다."""

    return bool(re.search(r"(?<!\d)\d{1,2}\.\s*", title))


def infer_rear_end_actor_from_body(text: str) -> Optional[str]:
    """당사자 action에서 추돌 주체를 추정합니다."""

    party_actions = re.findall(r"(?m)^(PM|자동차)\s*[AB]\s*:\s*(.+)$", text)

    for party_type, action in party_actions:
        if "추돌" in action and "피추돌" not in action:
            return party_type

    return None


def remove_embedded_chart_number(title: str) -> str:
    """제목 앞에 섞인 숫자형 header를 제거합니다."""

    return re.sub(r"^(?:\d{1,2}\.\s*)+", "", title).strip()


def dedupe_sections_by_chart_no(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """같은 도표 번호가 중복될 경우 하나만 남깁니다."""

    # 번호별 section 저장소입니다.
    by_no: Dict[int, Dict[str, Any]] = {}

    # section을 순서대로 확인합니다.
    for section in sections:
        # 도표 번호입니다.
        chart_no = int(section["chart_no"])

        # 처음 나온 번호는 저장합니다.
        if chart_no not in by_no:
            by_no[chart_no] = section
            continue

        # 더 긴 텍스트를 가진 section을 우선합니다.
        old_len = len(by_no[chart_no].get("structured_text", ""))
        new_len = len(section.get("structured_text", ""))

        # 새 section이 더 길면 교체합니다.
        if new_len > old_len:
            by_no[chart_no] = section

    # 도표 번호 순서대로 반환합니다.
    return [by_no[chart_no] for chart_no in sorted(by_no)]
