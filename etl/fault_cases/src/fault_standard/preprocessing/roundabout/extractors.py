# -*- coding: utf-8 -*-
"""회전교차로 rule 내부 정보를 추출합니다."""

import re
from typing import Any, Dict, List, Optional, Tuple

from .cleaners import clean_pdf_text, normalize_spaces, structure_rule_text
from .file_utils import dedupe_rows


def extract_parties(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """레드(A), 블루(B) 차량 정보를 추출합니다."""

    # 결과 리스트입니다.
    parties: List[Dict[str, Any]] = []
    round_no = extract_round_no(rule_id, text)
    rule_title = extract_rule_title_from_text(text)

    # 레드(A) : ... 또는 블루(B) : ... 구간입니다. action이 다음 줄로 이어져도 함께 잡습니다.
    pattern = re.compile(
        r"(?ms)^\s*(?P<label>레드|블루)\s*\((?P<key>[AB])\)\s*:\s*(?P<action>.*?)(?=\n\s*(?:레드|블루)\s*\([AB]\)\s*:|\n\s*기본\s*과실비율|\Z)"
    )

    # 모든 당사자 줄을 찾습니다.
    for match in pattern.finditer(text):
        # 색상 한글입니다.
        color_ko = match.group("label")

        # A/B 키입니다.
        party_key = match.group("key")

        # 행동 원문입니다.
        action = normalize_party_action(match.group("action"))

        # 영문 색상입니다.
        party_color = "red" if color_ko == "레드" else "blue"

        # rule 번호별 강제 복원은 하지 않습니다.
        # action이 불완전하면 validator에서 dangling_action_suffix로 잡습니다.

        action_info = parse_party_action(action, rule_title)

        # party row를 추가합니다.
        parties.append(
            {
                "party_id": f"party_{rule_id}_{party_key}",
                "rule_id": rule_id,
                "party_key": party_key,
                "party_color": party_color,
                "party_label": f"{color_ko}({party_key})",
                "party_type": "vehicle",
                **action_info,
                "action_summary": action,
                "is_first_entry": "선진입" in action,
                "is_late_entry": "후진입" in action,
                "is_lane_changing": "차로변경" in action or "진로변경" in action,
                "is_exiting": "진출" in action,
                "violated_road_marking": None,
                "raw_text": f"{color_ko}({party_key}) : {action}",
            }
        )

    # 표 상단의 짧은 action에는 방향이나 차로변경 목적지가 생략되고, 사고 상황 본문에만
    # 명시되는 경우가 있습니다. rule 번호별 예외 없이 제목/사고상황의 명시 표현으로 보강합니다.
    enrich_parties_from_section_context(parties, text, rule_title)

    # 당사자 목록을 반환합니다.
    return parties


def parse_party_action(action: str, rule_title: str) -> Dict[str, Any]:
    """party action에서 역할/방향/차로 정보를 source와 함께 추출합니다."""

    role_info = infer_role_info(action, rule_title)
    entry_direction_info = extract_direction_info(action, "entry")
    exit_direction_info = extract_direction_info(action, "exit")

    # 회전교차로 도표 제목의 ``3시/12시/9시 진출부 사고``는 해당 도표의 명시적
    # 진출 방향입니다. action에 진출 동작은 있지만 방향이 생략된 경우에만 사용합니다.
    if "진출" in action and not exit_direction_info.get("value"):
        title_exit_direction = extract_exit_direction_from_title(rule_title)
        if title_exit_direction:
            exit_direction_info = {
                "value": title_exit_direction,
                "source": "rule_title_exit_direction",
                "confidence": 0.98,
            }

    return {
        "role_in_rule": role_info["value"],
        "role_source": role_info["source"],
        "role_confidence": role_info["confidence"],
        "entry_direction": entry_direction_info["value"],
        "entry_direction_source": entry_direction_info["source"],
        "entry_direction_confidence": entry_direction_info["confidence"],
        "entry_lane": extract_lane(action, "진입"),
        "circulation_lane": extract_lane(action, "회전"),
        "exit_direction": exit_direction_info["value"],
        "exit_direction_source": exit_direction_info["source"],
        "exit_direction_confidence": exit_direction_info["confidence"],
        "exit_lane": extract_lane(action, "진출"),
        "lane_change_from": extract_lane_change_from(action),
        "lane_change_to": extract_lane_change_to(action),
    }


def enrich_parties_from_section_context(
    parties: List[Dict[str, Any]],
    text: str,
    rule_title: str,
) -> None:
    """표 상단 action에서 생략된 값을 같은 도표의 명시적 본문으로 보강합니다.

    회전번호나 차량 색상을 기준으로 값을 넣지 않습니다. 제목에 명시된 진출 방향과
    ``사고 상황``에 명시된 ``X차로에서 Y차로로 변경`` 문법만 사용합니다.
    """

    accident_context = extract_between(text, "사고 상황", "기본 과실비율") or ""
    title_exit_direction = extract_exit_direction_from_title(rule_title)

    for party in parties:
        if party.get("is_exiting") and not party.get("exit_direction") and title_exit_direction:
            party["exit_direction"] = title_exit_direction
            party["exit_direction_source"] = "rule_title_exit_direction"
            party["exit_direction_confidence"] = 0.98

        if not party.get("is_lane_changing"):
            continue

        source_lane = party.get("lane_change_from") or party.get("circulation_lane")
        if source_lane and not party.get("lane_change_from"):
            party["lane_change_from"] = source_lane
            party["lane_change_from_source"] = "party_circulation_lane"
            party["lane_change_from_confidence"] = 0.9

        if party.get("lane_change_to"):
            continue

        target_lane = extract_lane_change_target_from_context(accident_context, source_lane)
        if target_lane:
            party["lane_change_to"] = target_lane
            party["lane_change_to_source"] = "explicit_accident_context"
            party["lane_change_to_confidence"] = 0.95


def extract_exit_direction_from_title(title: str) -> Optional[str]:
    """도표 제목의 명시적 진출부 방향을 반환합니다."""

    match = re.search(r"(?P<direction>(?:3시|6시|9시|12시))\s*(?:방향\s*)?진출부\s*사고", normalize_spaces(title))
    return f"{match.group('direction')} 방향" if match else None


def extract_lane_change_target_from_context(text: str, source_lane: Optional[str]) -> Optional[str]:
    """사고상황의 명시적인 차로변경 목적지를 추출합니다."""

    normalized = normalize_spaces(text)
    if not normalized:
        return None

    target_pattern = r"(?P<to>(?:회전|진출)[12]차로)(?:로)?\s*(?:차로|진로)(?:를\s*)?변경"
    if source_lane:
        match = re.search(
            rf"{re.escape(source_lane)}(?:에|에서|로)?(?:(?!충돌).){{0,160}}?{target_pattern}",
            normalized,
        )
        if match and match.group("to") != source_lane:
            return match.group("to")

    # 출발 차로를 action에서 알 수 없을 때는 본문 전체에서 목적지가 하나로만 명시된 경우만 사용합니다.
    targets = {match.group("to") for match in re.finditer(target_pattern, normalized)}
    return next(iter(targets)) if len(targets) == 1 else None


def normalize_party_action(action: str) -> str:
    """party action의 제어문자와 줄바꿈을 정리합니다."""

    action = clean_pdf_text(action)
    action = re.sub(r"\s*\n\s*", " ", action)
    action = normalize_spaces(action)
    return action


def extract_round_no(rule_id: str, text: str) -> Optional[int]:
    """rule_id 또는 본문에서 회전 번호를 추출합니다."""

    match = re.search(r"회전-(\d{1,2})", f"{rule_id}\n{text}")
    return int(match.group(1)) if match else None


def extract_rule_title_from_text(text: str) -> str:
    """rule 본문에서 제목을 추출합니다.

    특정 회전번호를 기준으로 보정하지 않고, 본문 첫머리의 회전-N 다음 줄을 제목으로 사용합니다.
    """

    lines = [normalize_spaces(line) for line in text.splitlines() if normalize_spaces(line)]
    for idx, line in enumerate(lines):
        if re.fullmatch(r"회전-\d{1,2}", line) and idx + 1 < len(lines):
            return lines[idx + 1]
        match = re.match(r"회전-\d{1,2}\s+(.+)", line)
        if match:
            return normalize_spaces(match.group(1))
    return ""


def has_dangling_action_suffix(action: str) -> bool:
    """action 끝이 조사/연결어에서 끊긴 것으로 보이는지 판단합니다."""

    action = normalize_spaces(action)
    dangling_suffixes = (
        "차로로",
        "방향으로",
        "차로변경하여",
        "진로변경하여",
        "9시",
        "12시",
        "3시",
        "6시",
    )
    return action.endswith(dangling_suffixes)


def extract_base_fault(text: str) -> Dict[str, Any]:
    """기본 과실비율 레드:블루를 추출합니다."""

    # 기본 과실비율 레드 20 : 블루 80 패턴입니다.
    match = re.search(r"기본\s*과실비율\s*레드\s*(?P<red>\d{1,3})\s*:\s*블루\s*(?P<blue>\d{1,3})", text)

    # 찾지 못하면 빈 구조를 반환합니다.
    if not match:
        return {
            "base_fault_type": "pair_ratio",
            "red_ratio": None,
            "blue_ratio": None,
            "party_a_ratio": None,
            "party_b_ratio": None,
            "normalized_ratio": None,
            "red_blue_normalized_ratio": None,
            "raw_text": None,
            "heavier_fault_party": None,
            "is_one_sided_fault": False,
        }

    # 레드 과실입니다.
    red = int(match.group("red"))

    # 블루 과실입니다.
    blue = int(match.group("blue"))

    # 기본과실 구조를 반환합니다.
    return {
        "base_fault_type": "pair_ratio",
        "red_ratio": red,
        "blue_ratio": blue,
        "party_a_ratio": red,
        "party_b_ratio": blue,
        "normalized_ratio": f"{red}:{blue}",
        "red_blue_normalized_ratio": f"{red}:{blue}",
        "raw_text": match.group(0),
        "heavier_fault_party": infer_heavier_color(red, blue),
        "is_one_sided_fault": (red == 100 and blue == 0) or (red == 0 and blue == 100),
    }


def extract_adjustment_factors(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """레드/블루별 과실비율 조정요소를 추출합니다."""

    factors: List[Dict[str, Any]] = []

    # 수정요소 구간을 우선 쓰되, 세로 라벨이 깨진 경우에도 전체 텍스트에서 후보를 찾습니다.
    block = extract_between(text, "과실비율 조정 예시", "사고 상황") or text

    # PyMuPDF 추출에서는 항목명과 +10/-10이 다음 줄로 분리될 수 있어 줄을 결합합니다.
    candidate_lines = merge_modifier_name_and_delta_lines(block.splitlines())

    pattern = re.compile(r"^(?P<color>레드|블루)\s*\((?P<key>[AB])\)\s*(?P<name>.+?)\s*(?P<delta>[+-]\s*\d{1,2})$")

    for line in candidate_lines:
        line = normalize_spaces(line)
        match = pattern.match(line)
        if not match:
            continue

        color = "red" if match.group("color") == "레드" else "blue"
        key = match.group("key")
        name = normalize_spaces(match.group("name"))
        raw_delta = match.group("delta").replace(" ", "")
        delta = int(raw_delta)

        factors.append({
            "adjustment_id": f"adj_{rule_id}_{len(factors)+1:03d}",
            "rule_id": rule_id,
            "target_party_key": key,
            "target_party_color": color,
            "target_party_label": f"{match.group('color')}({key})",
            "factor_name": name,
            "factor_category": classify_adjustment_factor(name),
            "delta": delta,
            "delta_direction": "increase" if delta > 0 else "decrease",
            "raw_delta": raw_delta,
            "raw_text": line,
            "condition_text": None,
            "explanation_text": None,
            "is_common_factor": True,
            "is_entry_timing_factor": "선진입" in name,
        })

    return dedupe_rows(factors, ["target_party_key", "factor_name", "raw_delta"])


def merge_modifier_name_and_delta_lines(lines: List[str]) -> List[str]:
    """수정요소 항목명 줄과 다음 줄의 delta를 결합합니다."""

    result: List[str] = []
    pending: Optional[str] = None

    for raw in lines:
        line = normalize_spaces(raw.strip())
        if not line:
            continue

        # 세로 라벨 잔여 문자는 제거합니다.
        line = re.sub(r"^[과실비율조정예시]\s+(?=(레드|블루)\s*\([AB]\))", "", line)

        if re.fullmatch(r"[+-]\s*\d{1,2}", line):
            if pending:
                result.append(f"{pending} {line}")
                pending = None
            continue

        if re.match(r"^(레드|블루)\s*\([AB]\)", line):
            if re.search(r"[+-]\s*\d{1,2}$", line):
                result.append(line)
            else:
                if pending:
                    result.append(pending)
                pending = line
            continue

        if pending:
            pending = f"{pending} {line}"

    if pending:
        result.append(pending)

    return result


def split_rule_blocks(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """rule 내부 텍스트를 의미 block으로 나눕니다."""

    # block 기준입니다.
    specs = [
        ("rule_header", "회전-", "레드(A)"),
        ("party_condition", "레드(A)", "기본 과실비율"),
        ("base_fault", "기본 과실비율", "과실비율 조정 예시"),
        ("adjustment_factor_table", "과실비율 조정 예시", "사고 상황"),
        ("accident_situation", "사고 상황", "기본 과실비율"),
        ("base_fault_explanation", "기본 과실비율", "수정요소"),
        ("adjustment_explanation", "수정요소", "관련 법규"),
        ("related_law", "관련 법규", "참고 판례"),
        ("reference_case", "참고 판례", None),
    ]

    # 결과 block 목록입니다.
    blocks: List[Dict[str, Any]] = []

    # block을 하나씩 추출합니다.
    for block_type, start, end in specs:
        # 시작/끝 marker 사이 텍스트입니다.
        block_text = extract_between(text, start, end)

        # 없으면 건너뜁니다.
        if not block_text:
            continue

        # block row를 추가합니다.
        blocks.append(
            {
                "block_id": f"block_{rule_id}_{len(blocks)+1:03d}",
                "rule_id": rule_id,
                "block_type": block_type,
                "block_order": len(blocks) + 1,
                "block_title": start,
                "raw_text": block_text,
                "clean_text": clean_pdf_text(block_text),
                "structured_text": structure_rule_text(block_text),
            }
        )

    # block 목록을 반환합니다.
    return blocks


def extract_law_refs(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """도로교통법 등 법령 참조를 추출합니다."""

    # 관련 법규 block을 가져옵니다.
    law_block = extract_between(text, "관련 법규", "참고 판례") or ""

    # 법령명 + 조문 패턴입니다.
    pattern = r"([가-힣A-Za-z· ]+법(?:시행규칙)?)\s*제\s*(\d+조(?:의\d+)?)(?:\s*제\s*(\d+항))?"

    # 결과 리스트입니다.
    refs: List[Dict[str, Any]] = []

    # 법령 참조를 모두 찾습니다.
    for idx, match in enumerate(re.finditer(pattern, law_block), start=1):
        # 원문입니다.
        raw = match.group(0)

        # row를 추가합니다.
        refs.append(
            {
                "law_ref_id": f"law_{rule_id}_{idx:03d}",
                "rule_id": rule_id,
                "law_name": normalize_spaces(match.group(1)),
                "article": match.group(2),
                "paragraph": match.group(3),
                "item": None,
                "raw_text": raw,
                "context": get_context(law_block, match.start(), match.end()),
                "law_role": infer_law_role(law_block, raw),
            }
        )

    # 중복 제거 후 반환합니다.
    return dedupe_rows(refs, ["raw_text"])


def extract_reference_cases(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """참고 판례를 추출합니다."""

    # 참고 판례 block을 가져옵니다.
    block = extract_between(text, "참고 판례", None) or ""

    # 판례 패턴입니다.
    pattern = r"((?:대법원|[가-힣]+법원)\s*\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.?\s*선고\s*([0-9A-Za-z가-힣]+)\s*판결)"

    # 결과 리스트입니다.
    cases: List[Dict[str, Any]] = []

    # 모든 판례를 찾습니다.
    for idx, match in enumerate(re.finditer(pattern, block), start=1):
        # 원문입니다.
        raw = match.group(1)

        # 판례 row를 추가합니다.
        cases.append(
            {
                "reference_case_id": f"refcase_{rule_id}_{idx:03d}",
                "rule_id": rule_id,
                "court_name": extract_court_name(raw),
                "decision_date": extract_decision_date(raw),
                "case_number": match.group(2),
                "case_summary": None,
                "fault_ratio_in_case": extract_fault_ratio_text(get_context(block, match.start(), match.end(), 300)),
                "raw_text": raw,
                "context": get_context(block, match.start(), match.end(), 300),
                "case_relevance": infer_case_relevance(block),
            }
        )

    # 판례 목록을 반환합니다.
    return cases


def build_lane_path_context(parties: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    """레드/블루 차량의 경로 context를 생성합니다."""

    # 레드 party를 찾습니다.
    red = next((p for p in parties if p["party_color"] == "red"), {})

    # 블루 party를 찾습니다.
    blue = next((p for p in parties if p["party_color"] == "blue"), {})
    rule_hint = next((p.get("rule_id", "") for p in parties if p.get("rule_id")), "")
    round_no = extract_round_no(rule_hint, text)

    # 충돌 후보입니다.
    conflict_lane_info = infer_conflict_lane_info(parties, text)
    conflict_direction_info = infer_conflict_direction_info(parties, text)

    # lane path context를 반환합니다.
    return {
        "red_path": extract_lane_sequence(red),
        "blue_path": extract_lane_sequence(blue),
        "red_lane_steps": extract_lane_steps(red) if red else [],
        "blue_lane_steps": extract_lane_steps(blue) if blue else [],
        "red_path_text": red.get("action_summary"),
        "blue_path_text": blue.get("action_summary"),
        "red_expected_path": infer_expected_path(red.get("action_summary", "")),
        "blue_expected_path": infer_expected_path(blue.get("action_summary", "")),
        "expected_path_source": "explicit_text_only",
        "red_path_matches_marking": "unknown",
        "blue_path_matches_marking": "unknown",
        "path_conflict_type": infer_path_conflict_type(text),
        "conflict_lane": conflict_lane_info["value"],
        "conflict_lane_source": conflict_lane_info["source"],
        "conflict_lane_confidence": conflict_lane_info["confidence"],
        "conflict_lane_confirmed": conflict_lane_info["confirmed"],
        "conflict_direction": conflict_direction_info["value"],
        "conflict_direction_source": conflict_direction_info["source"],
        "conflict_direction_confidence": conflict_direction_info["confidence"],
        "conflict_direction_confirmed": conflict_direction_info["confirmed"],
        "route_rule_basis": None,
        "route_rule_basis_source": "not_hardcoded",
    }


def extract_between(text: str, start_marker: str, end_marker: Optional[str]) -> Optional[str]:
    """텍스트에서 시작 marker와 끝 marker 사이를 추출합니다."""

    # 시작 marker 위치입니다.
    start_idx = text.find(start_marker)

    # 시작 marker가 없으면 None입니다.
    if start_idx < 0:
        return None

    # 실제 내용 시작 위치입니다.
    content_start = start_idx + len(start_marker)

    # 끝 marker가 없으면 끝까지 반환합니다.
    if end_marker is None:
        return text[content_start:].strip()

    # 끝 marker 위치입니다.
    end_idx = text.find(end_marker, content_start)

    # 끝 marker가 없으면 끝까지 반환합니다.
    if end_idx < 0:
        return text[content_start:].strip()

    # marker 사이 텍스트를 반환합니다.
    return text[content_start:end_idx].strip()


def infer_role(action: str, rule_title: str = "") -> str:
    """행동 문장과 rule 제목으로 차량 역할을 추정합니다.

    회전번호나 색상별 예외를 두지 않고, 원문에 명시된 선진입/후진입/진입부/진출/차로변경
    신호를 우선합니다. 확정하기 어려우면 일반 entry_vehicle로 둡니다.
    """

    title = normalize_spaces(rule_title)
    action = normalize_spaces(action)

    if "진입한 차량 간" in title and "진입부 사고" in title:
        return "entry_vehicle"

    if "후진입" in action:
        return "late_entry_vehicle"

    if "선진입" in action:
        return "first_entry_vehicle"

    if ("차로변경" in action or "진로변경" in action) and "진출" in action:
        return "lane_changing_at_exit"

    if "차로변경" in action or "진로변경" in action:
        return "lane_changing_vehicle"

    if "진출" in action:
        return "exiting_vehicle"

    if "회전" in action and "진입" not in action:
        return "circulating_vehicle"

    return "entry_vehicle"


def infer_role_info(action: str, rule_title: str = "") -> Dict[str, Any]:
    """역할 값과 판단 근거를 함께 반환합니다."""

    role = infer_role(action, rule_title)
    if "진입한 차량 간" in rule_title and "진입부 사고" in rule_title:
        source = "title_entry_vehicle_pair"
        confidence = 0.95
    elif "후진입" in action:
        source = "action_contains_late_entry"
        confidence = 0.9
    elif "선진입" in action:
        source = "action_contains_first_entry"
        confidence = 0.9
    elif "차로변경" in action or "진로변경" in action:
        source = "action_contains_lane_change"
        confidence = 0.85
    elif "진출" in action:
        source = "action_contains_exit"
        confidence = 0.8
    elif "회전" in action:
        source = "action_contains_circulation"
        confidence = 0.75
    else:
        source = "fallback_entry_vehicle"
        confidence = 0.5
    return {"value": role, "source": source, "confidence": confidence}


def extract_lane(action: str, lane_type: str) -> Optional[str]:
    """행동 문장에서 진입/회전/진출 차로를 추출합니다.

    텍스트에 직접 등장한 표현을 우선하고, "12시 방향 1차로로 선진입"처럼
    문장상 진입 차로가 명시된 경우에만 정규화합니다.
    """

    action = normalize_spaces(action)

    direct = re.search(fr"{lane_type}\s*([12])차로", action)
    if direct:
        return f"{lane_type}{direct.group(1)}차로"

    if lane_type == "진입":
        patterns = [
            r"(?:3시|6시|9시|12시)\s*방향\s*([12])차로(?:에서|로)?\s*(?:선진입|후진입|진입)",
            r"([12])차로(?:에서|로)?\s*(?:선진입|후진입|진입)",
        ]
        for pattern in patterns:
            match = re.search(pattern, action)
            if match:
                return f"진입{match.group(1)}차로"

    if lane_type == "회전":
        # 명시적 회전차로가 없으면 진입 후 실제 회전 차로로 연결되는 경우만 보수적으로 정규화합니다.
        match = re.search(r"(?:선진입|후진입|진입)하여\s*회전(?:하다|하며|하던|\s*중)?", action)
        entry_lane = extract_lane(action, "진입")
        if match and entry_lane:
            return entry_lane.replace("진입", "회전")

    if lane_type == "진출":
        patterns = [
            r"(?:3시|6시|9시|12시)\s*방향\s*([12])차로(?:로)?\s*진출",
            r"([12])차로(?:로)?\s*진출",
        ]
        for pattern in patterns:
            match = re.search(pattern, action)
            if match:
                return f"진출{match.group(1)}차로"

    return None

def extract_lane_sequence(party: Dict[str, Any] | str) -> List[str]:
    """행동 문장에서 진입-회전-차로변경-진출 순서의 경로 문자열을 구성합니다."""

    if isinstance(party, str):
        action = party
        return re.findall(r"(?:진입|회전|진출)[12]차로", action)

    steps = [format_lane_step_text(step) for step in extract_lane_steps(party)]
    return [step for step in steps if step]


def extract_lane_steps(party: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Neo4j 적재용 LaneStep 후보를 생성합니다.

    좌표나 회전번호별 예외 없이 party에 추출된 명시 필드만 사용합니다.
    """

    action = party.get("action_summary", "")
    ordered = extract_ordered_lane_steps_from_action(action)
    if ordered:
        return merge_parsed_lane_change_steps(ordered, party)

    result: List[Dict[str, Any]] = []

    def add_step(movement: str, lane: Optional[str], direction: Optional[str] = None, source: str = "explicit_text") -> None:
        if not lane and not direction:
            return
        result.append({
            "seq": len(result) + 1,
            "movement": movement,
            "lane": lane,
            "direction": direction,
            "source": source,
            "source_text": None,
            "confidence": 0.8 if source == "explicit_text" else 0.5,
        })

    add_step("진입", party.get("entry_lane"), party.get("entry_direction"))
    add_step("회전", party.get("circulation_lane"), None)

    lane_change_from = party.get("lane_change_from")
    lane_change_to = party.get("lane_change_to")
    if lane_change_from or lane_change_to:
        add_step("차로변경_전", lane_change_from, None)
        add_step("차로변경_후", lane_change_to, None)

    add_step("진출", party.get("exit_lane"), party.get("exit_direction"))

    # 명시 차로가 거의 없고 방향만 있는 경우 방향 정보만 보존합니다.
    if not result:
        for direction in re.findall(r"(?:3시|6시|9시|12시)\s*방향", action):
            add_step("방향언급", None, direction, source="direction_only")

    return result


def merge_parsed_lane_change_steps(rows: List[Dict[str, Any]], party: Dict[str, Any]) -> List[Dict[str, Any]]:
    """action 순서 스캔 결과에 본문에서 확인된 차로변경 목적지를 결합합니다."""

    if not party.get("is_lane_changing"):
        return rows

    source_lane = party.get("lane_change_from")
    target_lane = party.get("lane_change_to")
    enriched = [dict(row) for row in rows]

    if source_lane and not any(row.get("lane") == source_lane for row in enriched):
        enriched.append({
            "seq": 0,
            "movement": "차로변경_전",
            "lane": source_lane,
            "direction": None,
            "source": party.get("lane_change_from_source") or "parsed_lane_change",
            "source_text": party.get("action_summary"),
            "confidence": party.get("lane_change_from_confidence", 0.85),
        })

    if target_lane and not any(
        str(row.get("movement") or "").startswith("차로변경") and row.get("lane") == target_lane
        for row in enriched
    ):
        target_row = {
            "seq": 0,
            "movement": "차로변경_후",
            "lane": target_lane,
            "direction": None,
            "source": party.get("lane_change_to_source") or "parsed_lane_change",
            "source_text": party.get("action_summary"),
            "confidence": party.get("lane_change_to_confidence", 0.85),
        }
        # 진출 step이 있으면 그 직전에, 아니면 경로의 끝에 변경 후 차로를 둡니다.
        exit_idx = next((idx for idx, row in enumerate(enriched) if row.get("movement") == "진출"), len(enriched))
        enriched.insert(exit_idx, target_row)

    for idx, row in enumerate(enriched, start=1):
        row["seq"] = idx
    return enriched


def extract_ordered_lane_steps_from_action(action: str) -> List[Dict[str, Any]]:
    """action 문장 안의 모든 방향/차로 mention을 순서 보존 LaneStep으로 변환합니다.

    핵심 원칙:
    - 한 party action 안에서 여러 차로/방향이 나오면 모두 step으로 펼칩니다.
    - ``진입1차로 진입, 회전1차로 진입``처럼 같은 문장에 2개 차로가 있으면 2개 step을 생성합니다.
    - ``12시 방향 1차로로 선진입하여 회전하다 3시 방향 1차로로 진출``처럼
      entry/exit 방향이 모두 있는 문장은 첫 진입 방향과 마지막 진출 방향을 분리합니다.
    - 회전번호별/색상별 강제 보정은 하지 않습니다. 원문에 없는 값은 derived/low-confidence로만 둡니다.
    """

    action = normalize_spaces(action or "")
    if not action:
        return []

    events: List[Dict[str, Any]] = []

    lane_pattern = re.compile(
        r"(?P<direction>(?:3시|6시|9시|12시)\s*방향)?\s*"
        r"(?P<lane>(?:(?:진입|회전|진출)\s*)?[12]차로)"
    )

    for match in lane_pattern.finditer(action):
        full_context = action[max(0, match.start() - 36): min(len(action), match.end() + 44)]
        prefix_context = action[max(0, match.start() - 18): match.start()]
        suffix_context = action[match.end(): min(len(action), match.end() + 28)]
        local_context = f"{suffix_context} {prefix_context}"
        full_context = normalize_spaces(full_context)
        local_context = normalize_spaces(local_context)
        lane_text = normalize_spaces(match.group("lane"))
        movement = infer_lane_event_movement(lane_text, local_context)
        lane = normalize_lane_token(lane_text, movement)
        direction = normalize_spaces(match.group("direction")) if match.group("direction") else (extract_near_direction(full_context) if movement in {"진입", "진출"} else None)

        events.append(
            {
                "start": match.start(),
                "movement": movement,
                "lane": lane,
                "direction": direction,
                "source_text": full_context,
                "confidence": 0.94 if re.match(r"^(진입|회전|진출)", lane_text) else 0.88,
            }
        )

    # 차로 없이 방향+동작만 있는 경우도 보존합니다. 예: 3시 방향으로 진출
    direction_action_pattern = re.compile(
        r"(?P<direction>(?:3시|6시|9시|12시)\s*방향)"
        r"(?P<context>.{0,40}?(?:선진입|후진입|진입|회전|직진|좌회전|우회전|차로변경|진로변경|진출))"
    )
    for match in direction_action_pattern.finditer(action):
        context = normalize_spaces(match.group(0))
        if any(abs(match.start() - event["start"]) <= 8 for event in events):
            continue
        movement = infer_step_movement(context)
        events.append(
            {
                "start": match.start(),
                "movement": movement,
                "lane": normalize_lane_token(context, movement),
                "direction": normalize_spaces(match.group("direction")),
                "source_text": context,
                "confidence": 0.82,
            }
        )

    rows: List[Dict[str, Any]] = []
    seen = set()
    for event in sorted(events, key=lambda row: row["start"]):
        key = (event.get("movement"), event.get("lane"), event.get("direction"), event.get("source_text"))
        if key in seen:
            continue
        if not event.get("lane") and not event.get("direction"):
            continue
        seen.add(key)
        rows.append(
            {
                "seq": len(rows) + 1,
                "movement": event["movement"],
                "lane": event.get("lane"),
                "direction": event.get("direction"),
                "source": "ordered_action_scan",
                "source_text": event.get("source_text"),
                "confidence": event.get("confidence", 0.85),
            }
        )

    rows = add_implicit_circulation_step(rows, action)
    rows = dedupe_lane_steps_preserve_order(rows)
    for idx, row in enumerate(rows, start=1):
        row["seq"] = idx
    return rows

def infer_lane_event_movement(lane_text: str, context: str) -> str:
    """lane token 자체의 prefix를 우선하고, generic 1/2차로는 가까운 주변 문맥으로 판단합니다."""

    normalized_lane = normalize_spaces(lane_text or "")
    context = normalize_spaces(context or "")
    if normalized_lane.startswith("진입"):
        return "진입"
    if normalized_lane.startswith("회전"):
        return "회전"
    if normalized_lane.startswith("진출"):
        return "진출"

    # generic 1차로/2차로는 suffix에 가장 가까운 동작을 우선합니다.
    candidates = []
    for movement, pattern in [
        ("진입", r"선진입|후진입|진입"),
        ("차로변경", r"차로변경|진로변경"),
        ("진출", r"진출"),
        ("회전", r"회전|직진|좌회전|우회전"),
    ]:
        match = re.search(pattern, context)
        if match:
            candidates.append((match.start(), movement))
    if candidates:
        return sorted(candidates, key=lambda item: item[0])[0][1]
    return "방향언급"

def add_implicit_circulation_step(rows: List[Dict[str, Any]], action: str) -> List[Dict[str, Any]]:
    """명시 회전 차로가 없지만 회전 동작이 있으면 진입 차로 연속성을 낮은 confidence로 표시합니다."""

    if not rows:
        return rows
    if any(row.get("movement") == "회전" for row in rows):
        return rows

    enriched: List[Dict[str, Any]] = []
    inserted = False
    for row in rows:
        enriched.append(row)
        lane = row.get("lane") or ""
        if not inserted and row.get("movement") == "진입" and lane.startswith("진입"):
            enriched.append({
                "seq": 0,
                "movement": "회전",
                "lane": lane.replace("진입", "회전", 1),
                "direction": None,
                "source": "derived_from_entry_lane_continuity",
                "source_text": row.get("source_text"),
                "confidence": 0.65,
            })
            inserted = True
    return enriched

def dedupe_lane_steps_preserve_order(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """동일 party action에서 반복 추출된 LaneStep을 순서 보존 중복 제거합니다."""

    result: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        key = (row.get("movement"), row.get("lane"), row.get("direction"))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result

def infer_step_movement(context: str) -> str:
    """LaneStep movement를 주변 표현으로 판단합니다.

    진출/진입처럼 단계가 명확한 표현을 차로변경/회전보다 우선합니다.
    예를 들어 ``3시 방향 1차로로 진출``은 generic 1차로라도 진출 step입니다.
    """

    context = normalize_spaces(context or "")
    if "진출" in context:
        return "진출"
    if "선진입" in context or "후진입" in context or "진입" in context:
        return "진입"
    if "차로변경" in context or "진로변경" in context:
        return "차로변경"
    if "회전" in context or "직진" in context or "좌회전" in context or "우회전" in context:
        return "회전"
    return "방향언급"

def normalize_lane_token(context: str, movement: str) -> Optional[str]:
    """context 안의 차로 표현을 movement에 맞춰 정규화합니다.

    - 진입1차로/회전2차로/진출1차로처럼 prefix가 있으면 그대로 사용합니다.
    - 1차로/2차로처럼 generic 표현이면 movement에 따라 진입/회전/진출 prefix를 붙입니다.
    """

    context = normalize_spaces(context or "")
    direct = re.search(r"(?P<prefix>진입|회전|진출)\s*(?P<num>[12])차로", context)
    if direct:
        return f"{direct.group('prefix')}{direct.group('num')}차로"

    generic = re.search(r"(?P<num>[12])차로", context)
    if not generic:
        return None

    if movement == "진입":
        prefix = "진입"
    elif movement == "진출":
        prefix = "진출"
    else:
        prefix = "회전"
    return f"{prefix}{generic.group('num')}차로"

def extract_near_direction(context: str) -> Optional[str]:
    """context 주변의 방향 표현을 반환합니다."""

    match = re.search(r"(?:3시|6시|9시|12시)\s*방향", context)
    return normalize_spaces(match.group(0)) if match else None

def format_lane_step_text(step: Dict[str, Any]) -> str:
    """LaneStep을 사람이 읽기 쉬운 문자열로 변환합니다."""

    direction = step.get("direction")
    lane = step.get("lane")
    if direction and lane:
        return f"{direction} {lane}"
    if lane:
        return str(lane)
    if direction:
        return str(direction)
    return ""

def extract_direction(action: str, keyword: str) -> Optional[str]:
    """3시 방향, 12시 방향 같은 방향 표현을 keyword 문맥에서 추출합니다.

    진입 방향은 선진입/후진입/진입 주변, 진출 방향은 진출 주변만 인정합니다.
    직진/회전 방향은 exit_direction으로 확정하지 않습니다.
    """

    kind = "entry" if keyword == "진입" else "exit" if keyword == "진출" else "generic"
    return extract_direction_info(action, kind).get("value")


def extract_direction_info(action: str, kind: str) -> Dict[str, Any]:
    """방향 값과 추출 source/confidence를 함께 반환합니다."""

    action = normalize_spaces(action)

    if kind == "entry":
        patterns = [
            ("near_entry_verb", r"(?P<direction>(?:3시|6시|9시|12시)\s*방향)\s*(?:[12]차로)?(?:에서|로)?\s*(?:선진입|후진입|진입)"),
            ("near_roundabout_entry", r"(?P<direction>(?:3시|6시|9시|12시)\s*방향)\s*(?:[12]차로)?(?:에서|로)?\s*회전교차로에\s*(?:선진입|후진입|진입)"),
        ]
        return match_direction_patterns(action, patterns, pick="first")

    if kind == "exit":
        patterns = [
            ("near_exit_verb", r"(?P<direction>(?:3시|6시|9시|12시)\s*방향)\s*(?:[12]차로)?(?:로)?\s*진출"),
            ("direction_to_exit", r"(?P<direction>(?:3시|6시|9시|12시)\s*방향)(?:으로)?\s*진출"),
        ]
        return match_direction_patterns(action, patterns, pick="last")

    return match_direction_patterns(action, [("generic_direction", r"(?P<direction>(?:3시|6시|9시|12시)\s*방향)")], pick="first")


def match_direction_patterns(text: str, patterns: List[Tuple[str, str]], pick: str) -> Dict[str, Any]:
    """방향 정규식 매칭 결과를 객체로 반환합니다."""

    matches: List[Tuple[str, re.Match[str]]] = []
    for source, pattern in patterns:
        matches.extend((source, match) for match in re.finditer(pattern, text))
    if not matches:
        return {"value": None, "source": None, "confidence": 0.0}
    source, match = matches[-1] if pick == "last" else matches[0]
    return {"value": normalize_spaces(match.group("direction")), "source": source, "confidence": 0.95}


def first_group_match(patterns: List[str], text: str, group_name: str) -> Optional[str]:
    """여러 정규식에서 첫 번째 group 값을 반환합니다."""

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return normalize_spaces(match.group(group_name))
    return None


def last_group_match(patterns: List[str], text: str, group_name: str) -> Optional[str]:
    """여러 정규식에서 마지막 group 값을 반환합니다."""

    matches = []
    for pattern in patterns:
        matches.extend(re.finditer(pattern, text))
    if not matches:
        return None
    return normalize_spaces(matches[-1].group(group_name))

def extract_lane_change_from(action: str) -> Optional[str]:
    """차로변경 전 차로를 원문 문맥에서 추출합니다."""

    action = normalize_spaces(action)

    patterns = [
        r"(?P<from>회전[12]차로)에서\s*(?:회전\s*)?(?:중\s*)?(?P<to>회전[12]차로)(?:로)?\s*(?:차로변경|진로변경)",
        r"(?P<from>회전[12]차로).*?(?:차로변경|진로변경).*?(?P<to>회전[12]차로)",
    ]
    for pattern in patterns:
        match = re.search(pattern, action)
        if match:
            return match.group("from")

    # "회전 중 2차로로 차로변경"처럼 출발 차로가 생략된 경우에는 추정하지 않습니다.
    return None

def extract_lane_change_to(action: str) -> Optional[str]:
    """차로변경 후 차로를 추정합니다."""

    # 차로변경 뒤에 나오는 회전 차로를 찾습니다.
    match = re.search(r"(?:차로변경|진로변경).*?(회전[12]차로)", action)

    if match:
        return match.group(1)

    match = re.search(r"([12])차로(?:로)?\s*(?:차로변경|진로변경)", action)
    if match:
        return f"회전{match.group(1)}차로"

    return None


def infer_expected_path(action: str) -> List[str]:
    """행동 문장에서 명시된 경로만 정상 경로 후보로 반환합니다.

    3시/9시/12시 방향별 정상 차로를 코드에서 강제하지 않습니다.
    노면표시 적합성 판단은 별도 검증 단계에서 rule diagram 또는 수동 태그로 처리합니다.
    """

    party = {
        "action_summary": action,
        "entry_direction": extract_direction(action, "진입"),
        "entry_lane": extract_lane(action, "진입"),
        "circulation_lane": extract_lane(action, "회전"),
        "exit_direction": extract_direction(action, "진출"),
        "exit_lane": extract_lane(action, "진출"),
        "lane_change_from": extract_lane_change_from(action),
        "lane_change_to": extract_lane_change_to(action),
    }
    return extract_lane_sequence(party)

def infer_path_conflict_type(text: str) -> Optional[str]:
    """경로 충돌 유형을 추정합니다."""

    if "회전1차로로 진입" in text and "진입2차로" in text:
        return "entry_lane_to_wrong_circulation_lane"

    if "차로변경" in text or "진로변경" in text:
        return "lane_change_conflict"

    if "진출" in text:
        return "exit_conflict"

    return None


def infer_conflict_lane(parties: List[Dict[str, Any]], text: str, round_no: Optional[int] = None) -> Optional[str]:
    """충돌 차로를 추정합니다.

    특정 회전번호별 고정값을 두지 않고, 차로변경/진출/충돌 문맥에 명시된 차로만 우선 사용합니다.
    """

    # 차로변경 충돌은 변경 후 차로가 충돌 차로 후보가 됩니다.
    for party in parties:
        if party.get("lane_change_to"):
            return party["lane_change_to"]

    # 진출부 사고는 진출 차로가 명시된 경우에만 사용합니다.
    exit_lanes = [party.get("exit_lane") for party in parties if party.get("exit_lane")]
    if exit_lanes:
        return exit_lanes[-1]

    conflict_context = extract_conflict_context(text)
    for lane in ["회전1차로", "회전2차로", "진출1차로", "진출2차로", "진입1차로", "진입2차로"]:
        if lane in conflict_context:
            return lane

    return None


def infer_conflict_lane_info(parties: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    """충돌 차로 값과 source/confidence를 함께 추정합니다."""

    conflict_context = extract_conflict_context(text)
    for lane in ["회전1차로", "회전2차로", "진출1차로", "진출2차로", "진입1차로", "진입2차로"]:
        if lane in conflict_context:
            return {"value": lane, "source": "explicit_conflict_context", "confidence": 0.9, "confirmed": True}

    for party in parties:
        if party.get("lane_change_to"):
            return {"value": party["lane_change_to"], "source": "derived_from_lane_change_to", "confidence": 0.65, "confirmed": False}

    exit_lanes = [party.get("exit_lane") for party in parties if party.get("exit_lane")]
    if exit_lanes:
        return {"value": exit_lanes[-1], "source": "derived_from_exit_lane", "confidence": 0.6, "confirmed": False}

    return {"value": None, "source": None, "confidence": 0.0, "confirmed": False}


def infer_conflict_direction(parties: List[Dict[str, Any]], text: str, round_no: Optional[int] = None) -> Optional[str]:
    """충돌 방향을 추정합니다.

    제목/충돌/진출 문맥에 명시된 방향만 사용하고, 전체 텍스트 첫/마지막 방향을 확정값처럼 사용하지 않습니다.
    """

    title_direction = extract_exit_direction_from_title(extract_rule_title_from_text(text))
    if title_direction:
        return title_direction

    conflict_context = extract_conflict_context(text)
    directions = re.findall(r"(?:3시|6시|9시|12시)\s*방향", conflict_context)
    if directions:
        return directions[-1]

    exit_directions = [party.get("exit_direction") for party in parties if party.get("exit_direction")]
    if exit_directions:
        return exit_directions[-1]

    return None


def infer_conflict_direction_info(parties: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    """충돌 방향 값과 source/confidence를 함께 추정합니다."""

    title_direction = extract_exit_direction_from_title(extract_rule_title_from_text(text))
    if title_direction:
        return {"value": title_direction, "source": "explicit_rule_title", "confidence": 0.98, "confirmed": True}

    conflict_context = extract_conflict_context(text)
    explicit = re.findall(r"(?:3시|6시|9시|12시)\s*방향", conflict_context)
    if explicit:
        return {"value": explicit[-1], "source": "explicit_conflict_context", "confidence": 0.9, "confirmed": True}

    exit_directions = [party.get("exit_direction") for party in parties if party.get("exit_direction")]
    if exit_directions:
        return {"value": exit_directions[-1], "source": "derived_from_exit_direction", "confidence": 0.65, "confirmed": False}

    return {"value": None, "source": None, "confidence": 0.0, "confirmed": False}


def extract_conflict_context(text: str) -> str:
    """충돌/사고/진출부 주변 문맥만 추출합니다."""

    normalized = normalize_spaces(text)
    patterns = [
        r"[^.\n]*(?:충돌|사고|진입부|회전 중|진출부)[^.\n]*",
        r"[^.\n]*(?:3시|6시|9시|12시)\s*방향\s*진출부[^.\n]*",
    ]
    contexts: List[str] = []
    for pattern in patterns:
        contexts.extend(match.group(0) for match in re.finditer(pattern, normalized))
    return " ".join(contexts) if contexts else ""

def infer_heavier_color(red: int, blue: int) -> Optional[str]:
    """과실이 더 큰 색상 당사자를 반환합니다."""

    if red > blue:
        return "red"

    if blue > red:
        return "blue"

    return None


def classify_adjustment_factor(name: str) -> str:
    """수정요소명을 카테고리로 분류합니다."""

    if "서행" in name:
        return "speed_or_slow_duty"

    if "현저" in name or "중과실" in name or "중대한" in name:
        return "severe_fault"

    if "선진입" in name:
        return "entry_timing"

    if "차로변경" in name or "진로변경" in name:
        return "lane_change"

    if "방향지시" in name:
        return "signal_or_indicator"

    return "other"


def infer_law_role(text: str, raw: str) -> str:
    """법령 문맥에서 해당 법령의 역할을 추정합니다."""

    context = text[max(0, text.find(raw) - 80): text.find(raw) + 160]

    if "회전교차로" in context or "양보" in context:
        return "roundabout_priority"

    if "차로" in context or "진로" in context:
        return "lane_change"

    if "신호" in context or "방향지시기" in context:
        return "turn_signal"

    return "safe_driving"


def extract_court_name(text: str) -> Optional[str]:
    """판례 원문에서 법원명을 추출합니다."""

    match = re.match(r"(대법원|[가-힣]+법원)", text)

    return match.group(1) if match else None


def extract_decision_date(text: str) -> Optional[str]:
    """판례 원문에서 선고일을 추출합니다."""

    match = re.search(r"\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.?", text)

    return match.group(0) if match else None


def extract_fault_ratio_text(text: str) -> Optional[str]:
    """문맥에서 과실비율 표현을 추출합니다."""

    for match in re.finditer(r"(?P<left>\d{1,3})\s*:\s*(?P<right>\d{1,3})|(?P<percent>\d{1,3})\s*%", text):
        context = text[max(0, match.start() - 30): match.end() + 30]

        if match.group("percent"):
            if any(word in context for word in ["과실", "비율", "책임", "부담"]):
                return match.group(0)
            continue

        left = int(match.group("left"))
        right = int(match.group("right"))
        # 10:02, 15:00 같은 사고 시각은 과실비율이 아닙니다.
        if is_time_like_ratio(left, right, context):
            continue

        if left + right == 100 or any(word in context for word in ["과실", "비율", "책임", "부담"]):
            return match.group(0)

    return None


def is_time_like_ratio(left: int, right: int, context: str) -> bool:
    """HH:MM 형태의 시간값을 과실비율 후보에서 제외합니다."""

    if 0 <= left <= 23 and 0 <= right <= 59 and not any(word in context for word in ["과실", "비율", "책임", "부담"]):
        return True

    return False


def infer_case_relevance(text: str) -> str:
    """판례 문맥에서 관련성을 추정합니다."""

    if "회전교차로" in text and "진입" in text:
        return "roundabout_entry"

    if "차선변경" in text or "차로변경" in text:
        return "lane_change"

    if "진출" in text:
        return "exit"

    return "general"


def get_context(text: str, start: int, end: int, window: int = 140) -> str:
    """매칭 주변 문맥을 반환합니다."""

    left = max(0, start - window)
    right = min(len(text), end + window)

    return normalize_spaces(text[left:right])





