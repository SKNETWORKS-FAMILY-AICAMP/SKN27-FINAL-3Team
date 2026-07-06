# -*- coding: utf-8 -*-
"""rule JSON 패키지와 DB 적재용 table row를 생성합니다."""

from pathlib import Path
import re
from typing import Any, Dict, List

from .chunker import build_chunks
from .classifiers_clean import build_hierarchy, classify_accident
from .config import PREPROCESSING_VERSION
from .extractors import (
    extract_adjustment_factors,
    extract_base_fault,
    extract_law_refs,
    extract_parties,
    extract_reference_cases,
    extract_usage_notes,
    extract_variants,
    split_rule_blocks,
)
from .file_utils import safe_filename


def build_rule_package(
    section: Dict[str, Any],
    pdf_path: Path,
    file_hash: str,
    page_coverage: Dict[str, Any],
) -> Dict[str, Any]:
    """rule section을 최종 rule JSON 구조로 변환합니다."""

    # 구조화된 rule 텍스트입니다.
    text = section["structured_text"]

    # rule code입니다.
    rule_code = section["rule_code"]

    # rule prefix입니다.
    rule_prefix = section["rule_prefix"]

    # 내부 rule ID입니다.
    rule_id = f"official_2023_{rule_code}"

    # hierarchy를 생성합니다.
    hierarchy = build_hierarchy(rule_prefix, section["page_start"], section["rule_title"])

    # 의미 block을 분리합니다.
    blocks = split_rule_blocks(text, rule_id)

    # 분류용 기본 사고상황 scope를 만듭니다.
    classification_scope = build_base_classification_scope(section, blocks)

    # 당사자 정보를 추출합니다.
    parties = extract_parties(text, rule_id, rule_prefix, rule_title=section["rule_title"])

    # 기본 과실비율을 추출합니다.
    base_fault = extract_base_fault(text, rule_prefix, rule_code)

    # 변형 정보를 추출합니다.
    variants = extract_variants(text, rule_id, rule_code=rule_code, rule_prefix=rule_prefix)

    # variants가 있는 rule은 계산 시 variants를 우선 사용하도록 표시합니다.
    base_fault = apply_base_fault_calculation_policy(base_fault, variants)

    # 수정요소를 추출합니다.
    adjustment_factors = extract_adjustment_factors(text, rule_id, parties, rule_prefix=rule_prefix, rule_title=section["rule_title"], base_fault=base_fault)

    # 관련 법규를 추출합니다.
    law_refs = extract_law_refs(text, rule_id)

    # 참고 판례를 추출합니다.
    reference_cases = extract_reference_cases(text, rule_id)

    # 활용시 참고 사항을 추출합니다.
    usage_notes = extract_usage_notes(text, rule_id)

    # 사고유형을 분류합니다.
    accident_classification = classify_accident(rule_prefix, section["rule_title"], classification_scope)
    accident_classification["classification_scope_source"] = "title_party_accident_base_blocks"

    # 검색용 chunk를 만듭니다.
    chunks = build_chunks(rule_id, section, blocks, base_fault, accident_classification)

    # 최종 rule JSON 구조를 반환합니다.
    return {
        "metadata": {
            "rule_id": rule_id,
            "source_type": "fault_standard",
            "source_subtype": "official_2023",
            "source_reliability": "official_standard",
            "source_file": pdf_path.name,
            "published_year": 2023,
            "published_month": 6,
            "preprocessing_version": PREPROCESSING_VERSION,
            "file_hash": file_hash,
            "page_start": section["page_start"],
            "page_end": section["page_end"],
            "page_count_checked": page_coverage["status"] == "success",
            "missing_pages": page_coverage["missing_pages"],
        },
        "hierarchy": {
            **hierarchy,
            "rule_group_ref": f"[{rule_code}]",
        },
        "rule_identity": {
            "rule_code": rule_code,
            "rule_prefix": rule_prefix,
            "rule_number": section["rule_number"],
            "rule_title": section["rule_title"],
            "rule_title_clean": safe_filename(section["rule_title"]),
            "accident_group": accident_classification["accident_group"],
            "accident_subgroup": accident_classification["accident_subgroup"],
            "rule_type": hierarchy["rule_type"],
            "has_multiple_variants": bool(variants),
            "variant_count": len(variants),
            "old_standard_refs": extract_old_standard_refs(text),
            "combined_parent_code": section.get("combined_parent_code"),
            "combined_rule_codes": section.get("combined_rule_codes", []),
        },
        "accident_classification": accident_classification,
        "parties": parties,
        "base_fault": base_fault,
        "variants": variants,
        "adjustment_factors": adjustment_factors,
        "blocks": blocks,
        "law_refs": law_refs,
        "reference_cases": reference_cases,
        "usage_notes": usage_notes,
        "texts": {
            "raw_text": section["raw_text"],
            "clean_text": section["clean_text"],
            "structured_text": section["structured_text"],
        },
        "cleaning_quality": build_cleaning_quality(section, base_fault, parties),
        "parse_quality": build_parse_quality(section, base_fault, parties, adjustment_factors, variants, law_refs, reference_cases, blocks),
        "chunks": chunks,
    }



