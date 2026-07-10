"""Gate 판정 및 100점 환산 점수 계산.

단건 채점(score_single_call), Gate 집계(check_gates),
최종 점수 정규화(normalize_scores)를 담당한다.
"""
from __future__ import annotations

from typing import Any

from .config import (
    CRITICAL_FIELDS,
    GATE_MIN_CRITICAL_RATE,
    GATE_MIN_DOCUMENT_DETECT,
    IMPORTANT_FIELDS,
    WEIGHT_COST,
    WEIGHT_PERF,
    WEIGHT_SPEED,
    WEIGHT_STABILITY,
)


# ---------------------------------------------------------------------------
# 단건 채점
# ---------------------------------------------------------------------------

def score_single_call(
    parsed: dict[str, Any],
    is_target_document: bool,
    ocr_status: str,
    json_success: bool,
    expected_status: str = "success",
) -> dict[str, Any]:
    """단건 OCR 결과를 채점하여 비율/플래그를 반환한다.

    hallucination_count, privacy_leak 은 자동 판별이 어렵기 때문에
    초기값 0으로 기록하고 실행 후 수동으로 수정한다.
    """
    extracted = parsed.get("extracted_fields") or {}

    critical_extracted = sum(
        1 for f in CRITICAL_FIELDS if _get_field_value(extracted, f) is not None
    )
    important_extracted = sum(
        1 for f in IMPORTANT_FIELDS if _get_field_value(extracted, f) is not None
    )

    return {
        "critical_extracted":  critical_extracted,
        "critical_total":      len(CRITICAL_FIELDS),
        "critical_rate":       critical_extracted / len(CRITICAL_FIELDS),
        "important_extracted": important_extracted,
        "important_total":     len(IMPORTANT_FIELDS),
        "important_rate":      important_extracted / len(IMPORTANT_FIELDS),
        "is_target_document":  is_target_document,
        "ocr_status":          ocr_status,
        "status_match":        ocr_status == expected_status,
        "json_success":        json_success,
        # 수동 확인 항목 (기본값 0)
        "privacy_leak":        0,
        "hallucination_count": 0,
    }


# ---------------------------------------------------------------------------
# Gate 집계 (5장 기준)
# ---------------------------------------------------------------------------

def check_gates(results: list[dict[str, Any]]) -> dict[str, Any]:
    """5장 단건 결과를 받아 Gate 조건 통과 여부를 반환한다."""
    total = len(results)
    if total == 0:
        return {"gate_pass": False, "fail_reasons": ["결과 없음"]}

    json_success_all  = all(r["json_success"] for r in results)
    privacy_leaks     = sum(r.get("privacy_leak", 0)        for r in results)
    hallucinations    = sum(r.get("hallucination_count", 0) for r in results)
    avg_critical_rate = sum(r["critical_rate"]              for r in results) / total
    doc_detected      = sum(1 for r in results if r.get("is_target_document"))

    gate_pass = (
        json_success_all
        and privacy_leaks == 0
        and hallucinations == 0
        and avg_critical_rate >= GATE_MIN_CRITICAL_RATE
        and doc_detected >= GATE_MIN_DOCUMENT_DETECT
    )

    return {
        "gate_pass":          gate_pass,
        "json_success_all":   json_success_all,
        "privacy_leaks":      privacy_leaks,
        "hallucinations":     hallucinations,
        "avg_critical_rate":  avg_critical_rate,
        "doc_detected":       doc_detected,
        "doc_total":          total,
        "fail_reasons":       _gate_fail_reasons(
            json_success_all, privacy_leaks, hallucinations,
            avg_critical_rate, doc_detected, total,
        ),
    }


# ---------------------------------------------------------------------------
# 최종 점수 계산 (Gate 통과 모델 대상)
# ---------------------------------------------------------------------------

