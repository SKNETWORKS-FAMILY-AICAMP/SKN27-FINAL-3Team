# -*- coding: utf-8 -*-
"""rule JSON 패키지와 DB 적재용 table row를 생성합니다."""

from pathlib import Path
from typing import Any, Dict, List, Optional

from .chunker import build_chunks
from .classifiers import build_priority_context, build_road_context, classify_accident
from .config import (
    DOCUMENT_TITLE,
    PUBLISHED_DATE,
    PUBLISHED_YEAR,
    PREPROCESSING_VERSION,
    RULE_ID_PREFIX,
    RULE_TYPE,
    SECTION_TITLE,
    SOURCE_RELIABILITY,
    SOURCE_SUBTYPE,
)
from .extractors import (
    extract_adjustment_factors,
    extract_base_fault,
    extract_law_refs,
    extract_parties,
    extract_reference_cases,
    extract_review_cases,
    split_rule_blocks,
)
from .file_utils import safe_filename


def build_rule_package(
    section: Dict[str, Any],
    summary_row: Optional[Dict[str, Any]],
    pdf_path: Path,
    file_hash: str,
    page_coverage: Dict[str, Any],
) -> Dict[str, Any]:
    """No별 section을 최종 rule JSON 구조로 변환합니다."""

    # 구조화된 rule 텍스트입니다.
    text = section["structured_text"]

    # rule 번호입니다.
    rule_no = int(section["rule_no"])

    # rule 코드입니다.
    rule_code = f"No.{rule_no}"

    # 내부 rule ID입니다.
    rule_id = f"{RULE_ID_PREFIX}_{rule_no:02d}"

    # 당사자 정보를 추출합니다.
    parties = extract_parties(text, rule_id)

    # 기본과실을 추출합니다.
    base_fault = extract_base_fault(text, summary_row)

    # 수정요소를 추출합니다.
    adjustment_factors = extract_adjustment_factors(text, rule_id)

    # 의미 block을 분리합니다.
    blocks = split_rule_blocks(text, rule_id)

    # 관련법규를 추출합니다.
    law_refs = extract_law_refs(text, rule_id)

    # 참고판례를 추출합니다.
    reference_cases = extract_reference_cases(text, rule_id)

    # 심의사례를 추출합니다.
    review_cases = extract_review_cases(text, rule_id)

    # 사고유형을 분류합니다.
    accident_classification = classify_accident(section["rule_title"], text)

    # 도로 context를 만듭니다.
    road_context = build_road_context(section["rule_title"], text)

    # 우선권 context를 만듭니다.
    priority_context = build_priority_context(text)

    # 검색용 chunk를 만듭니다.
    chunks = build_chunks(rule_id, rule_code, section, blocks, base_fault, accident_classification, road_context, priority_context)

    # 최종 rule JSON 구조를 반환합니다.
    return {
        "metadata": {
            "rule_id": rule_id,
            "source_type": "fault_standard",
            "source_subtype": SOURCE_SUBTYPE,
            "source_reliability": SOURCE_RELIABILITY,
            "source_file": pdf_path.name,
            "published_year": PUBLISHED_YEAR,
            "published_date": PUBLISHED_DATE,
            "preprocessing_version": PREPROCESSING_VERSION,
            "file_hash": file_hash,
            "page_start": section["page_start"],
            "page_end": section["page_end"],
            "page_count_checked": page_coverage["status"] == "success",
            "missing_pages": page_coverage["missing_pages"],
        },
        "hierarchy": {
            "document_title": DOCUMENT_TITLE,
            "section_title": SECTION_TITLE,
            "summary_table_exists": summary_row is not None,
            "rule_no": rule_no,
            "rule_ref": rule_code,
            "section_path": [
                DOCUMENT_TITLE,
                f"{rule_code} {section['rule_title']}",
            ],
        },
        "summary_table_row": build_summary_match(summary_row, base_fault),
        "rule_identity": {
            "rule_no": rule_no,
            "rule_code": rule_code,
            "rule_title": section["rule_title"],
            "rule_title_clean": safe_filename(section["rule_title"]),
            "rule_type": RULE_TYPE,
            "is_nontypical_standard": True,
            "related_official_standard_code": None,
            "has_review_case_before_rule": bool(review_cases),
            "has_reference_case": bool(reference_cases),
        },
        "accident_classification": accident_classification,
        "parties": parties,
        "road_context": road_context,
        "priority_context": priority_context,
        "base_fault": base_fault,
        "adjustment_factors": adjustment_factors,
        "blocks": blocks,
        "law_refs": law_refs,
        "reference_cases": reference_cases,
        "review_cases": review_cases,
        "texts": {
            "raw_text": section["raw_text"],
            "clean_text": section["clean_text"],
            "structured_text": section["structured_text"],
        },
        "cleaning_quality": build_cleaning_quality(section, summary_row, base_fault, review_cases),
        "parse_quality": build_parse_quality(section, summary_row, base_fault, parties, adjustment_factors, law_refs, reference_cases, review_cases, blocks, road_context),
        "chunks": chunks,
    }


