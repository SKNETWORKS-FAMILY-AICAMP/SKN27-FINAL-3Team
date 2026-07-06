# -*- coding: utf-8 -*-
"""rule JSON 패키지와 DB 적재용 table row를 생성합니다."""

import re
from pathlib import Path
from typing import Any, Dict, List

from .chunker import build_chunks
from .classifiers import build_applicability, build_road_context, build_signal_context, classify_accident, get_category_info
from .config import (
    DOCUMENT_TITLE,
    PUBLISHED_YEAR,
    PREPROCESSING_VERSION,
    RULE_ID_PREFIX,
    RULE_TYPE,
    SECTION_NO,
    SECTION_TITLE,
    CHART_NO_MAX,
    CHART_NO_MIN,
    SHARED_GROUP_ID_PREFIX,
    SOURCE_RELIABILITY,
    SOURCE_SUBTYPE,
)
from .extractors import (
    extract_base_context_text,
    build_pm_context,
    build_vehicle_context,
    extract_adjustment_factors,
    extract_base_fault,
    extract_law_refs,
    extract_parties,
    extract_reference_cases,
    extract_review_cases,
    extract_rule_scenarios,
    split_rule_blocks,
)
from .file_utils import safe_filename


def build_rule_package(
    section: Dict[str, Any],
    pdf_path: Path,
    file_hash: str,
    page_coverage: Dict[str, Any],
) -> Dict[str, Any]:
    """도표 section을 최종 rule JSON 구조로 변환합니다."""

    # 구조화된 rule 텍스트입니다.
    text = section["structured_text"]

    # 도표 번호입니다.
    chart_no = int(section["chart_no"])

    # 도표 코드입니다.
    chart_code = section["chart_code"]

    # 내부 rule ID입니다.
    rule_id = f"{RULE_ID_PREFIX}_{chart_code}"

    # 카테고리 정보입니다.
    category = get_category_info(chart_no)

    # 당사자 정보를 추출합니다.
    parties = extract_parties(text, rule_id)

    # 기본 사고상황 context용 텍스트입니다.
    base_context_text = extract_base_context_text(text)

    # 기본과실을 추출합니다.
    base_fault = extract_base_fault(text)

    # 수정요소를 추출합니다.
    adjustment_factors = extract_adjustment_factors(text, rule_id)

    # 다중 기본과실 시나리오를 추출합니다.
    rule_scenarios = extract_rule_scenarios(text, rule_id)
    apply_scenario_marker(base_fault, rule_scenarios)

    # 의미 block을 분리합니다.
    blocks = split_rule_blocks(text, rule_id)

    # 관련법규를 추출합니다.
    law_refs = extract_law_refs(text, rule_id)

    # 참고판례를 추출합니다.
    reference_cases = extract_reference_cases(text, rule_id)

    # 심의사례를 추출합니다.
    review_cases = extract_review_cases(text, rule_id)

    # PM context를 만듭니다.
    pm_context = build_pm_context(parties, text)

    # 자동차 context를 만듭니다.
    vehicle_context = build_vehicle_context(parties, text)

    # 사고유형을 분류합니다.
    accident_classification = classify_accident(chart_no, section["rule_title"], base_context_text)

    # 도로 context를 만듭니다.
    road_context = build_road_context(section["rule_title"], base_context_text)

    # 수정요소 조건 context를 따로 만듭니다.
    adjustment_condition_context = build_adjustment_condition_context(rule_id, adjustment_factors)

    # 신호 context를 만듭니다.
    signal_context = build_signal_context(section["rule_title"], base_context_text)

    # 검색용 chunk를 만듭니다.
    chunks = build_chunks(rule_id, chart_code, section, blocks, base_fault, accident_classification, pm_context)

    # 최종 rule JSON 구조를 반환합니다.
    return {
        "metadata": {
            "rule_id": rule_id,
            "source_type": "fault_standard",
            "source_subtype": SOURCE_SUBTYPE,
            "source_reliability": SOURCE_RELIABILITY,
            "source_file": pdf_path.name,
            "published_year": PUBLISHED_YEAR,
            "preprocessing_version": PREPROCESSING_VERSION,
            "file_hash": file_hash,
            "page_start": section["page_start"],
            "page_end": section["page_end"],
            "page_count_checked": page_coverage["status"] == "success",
            "missing_pages": page_coverage["missing_pages"],
        },
        "hierarchy": {
            "document_title": DOCUMENT_TITLE,
            "section_no": SECTION_NO,
            "section_title": SECTION_TITLE,
            "category_no": category["category_no"],
            "category_title": category["category_title"],
            "chart_no": chart_no,
            "chart_ref": chart_code,
            "section_path": [
                DOCUMENT_TITLE,
                SECTION_TITLE,
                category["category_title"],
                f"{chart_code} {section['rule_title']}",
            ],
        },
        "rule_identity": {
            "chart_no": chart_no,
            "chart_code": chart_code,
            "rule_title": section["rule_title"],
            "rule_title_clean": safe_filename(section["rule_title"]),
            "rule_type": RULE_TYPE,
            "chart_group": category["chart_group"],
            "has_related_charts": True,
            "related_chart_refs": infer_related_chart_refs(chart_no),
            "has_scenarios": bool(rule_scenarios),
            "scenario_count": len(rule_scenarios),
        },
        "applicability": build_applicability(),
        "accident_classification": accident_classification,
        "parties": parties,
        "pm_context": pm_context,
        "vehicle_context": vehicle_context,
        "road_context": road_context,
        "signal_context": signal_context,
        "base_fault": base_fault,
        "rule_scenarios": rule_scenarios,
        "adjustment_factors": adjustment_factors,
        "adjustment_condition_context": adjustment_condition_context,
        "blocks": blocks,
        "law_refs": law_refs,
        "reference_cases": reference_cases,
        "review_cases": review_cases,
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
            review_cases,
            blocks,
            road_context,
            adjustment_condition_context,
            rule_scenarios,
        ),
        "chunks": chunks,
    }


