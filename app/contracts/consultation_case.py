"""Pydantic request DTOs for consultation Case v2 endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


CaseStatusValue = Literal[
    "intake",
    "awaiting_fact_confirmation",
    "queued",
    "analyzing",
    "needs_input",
    "ready",
    "high_risk_handoff",
    "closed",
    "deleted",
]
AnalysisJobStatusValue = Literal["queued", "running", "success", "partial", "failed"]
AgentWorkItemStatusValue = Literal[
    "queued",
    "running",
    "success",
    "failed",
    "retrying",
    "canceled",
]
UploadedFileStatusValue = Literal[
    "pending",
    "uploaded",
    "scanning",
    "ready",
    "rejected",
    "deleted",
]
ReportTypeValue = Literal[
    "fine_notice_objection",
    "fault_ratio_analysis",
    "general",
    "initial_consultation",
    "expert_handoff",
]
ReportStatusValue = Literal["draft", "generating", "ready", "failed", "deleted"]


class ConsultationCaseRecord(StrictResponse):
    case_id: str = Field(min_length=1, max_length=64)
    owner_id: str = Field(min_length=1, max_length=128)
    title: str = Field(max_length=200)
    case_type: Literal["accident_fault"]
    status: CaseStatusValue
    risk_level: Literal["standard", "high_risk"]
    location: dict[str, Any]
    current_fact_version: int = Field(ge=0)
    current_report_version: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class ConfirmedFactRecord(StrictResponse):
    schema_version: Literal["confirmed_facts.v1"]
    fact_version_id: str = Field(min_length=1, max_length=64)
    case_id: str = Field(min_length=1, max_length=64)
    version_no: int = Field(ge=1)
    status: Literal["confirmed"]
    facts: dict[str, Any]
    sources: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    user_edit_history: list[dict[str, Any]]
    confirmed_by: str = Field(max_length=128)
    confirmed_at: datetime | None


class CaseWorkspaceAnalysisJob(StrictResponse):
    job_id: str = Field(min_length=1, max_length=64)
    status: AnalysisJobStatusValue
    active_node: str = Field(max_length=120)
    updated_at: datetime


class CaseWorkspaceReport(StrictResponse):
    report_id: str = Field(min_length=1, max_length=64)
    report_type: ReportTypeValue
    version_no: int = Field(ge=1)
    status: ReportStatusValue


class CaseWorkspaceAttachment(StrictResponse):
    attachment_id: str = Field(min_length=1, max_length=64)
    status: UploadedFileStatusValue
    purpose: str = Field(min_length=1, max_length=64)
    retention_expires_at: datetime | None


class CaseWorkspace(StrictResponse):
    contract_version: Literal["case_workspace.v2"]
    case: ConsultationCaseRecord
    consultation_state: dict[str, Any]
    confirmed_facts: list[ConfirmedFactRecord]
    analysis_jobs: list[CaseWorkspaceAnalysisJob]
    reports: list[CaseWorkspaceReport]
    attachments: list[CaseWorkspaceAttachment]


class CaseAnalysisJob(StrictResponse):
    job_id: str = Field(min_length=1, max_length=64)
    status: AnalysisJobStatusValue


class CaseAnalysisWorkItem(StrictResponse):
    work_item_id: str = Field(min_length=1, max_length=64)
    status: AgentWorkItemStatusValue


class CaseAnalysisPlanSummary(StrictResponse):
    plan_id: str = Field(min_length=1, max_length=64)
    node_codes: list[str] = Field(min_length=1)


class CreateConsultationCaseRequest(StrictRequest):
    session_id: str = Field(min_length=1, max_length=64)
    title: str = Field(default="", max_length=200)
    case_type: Literal["accident_fault"] = "accident_fault"
    consultation_state: dict[str, Any] = Field(default_factory=dict)
    location: dict[str, Any] = Field(default_factory=dict)


class ConfirmCaseFactsRequest(StrictRequest):
    facts: dict[str, Any] = Field(min_length=1)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    user_edit_history: list[dict[str, Any]] = Field(default_factory=list)


class StartCaseAnalysisRequest(StrictRequest):
    fact_version_id: str = Field(default="", max_length=64)


class ConsultationCaseListResponse(StrictResponse):
    contract_version: Literal["consultation_case_list.v2"]
    cases: list[ConsultationCaseRecord]


class CreateConsultationCaseResponse(StrictResponse):
    contract_version: Literal["consultation_case.v2"]
    case: ConsultationCaseRecord


class ConsultationCaseWorkspaceResponse(StrictResponse):
    workspace: CaseWorkspace


class ConfirmCaseFactsResponse(StrictResponse):
    contract_version: Literal["confirmed_facts.v1"]
    fact_version: ConfirmedFactRecord


class StartCaseAnalysisResponse(StrictResponse):
    contract_version: Literal["case_analysis_job.v2"]
    job: CaseAnalysisJob
    work_item: CaseAnalysisWorkItem
    analysis_plan: CaseAnalysisPlanSummary


CaseApiErrorCode = Literal[
    "login_required",
    "validation_error",
    "object_access_denied",
    "case_repository_error",
    "case_not_found",
    "case_conflict",
    "case_owner_mismatch",
    "confirmed_facts_required",
    "fact_readiness_not_met",
]
CaseRepositoryErrorCode = Literal[
    "case_repository_error",
    "case_not_found",
    "case_conflict",
    "case_owner_mismatch",
    "confirmed_facts_required",
    "fact_readiness_not_met",
]


class CaseLoginRequiredError(StrictResponse):
    contract_version: Literal["login_required.v1"]
    type: Literal["authorization"]
    code: Literal["login_required"]
    status: Literal[403]
    message: str
    required_action: Literal["login"]
    action: str
    reason: str
    policy_version: str
    subject: dict[str, Any]


class CaseLoginRequiredErrorResponse(StrictResponse):
    error: CaseLoginRequiredError


class RequestValidationIssue(StrictResponse):
    field: str
    type: str
    message: str


class CaseRequestValidationError(StrictResponse):
    contract_version: Literal["request_validation_error.v1"]
    type: Literal["validation"]
    code: Literal["validation_error"]
    status: Literal[422]
    message: str
    details: list[RequestValidationIssue]


class CaseRequestValidationErrorResponse(StrictResponse):
    error: CaseRequestValidationError


class ConsultationCaseRepositoryError(StrictResponse):
    contract_version: Literal["consultation_case_error.v2"]
    type: Literal["case"]
    code: CaseRepositoryErrorCode
    status: Literal[400, 403, 404, 409]
    message: str
    details: dict[str, Any] | None = None


class ConsultationCaseRepositoryErrorResponse(StrictResponse):
    error: ConsultationCaseRepositoryError


class CaseObjectAccessDeniedError(StrictResponse):
    contract_version: Literal["object_access.v1"]
    type: Literal["object_access"]
    code: Literal["object_access_denied"]
    status: Literal[403]
    message: str
    required_action: Literal["login_or_owner_match"]
    access: dict[str, Any]


class CaseObjectAccessDeniedErrorResponse(StrictResponse):
    error: CaseObjectAccessDeniedError


class CaseApiErrorResponse(
    RootModel[
        CaseLoginRequiredErrorResponse
        | CaseRequestValidationErrorResponse
        | ConsultationCaseRepositoryErrorResponse
        | CaseObjectAccessDeniedErrorResponse
    ]
):
    """Strict union of the error envelopes emitted by Case v2 endpoints."""
