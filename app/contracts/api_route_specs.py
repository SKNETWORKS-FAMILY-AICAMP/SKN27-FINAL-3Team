"""Shadow API route registry for executable contract drift checks.

The registry describes existing Django behavior. It does not generate or
replace ``urlpatterns`` while the contract is in ``shadow`` status.
"""

from __future__ import annotations

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
    ),
)


API_ROUTE_SPECS: tuple[RouteSpec, ...] = CASE_API_ROUTE_SPECS
