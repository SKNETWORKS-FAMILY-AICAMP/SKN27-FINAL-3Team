"""Server-owned intake contract for fine-notice consultations."""

from __future__ import annotations

from typing import Any, Mapping


FINE_NOTICE_REQUIRED_SLOTS = (
    "document_disposition_type",
    "issuing_authority",
    "response_deadline",
    "attachment_available",
)

FINE_NOTICE_QUESTIONS = {
    "document_disposition_type": "받은 문서의 이름 또는 처분 유형을 알려주세요.",
    "issuing_authority": "고지서를 발급한 기관을 알려주세요.",
    "response_deadline": "고지서에 적힌 의견제출 또는 이의신청 기한을 알려주세요.",
    "attachment_available": "고지서 사진이나 파일을 첨부할 수 있나요?",
}


def reduce_fine_notice_intake(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the required fine-notice slots without inferring missing facts."""

    source_message_id = str(
        payload.get("message_id") or payload.get("session_id") or "current"
    ).strip()
    explicit = payload.get("fine_notice_slots")
    explicit = explicit if isinstance(explicit, Mapping) else {}
    slots: dict[str, dict[str, Any]] = {}
    for field in FINE_NOTICE_REQUIRED_SLOTS:
        value = _slot_value(field, explicit.get(field))
        if value is None:
            continue
        slots[field] = _slot_record(
            value,
            source_type="user_structured_input",
            source_message_id=source_message_id,
        )

    confirmation = payload.get("ocr_confirmation")
    confirmation = confirmation if isinstance(confirmation, Mapping) else {}
    confirmed_fields = confirmation.get("fields")
    confirmed_fields = (
        confirmed_fields
        if confirmation.get("confirmed") is True
        and isinstance(confirmed_fields, Mapping)
        else {}
    )
    for field in FINE_NOTICE_REQUIRED_SLOTS[:-1]:
        if field in slots:
            continue
        value = _slot_value(field, confirmed_fields.get(field))
        if value is None:
            continue
        slots[field] = _slot_record(
            value,
            source_type="user_confirmed_ocr",
            source_message_id=source_message_id,
        )

    if "attachment_available" not in slots and any(
        isinstance(item, Mapping)
        and str(item.get("attachment_id") or "").strip()
        for item in payload.get("attachments") or []
    ):
        slots["attachment_available"] = _slot_record(
            True,
            source_type="server_attachment",
            source_message_id=source_message_id,
        )

    question_to_field = {
        question: field for field, question in FINE_NOTICE_QUESTIONS.items()
    }
    pending_field = ""
    for index, turn in enumerate(payload.get("conversation_history") or []):
        if not isinstance(turn, Mapping):
            continue
        role = str(turn.get("role") or "").strip()
        content = str(turn.get("content") or "").strip()
        if role == "assistant":
            pending_field = question_to_field.get(content, "")
            continue
        if role != "user" or not pending_field or pending_field in slots:
            continue
        value = _slot_value(pending_field, content)
        if value is not None:
            slots[pending_field] = _slot_record(
                value,
                source_type="user_confirmation",
                source_message_id=str(
                    turn.get("message_id") or f"history:{index}"
                ),
            )
        pending_field = ""

    missing_fields = [
        field for field in FINE_NOTICE_REQUIRED_SLOTS if field not in slots
    ]
    return {
        "contract_version": "fine_notice_intake.v1",
        "slots": slots,
        "missing_fields": missing_fields,
        "next_questions": [
            {"field": field, "question": FINE_NOTICE_QUESTIONS[field]}
            for field in missing_fields
        ],
    }


def _slot_value(field: str, value: Any) -> str | bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip()
    if not normalized or "모르" in normalized:
        return None
    if field != "attachment_available":
        return normalized
    lowered = normalized.lower()
    if lowered in {"yes", "y", "예", "네", "가능", "있음"}:
        return True
    if lowered in {"no", "n", "아니오", "아니요", "불가", "없음"}:
        return False
    return None


def _slot_record(
    value: str | bool,
    *,
    source_type: str,
    source_message_id: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "source_type": source_type,
        "source_message_id": source_message_id,
        "confidence": 1.0,
        "confirmed": True,
    }
