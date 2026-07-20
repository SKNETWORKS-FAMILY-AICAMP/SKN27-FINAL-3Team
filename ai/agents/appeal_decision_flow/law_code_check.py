from .state import AppealJudgmentState


def law_code_check_node(state: AppealJudgmentState) -> dict:
    """law_code 경량 검증 (LDB_CHECK, DATA-003 §7).

    법령DB(law_chunks)에서 law_code에 해당하는 조문이 존재하는지 단일 조회한다(재시도 없음).
    law_code 부재, 파싱 실패, DB 연결 오류 등 어떤 이유로든 확인이 안 되면 False만 기록하고
    판정 파이프라인(RG·MG·E)은 그대로 진행된다 — ⑥ disclaimer 문구만 조건부로 바뀐다.
    """
    law_code = state.get("law_code")
    if not law_code:
        return {"law_code_verified": False}

    from etl.legal.search import law_code_exists, law_code_last_verified

    return {
        "law_code_verified": law_code_exists(law_code),
        "law_reference_verified_at": law_code_last_verified(law_code),
    }
