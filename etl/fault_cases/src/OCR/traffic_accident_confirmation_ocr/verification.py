from __future__ import annotations

from typing import Any

from .constants import (
    DOCUMENT_TYPE_TRAFFIC_ACCIDENT_CONFIRMATION,
    DOCUMENT_TYPE_UNKNOWN,
    FAILURE_REASON_NOT_TARGET_DOCUMENT,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_SUCCESS,
)
from .state import TrafficAccidentConfirmationOCRState
from .utils import make_envelope, update_agent_results


ACCIDENT_LABELS = {
    "발생일시",
    "발생장소",
    "사고유형",
    "사고원인",
    "피해내용",
    "사고내용",
}

ISSUER_LABELS = {
    "교통사고 접수번호",
    "발급번호",
    "경찰서",
    "용도",
    "담당자",
    "경찰서장",
}


def document_verification_node(state: TrafficAccidentConfirmationOCRState) -> dict[str, Any]:
    if state.get("ocr_status") == STATUS_FAILED:
        return {}

    document_check = verify_document(
        document_name=(state.get("document_check") or {}).get("document_name"),
        detected_labels=_extract_detected_labels(state),
        issuer_labels=_extract_issuer_labels(state),
    )

    current_status = state.get("ocr_status") or STATUS_PARTIAL
    format_errors = list(state.get("format_errors") or [])
    missing_fields = list(state.get("missing_fields") or [])
    limitations = list(state.get("limitations") or [])
    failure_reason = state.get("failure_reason")

    if not document_check["is_target_document"]:
        next_status = STATUS_FAILED
        failure_reason = FAILURE_REASON_NOT_TARGET_DOCUMENT
        limitations.append("문서 검증 점수가 기준 미만입니다.")
    elif not document_check["verification_criteria"]["title_matched"]:
        next_status = STATUS_PARTIAL
        limitations.append("문서 제목이 확인되지 않아 partial로 유지합니다.")
    elif format_errors or missing_fields:
        next_status = STATUS_PARTIAL
    else:
        next_status = STATUS_SUCCESS if current_status == STATUS_SUCCESS else current_status

    document_type = (
        DOCUMENT_TYPE_TRAFFIC_ACCIDENT_CONFIRMATION
        if document_check["is_target_document"]
        else DOCUMENT_TYPE_UNKNOWN
    )
    structured = {
        "document_check": document_check,
        "page_info": state.get("page_info") or {},
        "scene_diagram": state.get("scene_diagram") or {},
        "quality": state.get("quality") or {},
        "privacy": state.get("privacy") or {},
        "extracted_fields": state.get("extracted_fields") or {},
        "raw_text_redacted": state.get("raw_text_redacted"),
    }
    summary = _build_verification_summary(next_status, document_check)
    envelope = make_envelope(
        status=next_status,
        structured=structured,
        missing=missing_fields,
        next_actions=_build_next_actions(next_status, document_check, missing_fields),
        summary=summary,
        limitations=limitations,
        failure_reason=failure_reason,
        message=summary,
    )

    return {
        "ocr_status": next_status,
        "document_type": document_type,
        "failure_reason": failure_reason,
        "document_check": document_check,
        "limitations": limitations,
        "agent_results": update_agent_results(state, envelope),
    }


def verify_document(
    document_name: str | None,
    detected_labels: list[str],
    issuer_labels: list[str],
) -> dict[str, Any]:
    title_matched = bool(document_name and "교통사고사실확인원" in document_name)
    accident_count = _count_matched_labels(detected_labels, ACCIDENT_LABELS)
    issuer_count = _count_matched_labels(issuer_labels, ISSUER_LABELS)
    score = int(title_matched) + int(accident_count >= 4) + int(issuer_count >= 2)

    return {
        "is_target_document": score >= 2,
        "document_name": document_name,
        "reason": _build_reason(title_matched, accident_count, issuer_count, score),
        "verification_score": score,
        "verification_criteria": {
            "title_matched": title_matched,
            "accident_labels_matched_count": accident_count,
            "issuer_structure_matched_count": issuer_count,
        },
    }


def _extract_detected_labels(state: TrafficAccidentConfirmationOCRState) -> list[str]:
    model_response = state.get("model_response") or {}
    labels = model_response.get("detected_labels") or []
    return labels if isinstance(labels, list) else []


def _extract_issuer_labels(state: TrafficAccidentConfirmationOCRState) -> list[str]:
    model_response = state.get("model_response") or {}
    labels = model_response.get("issuer_labels") or []
    return labels if isinstance(labels, list) else []


def _count_matched_labels(labels: list[str], expected_labels: set[str]) -> int:
    matched = set()
    for label in labels:
        text = str(label)
        for expected in expected_labels:
            if expected in text:
                matched.add(expected)
    return len(matched)


def _build_reason(title_matched: bool, accident_count: int, issuer_count: int, score: int) -> str:
    return (
        f"제목 일치: {title_matched}, "
        f"사고 라벨 일치 수: {accident_count}, "
        f"발급 구조 라벨 일치 수: {issuer_count}, "
        f"총점: {score}/3"
    )


def _build_verification_summary(status: str, document_check: dict[str, Any]) -> str:
    score = document_check.get("verification_score")
    if status == STATUS_FAILED:
        return f"교통사고사실확인원 문서 검증에 실패했습니다. 검증 점수: {score}/3"
    if status == STATUS_PARTIAL:
        return f"교통사고사실확인원으로 보이나 일부 확인이 필요합니다. 검증 점수: {score}/3"
    return f"교통사고사실확인원 문서 검증을 통과했습니다. 검증 점수: {score}/3"


def _build_next_actions(
    status: str,
    document_check: dict[str, Any],
    missing_fields: list[str],
) -> list[str]:
    if status == STATUS_FAILED:
        return ["교통사고사실확인원 1page 이미지를 다시 업로드해 주세요."]
    if not document_check["verification_criteria"]["title_matched"]:
        return ["문서 제목이 보이도록 다시 촬영하거나 교통사고사실확인원 1page가 맞는지 확인해 주세요."]
    if missing_fields:
        return ["누락된 항목을 사용자에게 추가 질문하거나 더 선명한 이미지를 요청하세요."]
    return ["과실비율 분석 Agent로 전달 가능합니다."]

