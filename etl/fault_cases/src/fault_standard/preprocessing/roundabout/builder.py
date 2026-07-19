# -*- coding: utf-8 -*-
"""rule JSON 패키지와 DB 적재용 table row를 생성합니다."""

import re
from pathlib import Path
from typing import Any, Dict, List

from .chunker import build_chunks
from .classifiers import build_roundabout_context, build_roundabout_scope, classify_accident, get_major_group
from .config import PREPROCESSING_VERSION
from .extractors import (
    build_lane_path_context,
    extract_adjustment_factors,
    extract_base_fault,
    extract_law_refs,
    extract_parties,
    extract_reference_cases,
    has_dangling_action_suffix,
    split_rule_blocks,
)
from .file_utils import safe_filename


def build_rule_package(
    section: Dict[str, Any],
    pdf_path: Path,
    file_hash: str,
    page_coverage: Dict[str, Any],
) -> Dict[str, Any]:
    """회전 rule section을 최종 rule JSON 구조로 변환합니다."""

    # 구조화된 rule 텍스트입니다.
    text = section["structured_text"]

    # 회전 번호입니다.
    round_no = int(section["round_no"])

    # 회전 코드입니다.
    round_code = section["round_code"]

    # 내부 rule ID입니다.
    rule_id = f"roundabout_2025_{round_code}"

    # 큰 사고군 정보입니다.
    major = get_major_group(round_no)

    # 당사자 정보를 추출합니다.
    parties = extract_parties(text, rule_id)

    # 기본 과실비율을 추출합니다.
    base_fault = extract_base_fault(text)

    # 수정요소를 추출합니다.
    adjustment_factors = extract_adjustment_factors(text, rule_id)

    # block을 분리합니다.
    blocks = split_rule_blocks(text, rule_id)

    # 관련 법규를 추출합니다.
    law_refs = extract_law_refs(text, rule_id)

    # 참고 판례를 추출합니다.
    reference_cases = extract_reference_cases(text, rule_id)

    # 차로 경로 context를 만듭니다.
    lane_path_context = build_lane_path_context(parties, text)

    # 사고유형을 분류합니다.
    accident_classification = classify_accident(round_no, section["rule_title"], text)

    # 검색용 chunk를 만듭니다.
    chunks = build_chunks(rule_id, round_code, section, blocks, base_fault, accident_classification, lane_path_context)

    # 레드/블루 context를 분리합니다.
    red_context = build_color_context(parties, "red")
    blue_context = build_color_context(parties, "blue")

    # 최종 rule JSON 구조를 반환합니다.
    return {
        "metadata": {
            "rule_id": rule_id,
            "source_type": "fault_standard",
            "source_subtype": "roundabout_2025",
            "source_reliability": "official_standard",
            "source_file": pdf_path.name,
            "published_year": 2025,
            "published_month": 6,
            "preprocessing_version": PREPROCESSING_VERSION,
            "file_hash": file_hash,
            "page_start": section["page_start"],
            "page_end": section["page_end"],
            "page_count_checked": page_coverage["status"] == "success",
            "missing_pages": page_coverage["missing_pages"],
        },
        "hierarchy": {
            "document_title": "2차로형 회전교차로 사고 과실비율 비정형 기준",
            "section_title": "2차로형 회전교차로 사고 과실비율 비정형 기준",
            "major_group_no": major["major_group_no"],
            "major_group_title": major["major_group_title"],
            "round_code": round_code,
            "round_no": round_no,
            "section_path": [
                "2차로형 회전교차로 사고 과실비율 비정형 기준",
                major["major_group_title"],
                f"{round_code} {section['rule_title']}",
            ],
        },
        "rule_identity": {
            "round_code": round_code,
            "round_no": round_no,
            "rule_title": section["rule_title"],
            "rule_title_clean": safe_filename(section["rule_title"]),
            "rule_type": "two_lane_roundabout",
            "major_group": major["major_group"],
            "related_existing_standard_codes": ["차54-1", "차54-2", "차54-3", "차54-4", "차54-5"],
            "is_nontypical_standard": True,
            "will_be_integrated_to_regular_standard": True,
        },
        "roundabout_scope": build_roundabout_scope(),
        "accident_classification": accident_classification,
        "parties": parties,
        "red_vehicle_context": red_context,
        "blue_vehicle_context": blue_context,
        "lane_path_context": lane_path_context,
        "roundabout_context": build_roundabout_context(),
        "base_fault": base_fault,
        "adjustment_factors": adjustment_factors,
        "blocks": blocks,
        "law_refs": law_refs,
        "reference_cases": reference_cases,
        "texts": {
            "raw_text": section["raw_text"],
            "clean_text": section["clean_text"],
            "structured_text": section["structured_text"],
        },
        "cleaning_quality": build_cleaning_quality(section, base_fault, parties),
        "parse_quality": build_parse_quality(
            section,
            base_fault,
            parties,
            adjustment_factors,
            law_refs,
            reference_cases,
            blocks,
            lane_path_context,
        ),
        "chunks": chunks,
    }


