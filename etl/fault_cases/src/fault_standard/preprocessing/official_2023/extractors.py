# -*- coding: utf-8 -*-
"""공식 인정기준 rule 내부 정보를 추출합니다."""

import re
from typing import Any, Dict, List, Optional, Tuple

from .cleaners import clean_pdf_text, normalize_spaces, structure_rule_text
from .file_utils import dedupe_rows

VARIANT_KEYS_PATTERN = "가나다라마바사아자차카타파하"


def extract_parties(text: str, rule_id: str, rule_prefix: str, rule_title: str = "") -> List[Dict[str, Any]]:
    """기준표의 당사자 정보를 추출합니다."""

    parties: List[Dict[str, Any]] = []

    # (A), (B), (보), (차), (보행자), (이륜차) 형태입니다.
    parenthesized_pattern = r"(?m)^\((?P<key>A|B|보|차|보행자|이륜차|자동차|자전거)\)\s*(?P<action>.+)$"
    for match in re.finditer(parenthesized_pattern, text):
        raw_key = match.group("key")
        key = normalize_party_key(raw_key, rule_prefix, len(parties))
        action = normalize_spaces(match.group("action"))
        parties.append(build_party_row(rule_id, key, raw_key, action, rule_prefix, match.group(0), rule_title))

    # 자동차 A : 직진 같은 2020 비정형 편입형 표기도 지원합니다.
    colon_pattern = r"(?m)^(?P<label>자동차|이륜차|자전거|PM|차량)\s*(?P<key>[AB])\s*:\s*(?P<action>.+)$"
    for match in re.finditer(colon_pattern, text):
        key = match.group("key")
        if any(p.get("party_key") == key for p in parties):
            continue
        raw_key = match.group("label")
        action = normalize_spaces(match.group("action"))
        parties.append(build_party_row(rule_id, key, raw_key, action, rule_prefix, match.group(0), rule_title))

    # 고속도로 보행자 사고처럼 당사자 줄이 없는 경우 title/table 기반 최소 party를 생성합니다.
    if not parties and rule_prefix == "보":
        parties.extend(infer_pedestrian_vehicle_parties(text, rule_id, rule_prefix, rule_title))

    return parties


def normalize_party_key(raw_key: str, rule_prefix: str, current_count: int) -> str:
    """다양한 party 라벨을 공통 key로 정규화합니다."""

    if raw_key in {"A", "B", "보", "차"}:
        return raw_key
    if raw_key == "보행자":
        return "보"
    if raw_key in {"이륜차", "자동차", "자전거"}:
        if rule_prefix == "보":
            return "차"
        return "A" if current_count == 0 else "B"
    return "A" if current_count == 0 else "B"


def build_party_row(rule_id: str, key: str, raw_key: str, action: str, rule_prefix: str, raw_text: str, rule_title: str = "") -> Dict[str, Any]:
    """party row를 생성합니다."""

    party_type = infer_party_type(key, rule_prefix, action + " " + raw_key)
    movement = infer_party_movement(action, raw_key, rule_title, party_type)

    return {
        "party_id": f"party_{rule_id}_{key}",
        "rule_id": rule_id,
        "party_key": key,
        "party_label": infer_party_label(key, rule_prefix, raw_key),
        "party_type": party_type,
        "movement": movement,
        "signal_state": infer_signal_state(action),
        "road_position": infer_road_position(action),
        "entry_timing": infer_entry_timing(action),
        "violation_type": infer_violation(action),
        "raw_text": raw_text,
        "action_summary": action,
    }


def infer_pedestrian_vehicle_parties(text: str, rule_id: str, rule_prefix: str, rule_title: str = "") -> List[Dict[str, Any]]:
    """보행자 사고에서 당사자 줄이 누락된 경우 A/B party를 보강합니다."""

    if "보행자" not in text and "횡단" not in text:
        return []

    return [
        build_party_row(rule_id, "A", "보행자", "보행자", rule_prefix, "보행자", rule_title),
        build_party_row(rule_id, "B", "자동차", "자동차", rule_prefix, "자동차", rule_title),
    ]


def extract_base_fault(text: str, rule_prefix: str, rule_code: str | None = None) -> Dict[str, Any]:
    """기본 과실비율을 추출합니다."""

    # 같은 원문 안에 rule code별 비율 설명이 있으면 그 값을 우선합니다.
    code_fault = extract_code_specific_base_fault(text, rule_code)
    if code_fault:
        return code_fault

    # 보행자 단일 과실비율을 먼저 찾습니다.
    single_match = re.search(r"보행자\s*기본\s*과실비율\s*(?P<ratio>\d{1,3})", text)
    if single_match:
        ratio = int(single_match.group("ratio"))
        return {
            "base_fault_type": "single_party_fault",
            "base_fault_label": "보행자 기본 과실비율",
            "base_fault_party": "pedestrian",
            "base_fault_ratio": ratio,
            "party_a_ratio": None,
            "party_b_ratio": None,
            "normalized_ratio": f"pedestrian:{ratio}",
            "raw_text": single_match.group(0),
            "ratio_sum": None,
            "is_one_sided_fault": False,
        }

    # 본문 해설에서 "보행자의 기본 과실비율을 70%"처럼 설명되는 경우를 추출합니다.
    pedestrian_explain_match = re.search(r"보행자의?\s*기본\s*과실비율을\s*(?P<ratio>\d{1,3})\s*%", text)
    if rule_prefix == "보" and pedestrian_explain_match:
        ratio = int(pedestrian_explain_match.group("ratio"))
        return {
            "base_fault_type": "single_party_fault",
            "base_fault_label": "보행자 기본 과실비율",
            "base_fault_party": "pedestrian",
            "base_fault_ratio": ratio,
            "party_a_ratio": None,
            "party_b_ratio": None,
            "normalized_ratio": f"pedestrian:{ratio}",
            "raw_text": pedestrian_explain_match.group(0),
            "ratio_sum": None,
            "is_one_sided_fault": ratio in {0, 100},
            "quality_flags": [],
        }

    # 보행자 기준에서 상대 차마의 일방과실이라고 명시된 경우 보행자 과실 0으로 처리합니다.
    if rule_prefix == "보" and re.search(r"(차량|차|자동차|이륜차)의?\s*일방\s*과실", text):
        return {
            "base_fault_type": "single_party_fault",
            "base_fault_label": "보행자 기본 과실비율",
            "base_fault_party": "pedestrian",
            "base_fault_ratio": 0,
            "party_a_ratio": None,
            "party_b_ratio": None,
            "normalized_ratio": "pedestrian:0",
            "raw_text": "상대 차마 일방과실",
            "ratio_sum": None,
            "is_one_sided_fault": True,
            "quality_flags": [],
        }

    # 변형 시나리오가 2개 이상이면 단일 A:B로 확정하지 않습니다.
    variants = extract_variants(text, "temp_rule")

    # A:B 후보를 모두 찾되 합계가 100인 후보만 기본과실 후보로 인정합니다.
    pair_matches = list(re.finditer(r"A\s*(?P<a>\d{1,3})\s*:?\s*B\s*(?P<b>\d{1,3})", text))
    valid_pairs = []
    invalid_pairs = []
    for match in pair_matches:
        a = int(match.group("a"))
        b = int(match.group("b"))
        if a + b == 100:
            valid_pairs.append((match, a, b))
        else:
            invalid_pairs.append(match.group(0))

    if variants and len(variants) >= 2:
        return {
            "base_fault_type": "variant_ratio",
            "base_fault_label": "기본 과실비율",
            "base_fault_party": None,
            "base_fault_ratio": None,
            "party_a_ratio": None,
            "party_b_ratio": None,
            "normalized_ratio": None,
            "raw_text": None,
            "ratio_sum": None,
            "is_one_sided_fault": False,
            "quality_flags": ["multiple_variant_ratios"],
        }

    if valid_pairs:
        match, a, b = valid_pairs[0]
        return {
            "base_fault_type": "pair_ratio",
            "base_fault_label": "기본 과실비율",
            "base_fault_party": None,
            "base_fault_ratio": None,
            "party_a_ratio": a,
            "party_b_ratio": b,
            "normalized_ratio": f"{a}:{b}",
            "raw_text": match.group(0),
            "ratio_sum": a + b,
            "is_one_sided_fault": (a == 100 and b == 0) or (a == 0 and b == 100),
            "quality_flags": [],
        }

    if variants:
        return {
            "base_fault_type": "variant_ratio",
            "base_fault_label": "기본 과실비율",
            "base_fault_party": None,
            "base_fault_ratio": None,
            "party_a_ratio": None,
            "party_b_ratio": None,
            "normalized_ratio": None,
            "raw_text": None,
            "ratio_sum": None,
            "is_one_sided_fault": False,
            "quality_flags": ["variant_ratio_detected"],
        }

    if invalid_pairs:
        return {
            "base_fault_type": "unknown",
            "base_fault_label": "기본 과실비율",
            "base_fault_party": None,
            "base_fault_ratio": None,
            "party_a_ratio": None,
            "party_b_ratio": None,
            "normalized_ratio": None,
            "raw_text": invalid_pairs[0],
            "ratio_sum": None,
            "is_one_sided_fault": False,
            "quality_flags": ["invalid_pair_ratio_sum"],
        }

    return {
        "base_fault_type": "unknown",
        "base_fault_label": None,
        "base_fault_party": None,
        "base_fault_ratio": None,
        "party_a_ratio": None,
        "party_b_ratio": None,
        "normalized_ratio": None,
        "raw_text": None,
        "ratio_sum": None,
        "is_one_sided_fault": False,
        "quality_flags": ["base_fault_not_found"],
    }


