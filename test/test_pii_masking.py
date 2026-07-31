from __future__ import annotations

from copy import deepcopy
import json

import pytest

from ai.agents.fine_notice_analysis import masking as fine_notice_masking
from app.security.pii_masking import (
    MASK_TOKEN,
    MASKED_ADDRESS,
    MASKED_SECRET,
    detect_text_categories,
    mask_address,
    mask_driver_license,
    mask_name,
    mask_phone,
    mask_resident_id,
    mask_text,
    mask_vehicle_number,
    sanitize_pii,
)
from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr import (
    masking as traffic_confirmation_masking,
)


RAW_PII = {
    "name": "홍길동",
    "phone": "010-1234-5678",
    "vehicle": "12가3456",
    "address": "서울특별시 강남구 테헤란로 123 101동 1001호",
    "resident_id": "900101-1234567",
    "driver_license": "11-22-123456-78",
}


@pytest.mark.parametrize(
    ("value", "category", "raw_identifier"),
    (
        ("900101-1234567이고", "resident_id", "900101-1234567"),
        ("900101-1234567입니다", "resident_id", "900101-1234567"),
        ("(900101-1234567)", "resident_id", "900101-1234567"),
        ("11-22-333333-44입니다", "driver_license", "11-22-333333-44"),
    ),
)
def test_identity_numbers_are_detected_with_korean_context(
    value: str,
    category: str,
    raw_identifier: str,
) -> None:
    assert detect_text_categories(value)[category] == 1
    assert raw_identifier not in mask_text(value)


@pytest.mark.parametrize(
    "value",
    (
        "1900101-1234567",
        "900101-12345678",
        "111-22-333333-44",
        "11-22-333333-445",
    ),
)
def test_identity_number_patterns_do_not_partially_match_adjacent_digits(
    value: str,
) -> None:
    categories = detect_text_categories(value)

    assert "resident_id" not in categories
    assert "driver_license" not in categories
    assert mask_text(value) == value


def test_canonical_field_masking_rules() -> None:
    assert mask_name(RAW_PII["name"]) == MASK_TOKEN
    assert mask_phone(RAW_PII["phone"]) == MASK_TOKEN
    assert mask_vehicle_number(RAW_PII["vehicle"]) == MASK_TOKEN
    assert mask_address(RAW_PII["address"]) == MASKED_ADDRESS
    assert mask_resident_id(RAW_PII["resident_id"]) == MASK_TOKEN
    assert mask_driver_license(RAW_PII["driver_license"]) == MASK_TOKEN


def test_free_text_masking_removes_pii_and_secret_sentinels() -> None:
    raw = (
        "성명: 홍길동, 전화: 010-1234-5678, 차량: 12가3456, "
        "주소: 서울특별시 강남구 테헤란로 123, "
        "주민등록번호: 900101-1234567, 면허: 11-22-123456-78, "
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature"
    )

    masked = mask_text(raw)

    for value in RAW_PII.values():
        assert value not in masked
    assert "eyJhbGciOiJIUzI1NiJ9.payload.signature" not in masked
    assert MASK_TOKEN in masked
    assert MASKED_ADDRESS in masked
    assert MASKED_SECRET in masked


def test_recursive_sanitizer_masks_ocr_structured_error_and_secret_fields() -> None:
    raw_error = (
        "OCR failed for 홍길동 010-1234-5678 12가3456 "
        "900101-1234567 11-22-123456-78"
    )
    payload = {
        "ocr_raw": raw_error,
        "structured_result": {
            "applicant_name": RAW_PII["name"],
            "phone_number": RAW_PII["phone"],
            "vehicle_number": RAW_PII["vehicle"],
            "home_address": RAW_PII["address"],
            "resident_registration_number": RAW_PII["resident_id"],
            "driver_license_number": RAW_PII["driver_license"],
            "ocr_error": raw_error,
        },
        "access_token": "secret-access-token-value",
    }

    sanitized = sanitize_pii(payload)
    serialized = repr(sanitized)

    for value in [*RAW_PII.values(), "secret-access-token-value"]:
        assert value not in serialized
    assert sanitized["structured_result"]["applicant_name"] == MASK_TOKEN
    assert sanitized["structured_result"]["home_address"] == MASKED_ADDRESS
    assert sanitized["access_token"] == MASKED_SECRET


