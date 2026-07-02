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
    """fine_type 분기 + notice_stage별 노드 순서 분기 (ARCH-001 §9-7).

    사전통지: opinion_deadline이 OCR 필드라 deadline_gate_node를 바로 실행 가능
    (기존 순서 유지). 1차 고지서: notice_received_date가 Supervisor 공급 필드라
    deadline_gate_node를 바로 실행할 수 없으므로, law_code_check_node부터
    시작한다 (v20 순서 수정의 실제 구현 지점).
    """
    if state.get("fine_type") == "범칙금":
        return "not_applicable_node"
    if state.get("notice_stage") == "1차 고지서":
        return "law_code_check_node"
    return "deadline_gate_node"


def _route_after_deadline(state: AppealJudgmentState) -> str:
    if state.get("deadline_passed"):
        return "deny_node"
    if state.get("notice_stage") == "1차 고지서":
        # 1차 고지서 경로: law_code_check_node·reason_intake_node를 이미 거쳐온
        # 상태이므로(§9-7), 곧바로 RG ∥ MG로 진입한다.
        return "dispatch_node"
    # 사전통지 경로: 기존 순서대로 law_code_check_node로 이어간다.
    return "law_code_check_node"


def _route_after_reason_intake(state: AppealJudgmentState) -> str:
    if state.get("judgment_status") == "input_required":
        return END
    if state.get("notice_stage") == "1차 고지서":
        # 1차 고지서 경로: 이제서야 필드가 확보됐으니 기한을 계산한다.
        return "deadline_gate_node"
    # 사전통지 경로: deadline_gate_node를 이미 거쳐왔으므로 곧바로 진입한다.
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