def extract_code_specific_base_fault(text: str, rule_code: str | None) -> Optional[Dict[str, Any]]:
    """본문 해설에서 특정 rule code에 직접 연결된 비율을 찾습니다."""

    if not rule_code:
        return None

    # ⊙ 문단 또는 빈 줄 단위로 나눠 code와 ratio가 같은 문맥에 있는지 봅니다.
    paragraphs = re.split(r"\n\s*\n|(?=⊙)", text)
    for paragraph in paragraphs:
        if rule_code not in paragraph:
            continue
        codes = re.findall(r"[보차거]\d+(?:-\d+)?", paragraph)
        if rule_code not in codes:
            continue
        for ratio_match in re.finditer(r"(?P<a>\d{1,3})\s*:\s*(?P<b>\d{1,3})", paragraph):
            a = int(ratio_match.group("a"))
            b = int(ratio_match.group("b"))
            if a + b != 100:
                continue
            return {
                "base_fault_type": "pair_ratio",
                "base_fault_label": "기본 과실비율",
                "base_fault_party": None,
                "base_fault_ratio": None,
                "party_a_ratio": a,
                "party_b_ratio": b,
                "normalized_ratio": f"{a}:{b}",
                "raw_text": normalize_spaces(paragraph[: ratio_match.end()]),
                "ratio_sum": a + b,
                "is_one_sided_fault": (a == 100 and b == 0) or (a == 0 and b == 100),
                "quality_flags": [],
            }

    # fallback: code 목록과 ratio가 한 줄/문단으로 붙은 경우를 넓게 탐색합니다.
    pattern = r"(?P<codes>(?:[보차거]\d+(?:-\d+)?(?:\s+|,|·|/|및|와|과)*)+).*?(?P<a>\d{1,3})\s*:\s*(?P<b>\d{1,3})"
    for match in re.finditer(pattern, text, flags=re.S):
        codes = re.findall(r"[보차거]\d+(?:-\d+)?", match.group("codes"))
        if rule_code in codes:
            a = int(match.group("a"))
            b = int(match.group("b"))
            if a + b != 100:
                continue
            return {
                "base_fault_type": "pair_ratio",
                "base_fault_label": "기본 과실비율",
                "base_fault_party": None,
                "base_fault_ratio": None,
                "party_a_ratio": a,
                "party_b_ratio": b,
                "normalized_ratio": f"{a}:{b}",
                "raw_text": normalize_spaces(match.group(0)),
                "ratio_sum": a + b,
                "is_one_sided_fault": (a == 100 and b == 0) or (a == 0 and b == 100),
                "quality_flags": [],
            }

    return None


def extract_combined_group_base_fault(text: str, rule_code: str | None) -> Optional[Dict[str, Any]]:
    """여러 세부 rule이 한 표에 묶인 경우 본문 해설에서 code별 비율을 찾습니다."""

    return extract_code_specific_base_fault(text, rule_code)


def extract_variants(text: str, rule_id: str, rule_code: str | None = None, rule_prefix: str | None = None) -> List[Dict[str, Any]]:
    """(가), (나) 등 시나리오별 과실비율을 추출합니다.

    단일 A:B가 아니라 조건별 기본과실인 경우를 variants로 분리합니다.
    예: 도로폭 기준별 보행자 사고처럼 소로/동일폭/대로에 따라 10/20/30%가 달라지는 구조.
    """

    variants: List[Dict[str, Any]] = []

    # 기본 과실비율 표가 (가)/(나)별 A/B 값을 열 형태로 갖는 경우를 먼저 처리합니다.
    variants.extend(extract_tabular_pair_variants(text, rule_id))
    existing = {row["variant_key"] for row in variants}

    # 해설 문단의 (가)/(나)/(다) 단위에서 ratio를 우선 추출합니다.
    paragraph_pattern = r"⊙\s*\((?P<key>[가나다라마바사아자차카타파하])\)(?P<body>.*?)(?=⊙\s*\([가나다라마바사아자차카타파하]\)|수정요소|활용시 참고 사항|관련 법규|참고 판례|$)"
    for match in re.finditer(paragraph_pattern, text, flags=re.S):
        key = match.group("key")
        if key in existing:
            continue
        body = normalize_spaces(match.group("body"))
        if len(body) > 500 or any(marker in body for marker in ["과실비율 조정 예시", "사고 상황", "관련 법규", "참고 판례"]):
            continue
        if is_adjustment_ratio_context(body):
            continue
        pair = re.search(r"(?P<a>\d{1,3})\s*:\s*(?P<b>\d{1,3})", body)
        single = None if pair else re.search(r"(?P<single>\d{1,3})\s*%", body)
        if not pair and not single:
            continue
        if single and not has_base_fault_ratio_context(body):
            continue
        if single and has_pair_ratio_context(body):
            continue
        a = int(pair.group("a")) if pair else None
        b = int(pair.group("b")) if pair else None
        single_ratio = int(single.group("single")) if single else None
        if pair and a + b != 100:
            continue
        variants.append({
            "variant_id": f"{rule_id}_{key}",
            "rule_id": rule_id,
            "variant_key": key,
            "variant_title": infer_variant_title_from_body(body),
            "party_a_ratio": a,
            "party_b_ratio": b,
            "single_party_ratio": single_ratio,
            "raw_text": match.group(0),
            "scenario_text": body,
            "ratio_source": "explicit_text",
            "scenario_parse_status": "complete",
        })
        existing.add(key)

    # 도로폭 기준별 보행자 사고는 설명문 전체에 여러 %가 있어 일반 inline parser가 오인할 수 있으므로 먼저 처리합니다.
    existing = {row["variant_key"] for row in variants}
    width_variants = extract_width_based_pedestrian_variants(text, rule_id, existing)
    if width_variants:
        variants.extend(width_variants)
        rows = dedupe_rows(variants, ["variant_key", "raw_text"])
        return enrich_variant_party_info(rows, rule_prefix) if len(rows) >= 2 else []

    existing = {row["variant_key"] for row in variants}
    variants.extend(extract_inline_variant_ratios(text, rule_id, existing))
    existing = {row["variant_key"] for row in variants}
    variants.extend(extract_labeled_single_ratio_variants(text, rule_id, existing))

    # 비율 없는 (가)/(나) 표식만으로는 RuleScenario를 만들지 않습니다.
    rows = dedupe_rows(variants, ["variant_key", "raw_text"])
    return enrich_variant_party_info(rows, rule_prefix) if len(rows) >= 2 else []

