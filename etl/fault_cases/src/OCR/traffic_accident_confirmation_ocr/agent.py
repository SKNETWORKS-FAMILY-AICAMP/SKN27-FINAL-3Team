from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any

from .constants import (
    DOCUMENT_TYPE_TRAFFIC_ACCIDENT_CONFIRMATION,
    DOCUMENT_TYPE_UNKNOWN,
    FAILURE_REASON_INVALID_IMAGE_PAYLOAD,
    FAILURE_REASON_OCR_FAILED,
    FAILURE_REASON_UNSUPPORTED_FILE_TYPE,
    IMAGE_QUALITY_UNKNOWN,
    SCENE_DIAGRAM_DEFERRED,
    STATUS_FAILED,
)
from .evaluator import evaluate_ocr_result
from .masking import mask_sensitive_fields
from .prompts import TRAFFIC_ACCIDENT_CONFIRMATION_OCR_PROMPT, get_ocr_model_name
from .state import TrafficAccidentConfirmationOCRState
from .utils import make_envelope, save_ocr_output, update_agent_results


ALLOWED_MIME_TYPES = {"image/jpeg", "image/png"}
DEFAULT_NEXT_ACTIONS = ["교통사고사실확인원 1page jpg/png 이미지를 다시 업로드해 주세요."]


def ocr_node(state: TrafficAccidentConfirmationOCRState) -> dict[str, Any]:
    document_image = state.get("document_image")
    document_mime_type = state.get("document_mime_type")
    source_filename = state.get("source_filename")

    if document_mime_type not in ALLOWED_MIME_TYPES:
        return _failed_result(
            state=state,
            failure_reason=FAILURE_REASON_UNSUPPORTED_FILE_TYPE,
            message="지원하지 않는 파일 형식입니다. jpg 또는 png 이미지를 업로드해 주세요.",
            source_filename=source_filename,
        )

    if not document_image:
        return _failed_result(
            state=state,
            failure_reason=FAILURE_REASON_INVALID_IMAGE_PAYLOAD,
            message="이미지 데이터가 없습니다. 교통사고사실확인원 1page 이미지를 다시 업로드해 주세요.",
            source_filename=source_filename,
        )

    try:
        cleaned_image = _clean_base64(document_image)
        _validate_base64_image(cleaned_image)
    except (binascii.Error, ValueError):
        return _failed_result(
            state=state,
            failure_reason=FAILURE_REASON_INVALID_IMAGE_PAYLOAD,
            message="이미지 base64를 디코딩할 수 없습니다. 원본 이미지를 다시 업로드해 주세요.",
            source_filename=source_filename,
        )

    try:
        model_response = _call_gpt_vision(cleaned_image, document_mime_type)
    except Exception as exc:
        return _failed_result(
            state=state,
            failure_reason=FAILURE_REASON_OCR_FAILED,
            message="OCR 모델 호출 또는 응답 파싱에 실패했습니다.",
            source_filename=source_filename,
            limitations=[str(exc)],
        )

    masked_response, masked_fields = mask_sensitive_fields(model_response)
    extracted_fields = _normalize_extracted_fields(masked_response.get("extracted_fields"))
    document_check = _build_initial_document_check(masked_response)
    format_errors = _validate_model_payload(masked_response)
    evaluation = evaluate_ocr_result(extracted_fields, document_check, format_errors)

    structured = {
        "document_check": document_check,
        "page_info": _normalize_page_info(masked_response.get("page_info")),
        "scene_diagram": {
            "page_2_exists": bool((masked_response.get("page_info") or {}).get("page_2_exists")),
            "analysis_status": SCENE_DIAGRAM_DEFERRED,
            "reason": "MVP에서는 사고현장약도/2page 분석을 수행하지 않습니다.",
            "raw_image_ref": None,
        },
        "quality": _normalize_quality(masked_response.get("quality")),
        "privacy": {
            "masking_applied": bool(masked_fields),
            "excluded_sensitive_fields": [
                "name",
                "resident_registration_number",
                "driver_license_number",
                "phone_number",
                "home_address",
                "owner_address",
                "owner_name",
                "vehicle_number",
            ],
            "masked_fields": masked_fields,
        },
        "extracted_fields": extracted_fields,
        "raw_text_redacted": masked_response.get("raw_text_redacted"),
    }

    status = evaluation["status"]
    missing_fields = evaluation["missing_fields"]
    limitations = _merge_unique(masked_response.get("limitations") or [], evaluation["limitations"])
    next_actions = _build_next_actions(status, missing_fields, evaluation.get("failure_reason"))
    summary = _build_summary(status, missing_fields)

    envelope = make_envelope(
        status=status,
        structured=structured,
        missing=missing_fields,
        next_actions=next_actions,
        summary=summary,
        limitations=limitations,
        failure_reason=evaluation.get("failure_reason"),
        message=summary,
    )
    saved_output_path = save_ocr_output(envelope, source_filename=source_filename)

    return {
        "document_image": None,
        "ocr_status": status,
        "document_type": (
            DOCUMENT_TYPE_TRAFFIC_ACCIDENT_CONFIRMATION
            if document_check.get("is_target_document")
            else DOCUMENT_TYPE_UNKNOWN
        ),
        "failure_reason": evaluation.get("failure_reason"),
        "ocr_error": None,
        "raw_text_redacted": structured["raw_text_redacted"],
        "extracted_fields": extracted_fields,
        "document_check": document_check,
        "page_info": structured["page_info"],
        "scene_diagram": structured["scene_diagram"],
        "quality": structured["quality"],
        "privacy": structured["privacy"],
        "missing_fields": missing_fields,
        "limitations": limitations,
        "format_errors": format_errors,
        "model_response": masked_response,
        "saved_output_path": saved_output_path,
        "agent_results": update_agent_results(state, envelope),
    }