def apply_base_fault_calculation_policy(base_fault: Dict[str, Any], variants: List[Dict[str, Any]]) -> Dict[str, Any]:
    """base fault 계산에 사용할 source 정책을 명시합니다."""

    if base_fault.get("base_fault_type") == "variant_ratio" or variants:
        enriched = dict(base_fault)
        enriched["base_fault_type"] = "variant_ratio"
        enriched["scenario_required"] = True
        enriched["variants_required"] = True
        enriched["calculation_source"] = "variants"
        enriched["auto_calculation_eligible"] = False
        enriched["manual_review_required"] = False
        return enriched

    enriched = dict(base_fault)
    enriched["scenario_required"] = False
    enriched["variants_required"] = False
    enriched["calculation_source"] = "base_faults"
    enriched["auto_calculation_eligible"] = is_base_fault_detected(base_fault)
    enriched["manual_review_required"] = not is_base_fault_detected(base_fault)
    return enriched
def build_base_classification_scope(section: Dict[str, Any], blocks: List[Dict[str, Any]]) -> str:
    """사고유형 분류에 쓸 기본 사고상황 scope만 조합합니다."""

    allowed_types = {"party_condition", "base_fault", "accident_situation"}
    parts = [section.get("rule_title", "")]
    parts.extend(block.get("structured_text", "") for block in blocks if block.get("block_type") in allowed_types)
    return "\n".join(part for part in parts if part)


def extract_old_standard_refs(text: str) -> List[str]:
    """舊 기준 번호를 추출합니다."""

    # 舊 201, 301, 302 기준 패턴을 찾습니다.
    match = __import__("re").search(r"舊\s*([0-9,\s]+)\s*기준", text)

    # 없으면 빈 리스트입니다.
    if not match:
        return []

    # 쉼표로 나눠 반환합니다.
    return [part.strip() for part in match.group(1).split(",") if part.strip()]


def is_base_fault_detected(base_fault: Dict[str, Any]) -> bool:
    """기본과실이 숫자 비율 또는 시나리오 비율 형태로 추출되었는지 판단합니다."""

    if base_fault.get("normalized_ratio"):
        return True
    if base_fault.get("base_fault_ratio") is not None:
        return True
    if base_fault.get("base_fault_type") == "variant_ratio":
        return True
    return False

def build_cleaning_quality(section: Dict[str, Any], base_fault: Dict[str, Any], parties: List[Dict[str, Any]]) -> Dict[str, Any]:
    """클리닝 품질 상태를 만듭니다."""

    return {
        "page_noise_removed": True,
        "header_footer_removed": True,
        "vertical_label_repaired": "과실비율 조정 예시" in section["structured_text"] or "과실" in section["structured_text"],
        "ratio_expression_normalized": base_fault.get("normalized_ratio") is not None,
        "long_spaces_normalized": True,
        "special_symbols_preserved": ["+", "-", ":", "①", "②", "舊", "·"],
        "uncertain_terms": [],
        "needs_manual_review": not is_base_fault_detected(base_fault),
    }



def has_adjustment_table_without_numeric_values(section: Dict[str, Any]) -> bool:
    """수정요소 표는 있으나 모든 값이 '-'처럼 비적용인 경우를 판별합니다."""

    text = section.get("structured_text") or section.get("clean_text") or ""
    if "과실비율 조정 예시" not in text:
        return False
    table_part = text.split("과실비율 조정 예시", 1)[1].split("※", 1)[0]
    dash_count = table_part.count("-")
    numeric_delta_exists = re.search(r"[+-]\s*\d{1,3}", table_part) is not None
    return dash_count >= 3 and not numeric_delta_exists