def extract_tabular_pair_variants(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """기본 과실비율 표의 label별 A/B pair 값을 variant로 추출합니다.

    PDF 표가 줄 단위로 풀리면 `(가) (나) / A100 A70 / B0 B30`처럼
    label 행과 A/B 값 행이 분리됩니다. 이 경우 단일 `%` 해설이 아니라
    A/B가 모두 확정된 pair_ratio 시나리오로 저장해야 합니다.
    """

    base_area = text.split("과실비율 조정 예시", 1)[0]
    if "기본 과실비율" not in base_area:
        return []

    labels = []
    for key in re.findall(r"\(([가나다라마바사아자차카타파하])\)", base_area):
        if key not in labels:
            labels.append(key)
    if len(labels) < 2:
        return []

    a_values = extract_party_ratio_values_from_table_area(base_area, "A")
    b_values = extract_party_ratio_values_from_table_area(base_area, "B")
    if len(a_values) < len(labels) or len(b_values) < len(labels):
        return []

    rows: List[Dict[str, Any]] = []
    for idx, key in enumerate(labels):
        a = a_values[idx]
        b = b_values[idx]
        if a + b != 100:
            continue
        rows.append({
            "variant_id": f"{rule_id}_{key}",
            "rule_id": rule_id,
            "variant_key": key,
            "variant_title": infer_variant_condition_title(base_area, key),
            "party_a_ratio": a,
            "party_b_ratio": b,
            "single_party_ratio": None,
            "raw_text": f"({key}) A{a} B{b}",
            "scenario_text": infer_variant_condition_title(base_area, key) or f"({key}) A{a}:B{b}",
            "ratio_source": "base_fault_table_pair_columns",
            "scenario_parse_status": "complete",
        })
    return rows if len(rows) >= 2 else []


def extract_party_ratio_values_from_table_area(text: str, party_key: str) -> List[int]:
    """표 영역에서 A/B 뒤에 붙은 비율 값을 등장 순서대로 추출합니다."""

    values: List[int] = []
    pattern = rf"{party_key}\s*:?\s*(?P<ratio>\d{{1,3}})"
    for match in re.finditer(pattern, text):
        ratio = int(match.group("ratio"))
        if 0 <= ratio <= 100:
            values.append(ratio)
    return values


def infer_variant_condition_title(text: str, key: str) -> Optional[str]:
    """party 조건 영역에서 `(가) 조건명` 형태의 시나리오 제목을 추정합니다."""

    pattern = rf"\({key}\)\s*(?P<title>[^\n()]+)"
    match = re.search(pattern, text)
    if not match:
        return None
    title = normalize_spaces(match.group("title"))
    if not title or re.search(r"^A?\s*\d{1,3}\s*:?\s*B?\s*\d{0,3}$", title):
        return None
    return title[:80]


def is_adjustment_ratio_context(text: str) -> bool:
    """수정요소 증감 설명을 variant 비율로 오인하지 않도록 거릅니다."""

    return bool(re.search(r"[+-]\s*\d{1,3}|가산|감산|수정요소|조정", text or ""))


def has_base_fault_ratio_context(text: str) -> bool:
    """단일 % 값을 variant로 인정할 만큼 기본과실 문맥이 명확한지 봅니다."""

    return bool(re.search(r"기본\s*과실\s*비율|기본과실비율", text or ""))


def has_pair_ratio_context(text: str) -> bool:
    """같은 문맥에 A:B pair 비율이 있으면 단일 % variant로 보지 않습니다."""

    return bool(re.search(r"\b\d{1,3}\s*:\s*\d{1,3}\b|A\s*\d{1,3}\s*:?\s*B\s*\d{1,3}", text or ""))


def extract_width_based_pedestrian_variants(text: str, rule_id: str, existing_keys: Optional[set[str]] = None) -> List[Dict[str, Any]]:
    """도로폭 기준별 보행자 기본과실 시나리오를 추출합니다.

    특정 rule_id를 하드코딩하지 않고, 원문에 다음 요소가 함께 있을 때만 작동합니다.
    - 도로폭/도로 폭/폭 기준 문맥
    - (가)/(나)/(다) 같은 시나리오 label
    - 좁을 때/같을 때/넓을 때 또는 소로/동일폭/대로와 연결되는 % 비율
    """

    rows: List[Dict[str, Any]] = []
    existing_keys = existing_keys or set()
    normalized = normalize_spaces(text or "")
    if not re.search(r"도로\s*폭|도로폭|폭\s*기준|소로|동일폭|대로", normalized):
        return rows
    if "보행자" not in normalized or "기본 과실비율" not in normalized:
        return rows

    # 설명문에서 폭 조건별 비율을 추출합니다.
    ratio_by_kind: Dict[str, int] = {}
    ratio_patterns = [
        ("narrow", r"(?:좁을\s*때|좁은\s*경우|소로).*?(?P<ratio>\d{1,3})\s*%"),
        ("wide", r"(?:넓을\s*때|넓은\s*경우|대로).*?(?P<ratio>\d{1,3})\s*%"),
        ("equal", r"(?:같을\s*때|같은\s*경우|동일폭|동일\s*폭).*?(?P<ratio>\d{1,3})\s*%"),
    ]
    for kind, pattern in ratio_patterns:
        match = re.search(pattern, normalized)
        if match:
            ratio = int(match.group("ratio"))
            if 0 <= ratio <= 100:
                ratio_by_kind[kind] = ratio

    if not ratio_by_kind:
        return rows

    # 보행자 기본 과실비율 표 아래의 (가)/(나)/(다) label을 읽습니다.
    label_pattern = r"\((?P<key>[가나다라마바사아자차카타파하])\)\s*(?P<title>[^\n()]{1,40})"
    for match in re.finditer(label_pattern, text):
        key = match.group("key")
        if key in existing_keys:
            continue
        title = normalize_spaces(match.group("title"))
        kind = None
        if re.search(r"소로|좁", title):
            kind = "narrow"
        elif re.search(r"동일폭|동일\s*폭|같", title):
            kind = "equal"
        elif re.search(r"대로|넓", title):
            kind = "wide"
        if not kind or kind not in ratio_by_kind:
            continue
        ratio = ratio_by_kind[kind]
        rows.append({
            "variant_id": f"{rule_id}_{key}",
            "rule_id": rule_id,
            "variant_key": key,
            "variant_title": title,
            "party_a_ratio": None,
            "party_b_ratio": None,
            "single_party_ratio": ratio,
            "raw_text": match.group(0),
            "scenario_text": f"{title}: 보행자 기본 과실비율 {ratio}%",
            "ratio_source": "width_based_explanation",
            "scenario_parse_status": "complete",
        })

    return rows

def extract_labeled_single_ratio_variants(text: str, rule_id: str, existing_keys: Optional[set[str]] = None) -> List[Dict[str, Any]]:
    """원문에 명시된 label + 단일 비율 시나리오를 추출합니다."""

    rows: List[Dict[str, Any]] = []
    existing_keys = existing_keys or set()
    pattern = r"\((?P<key>[가나다라마바사아자차카타파하])\)(?P<body>.*?)(?=\([가나다라마바사아자차카타파하]\)|수정요소|활용시 참고 사항|관련 법규|참고 판례|$)"
    for match in re.finditer(pattern, text, flags=re.S):
        key = match.group("key")
        if key in existing_keys:
            continue
        body = normalize_spaces(match.group("body"))
        if len(body) > 500:
            continue
        if is_adjustment_ratio_context(body):
            continue
        ratio_match = re.search(r"(?P<ratio>\d{1,3})\s*%", body)
        if not ratio_match:
            continue
        if not has_base_fault_ratio_context(body):
            continue
        if has_pair_ratio_context(body):
            continue
        ratio = int(ratio_match.group("ratio"))
        if not 0 <= ratio <= 100:
            continue
        rows.append({
            "variant_id": f"{rule_id}_{key}",
            "rule_id": rule_id,
            "variant_key": key,
            "variant_title": infer_variant_title_from_body(body),
            "party_a_ratio": None,
            "party_b_ratio": None,
            "single_party_ratio": ratio,
            "raw_text": match.group(0),
            "scenario_text": body,
            "ratio_source": "explicit_text",
            "scenario_parse_status": "complete",
        })
    return rows


def extract_inline_variant_ratios(text: str, rule_id: str, existing_keys: set[str]) -> List[Dict[str, Any]]:
    """본문 한 줄 안의 (가)/(나) + 비율 시나리오를 보완 추출합니다."""

    rows: List[Dict[str, Any]] = []
    pattern = r"\((?P<key>[가나다라마바사아자차카타파하])\)(?P<body>.*?)(?=\([가나다라마바사아자차카타파하]\)|수정요소|활용시 참고 사항|관련 법규|참고 판례|$)"

    for match in re.finditer(pattern, text, flags=re.S):
        key = match.group("key")
        if key in existing_keys:
            continue

        body = normalize_spaces(match.group("body"))
        if len(body) > 500 or any(marker in body for marker in ["과실비율 조정 예시", "사고 상황", "관련 법규", "참고 판례"]):
            continue
        if is_adjustment_ratio_context(body):
            continue
        pair = re.search(r"(?P<a>\d{1,3})\s*:\s*(?P<b>\d{1,3})", body)
        single = None if pair else re.search(r"(?P<single>\d{1,3})\s*%", body)
        if not pair and not single:
            continue
        if single and not has_base_fault_ratio_context(body):
            continue
        if single and has_pair_ratio_context(body):
            continue

        a = int(pair.group("a")) if pair else None
        b = int(pair.group("b")) if pair else None
        single_ratio = int(single.group("single")) if single else None
        if pair and a + b != 100:
            continue

        rows.append(
            {
                "variant_id": f"{rule_id}_{key}",
                "rule_id": rule_id,
                "variant_key": key,
                "variant_title": infer_variant_title_from_body(body),
                "party_a_ratio": a,
                "party_b_ratio": b,
                "single_party_ratio": single_ratio,
                "raw_text": match.group(0),
                "scenario_text": body,
            }
        )

    return rows



def enrich_variant_party_info(rows: List[Dict[str, Any]], rule_prefix: str | None = None) -> List[Dict[str, Any]]:
    """variant ratio가 어느 party 기준인지 계산 메타데이터를 보강합니다."""

    for row in rows:
        has_pair_ratio = row.get("party_a_ratio") is not None or row.get("party_b_ratio") is not None
        has_single_ratio = row.get("single_party_ratio") is not None
        row["calculation_source"] = "variants"
        if has_pair_ratio:
            row["ratio_interpretation"] = "pair_fault_ratio"
            row["single_party_key"] = None
            row["single_party_type"] = None
            row["single_party_inference_source"] = None
            row["single_party_inference_confidence"] = None
            continue
        if has_single_ratio:
            party_info = infer_variant_single_party_info(row.get("scenario_text", ""), rule_prefix)
            row["ratio_interpretation"] = "single_party_fault_ratio"
            row["single_party_key"] = party_info["party_key"]
            row["single_party_type"] = party_info["party_type"]
            row["single_party_inference_source"] = party_info["source"]
            row["single_party_inference_confidence"] = party_info["confidence"]
            row["single_party_needs_review"] = party_info["party_key"] is None
            continue
        row["ratio_interpretation"] = "unknown"
        row["single_party_key"] = None
        row["single_party_type"] = None
        row["single_party_inference_source"] = None
        row["single_party_inference_confidence"] = None
        row["single_party_needs_review"] = True
    return rows


def infer_variant_single_party_info(scenario_text: str, rule_prefix: str | None = None) -> Dict[str, Any]:
    """시나리오 문맥에서 단일 비율의 대상 party를 추론합니다."""

    text = normalize_spaces(scenario_text or "")
    if "보행자" in text or rule_prefix == "보":
        return {"party_key": "보", "party_type": "pedestrian", "source": "scenario_text_or_rule_prefix", "confidence": 0.9}
    if "자전거" in text or rule_prefix == "거":
        return {"party_key": "A", "party_type": "bicycle", "source": "scenario_text_or_rule_prefix", "confidence": 0.8}
    if "이륜" in text:
        return {"party_key": None, "party_type": "motorcycle", "source": "scenario_text_party_type_only", "confidence": 0.55}
    if "자동차" in text or "차량" in text or "차의" in text or rule_prefix == "차":
        return {"party_key": None, "party_type": "vehicle", "source": "scenario_text_or_rule_prefix_type_only", "confidence": 0.55}
    return {"party_key": None, "party_type": None, "source": None, "confidence": 0.0}

def infer_variant_title_from_body(body: str) -> Optional[str]:
    """시나리오 문단에서 짧은 제목을 추정합니다."""

    first_sentence = re.split(r"[.。\n]", body.strip())[0].strip()
    if not first_sentence:
        return None
    return first_sentence[:80]


def extract_adjustment_factors(
    text: str,
    rule_id: str,
    parties: List[Dict[str, Any]],
    rule_prefix: str = "",
    rule_title: str = "",
    base_fault: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """수정요소 표에서 가감 요소를 추출합니다."""

    # 결과 리스트입니다.
    factors: List[Dict[str, Any]] = []

    candidate_lines = merge_adjustment_lines(text)
    adjustment_target_context = extract_adjustment_target_context(text)

    # 줄 단위로 수정요소를 읽습니다.
    for line in candidate_lines:
        # 줄 앞뒤 공백을 제거합니다.
        line = normalize_spaces(line.strip())

        if is_shared_adjustment_marker(line):
            continue

        # 빈 줄은 건너뜁니다.
        if not line:
            continue

        # +5, -10, 비적용이 없는 줄은 건너뜁니다.
        if not re.search(r"[+-]\s*\d{1,2}|비적용", line):
            continue

        # 설명문이나 판례 문장은 제외합니다.
        if len(line) > 80:
            continue

        # 수정요소명을 추출합니다.
        parsed = parse_adjustment_line(line)

        # 추출 실패 시 건너뜁니다.
        if not parsed:
            continue

        target_info = infer_adjustment_target_info(parsed["target_party_key"], parsed["factor_name"], parties, rule_prefix, rule_title, base_fault or {}, adjustment_target_context, parsed.get("delta_direction"))

        # 수정요소 row를 추가합니다.
        factors.append(
            {
                "adjustment_id": f"adj_{rule_id}_{len(factors)+1:03d}",
                "rule_id": rule_id,
                "order_no": parsed["order_no"],
                "target_party_key": target_info["target_party_key"],
                "target_party_type": target_info["target_party_type"],
                "target_parse_status": target_info["target_parse_status"],
                "target_inference_source": target_info["target_inference_source"],
                "target_inference_confidence": target_info["target_inference_confidence"],
                "factor_name": parsed["factor_name"],
                "factor_category": classify_adjustment_factor(parsed["factor_name"]),
                "delta": parsed["delta"],
                "delta_direction": parsed["delta_direction"],
                "raw_delta": parsed["raw_delta"],
                "raw_text": line,
                "condition_text": parsed["factor_name"] or None,
                "explanation_text": target_info.get("target_context_text"),
                "is_applicable": parsed["delta_direction"] != "not_applicable",
                "needs_manual_review": target_info["target_parse_status"] == "unresolved",
                                "manual_review_reason": "adjustment_target_unresolved" if target_info["target_parse_status"] == "unresolved" else None,
                "auto_calculation_eligible": target_info["target_parse_status"] != "unresolved",
                "exclude_from_auto_calculation": target_info["target_parse_status"] == "unresolved",
                "exclusion_reason": "adjustment_target_unresolved" if target_info["target_parse_status"] == "unresolved" else None,
            }
        )

    # 중복 제거 후 반환합니다.
    return dedupe_rows(factors, ["target_party_key", "factor_name", "raw_delta"])


def merge_adjustment_lines(text: str) -> List[str]:
    """수정요소명 줄과 +5/-10만 있는 줄을 결합합니다."""

    block = extract_between(text, "과실비율 조정 예시", "사고 상황") or extract_between(text, "수정요소", "활용시 참고 사항") or text
    lines = [normalize_spaces(line.strip()) for line in block.splitlines() if line.strip()]
    result: List[str] = []
    pending_parts: List[str] = []

    for line in lines:
        if is_evidence_contamination_line(line):
            break

        if is_shared_adjustment_marker(line):
            pending_parts = []
            continue

        if len(line) > 120:
            continue

        if re.fullmatch(r"[+-]\s*\d{1,3}|비적용", line):
            if pending_parts:
                result.append(normalize_spaces(" ".join([*pending_parts, line])))
                pending_parts = []
            continue

        if re.search(r"[+-]\s*\d{1,3}|비적용", line):
            if pending_parts and not starts_with_target_prefix(line):
                result.append(normalize_spaces(" ".join([*pending_parts, line])))
            else:
                result.append(line)
            pending_parts = []
            continue

        if is_adjustment_name_candidate(line):
            pending_parts.append(line)
            if len(pending_parts) > 5:
                pending_parts = pending_parts[-5:]

    return result


def starts_with_target_prefix(line: str) -> bool:
    """A/B/보/차 target prefix로 시작하는지 확인합니다."""

    return bool(re.match(r"^(A|B|보|차|보행자|차량|자동차|자전거|이륜차)", line))


def is_shared_adjustment_marker(line: str) -> bool:
    """공통 해설 marker는 수정요소 row가 아니므로 제외합니다."""

    return "__SHARED_EXPLANATION__" in line or "__SHARED_" in line


def is_adjustment_name_candidate(line: str) -> bool:
    """수정요소명 후보인지 판단합니다."""

    if is_shared_adjustment_marker(line):
        return False

    if any(token in line for token in ["기본 과실비율", "사고 상황", "관련 법규", "참고 판례", "목차"]):
        return False

    if parse_rule_like_header(line):
        return False

    return len(line) <= 80



def extract_adjustment_target_context(text: str) -> str:
    """수정요소 해설 중 target 판단에 쓸 문맥만 추출합니다."""

    blocks = [
        extract_between(text, "수정요소", "활용시 참고 사항"),
        extract_between(text, "기본 과실비율 해설", "관련 법규"),
        extract_between(text, "사고 상황", "관련 법규"),
    ]
    context_lines: List[str] = []
    for block in blocks:
        if not block:
            continue
        for raw_line in block.splitlines():
            line = normalize_spaces(raw_line.strip())
            if not line:
                continue
            if any(token in line for token in ["과실", "가산", "감산", "수정요소", "현저한", "중대한"]):
                context_lines.append(line)
    return normalize_spaces(" ".join(context_lines))
def infer_adjustment_target_party(explicit_key: Optional[str], factor_name: str, parties: List[Dict[str, Any]]) -> Optional[str]:
    """수정요소 대상 party를 보완합니다.

    대상자가 원문에 없을 때 A/차로 강제 fallback하지 않습니다.
    강제 보정은 하드코딩 오류를 만들 수 있으므로, 명확한 단서가 있을 때만 보완하고
    나머지는 None으로 남겨 parse_quality에서 검수 대상으로 표시합니다.
    """

    if explicit_key:
        return resolve_target_token_to_party_key(explicit_key, parties)

    name = factor_name or ""
    keys = {party.get("party_key") for party in parties}

    # factor_name 자체가 대상자를 포함하는 경우만 보완합니다.
    if re.search(r"(^|\s)(A|Ａ)\s*", name) and "A" in keys:
        return "A"
    if re.search(r"(^|\s)(B|Ｂ)\s*", name) and "B" in keys:
        return "B"
    if re.search(r"보행자|A보행자|보\s", name) and "보" in keys:
        return "보"
    if re.search(r"자동차|차량|차\s", name) and "차" in keys and len(keys) == 1:
        return "차"

    return None


def resolve_target_token_to_party_key(token: str, parties: List[Dict[str, Any]]) -> Optional[str]:
    """원문 target token을 실제 party_key로 해석합니다."""

    normalized = normalize_target_token(token)
    party_keys = {party.get("party_key") for party in parties}
    if normalized in party_keys:
        return normalized

    if normalized == "차":
        normalized = "vehicle"
    elif normalized == "보":
        normalized = "pedestrian"

    candidates = [
        party for party in parties
        if party_matches_target_token(party, normalized)
    ]
    if len(candidates) == 1:
        return candidates[0].get("party_key")

    if normalized == "vehicle" and "차" in party_keys:
        return "차"
    if normalized == "pedestrian" and "보" in party_keys:
        return "보"

    return None


def normalize_target_token(token: str) -> str:
    """target prefix를 비교 가능한 token으로 정규화합니다."""

    if token in {"A", "B", "차", "보"}:
        return token
    if token in {"차량", "자동차"}:
        return "vehicle"
    if token == "보행자":
        return "pedestrian"
    if token == "자전거":
        return "bicycle"
    if token == "이륜차":
        return "motorcycle"
    return token


def party_matches_target_token(party: Dict[str, Any], token: str) -> bool:
    """party row가 target token과 일치하는지 판단합니다."""

    haystack = " ".join(
        str(party.get(key) or "")
        for key in ["party_key", "party_label", "party_type", "raw_text", "action_summary"]
    )

    if token == "vehicle":
        return party.get("party_type") in {"vehicle", "car", "motorcycle", "bicycle"} or any(value in haystack for value in ["자동차", "차량"])
    if token == "pedestrian":
        return party.get("party_type") == "pedestrian" or "보행자" in haystack
    if token == "bicycle":
        return party.get("party_type") == "bicycle" or "자전거" in haystack
    if token == "motorcycle":
        return party.get("party_type") == "motorcycle" or "이륜" in haystack
    return token in haystack


def infer_adjustment_target_from_rule_context(
    factor_name: str,
    parties: List[Dict[str, Any]],
    rule_prefix: str,
    rule_title: str,
) -> Optional[str]:
    """수정요소명/제목의 당사자 표현으로 target을 보완합니다."""

    context = f"{rule_title} {factor_name}"
    target_tokens = []
    if "보행자" in context:
        target_tokens.append("pedestrian")
    if "자전거" in context:
        target_tokens.append("bicycle")
    if "이륜" in context:
        target_tokens.append("motorcycle")
    if "자동차" in context or "차량" in context:
        target_tokens.append("vehicle")

    for token in target_tokens:
        matches = [party for party in parties if party_matches_target_token(party, token)]
        if len(matches) == 1:
            return matches[0].get("party_key")

    if rule_prefix == "보":
        matches = [party for party in parties if party.get("party_type") == "pedestrian" or party.get("party_key") == "보"]
        if len(matches) == 1 and any(word in factor_name for word in ["보행자", "어린이", "노인", "장애인"]):
            return matches[0].get("party_key")

    return None


def infer_adjustment_target_info(
    explicit_key: Optional[str],
    factor_name: str,
    parties: List[Dict[str, Any]],
    rule_prefix: str,
    rule_title: str,
    base_fault: Dict[str, Any],
    adjustment_context: str = "",
    delta_direction: Optional[str] = None,
) -> Dict[str, Any]:
    """수정요소 target과 판단 근거를 함께 반환합니다."""

    key = infer_adjustment_target_party(explicit_key, factor_name, parties)
    source = "line_target_prefix" if explicit_key and key else "line_target_prefix_unresolved" if explicit_key else "factor_name_label" if key else None
    confidence = 1.0 if explicit_key and key else 0.9 if key else 0.0

    if not key and base_fault.get("base_fault_type") == "single_party_fault":
        base_party = base_fault.get("base_fault_party")
        if base_party == "pedestrian":
            key = next((party.get("party_key") for party in parties if party.get("party_type") == "pedestrian" or party.get("party_key") == "보"), None)
            source = "single_party_base_fault_party" if key else None
            confidence = 0.8 if key else 0.0

    if not key:
        key = infer_adjustment_target_from_rule_context(factor_name, parties, rule_prefix, rule_title)
        if key:
            source = "rule_context_party_type"
            confidence = 0.7

    target_context_text = None
    if not key and adjustment_context:
        context_info = infer_adjustment_target_from_explanation(adjustment_context, parties, delta_direction)
        key = context_info["target_party_key"]
        if key:
            source = context_info["target_inference_source"]
            confidence = context_info["target_inference_confidence"]
            target_context_text = context_info["target_context_text"]

    party_type = infer_target_party_type(key, parties)
    return {
        "target_party_key": key,
        "target_party_type": party_type,
        "target_parse_status": "explicit" if explicit_key and key else "inferred" if key else "unresolved",
        "target_inference_source": source,
        "target_inference_confidence": confidence,
        "target_context_text": target_context_text,
    }



def infer_adjustment_target_from_explanation(
    adjustment_context: str,
    parties: List[Dict[str, Any]],
    delta_direction: Optional[str] = None,
) -> Dict[str, Any]:
    """해설 문장의 '누구의 과실을 가산/감산' 표현으로 target을 추론합니다."""

    action_words = ["가산", "감산"]
    if delta_direction == "increase":
        action_words = ["가산"]
    elif delta_direction == "decrease":
        action_words = ["감산"]

    sentences = re.split(r"(?<=[.。])\s+|\n+", adjustment_context)
    for sentence in sentences:
        normalized = normalize_spaces(sentence)
        if not normalized:
            continue
        if not any(word in normalized for word in action_words):
            continue
        token = extract_fault_owner_token(normalized)
        if not token:
            continue
        key = resolve_target_token_to_party_key(token, parties)
        if key:
            return {
                "target_party_key": key,
                "target_inference_source": "adjustment_explanation_fault_owner",
                "target_inference_confidence": 0.75,
                "target_context_text": normalized,
            }

    return {
        "target_party_key": None,
        "target_inference_source": None,
        "target_inference_confidence": 0.0,
        "target_context_text": None,
    }


def extract_fault_owner_token(sentence: str) -> Optional[str]:
    """'보행자의 과실', 'B차량의 과실', '차의 과실'에서 owner token을 뽑습니다."""

    patterns = [
        r"(?P<owner>A|B)\s*차량의?\s*과실",
        r"(?P<owner>A|B)의?\s*과실",
        r"(?P<owner>보행자|보|차|차량|자동차|자전거|이륜차)의?\s*과실",
    ]
    for pattern in patterns:
        match = re.search(pattern, sentence)
        if match:
            return match.group("owner")
    return None
def parse_adjustment_line(line: str) -> Optional[Dict[str, Any]]:
    """수정요소 한 줄을 구조화합니다."""

    # 원문 번호를 추출합니다.
    order_match = re.search(r"[①②③④⑤⑥⑦⑧⑨⑩]", line)

    # 원문 번호입니다.
    order_no = order_match.group(0) if order_match else None

    # 원문 번호를 제거합니다.
    cleaned = re.sub(r"[①②③④⑤⑥⑦⑧⑨⑩]", "", line).strip()

    # 대상 당사자 A/B/차/보를 추정합니다.
    target_party_key, cleaned, _target_prefix_source = split_adjustment_target_prefix(cleaned)

    # 비적용 처리입니다.
    if "비적용" in cleaned:
        name = cleaned.replace("비적용", "").strip()
        return {
            "order_no": order_no,
            "target_party_key": target_party_key,
            "factor_name": name,
            "delta": None,
            "delta_direction": "not_applicable",
            "raw_delta": "비적용",
        }

    # +10/-10 수치 처리입니다.
    delta_match = re.search(r"(?P<delta>[+-]\s*\d{1,2})$", cleaned)

    # 수치가 없으면 None입니다.
    if not delta_match:
        return None

    # 원문 수치입니다.
    raw_delta = delta_match.group("delta").replace(" ", "")

    # 정수 수치입니다.
    delta = int(raw_delta)

    # 수정요소명입니다.
    name = cleaned[:delta_match.start()].strip()
    name = re.sub(r"^[·ㆍ\-\s]+", "", name)
    if not name:
        return None

    # 결과를 반환합니다.
    return {
        "order_no": order_no,
        "target_party_key": target_party_key,
        "factor_name": name,
        "delta": delta,
        "delta_direction": "increase" if delta > 0 else "decrease",
        "raw_delta": raw_delta,
    }


def split_adjustment_target_prefix(cleaned: str) -> Tuple[Optional[str], str, Optional[str]]:
    """수정요소명 앞에 붙은 대상자 prefix를 분리합니다."""

    patterns = [
        (r"^(A|B|차|보)\s+", lambda match: match.group(1), "line_target_prefix"),
        (r"^(A|B)(?=[가-힣])", lambda match: match.group(1), "attached_ab_prefix"),
        (r"^(차|차량|자동차)의?\s+", lambda match: "차", "vehicle_label_prefix"),
        (r"^(보행자|보)의?\s+", lambda match: "보", "pedestrian_label_prefix"),
        (r"^(자전거|이륜차)의?\s+", lambda match: match.group(1), "vehicle_subtype_label_prefix"),
    ]

    for pattern, key_getter, source in patterns:
        match = re.match(pattern, cleaned)
        if not match:
            continue
        key = key_getter(match)
        return key, cleaned[match.end():].strip(), source

    return None, cleaned, None


def parse_rule_like_header(line: str) -> bool:
    """다음 rule/장/목차성 header인지 판단합니다."""

    return bool(
        re.fullmatch(r"[보차거]\d+(?:-\d+)?", line)
        or re.match(r"^제\s*\d+\s*장", line)
        or line in {"목차", "목 차"}
        or "세부유형별 과실비율 적용기준" in line
    )


def split_rule_blocks(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """rule 내부 텍스트를 의미 block으로 나눕니다."""

    # block 기준입니다.
    specs = [
        ("party_condition", None, "기본 과실비율"),
        ("base_fault", "기본 과실비율", "사고 상황"),
        ("accident_situation", "사고 상황", "기본 과실비율 해설"),
        ("base_fault_explanation", "기본 과실비율 해설", "수정요소"),
        ("adjustment_explanation", "수정요소", "활용시 참고 사항"),
        ("usage_note", "활용시 참고 사항", "관련 법규"),
        ("related_law", "관련 법규", "참고 판례"),
        ("reference_case", "참고 판례", None),
    ]

    # 결과 block 목록입니다.
    blocks: List[Dict[str, Any]] = []

    # block을 하나씩 추출합니다.
    for block_type, start, end in specs:
        # 텍스트 범위를 추출합니다.
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
                "block_title": start or "rule_header",
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
    sanitize_info = sanitize_evidence_block_info(extract_between(text, "관련 법규", "참고 판례") or "")
    law_block = sanitize_info["text"]

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
                "context_sanitized": sanitize_info["context_sanitized"],
                "context_skip_count": sanitize_info["skip_count"],
                "context_break_applied": sanitize_info["break_applied"],
            }
        )

    # 중복 제거 후 반환합니다.
    return dedupe_rows(refs, ["raw_text"])


def extract_reference_cases(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """참고 판례를 추출합니다."""

    # 참고 판례 block을 가져옵니다.
    sanitize_info = sanitize_evidence_block_info(extract_between(text, "참고 판례", None) or "")
    block = sanitize_info["text"]

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
                "context_sanitized": sanitize_info["context_sanitized"],
                "context_skip_count": sanitize_info["skip_count"],
                "context_break_applied": sanitize_info["break_applied"],
            }
        )

    # 판례 목록을 반환합니다.
    return cases