def compute_model_scores(
    model: str,
    gate: dict[str, Any],
    results: list[dict[str, Any]],
    raw_metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Gate 통과 여부와 성능/비용/속도 원점수를 하나의 딕셔너리로 묶는다.
    100점 정규화는 normalize_scores()에서 전체 모델을 비교해야 가능하므로 여기서는 하지 않는다.
    """
    base = {"model": model, "gate_pass": gate["gate_pass"]}
    if not gate["gate_pass"]:
        base["fail_reasons"] = gate.get("fail_reasons", [])
        return base

    n = len(results)
    avg_cost      = sum(m["cost_usd"]    for m in raw_metrics) / len(raw_metrics)
    avg_elapsed   = sum(m["elapsed_ms"]  for m in raw_metrics) / len(raw_metrics)
    avg_critical  = gate["avg_critical_rate"]
    avg_important = sum(r["important_rate"]  for r in results) / n
    avg_doc       = gate["doc_detected"]     / gate["doc_total"]
    avg_status    = sum(1 for r in results if r.get("status_match")) / n

    return {
        **base,
        "avg_cost_usd":          avg_cost,
        "avg_elapsed_ms":        avg_elapsed,
        "perf_critical_rate":    avg_critical,
        "perf_important_rate":   avg_important,
        "perf_doc_detect_rate":  avg_doc,
        "perf_status_match_rate":avg_status,
    }


def normalize_scores(all_model_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """전체 모델 원점수를 받아 비용/속도 점수를 정규화하고 최종점수를 계산한다.

    Gate 탈락 모델은 정규화 대상에서 제외하고 그대로 반환한다.
    """
    passed = [s for s in all_model_scores if s.get("gate_pass")]
    if not passed:
        return all_model_scores

    min_cost  = min(s["avg_cost_usd"]   for s in passed)
    min_time  = min(s["avg_elapsed_ms"] for s in passed)

    for s in passed:
        # 비용 점수: 가장 저렴한 모델 = 100점
        s["cost_score"] = (min_cost / s["avg_cost_usd"] * 100) if s["avg_cost_usd"] > 0 else 100.0

        # 속도 점수: 가장 빠른 모델 = 100점
        s["speed_score"] = (min_time / s["avg_elapsed_ms"] * 100) if s["avg_elapsed_ms"] > 0 else 100.0

        # 성능 점수 (100점 만점)
        s["perf_score"] = (
            s["perf_critical_rate"]     * 50
            + s["perf_important_rate"]  * 25
            + s["perf_doc_detect_rate"] * 15
            + s["perf_status_match_rate"] * 10
        )

        # 안정성 점수: Gate 통과 모델은 기본 100점
        s["stability_score"] = 100.0

        # 최종 가중합
        s["final_score"] = (
            s["cost_score"]      * WEIGHT_COST
            + s["perf_score"]    * WEIGHT_PERF
            + s["speed_score"]   * WEIGHT_SPEED
            + s["stability_score"] * WEIGHT_STABILITY
        )

    return all_model_scores


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _get_field_value(fields: dict[str, Any], field_path: str) -> Any:
    current: Any = fields
    for key in field_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    if current is None:
        return None
    if isinstance(current, str) and current.strip() == "":
        return None
    return current


def _gate_fail_reasons(
    json_ok: bool,
    privacy_leaks: int,
    hallucinations: int,
    critical_rate: float,
    doc_detected: int,
    total: int,
) -> list[str]:
    reasons: list[str] = []
    if not json_ok:
        reasons.append("JSON 파싱 실패")
    if privacy_leaks > 0:
        reasons.append(f"개인정보 누출 {privacy_leaks}건")
    if hallucinations > 0:
        reasons.append(f"치명적 환각 {hallucinations}건")
    if critical_rate < GATE_MIN_CRITICAL_RATE:
        reasons.append(f"Critical 추출률 {critical_rate:.1%} < 80%")
    if doc_detected < GATE_MIN_DOCUMENT_DETECT:
        reasons.append(f"문서 판별 {doc_detected}/{total} < {GATE_MIN_DOCUMENT_DETECT}")
    return reasons
