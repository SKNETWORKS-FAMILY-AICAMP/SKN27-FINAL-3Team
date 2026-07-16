"""Canonical fail-closed PII and secret masking policy."""

from __future__ import annotations

import re
from typing import Any


MASK_TOKEN = "[MASKED]"
MASKED_ADDRESS = MASK_TOKEN
MASKED_SECRET = MASK_TOKEN

SENSITIVE_FIELD_KEYS = {
    "address",
    "applicant_name",
    "contact_name",
    "display_name",
    "driver_license",
    "driver_license_number",
    "driver_name",
    "full_name",
    "home_address",
    "license_number",
    "mobile",
    "mobile_number",
    "name",
    "owner_address",
    "owner_name",
    "person_name",
    "phone",
    "phone_number",
    "plate_number",
    "recipient_name",
    "residence_address",
    "resident_id",
    "resident_registration_number",
    "rrn",
    "tel",
    "telephone",
    "vehicle_number",
}

SECRET_FIELD_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "client_secret",
    "cookie",
    "credential",
    "credentials",
    "id_token",
    "oauth_token",
    "openai_api_key",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "secret_key",
    "session_token",
    "set_cookie",
    "token",
    "x_api_key",
}

SECRET_FIELD_KEY_MARKERS = (
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)

SENSITIVE_CONTENT_FIELD_KEYS = {
    "completion",
    "error_detail",
    "error_message",
    "exception",
    "full_text",
    "model_response",
    "ocr_error",
    "ocr_raw",
    "ocr_text",
    "prompt",
    "provider_error",
    "raw_output",
    "raw_text",
    "reasoning",
    "transcript",
}

_RESIDENT_ID_PATTERN = re.compile(r"\b\d{6}\s*-\s*[1-8]\d{6}\b")
_DRIVER_LICENSE_PATTERN = re.compile(
    r"\b(?:[가-힣]{2}\s*)?\d{2}\s*[- ]?\s*\d{2}\s*[- ]?\s*\d{6}\s*[- ]?\s*\d{2}\b"
)
_MOBILE_PHONE_PATTERN = re.compile(r"\b01[016789]\s*[-.]?\s*\d{3,4}\s*[-.]?\s*\d{4}\b")
_LANDLINE_PHONE_PATTERN = re.compile(r"\b0\d{1,2}\s*[-.]?\s*\d{3,4}\s*[-.]?\s*\d{4}\b")
_VEHICLE_NUMBER_PATTERN = re.compile(
    r"\b(?:[가-힣]{2}\s*)?\d{2,3}\s*[가-힣]\s*\d{3,4}\b"
)
_DIPLOMATIC_VEHICLE_PATTERN = re.compile(r"\b외교\s*\d{5}\b")
_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b"
)
_NAME_LABEL_PATTERN = re.compile(
    r"((?:성명|이름|신청인|운전자|소유자)\s*[:=]\s*)"
    r"(?:[가-힣]{2,5}|[A-Za-z][A-Za-z .'-]{1,60})"
)
_ADDRESS_LABEL_PATTERN = re.compile(
    r"((?:주소|거주지|자택)\s*[:=]\s*)[^,;\r\n\"'{}\[\]]+"
)

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
)

TEXT_CATEGORY_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "secret": _SECRET_PATTERNS,
    "resident_id": (_RESIDENT_ID_PATTERN,),
    "driver_license": (_DRIVER_LICENSE_PATTERN,),
    "phone": (_MOBILE_PHONE_PATTERN, _LANDLINE_PHONE_PATTERN),
    "vehicle_number": (_VEHICLE_NUMBER_PATTERN, _DIPLOMATIC_VEHICLE_PATTERN),
    "email": (_EMAIL_PATTERN,),
    "name": (_NAME_LABEL_PATTERN,),
    "address": (_ADDRESS_LABEL_PATTERN,),
}


def mask_name(value: str | None) -> str | None:
    return _mask_nonempty(value)


def mask_phone(value: str | None) -> str | None:
    return _mask_nonempty(value)


def mask_vehicle_number(value: str | None) -> str | None:
    return _mask_nonempty(value)


def mask_address(value: str | None) -> str | None:
    return _mask_nonempty(value)