def extract_usage_notes(text: str, rule_id: str) -> List[Dict[str, Any]]:
    """활용시 참고 사항을 추출합니다."""

    # 활용시 참고 사항 block입니다.
    sanitize_info = sanitize_evidence_block_info(extract_between(text, "활용시 참고 사항", "관련 법규") or "")
    block = sanitize_info["text"]

    # 결과 리스트입니다.
    notes: List[Dict[str, Any]] = []

    # ⊙ 단위로 분리합니다.
    parts = [part.strip() for part in block.split("⊙") if part.strip()]

    # 각 참고사항을 row로 만듭니다.
    for idx, part in enumerate(parts, start=1):
        notes.append(
            {
                "usage_note_id": f"note_{rule_id}_{idx:03d}",
                "rule_id": rule_id,
                "note_text": normalize_spaces(part),
                "raw_text": part,
                "note_type": infer_usage_note_type(part),
                "context_sanitized": sanitize_info["context_sanitized"],
                "context_skip_count": sanitize_info["skip_count"],
                "context_break_applied": sanitize_info["break_applied"],
            }
        )

    # 참고사항 목록을 반환합니다.
    return notes


def extract_between(text: str, start_marker: Optional[str], end_marker: Optional[str]) -> Optional[str]:
    """텍스트에서 시작 marker와 끝 marker 사이를 추출합니다."""

    # 시작 marker가 없으면 처음부터 시작합니다.
    if start_marker is None:
        content_start = 0

    # 시작 marker가 있으면 위치를 찾습니다.
    else:
        start_idx = text.find(start_marker)
        if start_idx < 0:
            return None
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