def build_parse_quality(
    section: Dict[str, Any],
    base_fault: Dict[str, Any],
    parties: List[Dict[str, Any]],
    adjustments: List[Dict[str, Any]],
    variants: List[Dict[str, Any]],
    law_refs: List[Dict[str, Any]],
    reference_cases: List[Dict[str, Any]],
    blocks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """파싱 품질 상태를 만듭니다."""

    # 검수 필요 사유입니다.
    reasons: List[str] = []
    quality_flags: List[str] = []

    # 기본과실 추출 실패입니다.
    if not is_base_fault_detected(base_fault):
        reasons.append("base_fault_not_detected")

    # 당사자 2명 미만이면 검토가 필요합니다.
    if len(parties) < 2:
        reasons.append("party_parse_incomplete")

    # 수정요소가 없더라도 표의 모든 값이 '-'로 비적용이면 정상으로 봅니다.
    if not adjustments and not has_adjustment_table_without_numeric_values(section):
        reasons.append("adjustment_factors_not_detected")

    if any(not row.get("target_party_key") for row in adjustments):
        reasons.append("adjustment_target_party_missing")

    if any(row.get("target_parse_status") == "unresolved" for row in adjustments):
        reasons.append("adjustment_target_unresolved")

    if any(not row.get("target_party_type") for row in adjustments):
        reasons.append("adjustment_target_party_type_missing")

    if any(not row.get("factor_name") for row in adjustments):
        reasons.append("adjustment_factor_name_missing")

    if base_fault.get("base_fault_type") == "variant_ratio" and not variants:
        reasons.append("variant_ratio_missing")

    if any(is_false_variant_row(row) for row in variants):
        reasons.append("variant_false_positive")

    if section_page_span(section) > 12:
        reasons.append("rule_boundary_suspicious")

    if section.get("boundary_quality", {}).get("page_span_limited"):
        reasons.append("rule_boundary_page_span_limited")

    if any(is_context_contaminated(row.get("context", "")) for row in [*law_refs, *reference_cases]):
        reasons.append("evidence_context_contaminated")

    if any(not row.get("movement") for row in parties):
        reasons.append("movement_missing")

    if has_control_chars(section.get("structured_text", "")):
        reasons.append("control_char_detected")

    if section.get("rule_prefix") != "보" and classify_accident(section.get("rule_prefix", ""), section.get("rule_title", ""), section.get("rule_title", "")).get("accident_group") == "횡단보도":
        reasons.append("accident_group_suspicious")

    if any(row.get("context_sanitized") for row in [*law_refs, *reference_cases]):
        quality_flags.append("evidence_context_sanitized")

    # 품질 결과를 반환합니다.
    adjustment_quality = summarize_adjustment_quality(adjustments)
    party_quality = summarize_party_quality(parties)
    return {
        "parse_status": "valid" if not reasons else "review_required",
        "page_count_checked": True,
        "missing_pages": [],
        "rule_code_detected": bool(section.get("rule_code")),
        "title_detected": bool(section.get("rule_title")),
        "party_detected": bool(parties),
        "base_fault_detected": is_base_fault_detected(base_fault),
        "adjustment_factor_detected": bool(adjustments) or has_adjustment_table_without_numeric_values(section),
        "law_ref_detected": bool(law_refs),
        "reference_case_detected": bool(reference_cases),
        "block_split_success": bool(blocks),
        "variant_detected": bool(variants),
        "adjustment_target_detected": bool(adjustments) and all(row.get("target_party_key") for row in adjustments),
        "movement_complete": all(row.get("movement") for row in parties),
        "rule_page_span": section_page_span(section),
        "boundary_quality": section.get("boundary_quality", {}),
        **adjustment_quality,
        **party_quality,
        "quality_flags": [*quality_flags, *reasons],
        "needs_manual_review_reason": reasons,
    }


def summarize_adjustment_quality(adjustments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """수정요소 target 품질 요약을 만듭니다."""

    missing = [row.get("adjustment_id") for row in adjustments if not row.get("target_party_key")]
    unresolved = [row.get("adjustment_id") for row in adjustments if row.get("target_parse_status") == "unresolved"]
    low_confidence = [
        row.get("adjustment_id")
        for row in adjustments
        if row.get("target_inference_confidence") is not None and row.get("target_inference_confidence") < 0.75
    ]
    return {
        "adjustment_target_missing_count": len(missing),
        "adjustment_target_missing_ids": missing,
        "adjustment_target_unresolved_count": len(unresolved),
        "adjustment_target_unresolved_ids": unresolved,
        "adjustment_target_low_confidence_count": len(low_confidence),
        "adjustment_target_low_confidence_ids": low_confidence,
    }


def summarize_party_quality(parties: List[Dict[str, Any]]) -> Dict[str, Any]:
    """party movement 품질 요약을 만듭니다."""

    missing = [party.get("party_id") for party in parties if not party.get("movement")]
    return {
        "movement_missing_count": len(missing),
        "movement_missing_party_ids": missing,
    }


def section_page_span(section: Dict[str, Any]) -> int:
    """section page span을 계산합니다."""

    start = int(section.get("page_start") or 0)
    end = int(section.get("page_end") or 0)
    return max(0, end - start + 1)


def has_control_chars(text: str) -> bool:
    """줄바꿈/탭 외 제어문자가 남아 있는지 확인합니다."""

    return any(ord(ch) < 32 and ch not in "\n\t" for ch in text)


def is_context_contaminated(text: str) -> bool:
    """법규/판례 context가 목차나 다른 장으로 오염됐는지 확인합니다."""

    return any(marker in text for marker in ["목차", "목 차", "제2장", "제3장", "자동차와 자동차", "자동차와 자전거"])


def is_false_variant_row(row: Dict[str, Any]) -> bool:
    """비율 없이 (가)/(나) 표식만 잡힌 variant인지 확인합니다."""

    return (
        row.get("party_a_ratio") is None
        and row.get("party_b_ratio") is None
        and row.get("single_party_ratio") is None
    )


def flatten_packages_to_tables(packages: List[Dict[str, Any]], sections: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """nested rule JSON들을 DB 적재용 JSONL row로 분해합니다."""

    # table별 row를 저장할 딕셔너리입니다.
    tables = {
        "rulebooks": [],
        "sections": sections,
        "rules": [],
        "parties": [],
        "base_faults": [],
        "variants": [],
        "adjustment_factors": [],
        "rule_blocks": [],
        "law_refs": [],
        "reference_cases": [],
        "usage_notes": [],
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
        tables["variants"].extend(package["variants"])
        tables["adjustment_factors"].extend(package["adjustment_factors"])
        tables["rule_blocks"].extend(package["blocks"])
        tables["law_refs"].extend(package["law_refs"])
        tables["reference_cases"].extend(package["reference_cases"])
        tables["usage_notes"].extend(package["usage_notes"])
        tables["chunks"].extend(package["chunks"])
        tables["parse_quality_report"].append({"rule_id": rule_id, **package["parse_quality"]})

    # table row 묶음을 반환합니다.
    return tables


def flatten_rule(package: Dict[str, Any]) -> Dict[str, Any]:
    """rule JSON에서 rules.jsonl용 핵심 필드만 납작하게 뽑습니다."""

    # 자주 쓰는 하위 구조를 꺼냅니다.
    metadata = package["metadata"]
    identity = package["rule_identity"]
    hierarchy = package["hierarchy"]
    base = package["base_fault"]

    # 납작한 rule row를 반환합니다.
    return {
        "rule_id": metadata["rule_id"],
        "source_type": metadata["source_type"],
        "source_subtype": metadata["source_subtype"],
        "source_reliability": metadata["source_reliability"],
        "source_file": metadata["source_file"],
        "rule_code": identity["rule_code"],
        "rule_prefix": identity["rule_prefix"],
        "rule_number": identity["rule_number"],
        "rule_title": identity["rule_title"],
        "rule_type": identity["rule_type"],
        "section_path": hierarchy["section_path"],
        "accident_group": identity["accident_group"],
        "accident_subgroup": identity["accident_subgroup"],
        "classification_scope_source": package["accident_classification"].get("classification_scope_source"),
        "base_fault_type": base.get("base_fault_type"),
        "normalized_ratio": base.get("normalized_ratio"),
        "scenario_required": base.get("scenario_required"),
        "variants_required": base.get("variants_required"),
        "calculation_source": base.get("calculation_source"),
        "auto_calculation_eligible": base.get("auto_calculation_eligible"),
        "page_start": metadata["page_start"],
        "page_end": metadata["page_end"],
        "parse_status": package["parse_quality"]["parse_status"],
    }

