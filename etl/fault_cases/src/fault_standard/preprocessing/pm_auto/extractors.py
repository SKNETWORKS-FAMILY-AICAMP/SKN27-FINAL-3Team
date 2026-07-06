# -*- coding: utf-8 -*-
"""PM 대 자동차 rule 내부 정보를 추출합니다."""

import re
from typing import Any, Dict, List, Optional, Tuple

from .cleaners import clean_pdf_text, normalize_spaces, structure_rule_text
from .file_utils import dedupe_rows


def extract_parties(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """PM A/B, 자동차 A/B 당사자 정보를 추출합니다."""

    # 결과 리스트입니다.
    parties: List[Dict[str, Any]] = []

    # PM A : 직진 / 자동차 B : 적색 직진 패턴입니다.
    pattern = r"(?m)^(?P<type>PM|자동차)\s*(?P<key>[AB])\s*:\s*(?P<action>.+)$"

    # 모든 당사자 줄을 순회합니다.
    for match in re.finditer(pattern, text):
        # 당사자 유형 원문입니다.
        raw_type = match.group("type")

        # A/B 키입니다.
        party_key = match.group("key")

        # 행동 설명입니다.
        action = normalize_spaces(match.group("action"))

        # party row를 추가합니다.
        parties.append(
            {
                "party_id": f"party_{rule_id}_{party_key}",
                "rule_id": rule_id,
                "party_key": party_key,
                "party_label": f"{raw_type} {party_key}",
                "party_type": "pm" if raw_type == "PM" else "car",
                "movement": infer_movement(action),
                "signal_state": infer_signal_state(action),
                "road_position": infer_road_position(action),
                "lane_position": infer_lane_position(action),
                "direction_relation": infer_direction_relation(action),
                "entry_timing": infer_entry_timing(action),
                "violation_type": infer_violation(action),
                "raw_text": match.group(0),
                "action_summary": action,
            }
        )

    # 당사자 목록을 반환합니다.
    return parties


def extract_base_fault(text: str) -> Dict[str, Any]:
    """도표 본문에서 기본과실 A:B를 추출합니다."""

    # PDF에 따라 "기본과실 A 0 : B 100" 또는 "기본 A 0 : B 100 과실"처럼 추출됩니다.
    patterns = [
        r"기본과실\s*A\s*(?P<a>\d{1,3}(?:\(\d{1,3}\))?)\s*:\s*B\s*(?P<b>\d{1,3}(?:\(\d{1,3}\))?)",
        r"기본\s*A\s*(?P<a>\d{1,3}(?:\(\d{1,3}\))?)\s*:\s*B\s*(?P<b>\d{1,3}(?:\(\d{1,3}\))?)\s*과실",
        r"A\s*(?P<a>\d{1,3}(?:\(\d{1,3}\))?)\s*:\s*B\s*(?P<b>\d{1,3}(?:\(\d{1,3}\))?)",
    ]

    # 매칭 결과를 저장합니다.
    match = None

    # 패턴을 순서대로 시도합니다.
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            break

    # 찾지 못하면 빈 구조를 반환합니다.
    if not match:
        return {
            "base_fault_type": "pair_ratio",
            "party_a_ratio": None,
            "party_b_ratio": None,
            "party_a_ratio_alt": None,
            "party_b_ratio_alt": None,
            "normalized_ratio": None,
            "raw_text": None,
            "heavier_fault_party": None,
            "is_one_sided_fault": False,
        }

    # A 비율을 분리합니다.
    a, a_alt = parse_ratio_number(match.group("a"))

    # B 비율을 분리합니다.
    b, b_alt = parse_ratio_number(match.group("b"))

    # 기본과실 구조를 반환합니다.
    return {
        "base_fault_type": "pair_ratio",
        "party_a_ratio": a,
        "party_b_ratio": b,
        "party_a_ratio_alt": a_alt,
        "party_b_ratio_alt": b_alt,
        "normalized_ratio": f"{a}:{b}" if a is not None and b is not None else None,
        "raw_text": match.group(0),
        "heavier_fault_party": infer_heavier_party(a, b),
        "is_one_sided_fault": (a == 100 and b == 0) or (a == 0 and b == 100) if a is not None and b is not None else False,
    }


def extract_adjustment_factors(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """수정요소 표에서 A/B별 가감 요소를 추출합니다."""

    # 결과 리스트입니다.
    factors: List[Dict[str, Any]] = []

    # 수정요소 block을 추출합니다.
    block = extract_between(text, "수정요소 A B", "[도표해설]")

    # block이 없으면 빈 리스트를 반환합니다.
    if not block:
        return factors

    # 줄 단위로 수정요소를 읽습니다.
    for line in block.splitlines():
        # 줄 앞뒤 공백을 제거합니다.
        line = line.strip()

        # 빈 줄은 건너뜁니다.
        if not line:
            continue

        # A 좌측통행 +5 같은 패턴입니다.
        match = re.match(r"^(?:(?P<party>[AB])\s+)?(?P<name>.+?)\s+(?P<delta>[+-]\s*\d{1,2})$", line)

        # 매칭되지 않으면 건너뜁니다.
        if not match:
            continue

        # 수정요소명입니다.
        name = normalize_spaces(match.group("name"))

        # 대상 당사자입니다. 표의 A/B가 빠진 행은 PM 기준의 도메인 규칙으로 보완합니다.
        party = infer_adjustment_target_party(match.group("party"), name)

        # 원문 수치입니다.
        raw_delta = match.group("delta").replace(" ", "")

        # 정수 수치입니다.
        delta = int(raw_delta)

        # 수정요소 row를 추가합니다.
        factors.append(
            {
                "adjustment_id": f"adj_{rule_id}_{len(factors)+1:03d}",
                "rule_id": rule_id,
                "target_party_key": party,
                "target_party_type": infer_party_type_from_key(party),
                "factor_name": name,
                "factor_category": classify_adjustment_factor(name),
                "delta": delta,
                "delta_direction": "increase" if delta > 0 else "decrease",
                "raw_delta": raw_delta,
                "raw_text": line,
                "condition_text": None,
                "condition_context": build_adjustment_condition_context(name),
                "explanation_text": None,
                "is_pm_specific_factor": is_pm_specific_factor(name),
                "is_car_specific_factor": is_car_specific_factor(name),
            }
        )

    # 수정요소 목록을 반환합니다.
    return factors


def extract_base_context_text(text: str) -> str:
    """수정요소/해설을 제외한 기본 사고상황 텍스트만 반환합니다."""

    base_parts = []

    # 기본과실/사고상황 표와 당사자 action은 실제 도표의 기본 조건입니다.
    for start, end in [("기본과실", "수정요소 A B"), ("사고상황", "수정요소 A B")]:
        value = extract_between(text, start, end)
        if value:
            base_parts.append(strip_non_base_sections(value))

    action_lines = extract_party_action_lines(text)
    if action_lines:
        base_parts.extend(action_lines)

    # marker가 깨졌을 때는 수정요소 이후 문단을 잘라낸 본문을 fallback으로 씁니다.
    if not base_parts:
        base_parts.append(strip_non_base_sections(text))

    return normalize_spaces("\n".join(base_parts).strip())


def strip_non_base_sections(text: str) -> str:
    """수정요소/해설/법규 영역을 제거해 기본 사고상황 scope만 남깁니다."""

    return re.split(
        r"수정요소\s*A\s*B|\[도표해설\]|\[관련법규\]|\[참고판례\]|과실비율 조정|관련 법규|참고 판례",
        text,
        maxsplit=1,
    )[0].strip()


def extract_party_action_lines(text: str) -> List[str]:
    """PM A / 자동차 B 당사자 action 줄만 추출합니다."""

    return [
        normalize_spaces(match.group(0))
        for match in re.finditer(r"(?m)^(?:PM|자동차)\s*[AB]\s*:\s*.+$", strip_non_base_sections(text))
    ]


def extract_rule_scenarios(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """한 도표 안에 (가)/(나)/(다) 기본과실 시나리오가 있는 경우 분리합니다."""

    rows: List[Dict[str, Any]] = []

    for idx, (label, raw_text, a_ratio, b_ratio) in enumerate(dedupe_scenario_ratio_segments(extract_scenario_ratio_segments(text)), start=1):
        rows.append(
            {
                "scenario_id": f"scenario_{rule_id}_{label}",
                "rule_id": rule_id,
                "scenario_key": label,
                "scenario_order": idx,
                "scenario_label": f"({label})",
                "party_a_ratio": a_ratio,
                "party_b_ratio": b_ratio,
                "normalized_ratio": f"{a_ratio}:{b_ratio}",
                "raw_text": raw_text,
                "needs_manual_review": False,
            }
        )

    return rows


def dedupe_scenario_ratio_segments(segments: List[Tuple[str, str, int, int]]) -> List[Tuple[str, str, int, int]]:
    """동일 label/ratio 시나리오 중복을 제거합니다."""

    seen = set()
    result: List[Tuple[str, str, int, int]] = []
    for label, raw_text, a_ratio, b_ratio in segments:
        key = (label, a_ratio, b_ratio)
        if key in seen:
            continue
        seen.add(key)
        result.append((label, raw_text, a_ratio, b_ratio))
    return result


def extract_scenario_ratio_segments(text: str) -> List[Tuple[str, str, int, int]]:
    """본문에서 (가)/(나)/(다) 같은 시나리오 label과 A:B 비율을 직접 추출합니다."""

    scenario_rows: List[Tuple[str, str, int, int]] = []
    label_matches = list(re.finditer(r"\((?P<label>[가-힣])\)", text))

    for idx, match in enumerate(label_matches):
        segment_start = match.start()
        segment_end = label_matches[idx + 1].start() if idx + 1 < len(label_matches) else len(text)
        segment = text[segment_start:segment_end]
        segment = re.split(r"수정요소\s*A\s*B|\[도표해설\]|\[관련법규\]", segment, maxsplit=1)[0]

        ratio_match = find_ratio_in_segment(segment)
        if not ratio_match:
            continue

        a_ratio, b_ratio = ratio_match
        scenario_rows.append((match.group("label"), normalize_spaces(segment), a_ratio, b_ratio))

    return scenario_rows if len(scenario_rows) >= 2 else []


def find_ratio_in_segment(segment: str) -> Optional[Tuple[int, int]]:
    """시나리오 문단에서 A:B 기본과실 비율을 찾습니다."""

    patterns = [
        r"A\s*(?P<a>\d{1,3})\s*:\s*B\s*(?P<b>\d{1,3})",
        r"PM\s*A?\s*(?P<a>\d{1,3})\s*[:：]\s*(?:자동차\s*)?B?\s*(?P<b>\d{1,3})",
        r"(?P<a>\d{1,3})\s*[:：]\s*(?P<b>\d{1,3})",
    ]

    for pattern in patterns:
        match = re.search(pattern, segment)
        if not match:
            continue

        a_ratio = int(match.group("a"))
        b_ratio = int(match.group("b"))
        if 0 <= a_ratio <= 100 and 0 <= b_ratio <= 100 and a_ratio + b_ratio == 100:
            return a_ratio, b_ratio

    return None


def infer_adjustment_target_party(explicit_party: Optional[str], name: str) -> str:
    """수정요소 대상 A/B를 보완합니다."""

    if explicit_party in {"A", "B"}:
        return explicit_party

    # PM A에게 붙는 대표 조건입니다.
    pm_words = [
        "야간",
        "시야장애",
        "횡단금지",
        "좌측통행",
        "자전거도로",
        "보도통행",
        "보도 통행",
        "안전모",
        "주택",
        "상점가",
        "학교",
        "PM",
        "개인형이동장치",
    ]
    if any(word in name for word in pm_words):
        return "A"

    # 자동차 B에게 붙는 대표 조건입니다.
    car_words = ["제동등", "대형차", "자동차", "개문", "문열림", "문 열림", "진로변경", "주차", "정차"]
    if any(word in name for word in car_words):
        return "B"

    # PM 기준서는 A=PM, B=자동차 방향이 유지되므로 불명확 행은 A로 보수적으로 둡니다.
    return "A"


def infer_party_type_from_key(party_key: Optional[str]) -> Optional[str]:
    """PM 기준의 A/B를 party_type으로 변환합니다."""

    if party_key == "A":
        return "pm"

    if party_key == "B":
        return "car"

    return None


def build_adjustment_condition_context(name: str) -> Dict[str, Any]:
    """수정요소 이름에서 기본 도로상황과 분리할 조건 context를 만듭니다."""

    return {
        "near_bicycle_road": "자전거도로" in name,
        "pm_left_side_travel": "좌측통행" in name,
        "pm_sidewalk_travel": "보도통행" in name or "보도 통행" in name,
        "night_or_visibility_issue": "야간" in name or "시야장애" in name,
        "crossing_prohibited": "횡단금지" in name,
        "residential_commercial_school_area": any(word in name for word in ["주택", "상점가", "학교"]),
        "car_brake_light_failure": "제동등" in name,
        "car_door_opening": "개문" in name or "문열림" in name or "문 열림" in name,
    }


def split_rule_blocks(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """rule 내부 텍스트를 의미 block으로 나눕니다."""

    # block 분리 기준입니다.
    specs = [
        ("base_fault", "기본과실", "사고상황"),
        ("party_condition", "사고상황", "수정요소 A B"),
        ("adjustment_factor_table", "수정요소 A B", "[도표해설]"),
        ("rule_explanation", "[도표해설]", "[관련법규]"),
        ("related_law", "[관련법규]", "[참고판례]"),
        ("reference_case", "[참고판례]", "[심의결정사례]"),
        ("review_case", "[심의결정사례]", None),
    ]

    # 결과 block 목록입니다.
    blocks: List[Dict[str, Any]] = []

    # 각 기준에 따라 block을 추출합니다.
    for block_type, start, end in specs:
        # 시작/끝 marker 사이 텍스트를 가져옵니다.
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

    # 도표해설 내부의 텍스트 해설 sub-block도 추가합니다.
    blocks.extend(split_rule_explanation_subblocks(text, rule_id, len(blocks)))

    # block 목록을 반환합니다.
    return blocks


def split_rule_explanation_subblocks(text: str, rule_id: str, start_order: int) -> List[Dict[str, Any]]:
    """[도표해설] 내부 사고상황/기본과실/수정요소 해설을 추가 분리합니다."""

    # 도표해설 전체를 가져옵니다.
    explanation = extract_between(text, "[도표해설]", "[관련법규]")

    # 없으면 빈 리스트입니다.
    if not explanation:
        return []

    # 하위 block 기준입니다.
    sub_specs = [
        ("accident_situation", "사고상황 :", "기본과실 해설 :"),
        ("base_fault_explanation", "기본과실 해설 :", "수정요소 적용 해설 :"),
        ("adjustment_explanation", "수정요소 적용 해설 :", None),
    ]

    # 하위 block 결과입니다.
    sub_blocks: List[Dict[str, Any]] = []

    # 하위 block을 순서대로 추출합니다.
    for block_type, start, end in sub_specs:
        # marker 사이 텍스트를 추출합니다.
        block_text = extract_between(explanation, start, end)

        # 없으면 건너뜁니다.
        if not block_text:
            continue

        # 전체 block 순서입니다.
        order = start_order + len(sub_blocks) + 1

        # 하위 block row를 추가합니다.
        sub_blocks.append(
            {
                "block_id": f"block_{rule_id}_{order:03d}",
                "rule_id": rule_id,
                "block_type": block_type,
                "block_order": order,
                "block_title": start.replace(":", "").strip(),
                "raw_text": block_text,
                "clean_text": clean_pdf_text(block_text),
                "structured_text": structure_rule_text(block_text),
            }
        )

    # 하위 block 목록을 반환합니다.
    return sub_blocks


def extract_law_refs(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """도로교통법 등 법령 참조를 추출합니다."""

    # 관련법규 block을 가져옵니다.
    law_block = extract_between(text, "[관련법규]", "[참고판례]") or ""

    # 법령명 + 조문 패턴입니다.
    pattern = r"([가-힣A-Za-z· ]+법(?: 시행규칙)?)\s*제\s*(\d+조(?:의\d+)?)(?:\s*제\s*(\d+항))?"

    # 결과 리스트입니다.
    refs: List[Dict[str, Any]] = []

    # 법령 참조를 모두 찾습니다.
    for idx, match in enumerate(re.finditer(pattern, law_block), start=1):
        # 매칭 원문입니다.
        raw = match.group(0)

        # 법령 row를 추가합니다.
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
    """참고판례를 추출합니다."""

    # 참고판례 block을 가져옵니다.
    block = extract_between(text, "[참고판례]", "[심의결정사례]") or ""

    # 판례 패턴입니다.
    pattern = r"((?:대법원|[가-힣]+법원)\s*\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.?\s*선고\s*([0-9A-Za-z가-힣]+)\s*판결)"

    # 결과 리스트입니다.
    cases: List[Dict[str, Any]] = []

    # 모든 판례를 찾습니다.
    for idx, match in enumerate(re.finditer(pattern, block), start=1):
        # 판례 원문입니다.
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
                "fault_ratio_in_case": extract_fault_ratio_text(get_context(block, match.start(), match.end(), 250)),
                "raw_text": raw,
                "context": get_context(block, match.start(), match.end(), 250),
                "case_relevance": infer_case_relevance(block),
            }
        )

    # 판례 목록을 반환합니다.
    return cases


def extract_review_cases(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """심의결정사례 또는 심의접수번호 기반 사례를 추출합니다."""

    # 심의접수번호 문단 패턴입니다.
    pattern = r"심의접수번호\s*(\d{4}-\d{6})(.*?)(?=심의접수번호|\Z)"

    # 결과 리스트입니다.
    review_cases: List[Dict[str, Any]] = []

    # 모든 심의사례를 찾습니다.
    for idx, match in enumerate(re.finditer(pattern, text, flags=re.S), start=1):
        # 원문을 정리합니다.
        raw = normalize_spaces(match.group(0))

        # 심의사례 row를 추가합니다.
        review_cases.append(
            {
                "review_case_id": f"review_{rule_id}_{idx:03d}",
                "related_rule_id": rule_id,
                "review_receipt_no": match.group(1),
                "accident_summary": raw[:300],
                "decision_summary": raw,
                "raw_text": raw,
                "needs_manual_review": False,
            }
        )

    # 심의사례 목록을 반환합니다.
    return review_cases


def build_pm_context(parties: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    """PM 전용 context를 생성합니다."""

    # PM party를 찾습니다.
    pm = next((p for p in parties if p.get("party_type") == "pm"), {})

    # PM 행동입니다.
    action = pm.get("action_summary", "")

    # 기본 사고상황만 PM 기본 context에 사용합니다.
    base_text = extract_base_context_text(text)

    # PM context를 반환합니다.
    return {
        "pm_party_key": pm.get("party_key"),
        "pm_action": action,
        "pm_road_position": infer_road_position(action + " " + base_text),
        "pm_lane_position": infer_lane_position(action + " " + base_text),
        "pm_signal_state": infer_signal_state(action),
        "pm_riding_state": "riding",
        "pm_near_bicycle_road": "인근에 자전거도로" in base_text or "인근에 자전거 도로" in base_text,
        "pm_left_side_travel": "좌측통행" in base_text,
        "pm_sidewalk_travel": "보도" in action or "보도" in base_text,
        "pm_crosswalk_travel": "횡단보도" in action or "횡단보도" in base_text,
        "pm_bicycle_crossing_travel": "자전거횡단도" in action or "자전거횡단도" in base_text,
        "pm_centerline_violation": "중앙선" in action or "중앙선" in base_text,
        "pm_one_way_violation": "일방통행" in action or "일방통행" in base_text,
        "pm_lane_change": "진로변경" in action,
        "pm_rear_end": "추돌" in action,
        "pm_sudden_entry": "급진입" in action or "급진입" in base_text,
        "pm_noticeability_issue": "시야장애" in base_text or "야간" in base_text,
        "pm_vulnerability_basis": "PM은 자동차 대비 충돌 시 전도 및 피해 확대 위험이 큼",
    }


def build_vehicle_context(parties: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    """자동차 전용 context를 생성합니다."""

    # 자동차 party를 찾습니다.
    car = next((p for p in parties if p.get("party_type") == "car"), {})

    # 자동차 행동입니다.
    action = car.get("action_summary", "")

    # 기본 사고상황만 자동차 기본 context에 사용합니다.
    base_text = extract_base_context_text(text)

    # 자동차 context를 반환합니다.
    return {
        "car_party_key": car.get("party_key"),
        "car_action": action,
        "car_signal_state": infer_signal_state(action),
        "car_road_position": infer_road_position(action + " " + base_text),
        "car_lane_change": "진로변경" in action,
        "car_door_opening": "개문" in action or "개문" in base_text or "문열림" in action,
        "car_rear_end": "추돌" in action,
        "car_entering_bicycle_road": "자전거도로 진입" in base_text,
        "car_entering_from_non_road": "차도가 아닌 장소" in action or "차도가 아닌 장소" in base_text,
        "car_notice_duty_basis": "PM과 충돌 시 피해 확대 위험을 고려한 주의의무",
    }


def extract_between(text: str, start_marker: str, end_marker: Optional[str]) -> Optional[str]:
    """텍스트에서 시작 marker와 끝 marker 사이를 추출합니다."""

    # 시작 marker 위치를 찾습니다.
    start_idx = text.find(start_marker)

    # 시작 marker가 없으면 None입니다.
    if start_idx < 0:
        return None

    # 실제 내용 시작 위치입니다.
    content_start = start_idx + len(start_marker)

    # 끝 marker가 없으면 끝까지 반환합니다.
    if end_marker is None:
        return text[content_start:].strip()

    # 끝 marker 위치를 찾습니다.
    end_idx = text.find(end_marker, content_start)

    # 끝 marker가 없으면 끝까지 반환합니다.
    if end_idx < 0:
        return text[content_start:].strip()

    # marker 사이 텍스트를 반환합니다.
    return text[content_start:end_idx].strip()


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


def infer_heavier_party(a: Optional[int], b: Optional[int]) -> Optional[str]:
    """과실이 더 큰 당사자를 반환합니다."""

    if a is None or b is None:
        return None

    if a > b:
        return "A"

    if b > a:
        return "B"

    return None


def infer_movement(text: str) -> Optional[str]:
    """행동 문장에서 주요 이동 행위를 추정합니다."""

    movements = [
        "중앙선 침범",
        "보도 통행",
        "보도통행",
        "차도 진입",
        "진로변경",
        "문열림",
        "개문",
        "피추돌",
        "후행",
        "주차",
        "정차",
        "주행",
        "통행",
        "직진",
        "좌회전",
        "우회전",
        "유턴",
        "횡단",
        "추돌",
    ]

    for movement in movements:
        if movement in text:
            return movement

    return None


def infer_signal_state(text: str) -> Optional[str]:
    """녹색/황색/적색 등 신호 상태를 추정합니다."""

    for value in ["보행자 적색", "보행자 녹색", "적색", "황색", "녹색"]:
        if value in text:
            return value

    return None


def infer_road_position(text: str) -> Optional[str]:
    """도로 위치를 추정합니다."""

    for value in ["자전거횡단도", "횡단보도", "자전거도로", "보도", "차도가 아닌 장소", "차도", "교차로", "대로", "소로"]:
        if value in text:
            return value

    return None


def infer_lane_position(text: str) -> Optional[str]:
    """PM 통행 위치나 차로 위치를 추정합니다."""

    for value in ["좌측통행", "우측 가장자리", "차로 중앙통행", "우측 도로", "좌측 도로"]:
        if value in text:
            return value

    return None


def infer_direction_relation(text: str) -> Optional[str]:
    """진행 방향 관계를 추정합니다."""

    for value in ["같은 방향", "대향", "오른쪽 도로", "왼쪽 도로", "우측 도로", "좌측 도로", "선행", "후행"]:
        if value in text:
            return value

    return None


def infer_entry_timing(text: str) -> Optional[str]:
    """선진입/후진입/급진입 여부를 추정합니다."""

    if "선진입" in text:
        return "선진입"

    if "후진입" in text:
        return "후진입"

    if "급진입" in text:
        return "급진입"

    return None


def infer_violation(text: str) -> Optional[str]:
    """위반 유형을 추정합니다."""

    candidates = ["신호위반", "중앙선 침범", "보도 통행", "일방통행 위반", "진로변경", "좌측통행", "개문"]

    for candidate in candidates:
        if candidate in text:
            return candidate

    return None


def classify_adjustment_factor(name: str) -> str:
    """수정요소명을 카테고리로 분류합니다."""

    if "횡단금지" in name:
        return "crossing_prohibited"

    if "자전거도로" in name:
        return "near_bicycle_road"

    if "좌측통행" in name:
        return "left_side_travel"

    if "보도통행" in name or "보도 통행" in name:
        return "sidewalk_travel"

    if "야간" in name or "시야장애" in name:
        return "visibility"

    if any(word in name for word in ["주택", "상점가", "학교"]):
        return "residential_commercial_school_area"

    if "제동등" in name:
        return "brake_light_failure"

    if "개문" in name or "문열림" in name or "문 열림" in name:
        return "door_opening"

    if "현저" in name or "중과실" in name:
        return "severe_fault"

    if "선진입" in name:
        return "first_entry"

    if "서행" in name or "감속" in name:
        return "speed_or_slow_duty"

    return "other"


def is_pm_specific_factor(name: str) -> bool:
    """PM 전용 수정요소인지 판단합니다."""

    words = ["좌측통행", "자전거도로", "보도", "횡단금지", "야간", "시야장애", "안전모", "PM", "개인형이동장치"]

    return any(word in name for word in words)


def is_car_specific_factor(name: str) -> bool:
    """자동차 전용 수정요소인지 판단합니다."""

    words = ["자동차", "대형차", "개문", "문열림", "문 열림", "제동등", "진로변경", "추돌"]

    return any(word in name for word in words)


def infer_law_role(text: str, raw: str) -> str:
    """법령 문맥에서 해당 법령의 역할을 추정합니다."""

    context = text[max(0, text.find(raw) - 80): text.find(raw) + 160]

    if "신호" in context:
        return "signal"

    if "자전거도로" in context or "개인형이동장치" in context:
        return "pm_driving_rule"

    if "횡단" in context:
        return "crossing"

    if "교차로" in context:
        return "intersection"

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

    match = re.search(r"\d{1,3}\s*:\s*\d{1,3}|\d{1,3}\s*%", text)

    return match.group(0) if match else None


def infer_case_relevance(text: str) -> str:
    """판례 문맥에서 관련성을 추정합니다."""

    if "신호" in text:
        return "signal"

    if "교차로" in text:
        return "intersection"

    if "횡단보도" in text or "자전거횡단도" in text:
        return "crossing"

    if "진로변경" in text:
        return "lane_change"

    return "general"


def get_context(text: str, start: int, end: int, window: int = 140) -> str:
    """매칭 주변 문맥을 반환합니다."""

    left = max(0, start - window)
    right = min(len(text), end + window)

    return normalize_spaces(text[left:right])
