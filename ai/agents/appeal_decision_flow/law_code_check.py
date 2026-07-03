from .state import AppealJudgmentState


def law_code_check_node(state: AppealJudgmentState) -> dict:
    """law_code 경량 검증 (LDB_CHECK, DATA-003 §7).

    MVP: 팀 법령DB API 연동 전까지 law_code_verified를 항상 True로 스텁 처리한다
    (ARCH-001 §9-1) — 가짜 검증 로직을 만드는 것보다 "미구현"임을 명시하는 게 안전하다.
    실패해도 판정 파이프라인을 막지 않는 설계라, 이 스텁 값이 판정 로직(RG·MG·E)에
    영향을 주지 않는다 — ⑥ disclaimer 문구만 조건부로 바뀔 뿐이다.
    """
    return {"law_code_verified": True}
