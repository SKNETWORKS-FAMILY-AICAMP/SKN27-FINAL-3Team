from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.e2e_evidence_bundle_service import (
    EvidenceBundleValidationError,
    build_e2e_evidence_bundle,
    validate_e2e_evidence_bundle,
)


def _complete_bundle() -> dict[str, object]:
    return {
        "contract_version": "pilot_e2e_evidence.v1",
        "test_id": "ID-04-authenticated",
        "exact_input": "합성 고지서를 분석하고 확인이 필요한 항목을 알려주세요.",
        "executed_at": "2026-07-31T18:00:00+09:00",
        "account_type": "authenticated",
        "release": {
            "sha": "a" * 40,
            "frontend_image_digest": f"sha256:{'b' * 64}",
            "backend_image_digest": f"sha256:{'c' * 64}",
        },
        "browser_evidence": {
            "input_response_screenshot": "ID-04-authenticated-input-response.png",
        },
        "http": {
            "status_code": 200,
            "public_response": {
                "contract_version": "analysis_result.v2",
                "status": "partial",
            },
        },
        "execution": {
            "routing_intent": "fine_notice_analysis",
            "node_list": [
                "attachment_document_classification",
                "fine_notice_analysis",
            ],
            "semantic_status": "needs_input",
            "job_id": "job_e2e_04",
            "correlation_id": "awork_job_e2e_04",
        },
        "sanitized_logs": [
            {
                "event": "analysis_progress",
                "status": "needs_input",
            }
        ],
    }


def test_complete_synthetic_bundle_builds_the_exact_public_contract() -> None:
    source = _complete_bundle()

    bundle = build_e2e_evidence_bundle(source)

    assert bundle == source
    assert validate_e2e_evidence_bundle(bundle) == []


@pytest.mark.parametrize(
    "path",
    [
        "contract_version",
        "test_id",
        "exact_input",
        "executed_at",
        "account_type",
        "release.sha",
        "release.frontend_image_digest",
        "release.backend_image_digest",
        "browser_evidence.input_response_screenshot",
        "http.status_code",
        "http.public_response",
        "execution.routing_intent",
        "execution.node_list",
        "execution.semantic_status",
        "execution.job_id",
        "execution.correlation_id",
        "sanitized_logs",
    ],
)
def test_validation_reports_each_missing_required_field(path: str) -> None:
    payload = _complete_bundle()
    target = payload
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]  # type: ignore[index,assignment]
    del target[parts[-1]]  # type: ignore[index]

    assert f"missing:{path}" in validate_e2e_evidence_bundle(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("contract_version", "pilot_e2e_evidence.v0"),
        ("test_id", "scenario four"),
        ("executed_at", "July 31"),
        ("account_type", "root"),
        ("release.sha", "abc123"),
        ("release.frontend_image_digest", "latest"),
        ("release.backend_image_digest", "sha256:not-hex"),
        ("http.status_code", "200"),
        ("execution.routing_intent", "../private"),
        ("execution.node_list", ["valid_node", "../private"]),
        ("execution.semantic_status", "completed"),
        ("execution.job_id", "https://private.example/job"),
        ("execution.correlation_id", "C:\\private\\work"),
    ],
)
def test_validation_rejects_malformed_contract_fields(
    path: str,
    value: object,
) -> None:
    payload = _complete_bundle()
    target = payload
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]  # type: ignore[index,assignment]
    target[parts[-1]] = value  # type: ignore[index]

    assert f"invalid:{path}" in validate_e2e_evidence_bundle(payload)


@pytest.mark.parametrize(
    "reference",
    [
        "C:\\private\\screens\\e2e.png",
        "/var/private/e2e.png",
        "file:///private/e2e.png",
        "s3://private-bucket/e2e.png",
        "https://storage.example/e2e.png?X-Amz-Signature=secret",
    ],
)
def test_screenshot_reference_must_be_a_relative_artifact_name(
    reference: str,
) -> None:
    payload = _complete_bundle()
    payload["browser_evidence"]["input_response_screenshot"] = reference  # type: ignore[index]

    errors = validate_e2e_evidence_bundle(payload)

    assert "unsafe:browser_evidence.input_response_screenshot" in errors
    assert reference not in repr(errors)


def test_builder_masks_pii_and_credential_fields_without_mutating_source() -> None:
    payload = _complete_bundle()
    payload["exact_input"] = "주민번호 900101-1234567, 전화 010-1234-5678"
    payload["http"]["public_response"] = {  # type: ignore[index]
        "access_token": "secret-access-token",
        "message": "연락처 010-9876-5432",
    }
    payload["sanitized_logs"] = [
        {
            "event": "safe",
            "password": "synthetic-password",
        }
    ]
    original = deepcopy(payload)

    bundle = build_e2e_evidence_bundle(payload)

    assert payload == original
    serialized = repr(bundle)
    for private_value in (
        "900101-1234567",
        "010-1234-5678",
        "secret-access-token",
        "010-9876-5432",
        "synthetic-password",
    ):
        assert private_value not in serialized
    assert "[MASKED]" in serialized
    assert validate_e2e_evidence_bundle(bundle) == []


@pytest.mark.parametrize(
    ("path", "unsafe_value", "expected_error"),
    [
        (
            "http.public_response",
            {"storage_uri": "s3://private-bucket/raw.json"},
            "unsafe:http.public_response",
        ),
        (
            "http.public_response",
            {"report_url": "https://storage.example/report?sig=secret"},
            "unsafe:http.public_response",
        ),
        (
            "sanitized_logs",
            [{"Authorization": "Bearer synthetic-secret"}],
            "unsafe:sanitized_logs",
        ),
        (
            "sanitized_logs",
            [{"raw_ocr_text": "private OCR content"}],
            "unsafe:sanitized_logs",
        ),
    ],
)
def test_builder_rejects_unsafe_evidence_without_echoing_values(
    path: str,
    unsafe_value: object,
    expected_error: str,
) -> None:
    payload = _complete_bundle()
    target = payload
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]  # type: ignore[index,assignment]
    target[parts[-1]] = unsafe_value  # type: ignore[index]

    with pytest.raises(EvidenceBundleValidationError) as raised:
        build_e2e_evidence_bundle(payload)

    assert expected_error in raised.value.errors
    assert repr(unsafe_value) not in str(raised.value)


def test_validator_rejects_unapproved_fields_without_echoing_them() -> None:
    payload = _complete_bundle()
    payload["private_debug_payload"] = "synthetic-secret"
    payload["http"]["internal_trace"] = "private traceback"  # type: ignore[index]

    errors = validate_e2e_evidence_bundle(payload)

    assert "unexpected:top_level" in errors
    assert "unexpected:http" in errors
    assert "private_debug_payload" not in repr(errors)
    assert "synthetic-secret" not in repr(errors)
    assert "internal_trace" not in repr(errors)
    assert "private traceback" not in repr(errors)


@pytest.mark.parametrize(
    "unsafe_input",
    [
        "첨부 위치 C:\\private\\evidence.png",
        "확인 링크 https://storage.example/evidence?sig=synthetic-secret",
    ],
)
def test_builder_rejects_unsafe_exact_input_without_echoing_it(
    unsafe_input: str,
) -> None:
    payload = _complete_bundle()
    payload["exact_input"] = unsafe_input

    with pytest.raises(EvidenceBundleValidationError) as raised:
        build_e2e_evidence_bundle(payload)

    assert "unsafe:exact_input" in raised.value.errors
    assert unsafe_input not in str(raised.value)