def _failed_result(
    state: TrafficAccidentConfirmationOCRState,
    failure_reason: str,
    message: str,
    source_filename: str | None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    structured = {
        "document_check": {
            "is_target_document": False,
            "document_name": None,
            "reason": message,
            "verification_score": 0,
            "verification_criteria": {
                "title_matched": False,
                "accident_labels_matched_count": 0,
                "issuer_structure_matched_count": 0,
            },
        },
        "extracted_fields": {},
    }
    envelope = make_envelope(
        status=STATUS_FAILED,
        structured=structured,
        missing=[],
        next_actions=DEFAULT_NEXT_ACTIONS,
        summary=message,
        limitations=limitations or [],
        failure_reason=failure_reason,
        message=message,
    )
    saved_output_path = save_ocr_output(envelope, source_filename=source_filename)
    return {
        "document_image": None,
        "ocr_status": STATUS_FAILED,
        "document_type": DOCUMENT_TYPE_UNKNOWN,
        "failure_reason": failure_reason,
        "ocr_error": message,
        "missing_fields": [],
        "limitations": limitations or [],
        "saved_output_path": saved_output_path,
        "agent_results": update_agent_results(state, envelope),
    }


def _call_gpt_vision(base64_image: str, mime_type: str) -> dict[str, Any]:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    from openai import OpenAI

    client = OpenAI()
    response = client.chat.completions.create(
        model=get_ocr_model_name(),
        max_tokens=1600,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": TRAFFIC_ACCIDENT_CONFIRMATION_OCR_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{base64_image}"},
                    },
                ],
            }
        ],
    )
    raw_content = response.choices[0].message.content or ""
    return _parse_json_response(raw_content)


def _parse_json_response(raw_content: str) -> dict[str, Any]:
    cleaned = raw_content.strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group())

    if not isinstance(parsed, dict):
        raise ValueError("OCR response must be a JSON object.")
    return parsed


def _clean_base64(document_image: str) -> str:
    cleaned = document_image.strip()
    if "," in cleaned and cleaned.lower().startswith("data:"):
        cleaned = cleaned.split(",", 1)[1]
    return cleaned.replace("\n", "").replace("\r", "")


def _validate_base64_image(base64_image: str) -> bytes:
    return base64.b64decode(base64_image, validate=True)