def build_summary_match(summary_row: Optional[Dict[str, Any]], base_fault: Dict[str, Any]) -> Dict[str, Any]:
    """요약표 row와 상세 기본과실의 매칭 결과를 만듭니다."""

    # 요약표 row가 없으면 매칭 실패로 반환합니다.
    if not summary_row:
        return {"matched_detail_rule": False, "ratio_matches_detail": False}

    # 상세 본문 A/B 비율입니다.
    detail_a = base_fault.get("party_a_ratio")
    detail_b = base_fault.get("party_b_ratio")

    # 요약표 row에 매칭 결과를 추가합니다.
    return {
        **summary_row,
        "matched_detail_rule": True,
        "ratio_matches_detail": summary_row.get("summary_party_a_ratio") == detail_a and summary_row.get("summary_party_b_ratio") == detail_b,
    }


def build_cleaning_quality(
    section: Dict[str, Any],
    summary_row: Optional[Dict[str, Any]],
    base_fault: Dict[str, Any],
    review_cases: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """클리닝 품질 상태를 만듭니다."""

    return {
        "page_noise_removed": True,
        "header_footer_removed": True,
        "ratio_expression_normalized": base_fault.get("normalized_ratio") is not None,
        "direction_arrow_preserved": "→" in section["structured_text"] or "→" in section["raw_text"],
        "summary_detail_ratio_matched": base_fault.get("summary_detail_ratio_match"),
        "review_case_separated": bool(review_cases),
        "special_symbols_preserved": ["+", "-", ":", "→", "[도표해설]", "[관련법규]", "[참고판례]"],
        "uncertain_terms": [],
        "needs_manual_review": not base_fault.get("normalized_ratio"),
    }


def build_parse_quality(
    section: Dict[str, Any],
    summary_row: Optional[Dict[str, Any]],
    base_fault: Dict[str, Any],
    parties: List[Dict[str, Any]],
    adjustments: List[Dict[str, Any]],
    law_refs: List[Dict[str, Any]],
    reference_cases: List[Dict[str, Any]],
    review_cases: List[Dict[str, Any]],
    blocks: List[Dict[str, Any]],
    road_context: Dict[str, Any],
) -> Dict[str, Any]:
    """파싱 품질 상태를 만듭니다."""

    # 검수 필요 사유입니다.
    reasons: List[str] = []

    # 요약표 매칭 실패입니다.
    if not summary_row:
        reasons.append("summary_table_row_missing")

    # 기본과실 추출 실패입니다.
    if not base_fault.get("normalized_ratio"):
        reasons.append("base_fault_not_detected")

    # 당사자 2명 미만이면 실패입니다.
    if len(parties) < 2:
        reasons.append("party_parse_incomplete")

    # 수정요소가 없으면 검토가 필요합니다.
    if not adjustments:
        reasons.append("adjustment_factors_not_detected")

    if summary_row:
        summary_title = summary_row.get("summary_title") or ""
        detail_title = section.get("rule_title") or ""
        if summary_title and detail_title and summary_title != detail_title:
            reasons.append("summary_title_mismatch")

    suspicious_road_area = detect_suspicious_road_context(section.get("rule_title", ""), road_context)
    if suspicious_road_area:
        reasons.append("road_context_suspicious")

    if any(not party.get("movement") for party in parties):
        reasons.append("movement_missing")

    if any(
        case.get("claim_vehicle_fault_ratio") is None or case.get("respondent_vehicle_fault_ratio") is None
        for case in review_cases
    ):
        reasons.append("review_case_ratio_missing")

    # 품질 결과를 반환합니다.
    return {
        "parse_status": "valid" if not reasons else "review_required",
        "quality_flags": reasons,
        "page_count_checked": True,
        "missing_pages": [],
        "summary_table_detected": summary_row is not None,
        "summary_no_detected": summary_row is not None,
        "detail_rule_detected": True,
        "summary_detail_matched": base_fault.get("summary_detail_ratio_match"),
        "base_fault_detected": bool(base_fault.get("normalized_ratio")),
        "party_detected": len(parties) >= 2,
        "adjustment_factor_detected": bool(adjustments),
        "law_ref_detected": bool(law_refs),
        "reference_case_detected": bool(reference_cases),
        "review_case_detected": bool(review_cases),
        "block_split_success": bool(blocks),
        "road_context_suspicious": bool(suspicious_road_area),
        "movement_missing": any(not party.get("movement") for party in parties),
        "review_case_ratio_missing": any(
            case.get("claim_vehicle_fault_ratio") is None or case.get("respondent_vehicle_fault_ratio") is None
            for case in review_cases
        ),
        "needs_manual_review_reason": reasons,
    }


def detect_suspicious_road_context(title: str, road_context: Dict[str, Any]) -> Optional[str]:
    """제목과 road_area가 명백히 어긋나는 경우를 표시합니다."""

    road_area = road_context.get("road_area")

    if ("점멸" in title or "교차로" in title) and road_area != "교차로":
        return "expected_intersection"

    if ("진로변경" in title or "동일차로" in title or "끼어들기" in title or "급진입" in title) and road_area not in {"동일차로", "추월"}:
        return "expected_same_lane"

    if ("주차장" in title or "주차" in title or "출차" in title) and road_area != "주차장":
        return "expected_parking_lot"

    return None


def flatten_packages_to_tables(packages: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """nested rule JSON들을 DB 적재용 JSONL row로 분해합니다."""

    # table별 row를 저장할 딕셔너리입니다.
    tables = {
        "rulebooks": [],
        "summary_table_rows": [],
        "rules": [],
        "parties": [],
        "base_faults": [],
        "road_contexts": [],
        "priority_contexts": [],
        "adjustment_factors": [],
        "rule_blocks": [],
        "law_refs": [],
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
        tables["summary_table_rows"].append({"rule_id": rule_id, **package["summary_table_row"]})
        tables["rules"].append(flatten_rule(package))
        tables["parties"].extend(package["parties"])
        tables["base_faults"].append({"rule_id": rule_id, **package["base_fault"]})
        tables["road_contexts"].append({"rule_id": rule_id, **package["road_context"]})
        tables["priority_contexts"].append({"rule_id": rule_id, **package["priority_context"]})
        tables["adjustment_factors"].extend(package["adjustment_factors"])
        tables["rule_blocks"].extend(package["blocks"])
        tables["law_refs"].extend(package["law_refs"])
        tables["reference_cases"].extend(package["reference_cases"])
        tables["review_cases"].extend(package["review_cases"])
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
    accident = package["accident_classification"]

    # 납작한 rule row를 반환합니다.
    return {
        "rule_id": metadata["rule_id"],
        "source_type": metadata["source_type"],
        "source_subtype": metadata["source_subtype"],
        "source_reliability": metadata["source_reliability"],
        "source_file": metadata["source_file"],
        "rule_no": identity["rule_no"],
        "rule_code": identity["rule_code"],
        "rule_title": identity["rule_title"],
        "rule_type": identity["rule_type"],
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
