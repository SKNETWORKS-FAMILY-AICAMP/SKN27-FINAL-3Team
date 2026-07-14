from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


JsonDict = dict[str, Any]


RATIO_PATTERN = re.compile(
    r"(?P<percent>(?<![\d.])\d{1,3}\s*(?:%|퍼센트))|"
    r"(?P<colon>\d{1,2}\s*(?:%?\s*)[:：]\s*(?:%?\s*)\d{1,2}\s*%?)|"
    r"(?P<dae>\d{1,2}\s*대\s*\d{1,2})|"
    r"(?P<hal>\d{1,2}\s*할(?:\s*\d{1,2}\s*푼)?)|"
    r"(?P<fraction>\d{1,2}\s*분의\s*\d{1,2})"
)

DIRECT_FAULT_CONTEXT_PATTERN = re.compile(
    r"과실비율|과실\s*비율|책임비율|책임\s*비율|책임분담비율|"
    r"과실상계|책임제한|책임\s*제한|피해자의\s*과실|가해자의\s*책임|"
    r"피고의\s*책임.{0,20}제한|원고의\s*과실.{0,20}참작"
)
GENERAL_FAULT_CONTEXT_PATTERN = re.compile(
    r"과실|책임|손해배상책임|참작|제한|인정|분담"
)
PARTY_OR_ACCIDENT_CONTEXT_PATTERN = re.compile(
    r"원고|피고|피해자|가해자|운전자|망인|차량|교통사고|사고|공동불법행위"
)
LOW_CONFIDENCE_EXCLUSION_PATTERN = re.compile(
    r"연\s*\d{1,3}\s*%|이자|지연손해금|통상임금|가산|혈중알코올|"
    r"노동능력상실|상실률|장해율|장해|후유장해|금고\s*\d|징역\s*\d|"
    r"집행유예|사회봉사|수강\s*\d|업무시간|근무시간|산재|자기부담금|"
    r"보험약관|시각|시간|오전|오후|\d{1,2}:\d{2}\s*경"
)

SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.。])\s+|\n+")
TIME_COLON_PATTERN = re.compile(r"^\s*(?:[01]?\d|2[0-3])\s*[:：]\s*[0-5]\d(?:\s*[:：]\s*[0-5]\d)?\s*$")


@dataclass
class RatioCandidate:
    text: str
    sentence: str
    start: int
    end: int
    kind: str | None
    confidence: str
    candidate_context: str
    has_fault_context: bool
    has_direct_fault_context: bool
    has_party_or_accident_context: bool
    has_exclusion_context: bool


def split_sentences(text: str) -> list[str]:
    """Split text into sentence-like chunks without aggressive parsing."""

    if not text:
        return []

    chunks = SENTENCE_SPLIT_PATTERN.split(text)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def has_fault_context(text: str) -> bool:
    """Return True when text contains fault or liability context."""

    return bool(
        DIRECT_FAULT_CONTEXT_PATTERN.search(text)
        or GENERAL_FAULT_CONTEXT_PATTERN.search(text)
    )


def has_direct_fault_context(text: str) -> bool:
    """Return True when text contains direct fault-ratio keywords."""

    return bool(DIRECT_FAULT_CONTEXT_PATTERN.search(text))


def has_party_or_accident_context(text: str) -> bool:
    """Return True when text contains party or accident context."""

    return bool(PARTY_OR_ACCIDENT_CONTEXT_PATTERN.search(text))


def has_exclusion_context(text: str) -> bool:
    """Return True when text contains contexts that often create false positives."""

    return bool(LOW_CONFIDENCE_EXCLUSION_PATTERN.search(text))


def candidate_context(sentence: str, start: int, end: int, window: int = 50) -> str:
    """Return a local window around a ratio candidate."""

    context_start = max(0, start - window)
    context_end = min(len(sentence), end + window)
    return sentence[context_start:context_end]


def parse_percent_number(candidate_text: str) -> int | None:
    """Parse a percent candidate into an integer."""

    match = re.search(r"\d{1,3}", candidate_text)

    if not match:
        return None

    return int(match.group(0))


def has_leading_zero_percent(candidate_text: str) -> bool:
    """Return True for percent values like 015% or 07%."""

    match = re.search(r"\d{1,3}", candidate_text)

    if not match:
        return False

    digits = match.group(0)
    return len(digits) > 1 and digits.startswith("0")


def parse_colon_numbers(candidate_text: str) -> tuple[int, int] | None:
    """Parse a colon ratio candidate into two integers."""

    numbers = re.findall(r"\d{1,2}", candidate_text)

    if len(numbers) != 2:
        return None

    return int(numbers[0]), int(numbers[1])