def sanitize_evidence_block(text: str) -> str:
    """법규/판례/참고사항 block에서 반복 footer/header만 제거하고 본문은 보존합니다.

    이전 방식처럼 contamination marker를 만나자마자 break하면 다음 페이지에 이어지는 법규/판례가
    통째로 사라질 수 있습니다. 따라서 반복 레이아웃 노이즈는 skip하고, 별첨/변경대비표처럼
    명확한 종료 marker만 break합니다.
    """

    return sanitize_evidence_block_info(text)["text"]


def sanitize_evidence_block_info(text: str) -> Dict[str, Any]:
    """evidence block 정리 결과와 처리 메타데이터를 함께 반환합니다."""

    kept: List[str] = []
    skip_count = 0
    break_applied = False
    for raw_line in text.splitlines():
        line = normalize_spaces(raw_line.strip())
        if not line:
            kept.append("")
            continue

        action = evidence_line_action(line)
        if action == "break":
            break_applied = True
            break
        if action == "skip":
            skip_count += 1
            continue

        kept.append(line)

    return {
        "text": normalize_spaces("\n".join(kept)),
        "context_sanitized": skip_count > 0 or break_applied,
        "skip_count": skip_count,
        "break_applied": break_applied,
    }


def evidence_line_action(line: str) -> str:
    """evidence block 내부 line 처리 방식을 반환합니다."""

    if "변경대비표" in line and "별첨" in line:
        return "break"

    if line in {"목차", "목 차"}:
        return "skip"

    if line in {
        "제1장. 자동차와 보행자의 사고",
        "제2장. 자동차와 자동차(이륜차 포함)의 사고",
        "제3장. 자동차와 자전거(농기계 포함)의 사고",
    }:
        return "skip"

    return "keep"