def build_adjustment_condition_context(rule_id: str, adjustments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """수정요소에 들어 있는 조건을 기본 road_context와 분리해 저장합니다."""

    contexts = [row.get("condition_context") or {} for row in adjustments]

    return {
        "rule_id": rule_id,
        "near_bicycle_road": any(ctx.get("near_bicycle_road") for ctx in contexts),
        "pm_left_side_travel": any(ctx.get("pm_left_side_travel") for ctx in contexts),
        "pm_sidewalk_travel": any(ctx.get("pm_sidewalk_travel") for ctx in contexts),
        "night_or_visibility_issue": any(ctx.get("night_or_visibility_issue") for ctx in contexts),
        "crossing_prohibited": any(ctx.get("crossing_prohibited") for ctx in contexts),
        "residential_commercial_school_area": any(ctx.get("residential_commercial_school_area") for ctx in contexts),
        "car_brake_light_failure": any(ctx.get("car_brake_light_failure") for ctx in contexts),
        "car_door_opening": any(ctx.get("car_door_opening") for ctx in contexts),
        "condition_factor_count": sum(1 for ctx in contexts if any(ctx.values())),
    }


def apply_scenario_marker(base_fault: Dict[str, Any], rule_scenarios: List[Dict[str, Any]]) -> None:
    """다중 기본과실 도표는 RuleScenario를 우선 사용하도록 표시합니다."""

    if not rule_scenarios:
        base_fault["scenario_required"] = False
        return

    base_fault["base_fault_type"] = "scenario_required"
    base_fault["scenario_required"] = True
    base_fault["scenario_count"] = len(rule_scenarios)
    base_fault["scenario_source"] = "rule_scenarios"


def infer_related_chart_refs(chart_no: int) -> List[str]:
    """인접 도표 관계를 반환합니다."""

    # 앞뒤 도표를 후보로 둡니다.
    refs = []

    # 이전 도표입니다.
    if chart_no > CHART_NO_MIN:
        refs.append(f"도표{chart_no - 1:02d}")

    # 다음 도표입니다.
    if chart_no < CHART_NO_MAX:
        refs.append(f"도표{chart_no + 1:02d}")

    # 관련 도표 목록을 반환합니다.
    return refs


def build_cleaning_quality(section: Dict[str, Any], base_fault: Dict[str, Any], parties: List[Dict[str, Any]]) -> Dict[str, Any]:
    """클리닝 품질 상태를 만듭니다."""

    return {
        "page_noise_removed": True,
        "header_footer_removed": True,
        "vertical_label_repaired": True,
        "ratio_expression_normalized": base_fault.get("normalized_ratio") is not None,
        "pm_terms_normalized": "개인형이동장치" in section["structured_text"] or "PM" in section["structured_text"],
        "special_symbols_preserved": ["+", "-", ":", "A", "B", "PM"],
        "uncertain_terms": [],
        "needs_manual_review": not base_fault.get("normalized_ratio") or len(parties) < 2,
    }


def build_parse_quality(
    section: Dict[str, Any],
    base_fault: Dict[str, Any],
    parties: List[Dict[str, Any]],
    adjustments: List[Dict[str, Any]],
    law_refs: List[Dict[str, Any]],
    reference_cases: List[Dict[str, Any]],
    review_cases: List[Dict[str, Any]],
    blocks: List[Dict[str, Any]],
    road_context: Dict[str, Any],
    adjustment_condition_context: Dict[str, Any],
    rule_scenarios: List[Dict[str, Any]],
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

    # 수정요소 target 누락 여부입니다.
    if any(not row.get("target_party_key") for row in adjustments):
        reasons.append("adjustment_target_party_missing")

    if any(not row.get("target_party_type") for row in adjustments):
        reasons.append("adjustment_target_party_type_missing")

    # movement 누락 여부입니다.
    if any(not row.get("movement") for row in parties):
        reasons.append("movement_missing")

    # 수정요소 조건이 실제로 감지되는지 기록합니다.
    if adjustment_condition_context.get("condition_factor_count", 0) > 0:
        quality_flags.append("adjustment_condition_context_detected")

    # 기본 road_context에 수정요소성 조건이 섞였는지 의심되는 경우입니다.
    if road_context.get("has_bicycle_road") and adjustment_condition_context.get("near_bicycle_road"):
        reasons.append("road_context_bicycle_road_check")

    if road_context.get("has_sidewalk") and adjustment_condition_context.get("pm_sidewalk_travel"):
        reasons.append("road_context_sidewalk_check")

    # 다중 기본과실 label이 있는데 scenario가 추출되지 않은 경우입니다.
    if has_scenario_labels(section.get("structured_text", "")) and not rule_scenarios:
        reasons.append("rule_scenario_missing")

    # 제목에 다른 chart 번호가 섞인 경우입니다.
    title = section.get("rule_title", "")
    chart_no = int(section.get("chart_no", 0))
    if has_other_chart_number_in_title(title, chart_no):
        reasons.append("chart_title_suspicious")

    quality_flags = [*quality_flags, *reasons]

    # 품질 결과를 반환합니다.
    return {
        "parse_status": "valid" if not reasons else "review_required",
        "page_count_checked": True,
        "missing_pages": [],
        "chart_code_detected": bool(section.get("chart_code")),
        "title_detected": bool(section.get("rule_title")),
        "pm_party_detected": any(p.get("party_type") == "pm" for p in parties),
        "car_party_detected": any(p.get("party_type") == "car" for p in parties),
        "base_fault_detected": bool(base_fault.get("normalized_ratio")),
        "adjustment_factor_detected": bool(adjustments),
        "law_ref_detected": bool(law_refs),
        "reference_case_detected": bool(reference_cases),
        "review_case_detected": bool(review_cases),
        "block_split_success": bool(blocks),
        "rule_scenario_detected": bool(rule_scenarios),
        "adjustment_condition_context_detected": adjustment_condition_context.get("condition_factor_count", 0) > 0,
        "quality_flags": quality_flags,
        "needs_manual_review_reason": reasons,
    }


def has_scenario_labels(text: str) -> bool:
    """본문에 다중 시나리오 label이 있는지 판단합니다."""

    return len({match.group(1) for match in re.finditer(r"\(([가-힣])\)", text)}) >= 2


def has_other_chart_number_in_title(title: str, chart_no: int) -> bool:
    """제목에 현재 도표 번호가 아닌 숫자형 도표 표시가 섞였는지 확인합니다."""

    for match in re.finditer(r"(?<!\d)(\d{1,2})\.", title):
        if int(match.group(1)) != chart_no:
            return True

    return False


def apply_shared_rule_groups(packages: List[Dict[str, Any]]) -> None:
    """공통 해설/법규를 공유하는 도표 묶음을 SharedRuleGroup으로 연결합니다."""

    ordered_packages = sorted(packages, key=lambda package: int(package["hierarchy"]["chart_no"]))
    used_rule_ids = set()

    for left, right in zip(ordered_packages, ordered_packages[1:]):
        if left["metadata"]["rule_id"] in used_rule_ids or right["metadata"]["rule_id"] in used_rule_ids:
            continue

        evaluation = evaluate_shared_rule_group(left, right)
        if not evaluation["should_share"]:
            continue

        members = [left, right]
        source = max(members, key=lambda package: len(package.get("blocks", [])) + len(package.get("law_refs", [])))
        left_no = int(left["hierarchy"]["chart_no"])
        right_no = int(right["hierarchy"]["chart_no"])
        group_title = infer_shared_group_title(left, right)
        group_id = f"{SHARED_GROUP_ID_PREFIX}_{left_no:02d}_{right_no:02d}"
        group = {
            "shared_group_id": group_id,
            "group_title": group_title,
            "member_chart_refs": [f"도표{left_no:02d}", f"도표{right_no:02d}"],
            "source_rule_id": source["metadata"]["rule_id"],
            "shared_block_count": len(source.get("blocks", [])),
            "shared_law_ref_count": len(source.get("law_refs", [])),
            "shared_chunk_count": len(source.get("chunks", [])),
            "sharing_strategy": "auto_detected_shared_rule_group",
            "sharing_reason": evaluation,
        }

        for order, package in enumerate(members, start=1):
            package["shared_rule_group"] = group
            package["shared_rule_group_member"] = {
                "shared_group_id": group_id,
                "rule_id": package["metadata"]["rule_id"],
                "chart_no": package["hierarchy"]["chart_no"],
                "chart_code": package["rule_identity"]["chart_code"],
                "member_order": order,
                "uses_shared_explanation": True,
                "uses_shared_law_refs": True,
                "uses_shared_chunks": True,
            }
            package["parse_quality"].setdefault("quality_flags", []).append("shared_rule_group_attached")

        group["shared_blocks"] = [build_shared_block_row(group_id, row) for row in source.get("blocks", [])]
        group["shared_law_refs"] = [build_shared_law_ref_row(group_id, row) for row in source.get("law_refs", [])]
        group["shared_chunks"] = [build_shared_chunk_row(group_id, row) for row in source.get("chunks", [])]
        used_rule_ids.update(package["metadata"]["rule_id"] for package in members)


def should_share_rule_group(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    """인접 도표가 공통 해설/법규를 공유하는지 판단합니다."""

    return evaluate_shared_rule_group(left, right)["should_share"]


def evaluate_shared_rule_group(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """공유 그룹 생성 여부와 판단 근거를 함께 반환합니다."""

    if left["rule_identity"].get("chart_group") != right["rule_identity"].get("chart_group"):
        return {"should_share": False, "reason": "different_chart_group"}

    left_score = evidence_score(left)
    right_score = evidence_score(right)
    if min(left_score, right_score) > 2:
        return {"should_share": False, "reason": "both_rules_have_enough_evidence", "left_evidence_score": left_score, "right_evidence_score": right_score}

    if max(left_score, right_score) < 5:
        return {"should_share": False, "reason": "shared_evidence_not_enough", "left_evidence_score": left_score, "right_evidence_score": right_score}

    title_score = title_similarity(left["rule_identity"].get("rule_title", ""), right["rule_identity"].get("rule_title", ""))
    same_accident_group = left["accident_classification"].get("accident_group") == right["accident_classification"].get("accident_group")

    should_share = same_accident_group and title_score >= 0.35
    return {
        "should_share": should_share,
        "same_chart_group": True,
        "left_evidence_score": left_score,
        "right_evidence_score": right_score,
        "title_similarity": title_score,
        "same_accident_group": same_accident_group,
        "reason": "adjacent_rule_uses_shared_evidence" if should_share else "similarity_or_group_check_failed",
    }


def evidence_score(package: Dict[str, Any]) -> int:
    """해설/법규/chunk가 얼마나 붙어 있는지 점수화합니다."""

    return len(package.get("blocks", [])) + len(package.get("law_refs", [])) + len(package.get("chunks", []))


def infer_shared_group_title(left: Dict[str, Any], right: Dict[str, Any]) -> str:
    """공유 그룹 제목을 카테고리와 공통 제목 토큰으로 만듭니다."""

    category_title = left["hierarchy"].get("category_title") or left["accident_classification"].get("accident_group")
    common_words = sorted(title_word_set(left["rule_identity"].get("rule_title", "")) & title_word_set(right["rule_identity"].get("rule_title", "")))

    if common_words:
        return f"{category_title} - {' '.join(common_words)}"

    return str(category_title)


def title_similarity(left: str, right: str) -> float:
    """공유 그룹 판단용 제목 유사도를 계산합니다."""

    left_tokens = title_word_set(left)
    right_tokens = title_word_set(right)

    if not left_tokens or not right_tokens:
        return 0.0

    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def title_word_set(title: str) -> set[str]:
    """PM/자동차처럼 주체만 다른 제목을 비교하기 위해 공통 토큰을 뽑습니다."""

    title = re.sub(r"[()·,，/]", " ", title)
    words = {word for word in title.split() if len(word) >= 2}
    return {word for word in words if word not in {"PM", "자동차", "사고", "차량"}}


def build_shared_block_row(group_id: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """SharedRuleGroup에 연결할 block row를 만듭니다."""

    return {
        "shared_group_id": group_id,
        "source_rule_id": row.get("rule_id"),
        "source_block_id": row.get("block_id"),
        "block_type": row.get("block_type"),
        "block_order": row.get("block_order"),
        "block_title": row.get("block_title"),
        "raw_text": row.get("raw_text"),
        "clean_text": row.get("clean_text"),
        "structured_text": row.get("structured_text"),
    }


def build_shared_law_ref_row(group_id: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """SharedRuleGroup에 연결할 law_ref row를 만듭니다."""

    return {
        "shared_group_id": group_id,
        "source_rule_id": row.get("rule_id"),
        "source_law_ref_id": row.get("law_ref_id"),
        "law_name": row.get("law_name"),
        "article": row.get("article"),
        "paragraph": row.get("paragraph"),
        "item": row.get("item"),
        "raw_text": row.get("raw_text"),
        "context": row.get("context"),
        "law_role": row.get("law_role"),
    }


def build_shared_chunk_row(group_id: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """SharedRuleGroup에 연결할 chunk row를 만듭니다."""

    metadata = {
        "chart_no": row.get("chart_no"),
        "chart_code": row.get("chart_code"),
        "rule_title": row.get("rule_title"),
        "chunk_type": row.get("chunk_type"),
        "accident_group": row.get("accident_group"),
        "accident_subgroup": row.get("accident_subgroup"),
        "party_a_ratio": row.get("party_a_ratio"),
        "party_b_ratio": row.get("party_b_ratio"),
        "pm_party_key": row.get("pm_party_key"),
        "pm_action": row.get("pm_action"),
        "accident_tags": row.get("accident_tags"),
        "source_reliability": row.get("source_reliability"),
    }

    return {
        "shared_group_id": group_id,
        "source_rule_id": row.get("rule_id"),
        "source_chunk_id": row.get("chunk_id"),
        "chunk_type": row.get("chunk_type"),
        "chunk_order": row.get("chunk_order"),
        "text": row.get("chunk_text"),
        "metadata": metadata,
    }


def flatten_packages_to_tables(packages: List[Dict[str, Any]], sections: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """nested rule JSON들을 DB 적재용 JSONL row로 분해합니다."""

    # table별 row를 저장할 딕셔너리입니다.
    tables = {
        "rulebooks": [],
        "sections": sections,
        "rules": [],
        "parties": [],
        "base_faults": [],
        "rule_scenarios": [],
        "pm_contexts": [],
        "vehicle_contexts": [],
        "road_contexts": [],
        "signal_contexts": [],
        "adjustment_condition_contexts": [],
        "adjustment_factors": [],
        "rule_blocks": [],
        "law_refs": [],
        "shared_rule_groups": [],
        "shared_rule_group_members": [],
        "shared_rule_group_blocks": [],
        "shared_rule_group_law_refs": [],
        "shared_rule_group_chunks": [],
        "reference_cases": [],
        "review_cases": [],
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
        tables["rule_scenarios"].extend(package["rule_scenarios"])
        tables["pm_contexts"].append({"rule_id": rule_id, **package["pm_context"]})
        tables["vehicle_contexts"].append({"rule_id": rule_id, **package["vehicle_context"]})
        tables["road_contexts"].append({"rule_id": rule_id, **package["road_context"]})
        tables["signal_contexts"].append({"rule_id": rule_id, **package["signal_context"]})
        tables["adjustment_condition_contexts"].append(package["adjustment_condition_context"])
        tables["adjustment_factors"].extend(package["adjustment_factors"])
        tables["rule_blocks"].extend(package["blocks"])
        tables["law_refs"].extend(package["law_refs"])
        append_shared_group_rows(tables, package)
        tables["reference_cases"].extend(package["reference_cases"])
        tables["review_cases"].extend(package["review_cases"])
        tables["chunks"].extend(package["chunks"])
        tables["parse_quality_report"].append({"rule_id": rule_id, **package["parse_quality"]})

    # table row 묶음을 반환합니다.
    return tables


def append_shared_group_rows(tables: Dict[str, List[Dict[str, Any]]], package: Dict[str, Any]) -> None:
    """SharedRuleGroup 관련 table row를 중복 없이 추가합니다."""

    group = package.get("shared_rule_group")
    member = package.get("shared_rule_group_member")

    if not group or not member:
        return

    group_id = group["shared_group_id"]

    if not any(row.get("shared_group_id") == group_id for row in tables["shared_rule_groups"]):
        tables["shared_rule_groups"].append(
            {
                "shared_group_id": group_id,
                "group_title": group["group_title"],
                "member_chart_refs": group["member_chart_refs"],
                "source_rule_id": group["source_rule_id"],
                "shared_block_count": group["shared_block_count"],
                "shared_law_ref_count": group["shared_law_ref_count"],
                "shared_chunk_count": group["shared_chunk_count"],
                "sharing_strategy": group["sharing_strategy"],
            }
        )
        tables["shared_rule_group_blocks"].extend(group.get("shared_blocks", []))
        tables["shared_rule_group_law_refs"].extend(group.get("shared_law_refs", []))
        tables["shared_rule_group_chunks"].extend(group.get("shared_chunks", []))

    tables["shared_rule_group_members"].append(member)


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
        "chart_no": identity["chart_no"],
        "chart_code": identity["chart_code"],
        "rule_title": identity["rule_title"],
        "rule_type": identity["rule_type"],
        "chart_group": identity["chart_group"],
        "has_scenarios": identity.get("has_scenarios", False),
        "scenario_count": identity.get("scenario_count", 0),
        "base_fault_type": base.get("base_fault_type"),
        "section_path": hierarchy["section_path"],
        "accident_group": accident["accident_group"],
        "accident_subgroup": accident["accident_subgroup"],
        "party_a_ratio": base.get("party_a_ratio"),
        "party_b_ratio": base.get("party_b_ratio"),
        "normalized_ratio": base.get("normalized_ratio"),
        "page_start": metadata["page_start"],
        "page_end": metadata["page_end"],
        "parse_status": package["parse_quality"]["parse_status"],
    }
