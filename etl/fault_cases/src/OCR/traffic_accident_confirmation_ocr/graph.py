from __future__ import annotations

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover - optional dependency fallback.
    END = "__end__"
    StateGraph = None

from .agent import ocr_node
from .constants import STATUS_FAILED
from .state import TrafficAccidentConfirmationOCRState
from .verification import document_verification_node


def _route_after_ocr(state: TrafficAccidentConfirmationOCRState) -> str:
    if state.get("ocr_status") == STATUS_FAILED:
        return END
    return "document_verification_node"


class _FallbackTrafficAccidentConfirmationOCRGraph:
    def invoke(
        self,
        state: TrafficAccidentConfirmationOCRState,
    ) -> TrafficAccidentConfirmationOCRState:
        ocr_state = ocr_node(state)
        if _route_after_ocr(ocr_state) == END:
            return ocr_state

        verification_state = document_verification_node(ocr_state)
        return {**ocr_state, **verification_state}


def build_graph():
    if StateGraph is None:
        return _FallbackTrafficAccidentConfirmationOCRGraph()

    builder = StateGraph(TrafficAccidentConfirmationOCRState)
    builder.add_node("ocr_node", ocr_node)
    builder.add_node("document_verification_node", document_verification_node)
    builder.set_entry_point("ocr_node")
    builder.add_conditional_edges("ocr_node", _route_after_ocr)
    builder.add_edge("document_verification_node", END)
    return builder.compile()


graph = build_graph()