def _build_initial_document_check(model_response: dict[str, Any]) -> dict[str, Any]:
    document_name = model_response.get("document_name")
    detected_labels = model_response.get("detected_labels") or []
    issuer_labels = model_response.get("issuer_labels") or []

    title_matched = bool(document_name and "교통사고사실확인원" in str(document_name))
    accident_count = len([label for label in detected_labels if label])
    issuer_count = len([label for label in issuer_labels if label])
    score = int(title_matched) + int(accident_count >= 4) + int(issuer_count >= 2)

    return {
        "is_target_document": score >= 2,
        "document_name": document_name,
        "reason": "초기 OCR 응답 기준 문서 판정입니다. verification.py에서 최종 검증합니다.",
        "verification_score": score,
        "verification_criteria": {
            "title_matched": title_matched,
            "accident_labels_matched_count": accident_count,
            "issuer_structure_matched_count": issuer_count,
        },
    }


def _normalize_extracted_fields(value: Any) -> dict[str, Any]:
    fields = value if isinstance(value, dict) else {}
    return {
        "receipt_number": fields.get("receipt_number"),
        "issue_number": fields.get("issue_number"),
        "police_station": fields.get("police_station"),
        "accident_datetime": fields.get("accident_datetime"),
        "accident_location": fields.get("accident_location"),
        "accident_type": _normalize_accident_type(fields.get("accident_type")),
        "accident_cause": fields.get("accident_cause"),
        "damage": _normalize_damage(fields.get("damage")),
        "accident_description": fields.get("accident_description"),
        "usage": fields.get("usage"),
    }


def _normalize_accident_type(value: Any) -> dict[str, Any]:
    accident_type = value if isinstance(value, dict) else {}
    return {
        "value": accident_type.get("value"),
        "raw_text": accident_type.get("raw_text"),
    }


def _normalize_damage(value: Any) -> dict[str, Any]:
    damage = value if isinstance(value, dict) else {}
    return {
        "raw_text": damage.get("raw_text"),
        "death_count": _parse_optional_int(damage.get("death_count")),
        "injury_count": _parse_optional_int(damage.get("injury_count")),
        "property_damage_amount": _parse_optional_int(damage.get("property_damage_amount")),
    }


def _normalize_page_info(value: Any) -> dict[str, bool]:
    page_info = value if isinstance(value, dict) else {}
    return {
        "page_1_processed": bool(page_info.get("page_1_processed", True)),
        "page_2_exists": bool(page_info.get("page_2_exists", False)),
    }


def _normalize_quality(value: Any) -> dict[str, Any]:
    quality = value if isinstance(value, dict) else {}
    warnings = quality.get("warnings")
    return {
        "ocr_confidence": quality.get("ocr_confidence"),
        "image_quality": quality.get("image_quality") or IMAGE_QUALITY_UNKNOWN,
        "warnings": warnings if isinstance(warnings, list) else [],
    }


def _validate_model_payload(model_response: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(model_response.get("extracted_fields"), dict):
        errors.append("missing extracted_fields object")
    if not isinstance(model_response.get("detected_labels", []), list):
        errors.append("detected_labels must be a list")
    if not isinstance(model_response.get("issuer_labels", []), list):
        errors.append("issuer_labels must be a list")
    return errors


def _parse_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def _build_next_actions(
    status: str,
    missing_fields: list[str],
    failure_reason: str | None,
) -> list[str]:
    if status == STATUS_FAILED:
        if failure_reason == FAILURE_REASON_OCR_FAILED:
            return ["이미지를 다시 업로드하거나 잠시 후 OCR을 재시도해 주세요."]
        return DEFAULT_NEXT_ACTIONS
    if missing_fields:
        return ["누락된 항목을 사용자에게 추가 질문하거나 더 선명한 1page 이미지를 재업로드 요청하세요."]
    return ["과실비율 분석 Agent로 전달 가능합니다."]


def _build_summary(status: str, missing_fields: list[str]) -> str:
    if status == STATUS_FAILED:
        return "교통사고사실확인원 OCR 처리를 완료하지 못했습니다."
    if missing_fields:
        return "교통사고사실확인원 OCR은 완료되었지만 일부 항목이 누락되었습니다."
    return "교통사고사실확인원 OCR 처리가 완료되었습니다."


def _merge_unique(*items: list[str]) -> list[str]:
    merged: list[str] = []
    for item in items:
        for value in item:
            if value and value not in merged:
                merged.append(value)
    return merged

