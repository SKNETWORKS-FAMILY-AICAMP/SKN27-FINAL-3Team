from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.contracts.report import (
    ReportApiErrorResponse,
    ReportContent,
    ReportListResponse,
    ReportMetadata,
    ReportReportingPayload,
)
from app.services.report_query_service import (
    compose_report_error_response,
    compose_report_detail_response,
    compose_report_list_response,
    report_api_surface,
    report_execution_mode,
)


def _report_record(report_id: str = "rep_123") -> dict[str, object]:
    return {
        "report_id": report_id,
        "source": "analysis_worker_reporting",
        "report_type": "fault_ratio_analysis",
        "screen_id": "UI-REPORT-FAULT-001",
        "title": "Owner report",
        "status": "ready",
        "session_id": "ses_123",
        "job_id": "job_123",
        "summary": "Safe summary",
        "download_url": f"/api/reports/{report_id}/download/",
        "partial_report": False,
        "created_at": "2026-07-18T00:00:00+00:00",
        "updated_at": "2026-07-18T00:00:00+00:00",
        "owner_id": "usr_owner",
        "storage_uri": "s3://private/owner-report.pdf",
        "content": {
            "contract_version": "analysis_report.v1",
            "format": "json",
            "action": "worker_finalize",
            "reporting_payload": {
                "report_type": "fault_ratio_analysis",
                "screen_id": "UI-REPORT-FAULT-001",
                "stage": "agent_execution_ready",
                "title": "Owner report",
                "summary": "Safe summary",
                "document_variant": "traffic_accident",
                "document_readiness": {
                    "ready_for_docx": True,
                    "missing_field_details": [],
                },
                "report_actions": [
                    {
                        "type": "download_objection",
                        "label": "교통사고 이의신청서 DOCX 다운로드",
                        "document_type": "traffic_accident_objection_docx",
                        "document_format": "docx",
                    }
                ],
                "appeal_gate": {"blocked": False, "reason": ""},
                "document_cards": [
                    {
                        "type": "fact_summary",
                        "title": "사실관계 정리",
                        "description": "공개 사실관계를 정리합니다.",
                        "status": "ready",
                        "sections": [
                            {
                                "title": "사실관계",
                                "body": "Known facts",
                                "storage_uri": "s3://private/card.json",
                            }
                        ],
                        "copy_text": "사실관계 정리\n\nKnown facts",
                        "notice": "제출 전 확인",
                        "internal_note": "must-not-leak",
                    }
                ],
                "sections": [
                    {
                        "title": "Facts",
                        "body": "Known facts",
                        "items": ["Verified", 3],
                        "provenance": {"fingerprint": "must-not-leak"},
                        "storage_uri": "s3://private/section.json",
                        "access_token": "must-not-leak",
                    }
                ],
                "provenance": {"fingerprint": "must-not-leak"},
                "source_node_codes": ["law_ground_search"],
                "data": {"access_token": "must-not-leak"},
            },
            "source": {"request_fingerprint": "must-not-leak"},
            "quality": {"agent_status_counts": {"success": 1}},
        },
        "metadata": {
            "report_quality": {
                "contract_version": "report_quality.v2",
                "partial_report": False,
                "review_required": True,
                "limitation_count": 1,
                "limitations": ["Verify facts"],
                "agent_status_counts": {"success": 1},
            },
            "limitations": ["Verify facts"],
            "object_storage": {
                "storage_uri": "s3://private/owner-report.pdf",
                "key": "private/owner-report.pdf",
            },
        },
        "job": {"job_id": "job_123", "mock_scenario": "fault_ratio"},
    }


def test_detail_projection_preserves_display_fields_and_drops_internal_fields() -> None:
    record = _report_record()
    original = deepcopy(record)

    response = compose_report_detail_response(
        record,
        api_surface="canonical",
        execution_mode="async_worker",
    )

    report = response["report"]
    payload = report["content"]["reporting_payload"]
    assert payload["sections"] == [
        {
            "title": "Facts",
            "body": "Known facts",
            "items": ["Verified"],
        }
    ]
    assert payload["document_cards"] == [
        {
            "type": "fact_summary",
            "title": "사실관계 정리",
            "description": "공개 사실관계를 정리합니다.",
            "status": "ready",
            "sections": [
                {
                    "title": "사실관계",
                    "body": "Known facts",
                    "items": [],
                }
            ],
            "copy_text": "사실관계 정리\n\nKnown facts",
            "notice": "제출 전 확인",
        }
    ]
    assert set(payload) == {
        "report_type",
        "screen_id",
        "stage",
        "title",
        "summary",
        "document_variant",
        "document_readiness",
        "report_actions",
        "appeal_gate",
        "document_confirmation",
        "document_cards",
        "sections",
    }
    assert set(report["metadata"]["report_quality"]) == {
        "contract_version",
        "partial_report",
        "review_required",
        "limitation_count",
        "limitations",
        "confidence_label",
    }
    assert "owner_id" not in report
    assert "source" not in report
    assert "storage_uri" not in report
    assert "source" not in report["content"]
    assert "quality" not in report["content"]
    assert "object_storage" not in report["metadata"]
    assert record == original