def is_time_colon_expression(candidate_text: str) -> bool:
    """Return True when a colon candidate clearly looks like a time."""

    return bool(TIME_COLON_PATTERN.match(candidate_text))


def is_plausible_colon_ratio(candidate_text: str, context: str) -> bool:
    """
    Decide whether a 숫자:숫자 expression is likely a ratio, not a time.

    The expression is kept when direct/general fault context supports it, or
    when the two numbers add up to common ratio totals such as 10 or 100.
    """

    if is_time_colon_expression(candidate_text):
        return False

    if has_direct_fault_context(context):
        return True

    if has_fault_context(context) and has_party_or_accident_context(context):
        return True

    parsed = parse_colon_numbers(candidate_text)

    if parsed is None:
        return False

    left, right = parsed
    return left + right in {10, 100}


def is_valid_percent_candidate(candidate_text: str) -> bool:
    """Return True when a percent candidate has a plausible fault-ratio form."""

    if has_leading_zero_percent(candidate_text):
        return False

    value = parse_percent_number(candidate_text)

    if value is None:
        return False

    return 0 <= value <= 100


def is_valid_ratio_candidate(candidate_text: str, kind: str | None, context: str) -> bool:
    """Apply stage 1 candidate validation."""

    if kind == "percent":
        return is_valid_percent_candidate(candidate_text)

    if kind == "colon":
        return is_plausible_colon_ratio(candidate_text, context)

    return True


def classify_confidence(
    candidate_text: str,
    kind: str | None,
    sentence: str,
    start: int,
    end: int,
) -> str:
    """Classify ratio candidate confidence using the four-step rule."""

    context = candidate_context(sentence, start, end)

    if not is_valid_ratio_candidate(candidate_text, kind, context):
        return "low"

    if has_exclusion_context(context):
        return "low"

    if has_direct_fault_context(context):
        return "high"

    if has_fault_context(context) and has_party_or_accident_context(context):
        return "medium"

    return "low"


def find_ratio_expressions(text: str) -> list[dict[str, Any]]:
    """Find raw ratio expressions in text."""

    if not text:
        return []

    return [
        {
            "text": match.group(0),
            "start": match.start(),
            "end": match.end(),
            "kind": match.lastgroup,
        }
        for match in RATIO_PATTERN.finditer(text)
    ]


def extract_fault_ratio_candidates(text: str | None) -> list[dict[str, Any]]:
    """
    Extract ratio expression candidates.

    Preprocessing only stores a compact 과실비율 summary in the final JSONL.
    Candidate sentences are kept for debug review, not as final legal grounds.
    """

    if not text:
        return []

    candidates: list[dict[str, Any]] = []

    for sentence in split_sentences(text):
        for match in RATIO_PATTERN.finditer(sentence):
            context = candidate_context(sentence, match.start(), match.end())
            confidence = classify_confidence(
                match.group(0),
                match.lastgroup,
                sentence,
                match.start(),
                match.end(),
            )
            candidate = RatioCandidate(
                text=match.group(0),
                sentence=sentence,
                start=match.start(),
                end=match.end(),
                kind=match.lastgroup,
                confidence=confidence,
                candidate_context=context,
                has_fault_context=has_fault_context(context),
                has_direct_fault_context=has_direct_fault_context(context),
                has_party_or_accident_context=has_party_or_accident_context(context),
                has_exclusion_context=has_exclusion_context(context),
            )
            candidates.append(asdict(candidate))

    return candidates


def summarize_fault_ratio(candidates: list[dict[str, Any]]) -> str | None:
    """Build a compact ratio-expression summary from high-confidence candidates."""

    expressions: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        if candidate.get("confidence") != "high":
            continue

        expression = str(candidate.get("text") or "").strip()

        if not expression or expression in seen:
            continue

        seen.add(expression)
        expressions.append(expression)

    if not expressions:
        return None

    return ", ".join(expressions[:10])


def extract_fault_ratio_fields(row: JsonDict) -> JsonDict:
    """Fill only the final 과실비율 field from row text."""

    updated = dict(row)
    source_text = updated.get("이유") or updated.get("판례내용") or ""
    candidates = extract_fault_ratio_candidates(str(source_text))

    if not updated.get("과실비율"):
        updated["과실비율"] = summarize_fault_ratio(candidates)

    updated["_fault_ratio_candidates"] = candidates
    return updated


def extract_fault_ratio_rows(rows: list[JsonDict]) -> list[JsonDict]:
    """Extract fault-ratio fields for multiple rows."""

    return [extract_fault_ratio_fields(row) for row in rows]
