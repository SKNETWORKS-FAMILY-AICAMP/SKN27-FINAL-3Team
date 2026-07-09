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
        if computed_deadline is None:
            # (v22) notice_received_date가 없어도 판정 자체는 진행하지만, 법정
            # 이의제기 마감은 계산할 수 없다 — "승산만 궁금한" 사용자를 막지 않는
            # 대신 여기서 명확하게 경고한다.
            return (
                "⚠️ 고지서 수령일을 알려주지 않아 법정 이의제기 마감(수령일+60일, "
                "질서위반행위규제법 제20조)을 계산할 수 없습니다. 고지서에 인쇄된 "
                f"납부기한({opinion_deadline or '확인 불가'})은 법정 이의제기 마감과 "
                "다른 값입니다 — 수령일을 모른 채 이의제기를 진행하면 법정 기한을 "
                "넘겨 불복 기회를 잃을 수 있으니, 정확한 기한이 필요하면 수령일을 "
                "알려주세요."
            )
        return (
            f"법정 이의제기 마감(수령일+60일, 질서위반행위규제법 제20조): "
            f"{computed_deadline}. 고지서에 인쇄된 납부기한"
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


# ── RG × MG 6칸 조합 매트릭스 (DATA-003 §4) ────────────────────────────
# merit=강함 & risk=true는 카테고리(A/B vs C)에 따라 조건부/무조건 톤이 갈리므로
# 별도 분기한다. 그 외 5칸은 고정 문구.
_TONE_SAFE = {
    "강함": "이 사유는 인정 가능성이 높고 신원노출 위험도 없는 조합입니다 — 안심하고 진행해도 됩니다.",
    "보류": "판단은 애매하지만 위험은 없는 조합입니다 — 증거를 보강해서 진행을 검토해보세요.",
    "낮음": "인정되기는 어려워 보이지만 위험은 없는 조합입니다 — 기대치를 낮춰서 참고하세요.",
}
_TONE_RISKY_NON_STRONG = {
    "보류": "판단도 애매하고 위험도 있는 조합입니다 — 가장 신중한 접근이 필요하며, 필요하면 "
           "전문가 상담을 권합니다.",
    "낮음": "승산도 낮고 위험까지 있는 조합입니다 — 진행 자체를 재고해보시길 권합니다.",
}
_TONE_STRONG_CONDITIONAL = (
    "이 사유는 조건부 위험입니다 — 사유가 받아들여지면 과태료 처분 자체가 "
    "면제되어 위험이 실현되지 않지만, 받아들여지지 않으면 이미 운전자 신원이 "
    "드러난 상태라 범칙금으로 전환될 수 있습니다. 표현을 다듬어도 사실관계 "
    "자체를 바꾸지 않는 한 이 위험은 없어지지 않습니다."
)
_TONE_STRONG_UNCONDITIONAL = (
    "이 사유는 신원을 특정하는 진술을 포함하고 있어, 절차가 진행되면 성공·"
    "실패와 무관하게 범칙금 전환으로 이어질 위험이 있습니다."
)


# merit="강함"이어도 근거 조문이 "감경"형(예: 질서법 제10조②)이면 처분 자체가 없어지는
# 게 아니라 금액만 줄어드는 것 — "면제·감경 사유 merit 구분 설계.md" 참고. 사용자가
# "이의제기하면 처분이 취소될 수도 있겠다"고 과도하게 기대하지 않도록 명시적으로 붙인다.
_RELIEF_TYPE_REDUCTION_NOTICE = (
    "⚠️ 이 사유는 인정되더라도 과태료 처분 자체가 없어지는 게 아니라 금액이 일부 "
    "감경되는 사유입니다 — 처분이 취소될 거라 기대하지 마시고, 참고용으로만 활용하세요."
)

# 기술적 실패로 merit="보류"가 나왔을 때 붙이는 정정 문구 (RG의 risk_flag는 이 실패와
# 무관하게 정상 평가된 값이므로 톤 자체는 그대로 두고, 이 문구를 앞에 덧붙이기만 한다) —
# "판단이 애매하다"가 아니라 "판단을 못 했다"임을 명확히 해서, 승산 있는 사유를 사용자가
# 오해로 포기하지 않게 한다.
_MERIT_JUDGMENT_FAILED_NOTICE = (
    "⚠️ 사유 인정 가능성(merit) 판정이 일시적 기술 오류로 완료되지 못해 잠정적으로 "
    "'보류'로 표시됩니다 — 사유 내용을 실제로 검토해서 애매하다고 나온 결과가 아니라, "
    "시스템이 판단 자체를 하지 못한 것입니다. 아래 톤은 안전을 위한 임시 표시일 뿐이니 "
    "승산 있는 사유를 이것만 보고 포기하지 마시고, 잠시 후 다시 시도해 정확한 판정을 "
    "받아보세요."
)


def _merit_risk_tone(state: AppealJudgmentState) -> str | None:
    merit = state.get("merit")
    if merit not in ("강함", "보류", "낮음"):
        return None  # not_applicable/denied 경로 — MG가 실행되지 않아 merit이 없음

    if not state.get("risk_flag"):
        tone = _TONE_SAFE[merit]
    elif merit != "강함":
        tone = _TONE_RISKY_NON_STRONG[merit]
    else:
        # merit=강함 & risk=true: 카테고리 C만 조건부, 그 외(A/B, 또는 LLM 예외로
        # 카테고리를 알 수 없는 경우)는 안전 쪽으로 단정하지 않고 무조건 위험으로 취급
        if state.get("risk_trigger_category") == "C_본인운전인정형":
            tone = _TONE_STRONG_CONDITIONAL
        else:
            tone = _TONE_STRONG_UNCONDITIONAL

    if merit == "강함" and state.get("merit_relief_type") == "감경":
        tone = f"{tone}\n\n{_RELIEF_TYPE_REDUCTION_NOTICE}"

    if state.get("merit_judgment_failed"):
        tone = f"{_MERIT_JUDGMENT_FAILED_NOTICE}\n\n{tone}"

    return tone


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

    tone = _merit_risk_tone(state)
    if tone:
        parts.append(tone)

    return "\n\n".join(parts)


def _structured_result(state: AppealJudgmentState, guide: dict) -> dict:
    return {
        "judgment_status":       state.get("judgment_status"),
        "fine_type":             state.get("fine_type"),
        "notice_stage":          state.get("notice_stage"),
        "overall_possibility":   state.get("overall_possibility"),
        "merit":                 state.get("merit"),
        "merit_judgment_failed": state.get("merit_judgment_failed"),
        "merit_relief_type":     state.get("merit_relief_type"),
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
    next_actions = list(_NEXT_ACTIONS.get(judgment_status, []))
    if state.get("merit_judgment_failed"):
        # merit 판정이 기술적 실패로 "보류"에 머문 상태 — Supervisor가 이걸 "판정
        # 완료"로 오인하지 않고 재호출을 시도할 수 있게 명시적으로 알려준다.
        next_actions.append("MG(merit) 판정이 기술 오류로 미완료 — 재호출 시 정확한 판정 가능")
    fine_type_label = state.get("fine_type") or "미확인"
    notice_stage_label = state.get("notice_stage") or "미확인"
    summary = f"{fine_type_label} {notice_stage_label} — {judgment_status}"

    # (v22) 판정은 완료됐지만 notice_received_date가 없어 법정 기한을 못 구한
    # 경우, missing_fields로 남겨 Supervisor가 "정확한 기한을 원하면 수령일을
    # 알려달라"고 후속 안내할 수 있게 한다 — 판정 자체를 막지는 않는다.
    missing_fields = []
    if state.get("notice_stage") == "1차 고지서" and not state.get("notice_received_date"):
        missing_fields.append("notice_received_date")

    env = make_envelope(judgment_status, structured, missing_fields, next_actions, summary)

    return {
        "guide":         guide,
        "agent_results": update_agent_results(state, env),
    }