def is_evidence_contamination_line(line: str) -> bool:
    """다른 장/목차/다음 rule marker인지 판단합니다.

    호환용 함수입니다. evidence에서는 break 대신 sanitize_evidence_block의 skip/break 정책을 씁니다.
    """

    return evidence_line_action(line) in {"break", "skip"}


def infer_party_label(key: str, rule_prefix: str, raw_key: str | None = None) -> str:
    """party key를 사람이 읽는 라벨로 바꿉니다."""

    if key == "보":
        return "보행자"

    if key == "차":
        if raw_key == "이륜차":
            return "이륜차"
        if raw_key == "자전거":
            return "자전거"
        return "자동차"

    if key == "A":
        return "A차량"

    if key == "B":
        return "B차량"

    return key


def infer_party_type(key: str, rule_prefix: str, action: str) -> str:
    """party type을 추정합니다."""

    normalized = normalize_spaces(action or "")
    if key == "보":
        return "pedestrian"

    if key == "차":
        if "이륜" in normalized:
            return "motorcycle"
        if "자전거" in normalized:
            return "bicycle"
        return "vehicle"

    if "보행자" in normalized:
        return "pedestrian"

    if rule_prefix == "거" and key == "A":
        return "bicycle"

    if "이륜" in action:
        return "motorcycle"

    return "vehicle"


