"""Public DTOs for canonical report read and download endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.contracts.consultation_case import (
    ReportStatusValue,
    ReportTypeValue,
    StrictResponse,
)


class ReportApiContractModel(StrictResponse):
    """Reject fields that are not part of the public report API contract."""


class ReportSection(ReportApiContractModel):
    """One explicitly public report section without source provenance."""

    title: str | None = None
    body: str | None = None
    items: list[str] = Field(default_factory=list)


class ReportReportingPayload(ReportApiContractModel):
    report_type: ReportTypeValue | None = None
    screen_id: str | None = None
    stage: str | None = None
    title: str | None = None
    summary: str | None = None
    sections: list[ReportSection] = Field(default_factory=list)


class ReportQuality(ReportApiContractModel):
    contract_version: str | None = None
    partial_report: bool = False
    review_required: bool = False
    limitation_count: int = Field(default=0, ge=0)
    limitations: list[str] = Field(default_factory=list)
    confidence_label: str | None = None


class ReportSummary(ReportApiContractModel):
    report_id: str = Field(min_length=1, max_length=64)
    report_type: ReportTypeValue
    screen_id: str = ""
    title: str = ""
    status: ReportStatusValue
    session_id: str | None = None
    job_id: str | None = None
    summary: str = ""
    download_url: str | None = None
    partial_report: bool = False
    created_at: datetime
    updated_at: datetime


class ReportContent(ReportApiContractModel):
    contract_version: str | None = None
    format: str | None = None
    action: str | None = None
    reporting_payload: ReportReportingPayload


class ReportMetadata(ReportApiContractModel):
    report_quality: ReportQuality
    limitations: list[str] = Field(default_factory=list)


class ReportDetail(ReportSummary):
    content: ReportContent
    metadata: ReportMetadata


class ReportListResponse(ReportApiContractModel):
    api_surface: str = Field(min_length=1, max_length=32)
    reports: list[ReportSummary]


class ReportDetailResponse(ReportApiContractModel):
    api_surface: str = Field(min_length=1, max_length=32)
    execution_mode: str = Field(min_length=1, max_length=32)
    report: ReportDetail


class ReportErrorAuth(ReportApiContractModel):
    scheme: str | None = None
    reason: str | None = None


class ReportErrorSubject(ReportApiContractModel):
    subject_id: str | None = None
    subject_type: str | None = None
    user_id: str | None = None
    guest_id: str | None = None
    auth_session_id: str | None = None


class ReportErrorAccessResource(ReportApiContractModel):
    type: str | None = None
    report_id: str | None = None
    session_id: str | None = None


class ReportErrorAccess(ReportApiContractModel):
    contract_version: str | None = None
    allowed: bool = False
    reason: str | None = None
    resource: ReportErrorAccessResource | None = None


class ReportApiError(ReportApiContractModel):
    """Strictly modeled public error fields for report endpoint clients."""

    contract_version: str | None = None
    type: str | None = None
    code: Literal[
        "auth_required",
        "token_invalid",
        "token_expired",
        "guest_session_invalid",
        "login_required",
        "object_access_denied",
        "report_not_found",
        "report_not_ready",
    ]
    status: int | ReportStatusValue | None = None
    message: str = Field(min_length=1)
    missing_fields: list[str] = Field(default_factory=list)
    retryable: bool | None = None
    required_action: str | None = None
    action: str | None = None
    reason: str | None = None
    policy_version: str | None = None
    report_id: str | None = None
    guest_id: str | None = None
    guest_status: str | None = None
    auth: ReportErrorAuth | None = None
    subject: ReportErrorSubject | None = None
    access: ReportErrorAccess | None = None


class ReportApiErrorResponse(ReportApiContractModel):
    error: ReportApiError
