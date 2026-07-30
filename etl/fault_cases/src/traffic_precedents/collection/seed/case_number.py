"""대한민국 판례 사건번호 추출·정규화."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


CASE_KINDS = (
    "재추가",
    "재다",
    "재나",
    "재도",
    "다카",
    "가합",
    "가단",
    "가소",
    "구합",
    "구단",
    "카합",
    "카단",
    "헌가",
    "헌나",
    "헌다",
    "헌라",
    "헌마",
    "헌바",
    "다",
    "나",
    "도",
    "두",
    "누",
)

CASE_KIND_PATTERN = "|".join(
    re.escape(kind) for kind in sorted(CASE_KINDS, key=len, reverse=True)
)

FULL_CASE_RE = re.compile(
    rf"(?P<year>(?:19|20)?\d{{2}})\s*"
    rf"(?P<kind>{CASE_KIND_PATTERN})\s*"
    rf"(?P<number>\d+)"
)

CONTINUATION_RE = re.compile(
    r"^\s*[,·]\s*(?P<number>\d+)"
    r"(?=\s*(?:$|[,·;/)]|판결|결정|참조|및))"
)


@dataclass(frozen=True)
class CaseNumberMatch:
    """텍스트에서 발견한 사건번호 한 건."""

    normalized: str
    raw: str
    start: int
    end: int
    expanded_from_merged: bool = False


def normalize_case_number(value: str) -> str:
    """공백과 19xx 연도 표기를 정리한 사건번호를 반환합니다."""

    compact = re.sub(r"\s+", "", str(value or ""))
    match = re.fullmatch(
        rf"(?P<year>(?:19|20)?\d{{2}})"
        rf"(?P<kind>{CASE_KIND_PATTERN})"
        rf"(?P<number>\d+)",
        compact,
    )
    if not match:
        return compact

    year = match.group("year")
    if len(year) == 4 and year.startswith("19"):
        year = year[2:]

    return f"{year}{match.group('kind')}{match.group('number')}"


def case_number_search_variants(case_number: str) -> list[str]:
    """API 검색에 사용할 2자리·4자리 연도 변형을 반환합니다."""

    normalized = normalize_case_number(case_number)
    match = re.fullmatch(
        rf"(?P<year>\d{{2,4}})"
        rf"(?P<kind>{CASE_KIND_PATTERN})"
        rf"(?P<number>\d+)",
        normalized,
    )
    if not match:
        return [normalized]

    variants = [normalized]
    year = match.group("year")
    if len(year) == 2:
        century = "20" if int(year) <= 30 else "19"
        variants.append(f"{century}{year}{match.group('kind')}{match.group('number')}")

    return list(dict.fromkeys(variants))


def extract_case_numbers(text: str) -> list[CaseNumberMatch]:
    """본문에서 전체·병합 사건번호를 추출합니다."""

    source = str(text or "")
    matches: list[CaseNumberMatch] = []

    full_matches = list(FULL_CASE_RE.finditer(source))
    for index, match in enumerate(full_matches):
        raw = match.group(0)
        normalized = normalize_case_number(raw)
        matches.append(
            CaseNumberMatch(
                normalized=normalized,
                raw=raw,
                start=match.start(),
                end=match.end(),
            )
        )

        next_full_start = (
            full_matches[index + 1].start()
            if index + 1 < len(full_matches)
            else len(source)
        )
        cursor = match.end()
        while cursor < next_full_start:
            continuation = CONTINUATION_RE.match(source[cursor:next_full_start])
            if continuation is None:
                break

            prefix = f"{match.group('year')}{match.group('kind')}"
            continuation_raw = continuation.group(0)
            continuation_number = continuation.group("number")
            continuation_end = cursor + continuation.end()
            matches.append(
                CaseNumberMatch(
                    normalized=normalize_case_number(
                        f"{prefix}{continuation_number}"
                    ),
                    raw=continuation_raw.strip(" ,·"),
                    start=cursor + continuation.start(),
                    end=continuation_end,
                    expanded_from_merged=True,
                )
            )
            cursor = continuation_end

    deduplicated: dict[tuple[str, int, int], CaseNumberMatch] = {}
    for item in matches:
        deduplicated[(item.normalized, item.start, item.end)] = item
    return list(deduplicated.values())


def unique_case_numbers(values: Iterable[str]) -> list[str]:
    """사건번호를 정규화한 뒤 등장 순서대로 중복 제거합니다."""

    return list(dict.fromkeys(normalize_case_number(value) for value in values if value))

