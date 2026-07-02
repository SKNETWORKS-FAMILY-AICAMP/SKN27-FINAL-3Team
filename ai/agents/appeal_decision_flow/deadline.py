import datetime
from typing import Optional

from .law_refs import APPEAL_DEADLINE_DAYS
from .state import AppealJudgmentState


def _parse_date(value) -> Optional[datetime.date]:
    """날짜 파싱 → date 객체. 실패 시 None."""
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


# ── deadline_gate_node ──────────────────────────────────────────────────────
#
# notice_stage별로 기산일·기한 계산 방식이 다르다 (DATA-003 §6).
#
#   사전통지 · 범칙금 사전통지 · 즉결심판
#       → opinion_deadline 필드를 그대로 사용 (OCR 필드만으로 계산 가능)
#
#   1차 고지서
#       → opinion_deadline은 인쇄된 "납부기한"일 뿐, 법정 이의제기 마감이 아니다.
#         법정 마감은 notice_received_date(수령일) + 60일로 별도 계산해야 한다
#         (질서위반행위규제법 제20조 — 도달주의, 발송일이 아니라 받은 날 기준).
#
# ⚠️ 순서 주의 (ARCH-001 §9-7): notice_received_date는 Supervisor 공급 필드라
# 1차 고지서 경로에서는 이 노드보다 reason_intake_node가 먼저 실행되어 필드
# 존재를 보장한다고 가정한다. graph.py가 그 순서를 책임진다 — 이 노드 자체는
# notice_stage에 따라 값을 읽어 계산만 할 뿐, 노드 실행 순서는 모른다.

def deadline_gate_node(state: AppealJudgmentState) -> dict:
    notice_stage = state.get("notice_stage")

    if notice_stage == "1차 고지서":
        received = _parse_date(state.get("notice_received_date"))
        deadline = (
            received + datetime.timedelta(days=APPEAL_DEADLINE_DAYS)
            if received is not None else None
        )
    else:
        deadline = _parse_date(state.get("opinion_deadline"))

    if deadline is None:
        # 정상 흐름에서는 발생하지 않아야 한다 (§9-7이 보장) — 방어적 처리
        return {"computed_deadline": None, "deadline_passed": None}

    return {
        "computed_deadline": deadline.isoformat(),
        "deadline_passed":   deadline < datetime.date.today(),
    }