def mask_resident_id(value: str | None) -> str | None:
    return _mask_nonempty(value)


def mask_driver_license(value: str | None) -> str | None:
    return _mask_nonempty(value)


def mask_text(value: str) -> str:
    """Mask recognized PII and secret shapes inside otherwise useful text."""

    masked = value
    for pattern in _SECRET_PATTERNS:
        masked = pattern.sub(MASK_TOKEN, masked)
    for pattern in (
        _RESIDENT_ID_PATTERN,
        _DRIVER_LICENSE_PATTERN,
        _MOBILE_PHONE_PATTERN,
        _LANDLINE_PHONE_PATTERN,
        _VEHICLE_NUMBER_PATTERN,
        _DIPLOMATIC_VEHICLE_PATTERN,
        _EMAIL_PATTERN,
    ):
        masked = pattern.sub(MASK_TOKEN, masked)
    masked = _NAME_LABEL_PATTERN.sub(lambda match: f"{match.group(1)}{MASK_TOKEN}", masked)
    masked = _ADDRESS_LABEL_PATTERN.sub(
        lambda match: f"{match.group(1)}{MASK_TOKEN}",
        masked,
    )
    return masked


def detect_text_categories(value: str) -> dict[str, int]:
    """Return only sensitivity category counts, never matched source values."""

    counts: dict[str, int] = {}
    for category, patterns in TEXT_CATEGORY_PATTERNS.items():
        matched_spans = {
            match.span()
            for pattern in patterns
            for match in pattern.finditer(value)
        }
        if matched_spans:
            counts[category] = len(matched_spans)
    return counts


def sanitize_pii(value: Any) -> Any:
    """Return a recursively masked copy without mutating the caller's value."""

    return _sanitize_value(value, path="", masked_paths=None)


def mask_sensitive_fields(value: Any) -> tuple[Any, list[str]]:
    """Compatibility helper returning both the masked copy and changed paths."""

    masked_paths: list[str] = []
    masked = _sanitize_value(value, path="", masked_paths=masked_paths)
    return masked, masked_paths


def _sanitize_value(
    value: Any,
    *,
    path: str,
    masked_paths: list[str] | None,
) -> Any:
    if isinstance(value, dict):
        sanitized: dict[Any, Any] = {}
        for key, item in value.items():
            normalized_key = _normalize_key(key)
            item_path = _join_path(path, str(key))
            if _should_mask_whole_field(normalized_key, item):
                sanitized[key] = MASK_TOKEN
                _record_path(masked_paths, item_path)
            else:
                sanitized[key] = _sanitize_value(
                    item,
                    path=item_path,
                    masked_paths=masked_paths,
                )
        return sanitized
    if isinstance(value, list):
        return [
            _sanitize_value(
                item,
                path=f"{path}[{index}]",
                masked_paths=masked_paths,
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, tuple):
        return tuple(
            _sanitize_value(
                item,
                path=f"{path}[{index}]",
                masked_paths=masked_paths,
            )
            for index, item in enumerate(value)
        )
    if isinstance(value, str):
        masked = mask_text(value)
        if masked != value:
            _record_path(masked_paths, path)
        return masked
    return value


def _should_mask_whole_field(normalized_key: str, value: Any) -> bool:
    if value in (None, ""):
        return False
    return (
        normalized_key in SENSITIVE_FIELD_KEYS
        or normalized_key in SECRET_FIELD_KEYS
        or _contains_secret_field_marker(normalized_key)
        or normalized_key in SENSITIVE_CONTENT_FIELD_KEYS
    )


def _contains_secret_field_marker(normalized_key: str) -> bool:
    padded_key = f"_{normalized_key}_"
    return any(f"_{marker}_" in padded_key for marker in SECRET_FIELD_KEY_MARKERS)


def _mask_nonempty(value: str | None) -> str | None:
    if value in (None, ""):
        return value
    return MASK_TOKEN


def _record_path(masked_paths: list[str] | None, path: str) -> None:
    normalized_path = path or "$"
    if masked_paths is not None and normalized_path not in masked_paths:
        masked_paths.append(normalized_path)


def _join_path(parent: str, key: str) -> str:
    return f"{parent}.{key}" if parent else key


def _normalize_key(key: Any) -> str:
    text = str(key).strip()
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
