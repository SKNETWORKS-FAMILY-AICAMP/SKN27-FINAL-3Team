from .state import AppealJudgmentState


def make_envelope(
    status: str,
    structured: dict,
    missing: list[str],
    next_actions: list[str],
    summary: str = "",
) -> dict:
    return {
        "node_name":         "과태료 이의가능성 판단 노드",
        "node_code":         "appeal_judgment",
        "status":            status,
        "summary":           summary,
        "structured_result": structured,
        "evidence":          [],
        "missing_fields":    missing,
        "next_actions":      next_actions,
        "limitations":       [],
    }


def update_agent_results(state: AppealJudgmentState, envelope: dict) -> dict:
    results = dict(state.get("agent_results") or {})
    results["appeal_judgment"] = envelope
    return results
