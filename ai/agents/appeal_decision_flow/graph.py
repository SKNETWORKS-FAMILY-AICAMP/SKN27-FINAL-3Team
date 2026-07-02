from langgraph.graph import StateGraph, END

from .deadline import deadline_gate_node
from .guide import guide_generation_node
from .law_code_check import law_code_check_node
from .merit_gate import merit_classification_node
from .reason_intake import reason_intake_node
from .risk_gate import risk_classification_node
from .state import AppealJudgmentState
from .verdict import verdict_node


def _not_applicable_node(state: AppealJudgmentState) -> dict:
    return {"judgment_status": "not_applicable"}


def _deny_node(state: AppealJudgmentState) -> dict:
    return {"judgment_status": "denied"}


def _dispatch_node(state: AppealJudgmentState) -> dict:
    """RG ∥ MG 병렬 실행 전 fan-out 지점 (실질 로직 없음)."""
    return {}


def _entry_route(state: AppealJudgmentState) -> str:
    """fine_type 분기.

    (v22) notice_stage와 무관하게 과태료는 항상 deadline_gate_node부터 시작한다.
    v20에서는 1차 고지서만 순서를 바꿨었는데(law_code_check → reason_intake →
    deadline), 그건 notice_received_date 없이는 deadline_gate_node 실행 자체가
    불가능하다는 전제 때문이었다. 이제 notice_received_date가 더 이상 하드
    블로커가 아니고(reason_intake_node 참고) deadline_gate_node가 없는 값을
    방어적으로 처리하므로, 그 전제 자체가 사라져 순서를 다시 통일했다.
    """
    if state.get("fine_type") == "범칙금":
        return "not_applicable_node"
    return "deadline_gate_node"


def _route_after_deadline(state: AppealJudgmentState) -> str:
    if state.get("deadline_passed"):
        return "deny_node"
    return "law_code_check_node"


def _route_after_reason_intake(state: AppealJudgmentState) -> str:
    if state.get("judgment_status") == "input_required":
        return END
    return "dispatch_node"


def build_graph() -> StateGraph:
    builder = StateGraph(AppealJudgmentState)

    builder.add_node("not_applicable_node", _not_applicable_node)
    builder.add_node("deny_node", _deny_node)
    builder.add_node("dispatch_node", _dispatch_node)
    builder.add_node("deadline_gate_node", deadline_gate_node)
    builder.add_node("law_code_check_node", law_code_check_node)
    builder.add_node("reason_intake_node", reason_intake_node)
    builder.add_node("risk_classification_node", risk_classification_node)
    builder.add_node("merit_classification_node", merit_classification_node)
    builder.add_node("verdict_node", verdict_node)
    builder.add_node("guide_generation_node", guide_generation_node)

    builder.set_conditional_entry_point(_entry_route)

    builder.add_edge("not_applicable_node", "guide_generation_node")
    builder.add_edge("deny_node", "guide_generation_node")

    builder.add_conditional_edges("deadline_gate_node", _route_after_deadline)
    builder.add_edge("law_code_check_node", "reason_intake_node")
    builder.add_conditional_edges("reason_intake_node", _route_after_reason_intake)

    builder.add_edge("dispatch_node", "risk_classification_node")
    builder.add_edge("dispatch_node", "merit_classification_node")
    builder.add_edge("risk_classification_node", "verdict_node")
    builder.add_edge("merit_classification_node", "verdict_node")

    builder.add_edge("verdict_node", "guide_generation_node")
    builder.add_edge("guide_generation_node", END)

    return builder.compile()


graph = build_graph()
