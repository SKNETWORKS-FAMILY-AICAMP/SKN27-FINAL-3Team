from langgraph.graph import StateGraph, END

from .agent import ocr_node
from .state import FineNoticeState
from .verification import confidence_verification_node

_TERMINAL_STATUSES = {"failed", "rejected", "partial"}


def _route_after_ocr(state: FineNoticeState) -> str:
    """failed / rejected / partial → END (agent_results 이미 조립됨).
    success / degraded → confidence_verification_node."""
    if state.get("ocr_status") in _TERMINAL_STATUSES:
        return END
    return "confidence_verification_node"


def build_graph() -> StateGraph:
    builder = StateGraph(FineNoticeState)
    builder.add_node("ocr_node", ocr_node)
    builder.add_node("confidence_verification_node", confidence_verification_node)
    builder.set_entry_point("ocr_node")
    builder.add_conditional_edges("ocr_node", _route_after_ocr)
    builder.add_edge("confidence_verification_node", END)
    return builder.compile()


graph = build_graph()
