from .state import AppealJudgmentState
from .utils import make_envelope, update_agent_results

# ── ② 기대치 조정 (공용, fine_type·notice_stage 무관 고정 텍스트) ────
_EXPECTATION_TEXT = """\
이의제기가 항상 유리한 선택은 아닙니다. 과태료 이의제기는 처분 효력을 상실시킬 뿐 \
감액을 보장하지 않으며, 법원 재판으로 넘어가 결과가 같거나 더 불리해질 수 있습니다. \
이의제기를 선택하면 자진납부 20% 감경 기회는 사라집니다. 범칙금 즉결심판에서 유죄 \
판결이 나오면 범칙금 외에 재판비용까지 부담할 수 있습니다.

[과태료 유지 vs 범칙금 전환 비교]
- 금액: 과태료가 통상 다소 높으나(사전납부 20% 감경 시 역전 가능), 범칙금은 낮지만 \
대부분 벌점 동반
- 벌점: 과태료 없음 / 범칙금 있음(항목별 상이)
- 보험료: 과태료 영향 없음 / 범칙금 위반 2~3회 5% 할증, 4회 이상 10% 할증
- 신원: 과태료는 특정되지 않음(소유자 부과) / 범칙금은 본인이 운전 사실 인정
- 이력: 과태료는 안 남음 / 범칙금은 운전경력증명서에 5년 보존
- 재전환: 과태료→범칙금 전환 가능(사전통지·1차 부과 단계까지만), 역방향은 비가역

벌점이 없는 위반 항목(예: 제한속도 20km/h 이내 초과)은 범칙금 전환이 오히려 유리할 \
수 있습니다. 정확한 벌점 유무·수치는 이파인(경찰청 교통민원24) 전환 미리보기 화면에서 \
확인하세요. 착한운전마일리지 가입 여부도 함께 확인하면 벌점을 일부 상쇄할 수 있습니다.\
"""

# ── ③ 절차 방식 안내 (공용, 발부기관 구분 없음) ──────────────────────
_CHANNEL_TEXT = (
    "제출 방법은 서면(우편·방문)이 원칙이며, 온라인 접수 가능 여부는 관할 기관에 "
    "직접 확인하세요. 온라인 접수가 가능하더라도 신원노출 리스크는 별도이니 "
    "온라인이라는 이유로 안심하면 안 됩니다."
)

# ── ④ 철회 가능 시점 (공용) ────────────────────────────────────────
_WITHDRAWAL_TEXT = (
    "과태료는 행정청이 법원에 통보하기 전까지 서면으로 이의제기를 철회할 수 있습니다. "
    "범칙금 즉결심판 청구는 경찰서에 따라 취하 가능 여부가 다르며, 법원에 송부된 "
    "이후에는 취하가 어렵습니다."
)

# ── ⑤ 벌점·전과 오해 정정 (공용) ──────────────────────────────────
_PENALTY_MYTH_TEXT = (
    "범칙금은 무죄판결 시 벌점도 함께 취소됩니다. 통고처분·즉결심판 자체는 형사절차의 "
    "사전 단계 성격이라 통상 전과기록(범죄경력자료)에는 남지 않습니다 — '이의신청하면 "
    "전과 남는다'는 흔한 오해입니다. 다만 출석·납부기한 만료일로부터 60일이 지나도록 "
    "즉결심판을 받지 않으면 별도로 벌점 40점이 부과됩니다."
)

_RESIDUAL_RISK_NOTICE = (
    "이의제기 자체가 법원의 사실관계 조사로 이어질 수 있으며, 그 과정에서 실제 운전자가 "
    "밝혀지면 사건이 범칙금으로 전환될 수 있습니다. 이는 사전에 텍스트만으로는 판단할 수 "
    "없는 절차상 잔여 리스크이므로, 사유 내용과 무관하게 항상 참고용으로 안내합니다."
)

_NEXT_ACTIONS = {
    "success":        ["판정 결과 및 가이드 사용자 안내"],
    "denied":         ["기한 경과 안내, 타임라인 정보만 제공"],
    "not_applicable": ["OCR 결과 기반 절차 안내만 제공 — 이의신청서 생성 불가"],
}