def infer_party_movement(action: str, raw_key: str, rule_title: str, party_type: str) -> Optional[str]:
    """party action을 우선하고 title은 보조로만 사용해 movement를 추정합니다."""

    movement = infer_movement(f"{action} {raw_key}", party_type=party_type, allow_fallback=False)
    if movement:
        return movement
    if party_type in {"vehicle", "motorcycle", "bicycle", "pm"} and is_generic_vehicle_action(action, raw_key):
        return "주행"
    return infer_movement(f"{rule_title} {raw_key}", party_type=party_type, allow_fallback=True)


def is_generic_vehicle_action(action: str, raw_key: str) -> bool:
    """차량 party가 구체 행위 없이 차종명만 가진 경우 기본 주행으로 보강합니다."""

    normalized = normalize_spaces(f"{action} {raw_key}")
    tokens = set(normalized.split())
    vehicle_tokens = {"자동차", "차량", "차", "이륜차", "자전거", "PM", "A", "B"}
    return bool(tokens) and tokens.issubset(vehicle_tokens)


def infer_movement(text: str, party_type: Optional[str] = None, allow_fallback: bool = True) -> Optional[str]:
    """주요 이동 행위를 추정합니다."""

    normalized = normalize_spaces(text or "")
    movements = [
        "보행자 전용도로 침범 주행",
        "보행자 전용도로 보행",
        "차도 가장자리 보행",
        "차도 중앙부분 보행",
        "차도에서 놀기",
        "누워 있음",
        "이유없는 보행",
        "이유있는 보행",
        "중앙선 침범",
        "우측 끼어들기",
        "좌측 끼어들기",
        "정차 후 후진",
        "정차 후 출발",
        "선행 주차진행",
        "교차로 내 회전",
        "보도 침범 주행",
        "차도 보행",
        "보도 보행",
        "통로주행",
        "정상통행",
        "신호위반 직진",
        "신호위반 좌회전",
        "신호위반 우회전",
        "적재물 낙하",
        "실선 추월",
        "긴급자동차 추월",
        "본선차",
        "합류차",
        "문 열림",
        "문열림",
        "진로변경",
        "차로변경",
        "끼어들기",
        "역통행",
        "주정차",
        "피추돌",
        "합류",
        "직진",
        "좌회전",
        "우회전",
        "횡단",
        "후행차",
        "선행차",
        "후행",
        "선행",
        "후진",
        "출발",
        "주차",
        "정차",
        "주행",
        "통행",
        "보행",
        "유턴",
        "추돌",
        "개문",
        "진입",
        "회전",
    ]

    for movement in movements:
        if not is_movement_allowed_for_party_type(movement, party_type):
            continue
        if movement in normalized:
            return movement

    if not allow_fallback:
        return None

    # 표현이 짧아서 action만으로 비는 경우 보수 보강합니다.
    if "보행자" in normalized or normalized.strip() in {"보", "A", "A차량"}:
        if "차도" in normalized:
            return "차도 보행" if is_movement_allowed_for_party_type("차도 보행", party_type) else None
        if "보도" in normalized:
            return "보도 보행" if is_movement_allowed_for_party_type("보도 보행", party_type) else None
        if "횡단" in normalized or "교차로" in normalized:
            return "횡단"
        return "보행" if is_movement_allowed_for_party_type("보행", party_type) else None

    if "본선" in normalized:
        return "본선차"
    if "합류" in normalized:
        return "합류"
    if "추월" in normalized:
        return "추월"
    if "자동차" in normalized or "차량" in normalized or "A차량" in normalized or "B차량" in normalized:
        if "교차로" in normalized:
            return "진입"
        if "횡단" in normalized:
            return "주행"
        return "주행"


