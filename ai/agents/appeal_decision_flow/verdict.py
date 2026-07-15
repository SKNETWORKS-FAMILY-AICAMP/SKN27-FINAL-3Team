from .state import AppealJudgmentState

_OVERALL_POSSIBILITY_BY_STAGE = {
    "사전통지":   "의견_제출시_인정가능",
    "1차 고지서": "이의제기_인용가능",
}


def verdict_node(state: AppealJudgmentState) -> dict:
    """E — RG × MG 판정 통합 (DATA-003 §4).

    실제 톤·문구 조합(6칸 매트릭스, 카테고리 A/B/C 혼합 처리)은 guide_generation_node가
    risk_flag·merit·risk_trigger_category를 직접 읽어 담당한다. 이 노드는
    judgment_status·overall_possibility만 확정한다 — overall_possibility는
    merit 강도가 아니라 notice_stage에 따라 어느 절차 라벨을 쓸지 결정하는 값이다.
    """
    if state.get("legal_evidence_status") == "unavailable":
        return {
            "judgment_status": "failed",
            "overall_possibility": None,
        }

    return {
        "judgment_status":     "success",
        "overall_possibility": _OVERALL_POSSIBILITY_BY_STAGE.get(state.get("notice_stage")),
    }
