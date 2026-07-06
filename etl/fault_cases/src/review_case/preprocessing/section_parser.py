from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import ReviewCaseText
from .ratio_parser import find_final_ratio_text


SECTION_ALIASES = {
    "accident": ["사고내용"],
    "reference": ["참고 인정기준", "참고인정기준"],
    "arguments": ["주장 내용", "주장내용"],
    "evidence": ["입증 자료", "입증자료"],
    "issue": ["주요 쟁점", "주요쟁점"],
    "basis": ["결정 근거", "결정근거"],
    "reason": ["결정 이유", "결정이유"],
}


@dataclass
class HeaderResult:
    party_type: str | None
    header_title_raw: str | None
    header_accident_group: str | None
    header_road_context: str | None
    header_parse_method: str | None


@dataclass
class SectionsResult:
    accident_content: str | None
    reference_standard_no: str | None
    reference_standard_text: str | None
    base_fault_ratio_text: str | None
    claimant_argument: str | None
    respondent_argument: str | None
    evidence_text: str | None
    main_issue: str | None
    decision_basis: str | None
    decision_reason: str | None
    final_ratio_text: str | None


def _squash(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"\s+", " ", value).strip(" -:\n\t")
    value = _remove_navigation_tail(value)
    return value or None


def _remove_navigation_tail(value: str) -> str:
    """Drop repeated PDF navigation/footer text that appears between case pages."""

    index = value.find("목차보기")
    if index < 0:
        return value
    prefix = value[:index]
    chapter_matches = list(
        re.finditer(
            r"\s[123]\.\s*(?:자동차와 자동차의 사고|자동차와 이륜차의 사고|고속도로의 사고)",
            prefix,
        )
    )
    nearby_matches = [match for match in chapter_matches if match.start() >= max(0, index - 160)]
    cut_at = nearby_matches[0].start() if nearby_matches else index
    return value[:cut_at].strip()


def parse_header(text: str) -> HeaderResult:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    review_index = next((index for index, line in enumerate(lines) if "심의번호" in line), min(len(lines), 8))
    candidates = lines[:review_index]
    title = next((line for line in candidates if line.startswith(("차대차", "차대인", "차대이륜", "차대이륜차", "이륜차", "보행자"))), None)
    if not title:
        return HeaderResult(None, None, None, None, None)

    party_match = re.match(r"(차대차|차대인|차대이륜차|차대이륜|이륜차|보행자)\s*(.*)", title)
    party = party_match.group(1) if party_match else None
    rest = party_match.group(2).strip() if party_match else title
    if " - " in rest or "-" in rest:
        left, right = re.split(r"\s*-\s*", rest, maxsplit=1)
        return HeaderResult(party, title, _squash(left), _squash(right), "hyphen_split")
    return HeaderResult(party, title, _squash(rest), None, "single_group")


def _find_label_positions(text: str) -> list[tuple[int, str, str]]:
    positions: list[tuple[int, str, str]] = []
    label_to_key = {label: key for key, labels in SECTION_ALIASES.items() for label in labels}
    line_start = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        compact = re.sub(r"\s+", "", stripped)
        for label, key in label_to_key.items():
            if compact == re.sub(r"\s+", "", label):
                positions.append((line_start + line.index(stripped), key, stripped))
                break
        line_start += len(line)
    if positions:
        return sorted(positions)

    for key, labels in SECTION_ALIASES.items():
        for label in labels:
            pattern = rf"(?m)^\s*{re.escape(label)}\s*$"
            for match in re.finditer(pattern, text):
                positions.append((match.start(), key, label))
    return sorted(positions)


def _section_map(text: str) -> dict[str, str]:
    positions = _find_label_positions(text)
    result: dict[str, str] = {}
    for index, (start, key, label) in enumerate(positions):
        if key in result:
            continue
        content_start = start + len(label)
        content_end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        result[key] = text[content_start:content_end].strip()
    return result


def _parse_reference(text: str | None) -> tuple[str | None, str | None, str | None]:
    if not text:
        return None, None, None
    no_match = re.search(r"(\d{3})(?:-\d+)?", text)
    base_match = re.search(r"(기본비율\s*A\s*:\s*B\s*=\s*\d{1,3}\s*:\s*\d{1,3})", text)
    cleaned = re.sub(r"^\s*\d{3}(?:-\d+)?", "", text).strip()
    return no_match.group(1) if no_match else None, _squash(cleaned), base_match.group(1) if base_match else None


def _split_bullets(body: str) -> tuple[str | None, str | None]:
    parts = [part.strip() for part in re.split(r"(?=•|●|- )", body) if part.strip()]
    if len(parts) >= 2:
        midpoint = len(parts) // 2
        return _squash(" ".join(parts[:midpoint])), _squash(" ".join(parts[midpoint:]))
    midpoint = len(body) // 2
    return _squash(body[:midpoint]), _squash(body[midpoint:])


def _parse_arguments(text: str | None, case: ReviewCaseText) -> tuple[str | None, str | None]:
    if case.layout_claimant_argument or case.layout_respondent_argument:
        return _squash(case.layout_claimant_argument), _squash(case.layout_respondent_argument)
    if not text:
        return None, None
    double_label = re.search(r"청구인\s*피청구인\s*(?P<body>.*)$", text, flags=re.S)
    if double_label:
        return _split_bullets(double_label.group("body"))
    claimant_match = re.search(r"청구인\s*(?P<body>.*?)(?:피청구인|$)", text, flags=re.S)
    respondent_match = re.search(r"피청구인\s*(?P<body>.*)$", text, flags=re.S)
    claimant = claimant_match.group("body") if claimant_match else None
    respondent = respondent_match.group("body") if respondent_match else None
    if not claimant and respondent:
        return _split_bullets(respondent)
    return _squash(claimant), _squash(respondent)


def parse_sections(case: ReviewCaseText) -> SectionsResult:
    sections = _section_map(case.clean_text)
    reference_no, reference_text, base_ratio = _parse_reference(sections.get("reference"))
    claimant, respondent = _parse_arguments(sections.get("arguments"), case)
    reason = _squash(sections.get("reason"))
    final_ratio_text = find_final_ratio_text(reason)
    if not final_ratio_text:
        final_ratio_text = find_final_ratio_text(case.clean_text[-1200:])
    return SectionsResult(
        accident_content=_squash(sections.get("accident")),
        reference_standard_no=reference_no,
        reference_standard_text=reference_text,
        base_fault_ratio_text=base_ratio,
        claimant_argument=claimant,
        respondent_argument=respondent,
        evidence_text=_squash(sections.get("evidence")),
        main_issue=_squash(sections.get("issue")),
        decision_basis=_squash(sections.get("basis")),
        decision_reason=reason,
        final_ratio_text=final_ratio_text,
    )