def is_movement_allowed_for_party_type(movement: str, party_type: Optional[str]) -> bool:
    """party type과 명백히 충돌하는 movement를 제외합니다."""

    if not party_type:
        return True

    pedestrian_movements = {
        "보행자 전용도로 보행",
        "차도 가장자리 보행",
        "차도 중앙부분 보행",
        "차도에서 놀기",
        "이유없는 보행",
        "이유있는 보행",
        "차도 보행",
        "보도 보행",
        "보행",
        "횡단",
        "누워 있음",
    }
    vehicle_only_movements = {
        "보행자 전용도로 침범 주행",
        "중앙선 침범",
        "우측 끼어들기",
        "좌측 끼어들기",
        "정차 후 후진",
        "정차 후 출발",
        "선행 주차진행",
        "교차로 내 회전",
        "보도 침범 주행",
        "통로주행",
        "정상통행",
        "신호위반 직진",
        "신호위반 좌회전",
        "신호위반 우회전",
        "적재물 낙하",
        "실선 추월",
        "긴급자동차 추월",
        "문 열림",
        "문열림",
        "진로변경",
        "차로변경",
        "끼어들기",
        "역통행",
        "주정차",
        "피추돌",
        "합류",
        "후진",
        "출발",
        "주차",
        "정차",
        "주행",
        "통행",
        "직진",
        "좌회전",
        "우회전",
        "유턴",
        "추돌",
        "개문",
        "진입",
        "회전",
    }

    if party_type == "pedestrian":
        return movement not in vehicle_only_movements
    if party_type in {"vehicle", "motorcycle", "bicycle", "pm"}:
        return movement not in pedestrian_movements
    return True

    return None

def infer_signal_state(text: str) -> Optional[str]:
    """녹색/황색/적색 등 신호 상태를 추정합니다."""

    for value in ["녹색점멸", "녹색", "황색", "적색", "신호없음"]:
        if value in text:
            return value

    return None


def infer_road_position(text: str) -> Optional[str]:
    """도로 위치를 추정합니다."""

    for value in ["횡단보도", "회전교차로", "교차로", "자전거도로", "자전거횡단도", "보도", "차도", "대로", "소로", "주차장"]:
        if value in text:
            return value

    return None


def infer_entry_timing(text: str) -> Optional[str]:
    """선진입/후진입/통과 후 여부를 추정합니다."""

    if "선진입" in text:
        return "선진입"

    if "후진입" in text:
        return "후진입"

    if "통과 후" in text:
        return "교차로 통과 후"

    if "통과 전" in text:
        return "교차로 통과 전"

    return None


def infer_violation(text: str) -> Optional[str]:
    """위반 유형을 추정합니다."""

    candidates = ["신호위반", "중앙선 침범", "진로변경금지 위반", "좌회전 금지위반", "일시정지위반", "과속", "급진입"]

    for candidate in candidates:
        if candidate in text:
            return candidate

    return None


def infer_target_party_type(key: Optional[str], parties: List[Dict[str, Any]]) -> Optional[str]:
    """수정요소 대상 key로 party type을 찾습니다."""

    if key is None:
        return None

    for party in parties:
        if party.get("party_key") == key:
            return party.get("party_type")

    if key == "보":
        return "pedestrian"

    if key == "차":
        return "vehicle"

    if key in {"A", "B"}:
        return "vehicle"

    return None


def classify_adjustment_factor(name: str) -> str:
    """수정요소명을 카테고리로 분류합니다."""

    if "야간" in name or "시야장애" in name:
        return "visibility"

    if "간선도로" in name or "대로" in name or "소로" in name:
        return "road_type"

    if "주택" in name or "상점가" in name or "학교" in name:
        return "area_context"

    if "보호구역" in name:
        return "protected_area"

    if "어린이" in name or "노인" in name or "장애인" in name:
        return "vulnerable_person"

    if "현저" in name or "중대한" in name or "중과실" in name:
        return "severe_fault"

    if "선진입" in name:
        return "entry_timing"

    if "신호" in name:
        return "signal_behavior"

    if "진로변경" in name or "차로변경" in name:
        return "lane_behavior"

    if "비적용" in name:
        return "non_applicable"

    return "other"


def infer_law_role(text: str, raw: str) -> str:
    """법령 문맥에서 해당 법령의 역할을 추정합니다."""

    context = text[max(0, text.find(raw) - 80): text.find(raw) + 160]

    if "신호" in context:
        return "signal"

    if "보행자" in context or "횡단보도" in context:
        return "pedestrian_protection"

    if "교차로" in context:
        return "intersection"

    if "진로" in context or "차로" in context:
        return "lane_change"

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
    """문맥에서 과실비율 표현을 추출합니다. 시간(HH:MM)은 제외합니다."""

    for match in re.finditer(r"(?P<a>\d{1,3})\s*:\s*(?P<b>\d{1,3})", text):
        a = int(match.group("a"))
        b = int(match.group("b"))
        raw = match.group(0)
        if is_time_like_ratio(raw, a, b):
            continue
        if a + b == 100:
            return raw

    # %는 주변 문맥에 과실/비율/책임이 있을 때만 인정합니다.
    for match in re.finditer(r"(?P<value>\d{1,3})\s*%", text):
        left = text[max(0, match.start() - 25): match.start()]
        right = text[match.end(): match.end() + 25]
        if any(token in f"{left} {right}" for token in ["과실", "비율", "책임", "부담"]):
            return match.group(0)

    return None


def is_time_like_ratio(raw: str, a: int, b: int) -> bool:
    """10:02, 15:00 같은 사고 시각을 과실비율에서 제외합니다."""

    if a <= 24 and b <= 59:
        if re.fullmatch(r"\d{1,2}\s*:\s*\d{2}", raw):
            return True
    return False


def infer_case_relevance(text: str) -> str:
    """판례 문맥에서 관련성을 추정합니다."""

    if "횡단보도" in text:
        return "crosswalk"

    if "교차로" in text:
        return "intersection"

    if "중앙선" in text:
        return "centerline"

    if "진로변경" in text:
        return "lane_change"

    return "general"


def infer_usage_note_type(text: str) -> str:
    """활용시 참고 사항 유형을 추정합니다."""

    if "준용" in text:
        return "analogical_application"

    if "적용하지 않는다" in text:
        return "exclusion"

    if "동일하다" in text:
        return "same_application"

    return "general_note"


def get_context(text: str, start: int, end: int, window: int = 140) -> str:
    """매칭 주변 문맥을 반환합니다."""

    left = max(0, start - window)
    right = min(len(text), end + window)

    return normalize_spaces(text[left:right])





