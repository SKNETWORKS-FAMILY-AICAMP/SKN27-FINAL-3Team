from typing import Optional
from typing_extensions import TypedDict, Literal

OCRStatus   = Literal["success", "degraded", "partial", "failed", "rejected"]
FineType    = Literal["과태료", "범칙금", "벌금"]
NoticeStage = Literal["사전통지", "1차 고지서", "즉결심판"]


class FineNoticeState(TypedDict, total=False):
    # ── Supervisor 공급 ──────────────────────────────────────────────
    notice_image:               Optional[str]    # base64 (OCR 후 None)
    notice_mime_type:           Optional[str]    # "image/jpeg"|"image/png"|"application/pdf"

    # ── ocr_node 출력 ────────────────────────────────────────────────
    ocr_status:                 Optional[OCRStatus]
    ocr_error:                  Optional[str]    # 구조 오류 메시지 (R-08, R-03)
    fine_type:                  Optional[FineType]
    notice_stage:               Optional[NoticeStage]
    law_code:                   Optional[str]
    violation_text:             Optional[str]    # 마스킹 후
    violation_datetime:         Optional[str]
    violation_location:         Optional[str]
    fine_amount:                Optional[int]
    prepayment_amount:          Optional[int]    # 과태료 사전통지만 유효 (R-06)
    opinion_deadline:           Optional[str]    # YYYY-MM-DD (R-04)
    payment_deadline_2nd:       Optional[str]    # YYYY-MM-DD, ③ 전용
    additional_amount:          Optional[int]    # ③ 전용, fine_amount × 1.2
    issuing_authority:          Optional[str]
    vehicle_number:             Optional[str]    # 마스킹됨
    demerit_points_base:        Optional[int]    # 범칙금 전용
    demerit_points_accumulated: Optional[int]    # 범칙금 전용
    charge_number:              Optional[str]
    court_venue:                Optional[str]    # ④ 즉결심판 전용
    missing_fields:             list

    # ── confidence_verification_node 출력 ────────────────────────────
    format_errors:              list
    unconfirmed_fields:         list[str]
    requires_confirmation:      bool

    # ── Supervisor 수신 ──────────────────────────────────────────────
    agent_results:              dict