def build_color_context(parties: List[Dict[str, Any]], color: str) -> Dict[str, Any]:
    """레드/블루 차량 context를 납작한 딕셔너리로 만듭니다."""

    # 해당 색상 party를 찾습니다.
    party = next((p for p in parties if p.get("party_color") == color), {})

    # 접두어입니다.
    prefix = "red" if color == "red" else "blue"

    # 색상별 context를 반환합니다.
    return {
        f"{prefix}_party_key": party.get("party_key"),
        f"{prefix}_action": party.get("action_summary"),
        f"{prefix}_entry_direction": party.get("entry_direction"),
        f"{prefix}_entry_lane": party.get("entry_lane"),
        f"{prefix}_circulation_lane": party.get("circulation_lane"),
        f"{prefix}_exit_direction": party.get("exit_direction"),
        f"{prefix}_exit_lane": party.get("exit_lane"),
        f"{prefix}_is_first_entry": party.get("is_first_entry"),
        f"{prefix}_is_late_entry": party.get("is_late_entry"),
        f"{prefix}_is_lane_changing": party.get("is_lane_changing"),
        f"{prefix}_is_exiting": party.get("is_exiting"),
        f"{prefix}_violated_road_marking": party.get("violated_road_marking"),
    }


def build_cleaning_quality(section: Dict[str, Any], base_fault: Dict[str, Any], parties: List[Dict[str, Any]]) -> Dict[str, Any]:
    """클리닝 품질 상태를 만듭니다."""

    structured = section["structured_text"]
    raw = section.get("raw_text", "")

    return {
        "page_noise_removed": not any(marker in structured for marker in ["목 차", "자동차사고 과실비율 인정기준 0"]),
        "header_footer_removed": not bool(re.search(r"^\s*-\s*\d+\s*-\s*$", structured, re.MULTILINE)),
        "vertical_label_repaired": "과실비율 조정 예시" in structured,
        "ratio_expression_normalized": base_fault.get("normalized_ratio") is not None,
        "lane_expression_normalized": any(token in structured for token in ["진입1차로", "진입2차로", "회전1차로", "회전2차로"]),
        "direction_expression_preserved": any(x in structured for x in ["3시", "6시", "9시", "12시"]),
        "special_symbols_preserved": [symbol for symbol in ["+", "-", ":", "→", "·"] if symbol in raw or symbol in structured],
        "uncertain_terms": [p.get("party_key") for p in parties if has_dangling_action_suffix(p.get("action_summary", ""))],
        "needs_manual_review": not base_fault.get("normalized_ratio") or len(parties) < 2 or any(has_dangling_action_suffix(p.get("action_summary", "")) for p in parties),
    }


