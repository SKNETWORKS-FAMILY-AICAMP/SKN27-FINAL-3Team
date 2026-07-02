from .state import AppealJudgmentState
from .utils import make_envelope, update_agent_results

_NEXT_ACTIONS_1CHA = [
    "Supervisor가 사용자에게 이의신청 사유 질문 후 재호출 "
    "(고지서 수령일도 함께 물으면 법정 기한을 정확히 계산 가능 — 선택 사항)"
]
# 사전통지는 법적으로 "의견제출"이지 "이의신청"이 아니다 (질서위반행위규제법 제16조,
# ARCH-001 §5-3) — 정식 이의제기는 1차 고지서 단계부터다. 사용자에게 나가는 문구는
# 단계별로 정확한 절차명을 써야 혼동을 안 준다.
_NEXT_ACTIONS_SAJEON = ["Supervisor가 사용자에게 의견제출 사유 질문 후 재호출"]


def reason_intake_node(state: AppealJudgmentState) -> dict:
    """user_appeal_reason 존재 확인.

    (v22) `notice_received_date`(1차 고지서 기산일)는 더 이상 하드 블로커가 아니다 —
    "승산만 궁금한" 사용자를 막지 않기 위해, 없어도 판정(merit/risk)은 그대로
    진행하고 `guide_generation_node`가 "법정 기한을 계산할 수 없다"는 경고만
    남긴다. 사유가 없을 때만 재질문하며, 이왕 재질문하는 김에 1차 고지서라면
    수령일도 함께 물어본다(선택 사항 — 답 안 해도 재호출은 통과됨).

    (v22) `deadline_gate_node`가 notice_stage 구분 없이 이 노드보다 항상 먼저
    실행되므로, `computed_deadline`·`law_code_verified`는 이미 계산돼 있어
    partial_result에 항상 포함할 수 있다 (더 이상 notice_stage로 분기할 필요 없음).
    """
    notice_stage = state.get("notice_stage")
    if (state.get("user_appeal_reason") or "").strip():
        return {}

    missing: list[str] = ["user_appeal_reason"]
    if notice_stage == "1차 고지서" and not state.get("notice_received_date"):
        missing.append("notice_received_date")

    partial_result = {
        "judgment_status":   "input_required",
        "fine_type":         state.get("fine_type"),
        "notice_stage":      notice_stage,
        "law_code_verified": state.get("law_code_verified"),
        "computed_deadline": state.get("computed_deadline"),
        "deadline_passed":   state.get("deadline_passed"),
    }

    is_1cha = notice_stage == "1차 고지서"
    next_actions = _NEXT_ACTIONS_1CHA if is_1cha else _NEXT_ACTIONS_SAJEON
    summary = "이의신청 사유 정보 필요" if is_1cha else "의견제출 사유 정보 필요"

    env = make_envelope("input_required", partial_result, missing, next_actions, summary)

    return {
        "judgment_status": "input_required",
        "agent_results":   update_agent_results(state, env),
    }
