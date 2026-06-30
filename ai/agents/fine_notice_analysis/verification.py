import re
from typing import Optional

from .state import FineNoticeState
from .utils import make_envelope, update_agent_results

VALID_COMBINATIONS: set[tuple[str, str]] = {
    ("과태료", "사전통지"),
    ("과태료", "1차 고지서"),
    ("범칙금", "사전통지"),
    ("범칙금", "즉결심판"),
}

_LAW_CODE_RE = re.compile(r".+(법|규칙|령|조례|규정).+제\d+조")

_D3B_MISSING = ["law_code", "violation_text", "violation_datetime", "violation_location", "vehicle_number"]


def _structured_from_state(state: FineNoticeState, ocr_status: str) -> dict:
    return {
        "ocr_status":                 ocr_status,
        "ocr_error":                  state.get("ocr_error"),
        "fine_type":                  state.get("fine_type"),
        "notice_stage":               state.get("notice_stage"),
        "law_code":                   state.get("law_code"),
        "violation_text":             state.get("violation_text"),
        "violation_datetime":         state.get("violation_datetime"),
        "violation_location":         state.get("violation_location"),
        "fine_amount":                state.get("fine_amount"),
        "prepayment_amount":          state.get("prepayment_amount"),
        "opinion_deadline":           state.get("opinion_deadline"),
        "payment_deadline_2nd":       state.get("payment_deadline_2nd"),
        "additional_amount":          state.get("additional_amount"),
        "issuing_authority":          state.get("issuing_authority"),
        "vehicle_number":             state.get("vehicle_number"),
        "demerit_points_base":        state.get("demerit_points_base"),
        "demerit_points_accumulated": state.get("demerit_points_accumulated"),
        "charge_number":              state.get("charge_number"),
        "court_venue":                state.get("court_venue"),
        "missing_fields":             state.get("missing_fields") or [],
    }


def confidence_verification_node(state: FineNoticeState) -> dict:
    # ── V-01 ~ V-05 순차 검증 (오류 있어도 전부 실행) ────────────────────
    format_errors: list[str] = []

    # V-01
    if state.get("notice_stage") not in {"사전통지", "1차 고지서", "즉결심판"}:
        format_errors.append(f"invalid notice_stage: {state.get('notice_stage')!r}")

    # V-02
    if state.get("fine_type") not in {"과태료", "범칙금"}:
        format_errors.append(f"invalid fine_type: {state.get('fine_type')!r}")

    # V-03: null → OK (④ 즉결심판 fine_amount 없음)
    fine_amount = state.get("fine_amount")
    if fine_amount is not None and fine_amount <= 0:
        format_errors.append(f"invalid fine_amount: {fine_amount}")

    # V-04: null → OK
    law_code = state.get("law_code")
    if law_code and not _LAW_CODE_RE.match(law_code):
        format_errors.append(f"invalid law_code format: {law_code!r}")

    # V-05 R-01
    combo: tuple[Optional[str], Optional[str]] = (state.get("fine_type"), state.get("notice_stage"))
    if combo not in VALID_COMBINATIONS:
        format_errors.append(f"invalid combination: {combo}")

    # ── DOC_ROUTE: VPASS & VFAIL 모두 통과 ──────────────────────────────
    fine_type    = state.get("fine_type")
    notice_stage = state.get("notice_stage")
    missing      = state.get("missing_fields") or []

    # format_errors 있으면 partial로 오버라이드 (VFAIL 경로)
    ocr_status = "partial" if format_errors else state.get("ocr_status", "success")

    # ③-2: 범칙금 사전통지 + violation_text 없음 → ENV_DEG (degraded 고정)
    if fine_type == "범칙금" and notice_stage == "사전통지" and not state.get("violation_text"):
        structured = _structured_from_state(state, "degraded")
        summary    = "위반내용 미확인 — 사전통지 OCR degraded (별지 162·163호)"
        env = make_envelope("degraded", structured, _D3B_MISSING,
                            ["원처분 통고서 추가 제출 요청"], summary)
        return {
            "ocr_status":    "degraded",
            "format_errors": format_errors,
            "agent_results": update_agent_results(state, env),
        }

    # 일반 케이스 (①②③④) → ENV_OK
    next_actions = ["법률 근거 검색 노드 호출"] if ocr_status == "success" else ["이미지 재업로드 요청"]
    violation_text = state.get("violation_text") or ""
    summary = f"{violation_text[:20] or '내용 미확인'} — {notice_stage} OCR {ocr_status}"

    structured = _structured_from_state(state, ocr_status)
    env = make_envelope(ocr_status, structured, missing, next_actions, summary)

    return {
        "ocr_status":    ocr_status,
        "format_errors": format_errors,
        "agent_results": update_agent_results(state, env),
    }
