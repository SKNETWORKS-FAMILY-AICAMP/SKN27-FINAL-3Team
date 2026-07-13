"""Shadow API route registry for executable contract drift checks.

The registry describes existing Django behavior. It does not generate or
replace ``urlpatterns`` while the contract is in ``shadow`` status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.contracts.consultation_case import (
    CaseApiErrorCode,
    CaseApiErrorResponse,
    ConfirmCaseFactsRequest,
    ConfirmCaseFactsResponse,
    ConsultationCaseListResponse,
    ConsultationCaseWorkspaceResponse,
    CreateConsultationCaseRequest,
    CreateConsultationCaseResponse,
    StartCaseAnalysisRequest,
    StartCaseAnalysisResponse,
)


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
ContractStatus = Literal["shadow", "generated"]


@dataclass(frozen=True, slots=True)
class PathParameterSpec:
    name: str
    description: str
    min_length: int = 1
    max_length: int = 64

    def __post_init__(self) -> None:
        if not self.name or self.min_length < 1 or self.max_length < self.min_length:
            raise ValueError("invalid path parameter contract")


@dataclass(frozen=True, slots=True)
class RouteErrorSpec:
    status: int
    codes: tuple[CaseApiErrorCode, ...]
    response_model: type[BaseModel]


@dataclass(frozen=True, slots=True)
class RouteSpec:
    operation_id: str
    method: HttpMethod
    path: str
    route_name: str
    view_name: str
    request_model: type[BaseModel] | None
    response_model: type[BaseModel]
    success_status: int
    errors: tuple[RouteErrorSpec, ...]
    auth_required: bool
    contract_status: ContractStatus
    tags: tuple[str, ...]
    summary: str
    path_parameters: tuple[PathParameterSpec, ...] = ()

    def __post_init__(self) -> None:
        placeholders = tuple(re.findall(r"\{([^{}]+)\}", self.path))
        parameters = tuple(parameter.name for parameter in self.path_parameters)
        if placeholders != parameters:
            raise ValueError(
                f"path parameter drift for {self.method} {self.path}: "
                f"placeholders={placeholders!r}, specs={parameters!r}"
            )


@dataclass(frozen=True, slots=True)
class DeferredRouteSpec:
    method: HttpMethod
    path: str
    route_name: str
    view_name: str
    reason: str
    contract_status: Literal["deferred"] = "deferred"


def _case_errors(
    *entries: tuple[int, tuple[CaseApiErrorCode, ...]],
) -> tuple[RouteErrorSpec, ...]:
    return tuple(
        RouteErrorSpec(
            status=status,
            codes=codes,
            response_model=CaseApiErrorResponse,
        )
        for status, codes in entries
    )


CASE_ID_PATH_PARAMETER = PathParameterSpec(
    name="case_id",
    description="Canonical consultation Case identifier",
    max_length=64,
)


CASE_API_ROUTE_SPECS: tuple[RouteSpec, ...] = (
    RouteSpec(
        operation_id="listConsultationCases",
        method="GET",
        path="/api/cases/",
        route_name="canonical-consultation-cases",
        view_name="consultation_cases",
        request_model=None,
        response_model=ConsultationCaseListResponse,
        success_status=200,
        errors=_case_errors((403, ("login_required",))),
        auth_required=True,
        contract_status="shadow",
        tags=("Cases",),
        summary="List consultation cases owned by the authenticated user",
    ),
    RouteSpec(
        operation_id="createConsultationCase",
        method="POST",
        path="/api/cases/",
        route_name="canonical-consultation-cases",
        view_name="consultation_cases",
        request_model=CreateConsultationCaseRequest,
        response_model=CreateConsultationCaseResponse,
        success_status=201,
        errors=_case_errors(
            (403, ("login_required", "case_owner_mismatch")),
            (404, ("case_not_found",)),
            (409, ("case_conflict",)),
            (422, ("validation_error",)),
        ),
        auth_required=True,
        contract_status="shadow",
        tags=("Cases",),
        summary="Promote an authenticated consultation session to a Case",
    ),
    RouteSpec(
        operation_id="getConsultationCaseWorkspace",
        method="GET",
        path="/api/cases/{case_id}/workspace/",
        route_name="canonical-consultation-case-workspace",
        view_name="consultation_case_workspace",
        request_model=None,
        response_model=ConsultationCaseWorkspaceResponse,
        success_status=200,
        errors=_case_errors(
            (403, ("login_required", "object_access_denied")),
            (404, ("case_not_found",)),
        ),
        auth_required=True,
        contract_status="shadow",
        tags=("Cases",),
        summary="Read the authenticated owner's Case workspace",
        path_parameters=(CASE_ID_PATH_PARAMETER,),
    ),
    RouteSpec(
        operation_id="confirmConsultationCaseFacts",
        method="POST",
        path="/api/cases/{case_id}/facts/confirm/",
        route_name="canonical-consultation-case-fact-confirmation",
        view_name="consultation_case_fact_confirmation",
        request_model=ConfirmCaseFactsRequest,
        response_model=ConfirmCaseFactsResponse,
        success_status=201,
        errors=_case_errors(
            (
                403,
                (
                    "login_required",
                    "object_access_denied",
                    "case_owner_mismatch",
                ),
            ),
            (404, ("case_not_found",)),
            (409, ("case_conflict",)),
            (422, ("validation_error",)),
        ),
        auth_required=True,
        contract_status="shadow",
        tags=("Cases",),
        summary="Create an immutable confirmed-facts version for a Case",
        path_parameters=(CASE_ID_PATH_PARAMETER,),
    ),
    RouteSpec(
        operation_id="startConsultationCaseAnalysis",
        method="POST",
        path="/api/cases/{case_id}/analysis/jobs/",
        route_name="canonical-consultation-case-analysis-jobs",
        view_name="consultation_case_analysis_jobs",
        request_model=StartCaseAnalysisRequest,
        response_model=StartCaseAnalysisResponse,
        success_status=202,
        errors=_case_errors(
            (
                403,
                (
                    "login_required",
                    "object_access_denied",
                    "case_owner_mismatch",
                ),
            ),
            (404, ("case_not_found",)),
            (
                409,
                (
                    "case_conflict",
                    "confirmed_facts_required",
                    "fact_readiness_not_met",
                ),
            ),
            (422, ("validation_error",)),
        ),
        auth_required=True,
        contract_status="shadow",
        tags=("Cases",),
        summary="Queue analysis from an authenticated owner's confirmed facts",
        path_parameters=(CASE_ID_PATH_PARAMETER,),
    ),
)


API_ROUTE_SPECS: tuple[RouteSpec, ...] = CASE_API_ROUTE_SPECS


DEFERRED_ROUTE_SPECS: tuple[DeferredRouteSpec, ...] = (
    DeferredRouteSpec(
        method="GET",
        path="/api/health/",
        route_name="health-check",
        view_name="health_check",
        reason="Basic health response DTO is pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/health/live/",
        route_name="health-live",
        view_name="health_live",
        reason="Liveness response DTO is pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/health/ready/",
        route_name="health-ready",
        view_name="health_ready",
        reason="Readiness success and dependency-failure DTOs are pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/capabilities/",
        route_name="capabilities",
        view_name="capabilities",
        reason="Capability DTO exists in runtime data but is not registered as a route contract.",
    ),
    DeferredRouteSpec(
        method="POST",
        path="/api/auth/guest-session/",
        route_name="auth-guest-session",
        view_name="guest_session",
        reason="Guest authentication request and response DTOs are pending.",
    ),
    DeferredRouteSpec(
        method="POST",
        path="/api/auth/google/code/",
        route_name="auth-google-code",
        view_name="auth_google_code",
        reason="Google authorization-code and CSRF error DTOs are pending.",
    ),
    DeferredRouteSpec(
        method="POST",
        path="/api/auth/refresh/",
        route_name="auth-refresh",
        view_name="auth_refresh",
        reason="Rotating credential and revoked-session DTOs are pending.",
    ),
    DeferredRouteSpec(
        method="POST",
        path="/api/auth/logout/",
        route_name="auth-logout",
        view_name="auth_logout",
        reason="Logout and revoked-session DTOs are pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/auth/me/",
        route_name="auth-me",
        view_name="auth_me",
        reason="Current principal success and auth-error DTOs are pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/mypage/summary/",
        route_name="canonical-mypage-summary",
        view_name="mypage_summary",
        reason="Response DTO and application query service are not yet extracted.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/history/",
        route_name="canonical-history-events",
        view_name="history_events",
        reason="History filters and response DTO remain coupled to the Django view.",
    ),
    DeferredRouteSpec(
        method="POST",
        path="/api/chat/sessions/",
        route_name="canonical-create-chat-session",
        view_name="create_chat_session",
        reason="Authenticated session ownership DTO is pending.",
    ),
    DeferredRouteSpec(
        method="POST",
        path="/api/chat/messages/",
        route_name="canonical-submit-chat-message",
        view_name="submit_chat_message",
        reason="Chat orchestration request and async response DTOs are pending.",
    ),
    DeferredRouteSpec(
        method="POST",
        path="/api/chat/save-state/",
        route_name="canonical-chat-save-state",
        view_name="update_chat_save_state",
        reason="Conversation ownership and save-state DTOs are pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/files/",
        route_name="canonical-files",
        view_name="attachments",
        reason="File list DTO and owner-scoped query service are pending.",
    ),
    DeferredRouteSpec(
        method="POST",
        path="/api/files/",
        route_name="canonical-files",
        view_name="attachments",
        reason="Multipart upload DTO and scan-gate application service are pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/files/{attachment_id}/",
        route_name="canonical-file-detail",
        view_name="attachment_detail",
        reason="File detail DTO and owner-scoped query service are pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/analysis/jobs/",
        route_name="canonical-analysis-jobs",
        view_name="analysis_jobs",
        reason="Owner-scoped analysis job list DTO is pending.",
    ),
    DeferredRouteSpec(
        method="POST",
        path="/api/analysis/jobs/",
        route_name="canonical-analysis-jobs",
        view_name="analysis_jobs",
        reason="Queued analysis job request/response DTO promotion remains pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/analysis/jobs/{job_id}/",
        route_name="canonical-analysis-job-detail",
        view_name="analysis_job_detail",
        reason="Query service exists; owner authorization and response DTO remain pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/analysis/results/{job_id}/",
        route_name="canonical-analysis-result",
        view_name="analysis_result",
        reason="Query service exists; owner authorization and response DTO remain pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/agents/nodes/",
        route_name="canonical-agent-nodes",
        view_name="agent_nodes",
        reason="Typed node DTO exists but route request/error contracts are pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/reports/",
        route_name="canonical-report-action",
        view_name="report_action",
        reason="Owner-scoped report list DTO and application service are pending.",
    ),
    DeferredRouteSpec(
        method="POST",
        path="/api/reports/",
        route_name="canonical-report-action",
        view_name="report_action",
        reason="Report generation still contains legacy runtime behavior.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/reports/{report_id}/",
        route_name="canonical-report-detail",
        view_name="report_detail",
        reason="Report detail DTO and application query service are pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/reports/{report_id}/download/",
        route_name="canonical-download-report",
        view_name="download_report",
        reason="Binary PDF response and signed-access contract are pending.",
    ),
)
