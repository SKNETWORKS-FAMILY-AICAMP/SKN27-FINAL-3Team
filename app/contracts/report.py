"""Public DTOs for canonical report read and download endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.contracts.consultation_case import (
    ReportStatusValue,
    ReportTypeValue,
    StrictRequest,
    StrictResponse,
)


class ReportApiContractModel(StrictResponse):
    """Reject fields that are not part of the public report API contract."""


class ReportSection(ReportApiContractModel):
    """One explicitly public report section without source provenance."""

    title: str | None = None
    body: str | None = None
    items: list[str] = Field(default_factory=list)


class ReportDocumentReadiness(ReportApiContractModel):
    ready_for_docx: bool = False
    missing_field_details: list[dict[str, str]] = Field(default_factory=list)
    next_questions: list[dict[str, str]] = Field(default_factory=list)


class ReportDownloadAction(ReportApiContractModel):
    type: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=160)
    document_type: str = Field(min_length=1, max_length=64)
    document_format: Literal["docx"] | None = None


class ReportAppealGate(ReportApiContractModel):
    blocked: bool = False
    reason: str | None = None


class ReportDocumentConfirmation(ReportApiContractModel):
    required: bool = False
    confirmed: bool = False
    stale: bool = False
    confirmed_at: datetime | None = None


class ReportDocumentCard(ReportApiContractModel):
    type: Literal["objection_draft", "fact_summary", "insurance_submission"]
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=280)
    status: Literal["ready", "partial", "unavailable"]
    sections: list[ReportSection] = Field(default_factory=list)
    copy_text: str | None = None
    notice: str | None = None


class ConfirmReportDocumentRequest(StrictRequest):
    facts_confirmed: Literal[True]
    agency_confirmed: Literal[True]
    deadline_confirmed: Literal[True]
    attachments_confirmed: Literal[True]


class ConfirmReportDocumentResponse(ReportApiContractModel):
    contract_version: Literal["document_confirmation.v1"]
    document_confirmation: ReportDocumentConfirmation


class ReportReportingPayload(ReportApiContractModel):
    report_type: ReportTypeValue | None = None
    screen_id: str | None = None
    stage: str | None = None
    title: str | None = None
    summary: str | None = None
    document_variant: str | None = None
    document_readiness: ReportDocumentReadiness | None = None
    report_actions: list[ReportDownloadAction] = Field(default_factory=list)
    appeal_gate: ReportAppealGate | None = None
    document_confirmation: ReportDocumentConfirmation | None = None
    document_cards: list[ReportDocumentCard] = Field(default_factory=list)
    sections: list[ReportSection] = Field(default_factory=list)


class PublicQualityFreshness(ReportApiContractModel):
    effective_at: str | None = None
    retrieved_at: str | None = None
    limitation: str | None = None


class PublicQualityRetrieval(ReportApiContractModel):
    backend_label: str | None = None
    result_count: int | None = None
    used_fallback: bool = False


class PublicQualitySummary(ReportApiContractModel):
    status: str = "unavailable"
    partial_result: bool = False
    review_required: bool = False
    freshness: PublicQualityFreshness = Field(default_factory=PublicQualityFreshness)
    retrieval: PublicQualityRetrieval = Field(default_factory=PublicQualityRetrieval)
    limitation_count: int = Field(default=0, ge=0)
    limitations: list[str] = Field(default_factory=list)


class ReportQuality(ReportApiContractModel):
    contract_version: str | None = None
    partial_report: bool = False
    review_required: bool = False
    limitation_count: int = Field(default=0, ge=0)
    limitations: list[str] = Field(default_factory=list)
    confidence_label: str | None = None
    public_quality_summary: PublicQualitySummary | None = None


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
        "document_download_not_available",
        "document_confirmation_required",
        "appeal_gate_blocked",
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
