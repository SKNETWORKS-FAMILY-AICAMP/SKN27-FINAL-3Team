from .state import FineNoticeState


def make_envelope(
    status: str,
    structured: dict,
    missing: list[str],
    next_actions: list[str],
    summary: str = "",
) -> dict:
    return {
        "node_name":         "고지서 OCR·과태료/범칙금 분석 노드",
        "node_code":         "fine_notice_analysis",
        "status":            status,
        "summary":           summary,
        "structured_result": structured,
        "evidence":          [],
        "missing_fields":    missing,
        "next_actions":      next_actions,
        "limitations":       [],
    }


def update_agent_results(state: FineNoticeState, envelope: dict) -> dict:
    results = dict(state.get("agent_results") or {})
    results["fine_notice_analysis"] = envelope
    return results