def _timeline_text(state: AppealJudgmentState) -> str:
    fine_type    = state.get("fine_type")
    notice_stage = state.get("notice_stage")
    opinion_deadline = state.get("opinion_deadline")

    if fine_type == "과태료" and notice_stage == "1차 고지서":
        computed_deadline = state.get("computed_deadline")
        return (
            f"법정 이의제기 마감(수령일+60일, 질서위반행위규제법 제20조): "
            f"{computed_deadline or '계산 불가'}. 고지서에 인쇄된 납부기한"
            f"({opinion_deadline or '확인 불가'})과는 다른 값이니 혼동하지 마세요 — "
            "두 날짜 모두 지키지 못하면 각각 다른 불이익(납부기한 초과 시 가산금, "
            "이의제기 기한 초과 시 불복 기회 상실)이 발생합니다."
        )
    if fine_type == "과태료":  # 사전통지
        return (
            f"의견제출기한: {opinion_deadline or '확인 불가'} "
            "(10일 이상, 지자체별 15~20일도 있음)"
        )
    if notice_stage == "즉결심판":
        return (
            f"출석 예정일시: {opinion_deadline or '확인 불가'}. "
            "선고 전까지 범칙금의 1.5배를 납부하면 청구가 취소될 수 있습니다."
        )
    # 범칙금 사전통지(통고서)
    payment_2nd = state.get("payment_deadline_2nd")
    return (
        f"1차 납부기한: {opinion_deadline or '확인 불가'} "
        f"(미납 시 2차 납부기한 {payment_2nd or '확인 불가'}, 20% 가산)"
    )


def _disclaimer_text(state: AppealJudgmentState) -> str:
    parts = [
        "본 판단은 법률자문이 아니며 참고용입니다. 절차의 세부 운영(특히 온라인 접수 "
        "가능 여부)은 지자체·관할 기관마다 다를 수 있어, 최종 확인은 관할 기관에 "
        "하시기 바랍니다.",
        _RESIDUAL_RISK_NOTICE,
    ]

    if state.get("law_code_verified") is False:
        parts.append(
            "이의신청서에 인용된 법조항이 확인되지 않았습니다 — 고지서 원본과 대조해 "
            "직접 확인하세요."
        )
    elif state.get("law_code_verified") is True:
        parts.append("이의신청서에 인용될 법조항은 법령DB로 확인됐습니다.")

    if state.get("risk_flag"):
        if state.get("risk_trigger_category") == "C_본인운전인정형":
            parts.append(
                "이 사유는 조건부 위험입니다 — 사유가 받아들여지면 과태료 처분 자체가 "
                "면제되어 위험이 실현되지 않지만, 받아들여지지 않으면 이미 운전자 신원이 "
                "드러난 상태라 범칙금으로 전환될 수 있습니다. 표현을 다듬어도 사실관계 "
                "자체를 바꾸지 않는 한 이 위험은 없어지지 않습니다."
            )
        else:
            parts.append(
                "이 사유는 신원을 특정하는 진술을 포함하고 있어, 절차가 진행되면 성공·"
                "실패와 무관하게 범칙금 전환으로 이어질 위험이 있습니다."
            )

    return "\n\n".join(parts)


def _structured_result(state: AppealJudgmentState, guide: dict) -> dict:
    return {
        "judgment_status":       state.get("judgment_status"),
        "fine_type":             state.get("fine_type"),
        "notice_stage":          state.get("notice_stage"),
        "overall_possibility":   state.get("overall_possibility"),
        "merit":                 state.get("merit"),
        "risk_flag":             state.get("risk_flag"),
        "risk_confidence":       state.get("risk_confidence"),
        "risk_trigger_category": state.get("risk_trigger_category"),
        "computed_deadline":     state.get("computed_deadline"),
        "deadline_passed":       state.get("deadline_passed"),
        "law_code_verified":     state.get("law_code_verified"),
        "guide":                 guide,
    }


def guide_generation_node(state: AppealJudgmentState) -> dict:
    """G — ①~⑥ 가이드 조립 + 최종 응답 envelope 구성 (API-004 §3).

    fine_type·판정 성공 여부와 무관하게 항상 전체 출력되는 공용 템플릿이다
    (ARCH-001 §5-1) — not_applicable(범칙금)·denied(기한경과)·success 세 경로
    모두 이 노드로 들어온다.
    """
    guide = {
        "timeline":     _timeline_text(state),
        "expectation":  _EXPECTATION_TEXT,
        "channel":      _CHANNEL_TEXT,
        "withdrawal":   _WITHDRAWAL_TEXT,
        "penalty_myth": _PENALTY_MYTH_TEXT,
        "disclaimer":   _disclaimer_text(state),
    }

    judgment_status = state.get("judgment_status") or "success"
    structured = _structured_result(state, guide)
    next_actions = _NEXT_ACTIONS.get(judgment_status, [])
    fine_type_label = state.get("fine_type") or "미확인"
    notice_stage_label = state.get("notice_stage") or "미확인"
    summary = f"{fine_type_label} {notice_stage_label} — {judgment_status}"

    env = make_envelope(judgment_status, structured, [], next_actions, summary)

    return {
        "guide":         guide,
        "agent_results": update_agent_results(state, env),
    }