def test_recursive_sanitizer_is_idempotent_and_does_not_mutate_input() -> None:
    original = {
        "driver_name": RAW_PII["name"],
        "nested": [{"phone": RAW_PII["phone"]}],
    }
    snapshot = deepcopy(original)

    once = sanitize_pii(original)
    twice = sanitize_pii(once)

    assert original == snapshot
    assert once == twice
    assert once["driver_name"] == MASK_TOKEN


def test_legacy_ocr_masking_entrypoints_use_the_canonical_policy() -> None:
    raw = (
        "성명: 홍길동, 전화: 010-1234-5678, 차량: 12가3456, "
        "주소: 서울특별시 강남구 테헤란로 123 101동 1001호, "
        "주민등록번호: 900101-1234567, 면허: 11-22-123456-78"
    )

    fine_masked = fine_notice_masking.mask_personal_info(raw)
    traffic_masked = traffic_confirmation_masking.mask_sensitive_text(raw)
    structured, masked_paths = traffic_confirmation_masking.mask_sensitive_fields(
        {"driver_name": RAW_PII["name"], "vehicle_number": RAW_PII["vehicle"]}
    )

    assert fine_notice_masking.mask_field(RAW_PII["name"]) == MASK_TOKEN
    assert traffic_confirmation_masking.MASK_TOKEN == MASK_TOKEN
    for value in RAW_PII.values():
        assert value not in fine_masked
        assert value not in traffic_masked
    assert structured == {"driver_name": MASK_TOKEN, "vehicle_number": MASK_TOKEN}
    assert masked_paths == ["driver_name", "vehicle_number"]


def test_mask_text_preserves_valid_json_boundaries() -> None:
    raw_json = '{"raw":"주소: 서울특별시 강남구 테헤란로 123","x":1}'

    masked_json = mask_text(raw_json)

    assert json.loads(masked_json) == {"raw": f"주소: {MASK_TOKEN}", "x": 1}


def test_compact_and_legacy_pii_formats_are_masked() -> None:
    vectors = (
        "0212345678",
        "112212345678",
        "12나123",
        "외교12345",
    )

    for value in vectors:
        assert mask_text(value) == MASK_TOKEN
    assert mask_text("Authorization: Basic dXNlcjpwYXNzd29yZA==") == (
        f"Authorization: {MASK_TOKEN}"
    )


def test_camel_kebab_and_header_aliases_cannot_bypass_key_masking() -> None:
    sanitized = sanitize_pii(
        {
            "phoneNumber": RAW_PII["phone"],
            "driver-license-number": RAW_PII["driver_license"],
            "X-API-Key": "secret-api-key-value",
            "sessionToken": "secret-session-token-value",
            "set-cookie": "session=secret-cookie-value",
        }
    )

    assert set(sanitized.values()) == {MASK_TOKEN}


def test_guest_credential_is_masked_for_canonical_and_wsgi_header_keys() -> None:
    credential = "eyJhbGciOiJIUzI1NiJ9.guest-credential.signature"

    sanitized = sanitize_pii(
        {
            "guest_credential": credential,
            "HTTP_X_GUEST_CREDENTIAL": credential,
        }
    )

    assert sanitized == {
        "guest_credential": MASK_TOKEN,
        "HTTP_X_GUEST_CREDENTIAL": MASK_TOKEN,
    }


def test_root_scalar_masking_reports_a_changed_path() -> None:
    masked, masked_paths = traffic_confirmation_masking.mask_sensitive_fields(
        RAW_PII["phone"]
    )

    assert masked == MASK_TOKEN
    assert masked_paths == ["$"]
