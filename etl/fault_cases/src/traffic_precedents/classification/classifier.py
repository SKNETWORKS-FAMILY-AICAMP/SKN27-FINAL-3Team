"""D 의미 블록을 E~I 증거 게이트로 연결하는 보수적 판례 분류기."""

from __future__ import annotations

import re
from typing import Any


CLASSIFIER_VERSION = "evidence_gates_v1.1.0"
FORBIDDEN_RETRIEVAL_RATIO_CONTEXTS = {
    "INTEREST_RATE",
    "DISABILITY_RATE",
    "PREEXISTING_CONDITION_RATE",
    "DAMAGE_CALCULATION_RATE",
    "MEDICAL_STATISTIC",
}
FORBIDDEN_RETRIEVAL_TEXT_CUES = (
    "소송비용",
    "지연손해금",
    "가집행",
)

NONTRAFFIC_TITLE_PATTERNS = {
    "MEDICAL": (
        r"손해배상\(의\)",
        r"의료법",
        r"허위진단서",
        r"의사.*업무상과실",
        r"환자.*사망",
    ),
    "INDUSTRIAL": (
        r"산업안전보건법",
        r"산업재해",
        r"업무상 재해",
    ),
    "LABOR": (
        r"부당해고",
        r"근로자지위",
        r"노동조합",
        r"근로기준법",
    ),
    "MARITIME": (
        r"해상운송",
        r"선박.*충돌",
        r"해상사고",
    ),
}
TRAFFIC_TITLE_CUES = (
    "교통사고",
    "도로교통",
    "자동차",
    "손해배상(자)",
    "차량",
)
LEGAL_SUPPORT_CUES = (
    "구상금",
    "구상권",
    "보험자대위",
    "운행자책임",
    "자동차보험진료수가",
)
MEDICAL_CUES = ("환자", "수술", "진료", "의사", "의료과실", "병원")
INDUSTRIAL_CUES = ("산업재해", "산업안전", "작업장", "근로복지공단")
LABOR_CUES = ("부당해고", "노동조합", "근로자지위", "임금")
MARITIME_CUES = ("해상운송", "선박", "항해", "선하증권")


def _case_value(case: dict[str, Any], key: str) -> str:
    return str(case.get(key) or "")


def _main_issue(
    case: dict[str, Any],
    blocks: list[dict[str, Any]],
    valid_accident_count: int,
) -> tuple[str, list[str]]:
    title = _case_value(case, "사건명")
    traffic_title = any(cue in title for cue in TRAFFIC_TITLE_CUES)
    for issue, patterns in NONTRAFFIC_TITLE_PATTERNS.items():
        if any(re.search(pattern, title) for pattern in patterns) and not traffic_title:
            return issue, [f"H_TITLE_{issue}"]

    category_cues = {
        "MEDICAL": MEDICAL_CUES,
        "INDUSTRIAL": INDUSTRIAL_CUES,
        "LABOR": LABOR_CUES,
        "MARITIME": MARITIME_CUES,
    }
    scores = {
        issue: sum(
            1
            for block in blocks
            if sum(cue in block.get("text", "") for cue in cues) >= 2
        )
        for issue, cues in category_cues.items()
    }
    issue, score = max(scores.items(), key=lambda item: item[1])
    if score >= 2 and score > valid_accident_count * 2 and not traffic_title:
        return issue, [f"H_BLOCK_DOMINANCE_{issue}"]
    if valid_accident_count:
        return "ROAD_TRAFFIC_FAULT", ["H_TRAFFIC_EVIDENCE_PRESENT"]
    if any(cue in title for cue in LEGAL_SUPPORT_CUES):
        return "TRAFFIC_LEGAL_SUPPORT", ["H_LEGAL_SUPPORT_TITLE"]
    return "OTHER", ["H_MAIN_ISSUE_UNRESOLVED"]


def _relation(
    facts: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[str]]:
    best: dict[str, Any] | None = None
    for fact in facts:
        fact_subjects = set(
            (fact.get("linked_entities") or {}).get("subjects") or []
        )
        for decision in decisions:
            if fact.get("incident_id") != decision.get("incident_id"):
                continue
            decision_subjects = set(
                (decision.get("linked_entities") or {}).get("subjects") or []
            )
            shared = sorted(fact_subjects & decision_subjects)
            distance = max(
                0,
                max(
                    int(fact.get("start_offset", 0)),
                    int(decision.get("start_offset", 0)),
                )
                - min(
                    int(fact.get("end_offset", 0)),
                    int(decision.get("end_offset", 0)),
                ),
            )
            score = 0.50
            if shared:
                score += 0.30
            if distance <= 3000:
                score += 0.20
            elif distance <= 8000:
                score += 0.10
            candidate = {
                "fact_block_id": fact["block_id"],
                "decision_block_id": decision["block_id"],
                "incident_id": fact.get("incident_id"),
                "shared_subjects": shared,
                "offset_distance": distance,
                "relation_confidence": round(score, 4),
            }
            if best is None or candidate["relation_confidence"] > best[
                "relation_confidence"
            ]:
                best = candidate
    if best and best["relation_confidence"] >= 0.70:
        return best, ["G_FACT_DECISION_LINKED"]
    return None, ["G_NO_RELIABLE_FACT_DECISION_LINK"]