def build_parse_quality(
    section: Dict[str, Any],
    base_fault: Dict[str, Any],
    parties: List[Dict[str, Any]],
    adjustments: List[Dict[str, Any]],
    law_refs: List[Dict[str, Any]],
    reference_cases: List[Dict[str, Any]],
    blocks: List[Dict[str, Any]],
    lane_path_context: Dict[str, Any],
) -> Dict[str, Any]:
    """파싱 품질 상태를 만듭니다."""

    # 검수 필요 사유입니다.
    reasons: List[str] = []
    quality_flags: List[str] = []

    # 기본과실 추출 실패입니다.
    if not base_fault.get("normalized_ratio"):
        reasons.append("base_fault_not_detected")

    # 당사자 2명 미만이면 실패입니다.
    if len(parties) < 2:
        reasons.append("party_parse_incomplete")

    # 수정요소가 없으면 검토가 필요합니다.
    if not adjustments:
        reasons.append("adjustment_factors_not_detected")

    if not lane_path_context.get("red_path") or not lane_path_context.get("blue_path"):
        reasons.append("lane_path_empty")

    if any(has_control_chars(p.get("raw_text", "")) or has_control_chars(p.get("action_summary", "")) for p in parties):
        reasons.append("control_char_detected")

    if any(is_direction_parse_suspicious(p) for p in parties):
        reasons.append("direction_parse_suspicious")

    if any(("차로변경" in p.get("action_summary", "") or "진로변경" in p.get("action_summary", "")) and not p.get("lane_change_to") for p in parties):
        reasons.append("lane_change_parse_incomplete")

    if any(has_dangling_action_suffix(p.get("action_summary", "")) for p in parties):
        reasons.append("dangling_action_suffix")

    if lane_path_context.get("conflict_direction") and not lane_path_context.get("conflict_direction_confirmed"):
        quality_flags.append("conflict_direction_derived")

    if lane_path_context.get("conflict_lane") and not lane_path_context.get("conflict_lane_confirmed"):
        quality_flags.append("conflict_lane_derived")

    if any(p.get("entry_direction") and p.get("exit_direction") and p.get("entry_direction") == p.get("exit_direction") for p in parties):
        reasons.append("entry_exit_direction_same_check")

    # 품질 결과를 반환합니다.
    return {
        "parse_status": "valid" if not reasons else "review_required",
        "page_count_checked": True,
        "missing_pages": [],
        "round_code_detected": bool(section.get("round_code")),
        "title_detected": bool(section.get("rule_title")),
        "red_party_detected": any(p.get("party_color") == "red" for p in parties),
        "blue_party_detected": any(p.get("party_color") == "blue" for p in parties),
        "base_fault_detected": bool(base_fault.get("normalized_ratio")),
        "lane_path_detected": bool(lane_path_context.get("red_path")) and bool(lane_path_context.get("blue_path")),
        "adjustment_factor_detected": bool(adjustments),
        "law_ref_detected": bool(law_refs),
        "reference_case_detected": bool(reference_cases),
        "block_split_success": bool(blocks),
        "lane_path_empty": not lane_path_context.get("red_path") or not lane_path_context.get("blue_path"),
        "direction_parse_suspicious": any(is_direction_parse_suspicious(p) for p in parties),
        "control_char_detected": any(has_control_chars(p.get("raw_text", "")) or has_control_chars(p.get("action_summary", "")) for p in parties),
        "dangling_action_suffix": any(has_dangling_action_suffix(p.get("action_summary", "")) for p in parties),
        "conflict_direction_source": lane_path_context.get("conflict_direction_source"),
        "conflict_direction_confidence": lane_path_context.get("conflict_direction_confidence"),
        "conflict_direction_confirmed": lane_path_context.get("conflict_direction_confirmed"),
        "conflict_lane_source": lane_path_context.get("conflict_lane_source"),
        "conflict_lane_confidence": lane_path_context.get("conflict_lane_confidence"),
        "conflict_lane_confirmed": lane_path_context.get("conflict_lane_confirmed"),
        "quality_flags": [*quality_flags, *reasons],
        "needs_manual_review_reason": reasons,
    }


def has_control_chars(text: str) -> bool:
    """줄바꿈/탭 외 제어문자가 남아 있는지 확인합니다."""

    return any(ord(ch) < 32 and ch not in "\n\t" for ch in text)


def is_direction_parse_suspicious(party: Dict[str, Any]) -> bool:
    """진입/진출 방향이 같은 값으로 잘못 잡힌 것으로 의심되는지 확인합니다."""

    action = party.get("action_summary", "")
    entry_direction = party.get("entry_direction")
    exit_direction = party.get("exit_direction")

    if "진출" in action and not exit_direction:
        return True

    if entry_direction and exit_direction and entry_direction == exit_direction and len(set(re.findall(r"(?:3시|6시|9시|12시)\s*방향", action))) > 1:
        return True

    return False


