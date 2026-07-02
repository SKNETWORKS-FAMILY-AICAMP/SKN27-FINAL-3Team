from .state import AppealJudgmentState
from .utils import make_envelope, update_agent_results

_NEXT_ACTIONS_1CHA = ["Supervisor가 사용자에게 이의신청 사유·수령일 질문 후 재호출"]
# 사전통지는 법적으로 "의견제출"이지 "이의신청"이 아니다 (질서위반행위규제법 제16조,
# ARCH-001 §5-3) — 정식 이의제기는 1차 고지서 단계부터다. 사용자에게 나가는 문구는
# 단계별로 정확한 절차명을 써야 혼동을 안 준다.
_NEXT_ACTIONS_SAJEON = ["Supervisor가 사용자에게 의견제출 사유 질문 후 재호출"]


def reason_intake_node(state: AppealJudgmentState) -> dict:
    """user_appeal_reason(1차 고지서는 notice_received_date도 함께) 존재 확인
    (ARCH-001 §9-7).

    확인하는 필드는 notice_stage에 따라 다르다.
        사전통지   → user_appeal_reason만. 이 노드 호출 시점엔 deadline_gate_node·
                     law_code_check_node가 이미 실행돼 있어 computed_deadline·
                     law_code_verified를 partial_result에 함께 실어 보낼 수 있다.
        1차 고지서 → user_appeal_reason + notice_received_date 둘 다. 이 노드가
                     deadline_gate_node보다 먼저 실행되므로 law_code_verified만
                     partial_result에 포함 가능하고 computed_deadline은 아직 없다.
    """
    notice_stage = state.get("notice_stage")

    missing: list[str] = []
    if not (state.get("user_appeal_reason") or "").strip():
        # 공백만 있는 문자열("   ")도 누락으로 취급 — falsy 체크만으로는 안 걸러짐
        missing.append("user_appeal_reason")
    if notice_stage == "1차 고지서" and not state.get("notice_received_date"):
        missing.append("notice_received_date")

    if not missing:
        return {}

    partial_result: dict = {
        "judgment_status":   "input_required",
        "fine_type":         state.get("fine_type"),
        "notice_stage":      notice_stage,
        "law_code_verified": state.get("law_code_verified"),
    }
    if notice_stage != "1차 고지서":
        # 사전통지 경로는 deadline_gate_node가 이미 실행돼 타임라인 계산이 끝나 있음.
        # 1차 고지서 경로는 이 노드가 deadline_gate_node보다 먼저 실행되므로(§9-7)
        # computed_deadline은 아직 계산 전이라 partial_result에 넣지 않는다.
        partial_result["computed_deadline"] = state.get("computed_deadline")
        partial_result["deadline_passed"] = state.get("deadline_passed")

    is_1cha = notice_stage == "1차 고지서"
    next_actions = _NEXT_ACTIONS_1CHA if is_1cha else _NEXT_ACTIONS_SAJEON
    summary = "이의신청 사유·수령일 정보 필요" if is_1cha else "의견제출 사유 정보 필요"

    env = make_envelope("input_required", partial_result, missing, next_actions, summary)

    return {
        "judgment_status": "input_required",
        "agent_results":   update_agent_results(state, env),
    }
