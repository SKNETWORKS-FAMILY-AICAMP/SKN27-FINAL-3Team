"""분류기와 독립적으로 등급 불변조건을 재검사합니다."""

from __future__ import annotations

from typing import Any


VALIDATOR_VERSION = "grade_validator_v1.1.0"
FORBIDDEN_RETRIEVAL_RATIO_CONTEXTS = {
    "INTEREST_RATE",
    "DISABILITY_RATE",
    "PREEXISTING_CONDITION_RATE",
    "DAMAGE_CALCULATION_RATE",
    "MEDICAL_STATISTIC",
}


def validate_classification(result: dict[str, Any]) -> dict[str, Any]:
    grade = result["internal_grade"]
    gates = result["gates"]
    reasons: list[str] = []

    if grade == "SEED_READY":
        passed = result.get("source_route") == "SEED_READY"
        if not passed:
            reasons.append("SEED_READY_WITHOUT_SEED_ROUTE")
    elif grade == "GENERAL_READY_DIRECT":
        selected_contexts = [
            context
            for contexts in (
                result.get("search_safety", {})
                .get("selected_ratio_contexts", {})
                .values()
            )
            for context in contexts
        ]
        passed = all(
            [
                gates["E_actual_road_traffic_fact"],
                gates["F_court_fault_decision"],
                gates["G_fact_decision_link"],
                gates["H_target_main_issue"],
                result["main_issue"] == "ROAD_TRAFFIC_FAULT",
                bool(result["evidence_block_ids"]["accident_fact"]),
                bool(result["evidence_block_ids"]["fault_decision"]),
                not (
                    set(selected_contexts)
                    & FORBIDDEN_RETRIEVAL_RATIO_CONTEXTS
                ),
            ]
        )
        if not passed:
            reasons.append("DIRECT_INVARIANT_FAILED")
    elif grade == "GENERAL_READY_LEGAL_SUPPORT":
        passed = result["main_issue"] in {
            "TRAFFIC_LEGAL_SUPPORT",
            "ROAD_TRAFFIC_FAULT",
        }
        if not passed:
            reasons.append("LEGAL_SUPPORT_TRAFFIC_RELEVANCE_FAILED")
    elif grade == "GENERAL_EXCLUDED":
        passed = result["main_issue"] in {
            "MEDICAL",
            "INDUSTRIAL",
            "LABOR",
            "MARITIME",
        }
        if not passed:
            reasons.append("EXCLUDED_WITHOUT_HARD_MAIN_ISSUE")
    else:
        passed = grade == "GENERAL_QUARANTINE"
        if not passed:
            reasons.append("UNKNOWN_GRADE")

    return {
        "status": "PASSED" if passed else "FAILED",
        "reason_codes": reasons or ["GRADE_INVARIANTS_PASSED"],
        "validator_version": VALIDATOR_VERSION,
    }