def test_list_projection_preserves_order_without_exposing_internal_fields() -> None:
    first = _report_record("rep_first")
    second = _report_record("rep_second")
    original = deepcopy([first, second])

    response = compose_report_list_response(
        [first, second],
        api_surface="canonical",
    )

    assert [report["report_id"] for report in response["reports"]] == [
        "rep_first",
        "rep_second",
    ]
    assert set(response["reports"][0]) == {
        "report_id",
        "report_type",
        "screen_id",
        "title",
        "status",
        "session_id",
        "job_id",
        "summary",
        "download_url",
        "partial_report",
        "created_at",
        "updated_at",
    }
    assert [first, second] == original


def test_detail_projection_uses_safe_defaults_for_missing_nested_values() -> None:
    record = _report_record()
    record["content"] = None
    record["metadata"] = None

    response = compose_report_detail_response(
        record,
        api_surface="canonical_mock",
        execution_mode="mock",
    )

    assert response["report"]["content"] == {
        "contract_version": None,
        "format": None,
        "action": None,
        "reporting_payload": {
            "report_type": None,
            "screen_id": None,
            "stage": None,
            "title": None,
            "summary": None,
            "document_variant": None,
            "document_readiness": None,
            "report_actions": [],
            "appeal_gate": None,
            "document_confirmation": None,
            "document_cards": [],
            "sections": [],
        },
    }
    assert response["report"]["metadata"]["report_quality"]["partial_report"] is False
    assert response["report"]["metadata"]["limitations"] == []


def test_public_contract_rejects_unexpected_response_fields() -> None:
    with pytest.raises(ValidationError):
        ReportListResponse.model_validate(
            {
                "api_surface": "canonical",
                "reports": [],
                "object_storage": {"key": "must-not-be-public"},
            }
        )


def test_public_contract_rejects_unknown_nested_section_fields() -> None:
    with pytest.raises(ValidationError):
        ReportReportingPayload.model_validate(
            {
                "sections": [
                    {
                        "title": "Facts",
                        "storage_uri": "s3://private/section.json",
                    }
                ]
            }
        )


def test_public_contract_requires_detail_nested_values() -> None:
    with pytest.raises(ValidationError):
        ReportContent.model_validate({})

    with pytest.raises(ValidationError):
        ReportMetadata.model_validate({})


def test_public_error_contract_rejects_unmodeled_storage_fields() -> None:
    with pytest.raises(ValidationError):
        ReportApiErrorResponse.model_validate(
            {
                "error": {
                    "code": "report_not_found",
                    "message": "Report was not found.",
                    "storage_uri": "s3://private/report.pdf",
                }
            }
        )


def test_error_projection_drops_raw_authorization_and_storage_metadata() -> None:
    response = compose_report_error_response(
        {
            "contract_version": "object_access.v1",
            "type": "object_access",
            "code": "object_access_denied",
            "status": 403,
            "message": "Access denied.",
            "required_action": "login_or_owner_match",
            "access": {
                "contract_version": "object_access.v1",
                "allowed": False,
                "reason": "owner_mismatch",
                "subject": {"user_id": "usr_other"},
                "resource": {
                    "type": "report",
                    "report_id": "rep_123",
                    "session_id": "ses_123",
                    "owner_id": "usr_owner",
                    "storage_backend": "s3",
                },
            },
        }
    )

    assert response["error"]["access"] == {
        "contract_version": "object_access.v1",
        "allowed": False,
        "reason": "owner_mismatch",
        "resource": {
            "type": "report",
            "report_id": "rep_123",
            "session_id": "ses_123",
        },
    }


def test_error_projection_preserves_report_readiness_status_without_extra_fields() -> None:
    response = compose_report_error_response(
        {
            "contract_version": "report_download.v1",
            "code": "report_not_ready",
            "message": "Report is not ready.",
            "report_id": "rep_123",
            "status": "draft",
            "storage_uri": "s3://private/report.pdf",
        }
    )

    assert response == {
        "error": {
            "contract_version": "report_download.v1",
            "type": None,
            "code": "report_not_ready",
            "status": "draft",
            "message": "Report is not ready.",
            "missing_fields": [],
            "retryable": None,
            "required_action": None,
            "action": None,
            "reason": None,
            "policy_version": None,
            "report_id": "rep_123",
            "guest_id": None,
            "guest_status": None,
            "auth": None,
            "subject": None,
            "access": None,
        }
    }


@pytest.mark.parametrize(
    ("canonical", "source", "expected_surface", "expected_mode"),
    [
        (False, "analysis_worker_reporting", "mock", "async_worker"),
        (True, "analysis_worker_reporting", "canonical", "async_worker"),
        (True, "canonical_report_action", "canonical_mock", "mock"),
    ],
)
def test_surface_helpers_use_existing_runtime_labels(
    canonical: bool,
    source: str,
    expected_surface: str,
    expected_mode: str,
) -> None:
    assert report_api_surface(canonical=canonical, source=source) == expected_surface
    assert report_execution_mode(source=source) == expected_mode