def _search_safety(block: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    contexts = {
        str(mention.get("context") or "")
        for mention in block.get("ratio_mentions") or []
    }
    forbidden_contexts = sorted(contexts & FORBIDDEN_RETRIEVAL_RATIO_CONTEXTS)
    if forbidden_contexts:
        reasons.extend(f"UNSAFE_RATIO_CONTEXT_{value}" for value in forbidden_contexts)
    text = str(block.get("text") or "")
    found_text_cues = [cue for cue in FORBIDDEN_RETRIEVAL_TEXT_CUES if cue in text]
    if found_text_cues:
        reasons.extend(f"UNSAFE_TEXT_CONTEXT_{cue}" for cue in found_text_cues)
    if block.get("is_valid_evidence") is not True:
        reasons.append("BLOCK_NOT_VALID_EVIDENCE")
    return not reasons, reasons or ["SEARCH_SAFE_EVIDENCE_BLOCK"]


def classify_case(
    case: dict[str, Any],
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    """판례 한 건을 E~I 게이트와 근거 ID를 포함해 분류합니다."""

    record_id = str(
        case.get("판례정보일련번호")
        or case.get("판례일련번호")
        or case.get("_case_id")
        or ""
    )
    all_facts = [
        block
        for block in blocks
        if block.get("semantic_role") == "ACCIDENT_FACT"
        and block.get("is_valid_evidence") is True
    ]
    all_decisions = [
        block
        for block in blocks
        if block.get("semantic_role") == "FAULT_DECISION"
        and block.get("is_valid_evidence") is True
    ]
    rejected_search_blocks: list[dict[str, Any]] = []

    def safe_blocks(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        safe: list[dict[str, Any]] = []
        for block in candidates:
            passed, reasons = _search_safety(block)
            if passed:
                safe.append(block)
            else:
                rejected_search_blocks.append(
                    {
                        "block_id": block["block_id"],
                        "semantic_role": block["semantic_role"],
                        "reason_codes": reasons,
                    }
                )
        return safe

    facts = safe_blocks(all_facts)
    decisions = safe_blocks(all_decisions)
    e_passed = bool(facts)
    f_passed = bool(decisions)
    relation, g_reasons = _relation(facts, decisions)
    g_passed = relation is not None
    main_issue, h_reasons = _main_issue(case, blocks, len(facts))
    h_passed = main_issue in {
        "ROAD_TRAFFIC_FAULT",
        "TRAFFIC_LEGAL_SUPPORT",
        "OTHER",
    }

    if case.get("internal_grade") == "SEED_READY":
        grade = "SEED_READY"
        grade_reasons = ["I_OFFICIAL_SEED_PRESERVED"]
    elif main_issue in {"MEDICAL", "INDUSTRIAL", "LABOR", "MARITIME"}:
        grade = "GENERAL_EXCLUDED"
        grade_reasons = [f"I_EXCLUDED_MAIN_ISSUE_{main_issue}"]
    elif e_passed and f_passed and g_passed and main_issue == "ROAD_TRAFFIC_FAULT":
        grade = "GENERAL_READY_DIRECT"
        grade_reasons = ["I_DIRECT_ALL_EFGH_PASSED"]
    elif main_issue == "TRAFFIC_LEGAL_SUPPORT" or (
        any(cue in _case_value(case, "사건명") for cue in LEGAL_SUPPORT_CUES)
        and (e_passed or any("자동차" in block.get("text", "") for block in blocks))
    ):
        grade = "GENERAL_READY_LEGAL_SUPPORT"
        grade_reasons = ["I_TRAFFIC_LEGAL_SUPPORT"]
    else:
        grade = "GENERAL_QUARANTINE"
        grade_reasons = ["I_INSUFFICIENT_DIRECT_EVIDENCE"]

    reason_codes = (
        (["E_TRAFFIC_FACT_PRESENT"] if e_passed else ["E_TRAFFIC_FACT_MISSING"])
        + (
            ["F_COURT_FAULT_DECISION_PRESENT"]
            if f_passed
            else ["F_COURT_FAULT_DECISION_MISSING"]
        )
        + g_reasons
        + h_reasons
        + grade_reasons
    )
    return {
        "record_id": record_id,
        "case_number": case.get("사건번호"),
        "case_name": case.get("사건명"),
        "source_route": case.get("_preprocessing_input_route"),
        "internal_grade": grade,
        "gates": {
            "E_actual_road_traffic_fact": e_passed,
            "F_court_fault_decision": f_passed,
            "G_fact_decision_link": g_passed,
            "H_target_main_issue": h_passed,
        },
        "main_issue": main_issue,
        "evidence_block_ids": {
            "accident_fact": [block["block_id"] for block in facts],
            "fault_decision": [block["block_id"] for block in decisions],
        },
        "best_fact_decision_relation": relation,
        "search_safety": {
            "selected_evidence_block_count": len(facts) + len(decisions),
            "rejected_valid_evidence_blocks": rejected_search_blocks,
            "selected_ratio_contexts": {
                block["block_id"]: [
                    mention.get("context")
                    for mention in block.get("ratio_mentions") or []
                ]
                for block in facts + decisions
            },
        },
        "classification_reason_codes": reason_codes,
        "classifier_version": CLASSIFIER_VERSION,
    }
