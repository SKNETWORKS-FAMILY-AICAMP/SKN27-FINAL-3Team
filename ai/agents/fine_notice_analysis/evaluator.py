from typing import Optional

CRITICAL_FIELDS: dict[str, list[str]] = {
    "과태료": ["law_code", "violation_text", "notice_stage"],
    "범칙금": ["law_code", "violation_text", "notice_stage"],
}

IMPORTANT_FIELDS: dict[str, list[str]] = {
    "과태료": ["fine_amount", "opinion_deadline", "issuing_authority", "charge_number"],
    "범칙금": ["fine_amount", "opinion_deadline", "vehicle_number", "violation_datetime", "violation_location"],
}

# 서식 구조상 존재하지 않는 필드 — critical/important 체크에서 제외하여 degraded 처리
_STRUCTURAL_ABSENT: dict[tuple, set[str]] = {
    # ④ 즉결심판 출석통지서
    ("범칙금", "즉결심판"):  {"law_code", "vehicle_number"},
}


def evaluate_ocr(
    fields: dict,
    fine_type: str,
    notice_stage: Optional[str] = None,
) -> tuple[str, list[str]]:
    """ocr_status 판정. ④ 즉결심판의 구조적 부재 필드는 critical/important에서 제외."""
    absent: set[str] = _STRUCTURAL_ABSENT.get((fine_type, notice_stage), set())

    critical  = [f for f in CRITICAL_FIELDS.get(fine_type, [])  if f not in absent]
    important = [f for f in IMPORTANT_FIELDS.get(fine_type, []) if f not in absent]

    missing_critical  = [f for f in critical  if not fields.get(f)]
    missing_important = [f for f in important if not fields.get(f)]

    if missing_critical:
        return "partial", missing_critical + missing_important
    if missing_important:
        return "degraded", missing_important
    return "success", []
