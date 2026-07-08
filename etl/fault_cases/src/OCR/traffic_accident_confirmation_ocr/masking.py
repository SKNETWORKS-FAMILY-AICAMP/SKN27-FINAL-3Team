from __future__ import annotations

import copy
import re
from typing import Any


MASK_TOKEN = "[MASKED]"

SENSITIVE_FIELD_KEYS = {
    "name",
    "person_name",
    "owner_name",
    "driver_name",
    "resident_registration_number",
    "rrn",
    "driver_license_number",
    "phone",
    "phone_number",
    "mobile_number",
    "tel",
    "address",
    "home_address",
    "residence_address",
    "owner_address",
    "vehicle_number",
    "plate_number",
}

ALLOWED_LOCATION_KEYS = {"accident_location"}

SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("resident_registration_number", re.compile(r"\b\d{6}\s*-\s*[1-4]\d{6}\b")),
    ("phone_number", re.compile(r"\b01[016789]\s*[-.]?\s*\d{3,4}\s*[-.]?\s*\d{4}\b")),
    ("phone_number", re.compile(r"\b0\d{1,2}\s*[-.]?\s*\d{3,4}\s*[-.]?\s*\d{4}\b")),
    ("driver_license_number", re.compile(r"\b\d{2}\s*[- ]?\s*\d{2}\s*[- ]?\s*\d{6}\s*[- ]?\s*\d{2}\b")),
    ("vehicle_number", re.compile(r"\b\d{2,3}\s*[가-힣]\s*\d{4}\b")),
    ("vehicle_number", re.compile(r"\b[가-힣]{2}\s*\d{2}\s*[가-힣]\s*\d{4}\b")),
)


def mask_sensitive_text(text: str) -> str:
    masked = text
    for _, pattern in SENSITIVE_PATTERNS:
        masked = pattern.sub(MASK_TOKEN, masked)
    return masked


def mask_sensitive_fields(value: Any) -> tuple[Any, list[str]]:
    copied = copy.deepcopy(value)
    masked_fields: list[str] = []
    masked_value = _mask_value(copied, path="", masked_fields=masked_fields)
    return masked_value, masked_fields


def _mask_value(value: Any, path: str, masked_fields: list[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: _mask_dict_item(key, item, _join_path(path, key), masked_fields)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            _mask_value(item, f"{path}[{index}]", masked_fields)
            for index, item in enumerate(value)
        ]

    if isinstance(value, str):
        masked = mask_sensitive_text(value)
        if masked != value:
            masked_fields.append(path)
        return masked

    return value


def _mask_dict_item(key: str, value: Any, path: str, masked_fields: list[str]) -> Any:
    normalized_key = key.lower()

    if normalized_key in ALLOWED_LOCATION_KEYS:
        return _mask_value(value, path, masked_fields)

    if normalized_key in SENSITIVE_FIELD_KEYS and value not in (None, ""):
        masked_fields.append(path)
        return MASK_TOKEN

    return _mask_value(value, path, masked_fields)


def _join_path(parent: str, key: str) -> str:
    if not parent:
        return key
    return f"{parent}.{key}"