def flatten_packages_to_tables(packages: List[Dict[str, Any]], sections: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """nested rule JSON들을 DB 적재용 JSONL row로 분해합니다."""

    # table별 row를 저장할 딕셔너리입니다.
    tables = {
        "rulebooks": [],
        "sections": sections,
        "rules": [],
        "parties": [],
        "base_faults": [],
        "roundabout_contexts": [],
        "lane_paths": [],
        "lane_steps": [],
        "adjustment_factors": [],
        "rule_blocks": [],
        "law_refs": [],
        "reference_cases": [],
        "chunks": [],
        "parse_quality_report": [],
    }

    # 각 rule package를 table row로 나눕니다.
    for package in packages:
        # rule_id입니다.
        rule_id = package["metadata"]["rule_id"]

        # table별로 row를 추가합니다.
        tables["rules"].append(flatten_rule(package))
        tables["parties"].extend(package["parties"])
        tables["base_faults"].append({"rule_id": rule_id, **package["base_fault"]})
        tables["roundabout_contexts"].append({"rule_id": rule_id, **package["roundabout_context"]})
        tables["lane_paths"].extend(build_lane_path_rows(rule_id, package["lane_path_context"]))
        tables["lane_steps"].extend(build_lane_step_rows(rule_id, package["lane_path_context"]))
        tables["adjustment_factors"].extend(package["adjustment_factors"])
        tables["rule_blocks"].extend(package["blocks"])
        tables["law_refs"].extend(package["law_refs"])
        tables["reference_cases"].extend(package["reference_cases"])
        tables["chunks"].extend(package["chunks"])
        tables["parse_quality_report"].append({"rule_id": rule_id, **package["parse_quality"]})

    # table row 묶음을 반환합니다.
    return tables


def build_lane_path_rows(rule_id: str, lane_path_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert red/blue path context into party-level lane path rows."""

    rows: List[Dict[str, Any]] = []
    for color, party_key in [("red", "A"), ("blue", "B")]:
        steps = lane_path_context.get(f"{color}_lane_steps", []) or []
        lanes = [step.get("lane") for step in steps if step.get("lane")]
        rows.append({
            "lane_path_id": f"lane_path_{rule_id}_{party_key}",
            "rule_id": rule_id,
            "party_key": party_key,
            "entry_direction": first_step_value(steps, "진입", "direction"),
            "exit_direction": first_step_value(steps, "진출", "direction"),
            "entry_lane": first_step_value(steps, "진입", "lane"),
            "circulation_lane": first_step_value(steps, "회전", "lane"),
            "exit_lane": first_step_value(steps, "진출", "lane"),
            "is_lane_changing": len(set(lanes)) > 1,
            "is_exiting": any(step.get("movement") == "진출" for step in steps),
            "raw_text": lane_path_context.get(f"{color}_path_text"),
        })
    return rows


def first_step_value(steps: List[Dict[str, Any]], movement: str, key: str) -> Any:
    for step in steps:
        if step.get("movement") == movement and step.get(key) is not None:
            return step.get(key)
    return None


def build_lane_step_rows(rule_id: str, lane_path_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """lane_path_context의 red/blue lane steps를 DB 적재용 row로 변환합니다."""

    rows: List[Dict[str, Any]] = []
    for color, party_key in [("red", "A"), ("blue", "B")]:
        for step in lane_path_context.get(f"{color}_lane_steps", []) or []:
            rows.append({
                "lane_step_id": f"lane_step_{rule_id}_{party_key}_{int(step.get('seq', len(rows) + 1)):02d}",
                "rule_id": rule_id,
                "party_key": party_key,
                "party_color": color,
                "seq": step.get("seq"),
                "movement": step.get("movement"),
                "lane": step.get("lane"),
                "direction": step.get("direction"),
                "source": step.get("source"),
                "source_text": step.get("source_text"),
                "confidence": step.get("confidence"),
            })
    return rows


def flatten_rule(package: Dict[str, Any]) -> Dict[str, Any]:
    """rule JSON에서 rules.jsonl용 핵심 필드만 납작하게 뽑습니다."""

    # 자주 쓰는 하위 구조를 꺼냅니다.
    metadata = package["metadata"]
    identity = package["rule_identity"]
    hierarchy = package["hierarchy"]
    base = package["base_fault"]
    accident = package["accident_classification"]

    # 납작한 rule row를 반환합니다.
    return {
        "rule_id": metadata["rule_id"],
        "source_type": metadata["source_type"],
        "source_subtype": metadata["source_subtype"],
        "source_reliability": metadata["source_reliability"],
        "source_file": metadata["source_file"],
        "round_code": identity["round_code"],
        "round_no": identity["round_no"],
        "rule_title": identity["rule_title"],
        "rule_type": identity["rule_type"],
        "major_group": identity["major_group"],
        "section_path": hierarchy["section_path"],
        "accident_group": accident["accident_group"],
        "accident_subgroup": accident["accident_subgroup"],
        "red_ratio": base.get("red_ratio"),
        "blue_ratio": base.get("blue_ratio"),
        "normalized_ratio": base.get("normalized_ratio"),
        "page_start": metadata["page_start"],
        "page_end": metadata["page_end"],
        "parse_status": package["parse_quality"]["parse_status"],
    }
