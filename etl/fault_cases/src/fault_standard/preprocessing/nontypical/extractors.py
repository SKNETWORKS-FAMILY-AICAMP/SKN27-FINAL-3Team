# -*- coding: utf-8 -*-
"""rule 내부의 당사자, 과실, 수정요소, 법규, 사례를 추출합니다."""

import re
from typing import Any, Dict, List, Optional, Tuple

from .cleaners import clean_pdf_text, normalize_spaces, structure_rule_text
from .file_utils import dedupe_rows


def extract_parties(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """자동차 A/B, 이륜차 A/B 같은 당사자 정보를 추출합니다."""

    # 당사자 결과를 저장합니다.
    parties: List[Dict[str, Any]] = []

    # 자동차 A : 우회전 같은 줄을 찾습니다.
    pattern = r"(?m)^(?P<label>(?:자동차|이륜차|차량)\s*[AB])\s*:\s*(?P<action>.+)$"

    # 모든 당사자 줄을 순회합니다.
    for match in re.finditer(pattern, text):
        # 라벨을 정리합니다.
        label = normalize_spaces(match.group("label"))

        # 행동 설명을 정리합니다.
        action = normalize_spaces(match.group("action"))

        # A/B 키를 판단합니다.
        party_key = "A" if "A" in label else "B"

        # party row를 추가합니다.
        parties.append(
            {
                "party_id": f"party_{rule_id}_{party_key}",
                "rule_id": rule_id,
                "party_key": party_key,
                "party_label": label,
                "party_type": infer_party_type(label, action),
                "movement": infer_movement(action),
                "road_position": infer_road_position(action),
                "direction_relation": infer_direction_relation(action),
                "signal_state": infer_signal_state(action),
                "entry_timing": infer_entry_timing(action),
                "violation_type": infer_violation(action),
                "is_large_vehicle": None,
                "is_bus": "버스" in action,
                "is_overtaking_vehicle": "추월" in action or "앞지르기" in action,
                "is_departing_after_stop": "정차후 출발" in action or "정차 후 출발" in action,
                "raw_text": match.group(0),
            }
        )

    # 당사자 목록을 반환합니다.
    return parties


def extract_base_fault(text: str, summary_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """상세 본문에서 기본과실을 추출합니다."""

    # 기본과실 A 50 : B 50 형태를 찾습니다.
    match = re.search(
        r"기본과실\s*A\s*(?P<a>\d{1,3}(?:\(\d{1,3}\))?)\s*:\s*B\s*(?P<b>\d{1,3}(?:\(\d{1,3}\))?)",
        text,
    )

    # 찾지 못하면 빈 구조를 반환합니다.
    if not match:
        return {
            "base_fault_type": "pair_ratio",
            "party_a_ratio": None,
            "party_b_ratio": None,
            "normalized_ratio": None,
            "raw_text": None,
            "summary_ratio_raw": summary_row.get("summary_base_ratio_raw") if summary_row else None,
            "detail_ratio_raw": None,
            "summary_detail_ratio_match": False,
        }

    # A/B 비율을 숫자로 분리합니다.
    a, a_alt = parse_ratio_number(match.group("a"))
    b, b_alt = parse_ratio_number(match.group("b"))

    # 정규화 비율 문자열입니다.
    normalized = f"{a}:{b}" if a is not None and b is not None else None

    # 기본과실 구조를 반환합니다.
    return {
        "base_fault_type": "pair_ratio",
        "party_a_ratio": a,
        "party_b_ratio": b,
        "party_a_ratio_alt": a_alt,
        "party_b_ratio_alt": b_alt,
        "normalized_ratio": normalized,
        "raw_text": match.group(0),
        "summary_ratio_raw": summary_row.get("summary_base_ratio_raw") if summary_row else None,
        "detail_ratio_raw": match.group(0),
        "summary_detail_ratio_match": summary_row.get("summary_party_a_ratio") == a and summary_row.get("summary_party_b_ratio") == b if summary_row else False,
        "heavier_fault_party": infer_heavier_party(a, b),
        "is_equal_fault": a == b if a is not None and b is not None else False,
        "is_one_sided_fault": (a == 100 and b == 0) or (a == 0 and b == 100) if a is not None and b is not None else False,
    }


def extract_adjustment_factors(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """수정요소 표에서 A/B별 가감 요소를 추출합니다."""

    # 결과 리스트입니다.
    factors: List[Dict[str, Any]] = []

    # 수정요소 표 block을 추출합니다.
    block = extract_between(text, "수정요소 A B", "[도표해설]")

    # block이 없으면 빈 리스트를 반환합니다.
    if not block:
        return factors

    # 줄 단위로 수정요소를 읽습니다.
    for line in block.splitlines():
        # 앞뒤 공백을 제거합니다.
        line = line.strip()

        # A 대형차 +5 같은 패턴을 찾습니다.
        match = re.match(r"^(?P<party>[AB])\s+(?P<name>.+?)\s+(?P<delta>[+-]\s*\d{1,2})$", line)

        # 매칭되지 않으면 건너뜁니다.
        if not match:
            continue

        # 대상 당사자입니다.
        party = match.group("party")

        # 수정요소명입니다.
        name = normalize_spaces(match.group("name"))

        # 가감 수치 원문입니다.
        raw_delta = match.group("delta").replace(" ", "")

        # 가감 수치를 정수로 변환합니다.
        delta = int(raw_delta)

        # 수정요소 row를 추가합니다.
        factors.append(
            {
                "adjustment_id": f"adj_{rule_id}_{len(factors)+1:03d}",
                "rule_id": rule_id,
                "target_party_key": party,
                "target_party_type": "vehicle",
                "factor_name": name,
                "factor_category": classify_adjustment_factor(name),
                "delta": delta,
                "delta_direction": "increase" if delta > 0 else "decrease",
                "raw_delta": raw_delta,
                "raw_text": line,
                "condition_text": None,
                "explanation_text": None,
                "is_common_factor": is_common_adjustment(name),
                "is_priority_factor": "선진입" in name,
            }
        )

    # 수정요소 목록을 반환합니다.
    return factors


def split_rule_blocks(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """rule 내부 텍스트를 의미 block으로 나눕니다."""

    # 기본 block 분리 기준입니다.
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

    # 없으면 빈 리스트를 반환합니다.
    if not explanation:
        return []

    # 하위 block 기준입니다.
    sub_specs = [
        ("accident_situation", "사고 상황 :", "기본과실 해설 :"),
        ("base_fault_explanation", "기본과실 해설 :", "수정요소 해설 :"),
        ("adjustment_explanation", "수정요소 해설 :", None),
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
    pattern = r"([가-힣A-Za-z· ]+법(?: 시행령)?)\s*제\s*(\d+조(?:의\d+)?)(?:\s*제\s*(\d+항))?"

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
                "section_id": None,
                "law_name": normalize_spaces(match.group(1)),
                "article": match.group(2),
                "paragraph": match.group(3),
                "item": None,
                "raw_text": raw,
                "context": get_context(law_block, match.start(), match.end()),
                "law_role": infer_law_role(law_block, raw),
            }
        )

    # raw_text 기준으로 중복 법령을 제거해 반환합니다.
    return dedupe_rows(refs, ["raw_text"])


def extract_reference_cases(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """참고판례를 추출합니다."""

    # 참고판례 block을 가져옵니다.
    block = extract_between(text, "[참고판례]", "[심의결정사례]") or ""

    # 법원명 + 선고일 + 사건번호 패턴입니다.
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
    """심의접수번호 기반 심의사례를 추출합니다."""

    # 심의접수번호 문단 패턴입니다.
    pattern = r"심의접수번호\s*(\d{4}-\d{6})(.*?)(?=심의접수번호|\Z)"

    # 결과 리스트입니다.
    review_cases: List[Dict[str, Any]] = []

    # 모든 심의사례를 찾습니다.
    for idx, match in enumerate(re.finditer(pattern, text, flags=re.S), start=1):
        # 원문을 정리합니다.
        raw = normalize_spaces(match.group(0))

        # 청구/피청구 과실비율과 추출 근거를 함께 보존합니다.
        ratio_info = extract_claim_respondent_ratio_info(raw)
        claim_ratio = ratio_info["claim_ratio"]
        respondent_ratio = ratio_info["respondent_ratio"]

        # 심의사례 row를 추가합니다.
        review_cases.append(
            {
                "review_case_id": f"review_{rule_id}_{idx:03d}",
                "related_rule_id": rule_id,
                "review_receipt_no": match.group(1),
                "claim_vehicle_fault_ratio": claim_ratio,
                "respondent_vehicle_fault_ratio": respondent_ratio,
                "claim_vehicle_fault_ratio_source": ratio_info["claim_source"],
                "respondent_vehicle_fault_ratio_source": ratio_info["respondent_source"],
                "ratio_pair_complete": claim_ratio is not None and respondent_ratio is not None,
                "ratio_inference_applied": ratio_info["inference_applied"],
                "accident_summary": raw[:300],
                "decision_summary": raw,
                "raw_text": raw,
                "should_attach_to_previous_rule": False,
                "should_attach_to_next_rule": False,
                "needs_manual_review": False,
            }
        )

    # 심의사례 목록을 반환합니다.
    return review_cases


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

    # 숫자와 괄호 숫자를 매칭합니다.
    match = re.match(r"(?P<main>\d{1,3})(?:\((?P<alt>\d{1,3})\))?", value.strip())

    # 실패하면 None을 반환합니다.
    if not match:
        return None, None

    # 기본값입니다.
    main = int(match.group("main"))

    # 괄호 안 값입니다.
    alt = int(match.group("alt")) if match.group("alt") else None

    # 기본값과 괄호값을 반환합니다.
    return main, alt


def infer_heavier_party(a: Optional[int], b: Optional[int]) -> Optional[str]:
    """과실이 더 큰 당사자를 반환합니다."""

    # 둘 중 하나라도 없으면 판단하지 않습니다.
    if a is None or b is None:
        return None

    # A가 더 크면 A입니다.
    if a > b:
        return "A"

    # B가 더 크면 B입니다.
    if b > a:
        return "B"

    # 같으면 None입니다.
    return None


def infer_party_type(label: str, action: str) -> str:
    """당사자 유형을 추정합니다."""

    if "이륜" in label or "이륜" in action:
        return "motorcycle"

    if "버스" in action:
        return "bus"

    return "vehicle"


def infer_movement(text: str) -> Optional[str]:
    """행동 문장에서 주요 이동 행위를 추정합니다."""

    movement_aliases = [
        ("우측 끼어들기", "끼어들기"),
        ("끼어들기", "끼어들기"),
        ("급진입", "급진입"),
        ("주차진행", "주차진행"),
        ("주차 진행", "주차진행"),
        ("횡단보도 횡단", "횡단"),
        ("횡단", "횡단"),
        ("우회전 대기", "우회전 대기"),
        ("정차후 출발", "정차후 출발"),
        ("정차 후 출발", "정차후 출발"),
        ("진로변경", "진로변경"),
        ("차로변경", "진로변경"),
        ("앞지르기", "앞지르기"),
        ("추월", "추월"),
        ("후진", "후진"),
        ("직진", "직진"),
        ("좌회전", "좌회전"),
        ("우회전", "우회전"),
        ("유턴", "유턴"),
    ]

    for keyword, normalized in movement_aliases:
        if keyword in text:
            return normalized

    return None


def infer_road_position(text: str) -> Optional[str]:
    """행동 문장에서 도로 위치를 추정합니다."""

    positions = ["이면도로", "우측 도로", "좌측 도로", "버스정류장", "직선도로", "횡단보도", "차로", "주차장"]

    for position in positions:
        if position in text:
            return position

    return None


def infer_direction_relation(text: str) -> Optional[str]:
    """우측/좌측/우→좌 같은 방향 관계를 추정합니다."""

    for value in ["우→좌", "좌→우", "우측", "좌측", "맞은편", "동일차로", "후행", "선행"]:
        if value in text:
            return value

    return None


def infer_signal_state(text: str) -> Optional[str]:
    """적색점멸/황색점멸 등 신호 상태를 추정합니다."""

    for value in ["적색점멸", "황색점멸", "녹색", "적색", "황색"]:
        if value in text:
            return value

    return None


def infer_entry_timing(text: str) -> Optional[str]:
    """선진입/후진입 여부를 추정합니다."""

    if "선진입" in text:
        return "선진입"

    if "후진입" in text:
        return "후진입"

    return None


def infer_violation(text: str) -> Optional[str]:
    """위반 유형을 추정합니다."""

    candidates = ["신호위반", "중앙선", "진로변경", "우회전방법 위반", "좌회전방법 위반", "일방통행", "노면표시 위반"]

    for candidate in candidates:
        if candidate in text:
            return candidate

    return None


def classify_adjustment_factor(name: str) -> str:
    """수정요소명을 카테고리로 분류합니다."""

    if "대형차" in name:
        return "vehicle_size"

    if "우회전방법" in name or "좌회전방법" in name:
        return "turning_method_violation"

    if "진로변경" in name or "신호불이행" in name:
        return "lane_change_signal"

    if "서행" in name or "감속" in name:
        return "speed_or_slow_duty"

    if "선진입" in name:
        return "priority"

    if "현저" in name or "중과실" in name or "중대한" in name:
        return "severe_fault"

    if "추월" in name or "앞지르기" in name:
        return "overtaking"

    return "other"


def is_common_adjustment(name: str) -> bool:
    """여러 rule에서 반복되는 공통 수정요소인지 판단합니다."""

    common_words = ["현저한 과실", "중과실", "대형차", "명확한 선진입"]

    return any(word in name for word in common_words)


def infer_law_role(text: str, raw: str) -> str:
    """법령 문맥에서 해당 법령의 역할을 추정합니다."""

    context = text[max(0, text.find(raw) - 80): text.find(raw) + 160]

    if "우선" in context or "양보" in context:
        return "priority_basis"

    if "우회전" in context or "좌회전" in context:
        return "turning_method"

    if "앞지르기" in context or "추월" in context:
        return "overtaking"

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

    match = re.search(r"(\d{1,3})\s*%\s*[,，]?\s*(?:피청구차량|상대차량|피고|원고)?\s*과실\s*(\d{1,3})\s*%", text)

    return match.group(0) if match else None


def extract_claim_respondent_ratios(text: str) -> Tuple[Optional[int], Optional[int]]:
    """심의사례 문장에서 청구/피청구 과실비율을 추출합니다."""

    info = extract_claim_respondent_ratio_info(text)
    return info["claim_ratio"], info["respondent_ratio"]


def extract_claim_respondent_ratio_info(text: str) -> Dict[str, Any]:
    """심의사례의 쌍방 비율과 명시/파생 근거를 반환합니다.

    두 당사자 과실비율은 합계 100인 쌍입니다. 한쪽만 ``과실 N%``로 명시된 경우에는
    상대 비율을 100-N으로 계산하되, 원문 명시값과 구분되도록 source를 기록합니다.
    """

    normalized = normalize_party_ratio_text(text)
    claim_ratio = find_labeled_ratio(
        normalized,
        [
            r"(?<!피)청구차량\s*(?:과실)?\s*(\d{1,3})\s*%",
            r"(?<!피)청구\s*차량\s*(?:과실)?\s*(\d{1,3})\s*%",
            r"(?<!피)청구이륜차\s*(?:과실)?\s*(\d{1,3})\s*%",
            r"(?<!피)청구\s*이륜차\s*(?:과실)?\s*(\d{1,3})\s*%",
            r"원고차량\s*(?:과실)?\s*(\d{1,3})\s*%",
            r"원고\s*차량\s*(?:과실)?\s*(\d{1,3})\s*%",
            r"(?<!피)청구\s*(?:차량|자동차|이륜차|차)?\s*(?:과실)?\s*(\d{1,3})\s*%",
            r"원고\s*(?:차량|자동차|이륜차|차)?\s*(?:과실)?\s*(\d{1,3})\s*%",
        ],
    )
    respondent_ratio = find_labeled_ratio(
        normalized,
        [
            r"(?:피청구|피고|상대)\s*(?:차량|자동차|이륜차|차)?\s*(?:과실)?\s*(\d{1,3})\s*%",
            r"(?:피청구차량|피고차량|상대차량)\s*(?:과실)?\s*(\d{1,3})\s*%",
            r"(?:피청구이륜차|피고이륜차|상대이륜차)\s*(?:과실)?\s*(\d{1,3})\s*%",
        ],
    )
    claim_source = "explicit_text" if claim_ratio is not None else None
    respondent_source = "explicit_text" if respondent_ratio is not None else None
    inference_applied = False

    if claim_ratio is not None and respondent_ratio is None:
        ratios = [int(value) for value in re.findall(r"(?:과실\s*)?(\d{1,3})\s*%", normalized)]
        if len(ratios) >= 2:
            respondent_ratio = ratios[1]
            respondent_source = "unlabeled_pair_text"

    if respondent_ratio is not None and claim_ratio is None:
        ratios = [int(value) for value in re.findall(r"(?:과실\s*)?(\d{1,3})\s*%", normalized)]
        if len(ratios) >= 2:
            claim_ratio = ratios[0]
            claim_source = "unlabeled_pair_text"

    if claim_ratio is not None and respondent_ratio is None:
        respondent_ratio = 100 - claim_ratio
        respondent_source = "derived_complement"
        inference_applied = True

    if respondent_ratio is not None and claim_ratio is None:
        claim_ratio = 100 - respondent_ratio
        claim_source = "derived_complement"
        inference_applied = True

    return {
        "claim_ratio": claim_ratio,
        "respondent_ratio": respondent_ratio,
        "claim_source": claim_source,
        "respondent_source": respondent_source,
        "inference_applied": inference_applied,
    }


def normalize_party_ratio_text(text: str) -> str:
    """심의사례 비율 문장의 라벨/공백 변형을 정규화합니다."""

    normalized = normalize_spaces(text)
    normalized = normalized.replace("％", "%").replace("，", ",")
    # PDF 줄바꿈 때문에 핵심 라벨 한 단어가 둘로 갈라진 경우를 복원합니다.
    normalized = re.sub(r"과\s+실", "과실", normalized)
    normalized = re.sub(r"피청\s+구", "피청구", normalized)
    normalized = re.sub(r"(청구|피청구|원고|피고|상대)\s+(차량|자동차|이륜차|차)", r"\1\2", normalized)
    normalized = re.sub(r"\s*,\s*", ", ", normalized)
    return normalized


def find_labeled_ratio(text: str, patterns: List[str]) -> Optional[int]:
    """청구/피청구처럼 라벨이 붙은 과실비율을 찾습니다."""

    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue

        ratio = int(match.group(1))
        if 0 <= ratio <= 100:
            return ratio

    return None


def infer_case_relevance(text: str) -> str:
    """판례 문맥에서 관련성을 추정합니다."""

    if "우선" in text or "양보" in text:
        return "priority"

    if "우회전" in text or "좌회전" in text:
        return "turning_method"

    if "추월" in text or "앞지르기" in text:
        return "overtaking"

    if "유턴" in text:
        return "u_turn"

    if "중앙선" in text:
        return "centerline"

    return "general"


def get_context(text: str, start: int, end: int, window: int = 140) -> str:
    """매칭 주변 문맥을 반환합니다."""

    left = max(0, start - window)
    right = min(len(text), end + window)

    return normalize_spaces(text[left:right])
