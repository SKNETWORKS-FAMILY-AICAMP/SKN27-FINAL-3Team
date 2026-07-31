"""Deterministic pre-routing understanding gate for public chat input."""

from __future__ import annotations

import re
from typing import Any

from app.security.pii_masking import detect_text_categories


CONTRACT_VERSION = "input_understanding_gate.v1"
ALLOWED_STATUSES = frozenset(
    {"accepted", "needs_clarification", "blocked_sensitive", "out_of_scope"}
)
CLARIFICATION_MESSAGE = (
    "문의 내용을 이해하기 어렵습니다. 과태료 고지서, 교통사고, 교통 법령 중 "
    "어떤 문제인지 한두 문장으로 다시 입력해 주세요."
)

_PROFANITY_PATTERN = re.compile(
    r"(?i)(?:씨+\s*발+|시+\s*발+|개\s*소리(?:야|냐|네|다)?|"
    r"ㅅ\s*ㅂ|fuck(?:ing)?|shit)"
)
_DOMAIN_SIGNALS = (
    "과태료",
    "고지서",
    "범칙금",
    "의견제출",
    "이의신청",
    "단속",
    "정차",
    "사고",
    "충돌",
    "추돌",
    "접촉",
    "과실",
    "블랙박스",
    "법령",
    "조문",
    "도로교통법",
    "법적 근거",
    "보행자",
    "횡단보도",
)
_OUT_OF_SCOPE_SIGNALS = ("상속", "이혼", "부동산 분쟁")
_LOW_INFORMATION_TERMS = frozenset(
    {"help", "test", "testing", "asdf", "qwer", "unknown"}
)
_BLOCKED_SENSITIVE_CATEGORIES = frozenset(
    {"secret", "resident_id", "driver_license"}
)


def evaluate_input_understanding(
    *,
    user_text: str,
    attachments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify whether input is safe and meaningful enough for routing."""

    text = str(user_text or "").strip()
    categories = detect_text_categories(text)
    blocked_categories = sorted(
        category
        for category in categories
        if category in _BLOCKED_SENSITIVE_CATEGORIES
    )
    if blocked_categories:
        return _decision(
            status="blocked_sensitive",
            safe_user_text="",
            reason_code="sensitive_input_detected",
            message="민감정보를 제거한 뒤 다시 입력해 주세요.",
            noise_removed=False,
            sensitive_categories=blocked_categories,
        )

    cleaned_text, noise_removed = _remove_profanity(text)
    normalized = cleaned_text.lower()
    if any(signal in normalized for signal in _OUT_OF_SCOPE_SIGNALS):
        return _decision(
            status="out_of_scope",
            safe_user_text=cleaned_text,
            reason_code="explicit_non_traffic_domain",
            message="현재 서비스의 교통분쟁 지원 범위를 벗어난 문의입니다.",
            noise_removed=noise_removed,
        )

    has_domain_signal = any(signal in normalized for signal in _DOMAIN_SIGNALS)
    needs_clarification = (
        not attachments
        and (
            not cleaned_text
            or _is_compatibility_jamo_only(cleaned_text)
            or normalized in _LOW_INFORMATION_TERMS
            or (noise_removed and not has_domain_signal)
            or (not has_domain_signal and not _has_meaningful_token(cleaned_text))
        )
    )
    if needs_clarification:
        return _decision(
            status="needs_clarification",
            safe_user_text="",
            reason_code="insufficient_meaning",
            message=CLARIFICATION_MESSAGE,
            noise_removed=noise_removed,
        )

    return _decision(
        status="accepted",
        safe_user_text=cleaned_text,
        reason_code=(
            "domain_signal_with_noise_removed"
            if noise_removed
            else "meaningful_input"
        ),
        message="입력 이해도 검증을 통과했습니다.",
        noise_removed=noise_removed,
    )


def _decision(
    *,
    status: str,
    safe_user_text: str,
    reason_code: str,
    message: str,
    noise_removed: bool,
    sensitive_categories: list[str] | None = None,
) -> dict[str, Any]:
    if status not in ALLOWED_STATUSES:
        raise ValueError("unsupported_input_understanding_status")
    public_metadata = {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "reason_code": reason_code,
        "noise_removed": noise_removed,
        "sensitive_categories": list(sensitive_categories or []),
    }
    return {
        **public_metadata,
        "safe_user_text": safe_user_text,
        "message": message,
        "public_metadata": public_metadata,
    }


def _remove_profanity(value: str) -> tuple[str, bool]:
    cleaned, count = _PROFANITY_PATTERN.subn(" ", value)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([?.!,])", r"\1", cleaned).strip()
    return cleaned, count > 0


def _is_compatibility_jamo_only(value: str) -> bool:
    tokens = re.findall(r"[가-힣A-Za-z0-9\u3131-\u318E]+", value)
    compact = "".join(tokens)
    return bool(compact) and all("\u3131" <= char <= "\u318e" for char in compact)


def _has_meaningful_token(value: str) -> bool:
    return bool(re.search(r"[가-힣]{2,}|[A-Za-z]{3,}|\d{2,}", value))
