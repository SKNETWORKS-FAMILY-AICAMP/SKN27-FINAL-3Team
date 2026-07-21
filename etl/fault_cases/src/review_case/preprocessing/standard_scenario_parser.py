from __future__ import annotations

import re
from dataclasses import dataclass


SIGNAL_RE = re.compile(r"(신호등\s*(?:있음|없음)|신호기\s*(?:있는|없는)|신호\s*(?:있음|없음))")
ROAD_WORDS = ("사거리", "삼거리", "교차로", "중앙선", "도로", "주차장", "회전교차로", "합류", "분기", "횡단보도", "이면도로")
FAULT_TYPES = ("기본과실", "수정과실", "준용")


@dataclass
class StandardScenarioResult:
    case_title: str | None
    case_condition: str | None
    fault_type: str | None
    reference_chart_key: str | None
    reference_chart_no: str | None
    reference_chart_sub_no: str | None
    standard_scenario_raw: str | None
    standard_scenario_keywords: list[str]
    signal_condition: str | None
    road_feature: str | None
    standard_a_behavior: str | None
    standard_b_behavior: str | None


def normalize_keyword(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" -:·ㆍ\t\n"))


def _split_title_condition(title: str | None) -> tuple[str | None, str | None, str | None]:
    if not title:
        return None, None, None
    fault_type = None
    for candidate in FAULT_TYPES:
        if candidate in title:
            fault_type = candidate
            title = title.replace(candidate, "")
    condition_match = re.search(r"\(([^)]*)\)", title)
    condition = condition_match.group(1).strip() if condition_match else None
    condition = condition or None
    title = re.sub(r"\([^)]*\)", "", title).strip()
    return title or None, condition, fault_type


def _is_road(value: str) -> bool:
    return any(word in value for word in ROAD_WORDS)


def _extract_reference(lines: list[str]) -> tuple[str | None, str | None, str | None]:
    joined = "\n".join(lines)
    subpattern = r"(\d{3})(?:\s*(?:-\s*([가-하0-9]+)|\(([가-하0-9]+)\)))?"
    match = re.search(rf"참고기준\s*{subpattern}", joined)
    if not match:
        match = re.search(rf"참고\s*기준\s*{subpattern}", joined)
    if not match:
        return None, None, None
    no = match.group(1)
    sub = match.group(2) or match.group(3)
    return (f"{no}-{sub}" if sub else no), no, sub


def parse_standard_scenario(text: str, header_title_raw: str | None = None) -> StandardScenarioResult:
    lines = [normalize_keyword(line) for line in (text or "").splitlines() if normalize_keyword(line)]
    reference_key, reference_no, reference_sub_no = _extract_reference(lines)

    ref_index = next((index for index, line in enumerate(lines) if "참고기준" in line or "참고 기준" in line), -1)
    overview_index = next((index for index, line in enumerate(lines) if "사례 개요" in line), len(lines))

    title_line = None
    if ref_index > 0:
        title_parts: list[str] = []
        for line in reversed(lines[:ref_index]):
            if header_title_raw and line == normalize_keyword(header_title_raw):
                break
            if line.startswith(("차대차", "차대인", "차대이륜차", "차대이륜", "보행자")):
                break
            if re.match(r"^\d+\.\s", line):
                break
            title_parts.append(line)
        title_line = " ".join(reversed(title_parts)).strip() or None

    keyword_lines = lines[ref_index + 1:overview_index] if ref_index >= 0 else []
    if not reference_key:
        reference_key, reference_no, reference_sub_no = _extract_reference(["참고기준", *keyword_lines])

    case_title, case_condition, fault_type = _split_title_condition(title_line)
    keywords = []
    for line in keyword_lines:
        line = re.sub(r"참고\s*기준", "", line).strip()
        if not line or re.fullmatch(r"\d{3}(?:-\d+)?", line):
            continue
        if re.fullmatch(r"\([가-하]\)", line):
            continue
        keywords.append(normalize_keyword(line))

    signal = next((item for item in keywords if SIGNAL_RE.search(item)), None)
    road = next((item for item in keywords if item != signal and _is_road(item)), None)
    behavior_candidates = [item for item in keywords if item not in {signal, road}]
    a_behavior = behavior_candidates[0] if len(behavior_candidates) >= 1 else None
    b_behavior = behavior_candidates[1] if len(behavior_candidates) >= 2 else None

    return StandardScenarioResult(
        case_title=case_title,
        case_condition=case_condition,
        fault_type=fault_type,
        reference_chart_key=reference_key,
        reference_chart_no=reference_no,
        reference_chart_sub_no=reference_sub_no,
        standard_scenario_raw=" ".join(keywords) if keywords else None,
        standard_scenario_keywords=keywords,
        signal_condition=signal,
        road_feature=road,
        standard_a_behavior=a_behavior,
        standard_b_behavior=b_behavior,
    )


def behavior_for_role(a_role: str | None, b_role: str | None, a_behavior: str | None, b_behavior: str | None) -> tuple[str | None, str | None]:
    claimant = a_behavior if a_role == "claimant" else b_behavior if b_role == "claimant" else None
    respondent = a_behavior if a_role == "respondent" else b_behavior if b_role == "respondent" else None
    return claimant, respondent
