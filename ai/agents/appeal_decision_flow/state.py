from typing import Optional
from typing_extensions import TypedDict, Literal

JudgmentStatus = Literal[
    "success", "denied", "input_required", "not_applicable",
]
MeritLevel          = Literal["강함", "보류", "낮음"]
MeritReliefType     = Literal["면제", "감경"]
RiskTriggerCategory = Literal[
    "A_제3자운전주장", "B_명시적전환요청", "C_본인운전인정형",
]


class AppealJudgmentState(TypedDict, total=False):
    # ── OCR Agent 결과 (structured_result 평탄화 재사용) ─────────────
    fine_type:               Optional[str]    # "과태료" | "범칙금" — 「벌금」은 OCR 단계에서
                                                # 이미 거부되어 이 Agent에 도달하지 않음
    notice_stage:             Optional[str]    # "사전통지" | "1차 고지서" | "즉결심판"
    violation_text:           Optional[str]
    opinion_deadline:         Optional[str]    # YYYY-MM-DD, notice_stage별 의미 다름 (DATA-003 §1)
    payment_deadline_2nd:     Optional[str]    # 범칙금 2차 납부기한
    issuing_authority:        Optional[str]    # 가이드 ③에 그대로 노출만 함 (판별 안 함)
    law_code:                 Optional[str]    # (v3.12) 용도 1가지 — LDB_CHECK 경량 검증 → ⑥
                                                # disclaimer 조건부 문구. MG는 더 이상 이 값으로
                                                # 위반유형을 판별·라우팅하지 않는다 (DATA-003 §5)

    # ── Supervisor 공급 (OCR 결과에 없는 값) ─────────────────────────
    user_appeal_reason:       Optional[str]
    notice_received_date:     Optional[str]    # YYYY-MM-DD. OCR에 발송일 계열 필드가 없어
                                                # user_appeal_reason과 동일하게 Supervisor가 물어
                                                # 공급 (1차 고지서 기산일=수령일+60일 계산에 사용)

    # ── law_code_check_node (LDB_CHECK) 출력 ─────────────────────────
    law_code_verified:        Optional[bool]   # 실패해도 파이프라인은 계속 진행

    # ── deadline_gate_node 출력 ───────────────────────────────────────
    computed_deadline:        Optional[str]    # notice_stage별 계산된 실제 기한
    deadline_passed:          Optional[bool]

    # ── risk_classification_node (RG) 출력 ────────────────────────────
    risk_flag:                Optional[bool]
    risk_stage_matched:       Optional[str]    # "keyword" | "llm" | None
    risk_confidence:          Optional[float]
    risk_trigger_category:    Optional[RiskTriggerCategory]
    # 여러 카테고리가 동시에 매치되면 A/B(무조건 위험)를 C(조건부 위험)보다 우선 기록.
    # guide_generation_node가 이 값으로 disclaimer 프레이밍(조건부/무조건)을 결정한다.
    risk_judgment_failed:     Optional[bool]   # True면 이 risk_flag=true가 사유를 실제로
                                                # 분석해서 나온 결과가 아니라 LLM 호출 실패로
                                                # 인한 안전 기본값(재현율 우선 폴백)이라는 뜻
                                                # (merit_judgment_failed와 대칭 — RG는 실패 시
                                                # risk_flag를 여전히 true로 유지하지만, 그 이유가
                                                # "위험 감지"가 아니라 "판단 불가"임을 별도로
                                                # 구분해야 사용자가 불필요하게 위축되거나 재시도
                                                # 없이 포기하지 않는다). guide_generation_node가
                                                # 이 값으로 disclaimer에 재시도 안내를 추가한다.

    # ── merit_classification_node (MG) 출력 ───────────────────────────
    merit:                    Optional[MeritLevel]
    merit_basis:               Optional[str]    # LLM이 근거로 인용한 조문 요약
    merit_judgment_failed:     Optional[bool]   # True면 이 merit="보류"가 사유를 실제로
                                                # 검토한 결과가 아니라 LLM 호출 실패·응답
                                                # 파싱 실패로 인한 기본값이라는 뜻 (RG의
                                                # risk_flag는 이 영향을 안 받음). guide_
                                                # generation_node가 이 값으로 "판단은
                                                # 애매하다"는 문구 대신 "판단을 못 했다"는
                                                # 사실대로 안내한다.
    merit_relief_type:         Optional[MeritReliefType]  # merit="강함"일 때만 의미 있음.
                                                # "감경"이면 처분 자체가 아니라 금액만 줄어드는
                                                # 사유라는 뜻(예: 질서법 제10조②) — "면제"(처분
                                                # 자체 불가, 예: 제10조①·7~9조·142조)와 구분해서
                                                # 사용자가 "이의제기하면 처분이 없어질 수도
                                                # 있다"고 오해하지 않게 한다. 설계 근거는
                                                # `docs/architecture/appeal-judgment/
                                                # 면제·감경 사유 merit 구분 설계.md` 참고.

    # ── verdict_node (E) 출력 ──────────────────────────────────────────
    judgment_status:           Optional[JudgmentStatus]
    overall_possibility:       Optional[str]    # "의견_제출시_인정가능" | "이의제기_인용가능"

    # ── guide_generation_node 출력 ────────────────────────────────────
    guide:                     Optional[dict]   # ①~⑥ 키를 갖는 dict

    # ── Supervisor 수신 ───────────────────────────────────────────────
    agent_results:             dict
