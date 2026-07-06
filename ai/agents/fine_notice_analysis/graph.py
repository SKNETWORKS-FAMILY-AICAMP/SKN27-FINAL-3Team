try:
    from langgraph.graph import StateGraph, END
except ImportError:  # pragma: no cover - exercised only when optional runtime deps are absent.
    StateGraph = None
    END = "__end__"

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


class _FallbackFineNoticeGraph:
    """Minimal invoke-compatible graph for environments without langgraph installed."""

    def invoke(self, state: FineNoticeState) -> FineNoticeState:
        next_state = ocr_node(state)
        if _route_after_ocr(next_state) == END:
            return next_state
        return confidence_verification_node(next_state)


def build_graph():
    if StateGraph is None:
        return _FallbackFineNoticeGraph()

    builder = StateGraph(FineNoticeState)
    builder.add_node("ocr_node", ocr_node)
    builder.add_node("confidence_verification_node", confidence_verification_node)
    builder.set_entry_point("ocr_node")
    builder.add_conditional_edges("ocr_node", _route_after_ocr)
    builder.add_edge("confidence_verification_node", END)
    return builder.compile()


graph = build_graph()
