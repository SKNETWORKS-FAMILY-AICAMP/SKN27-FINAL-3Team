from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]


def test_case_api_route_specs_shadow_current_django_contract() -> None:
    module_path = ROOT / "app" / "contracts" / "api_route_specs.py"
    assert module_path.exists(), "API_ROUTE_SPECS shadow registry must exist"

    contracts = importlib.import_module("app.contracts.consultation_case")
    route_specs = importlib.import_module("app.contracts.api_route_specs")

    expected = {
        ("GET", "/api/cases/"): {
            "route_name": "canonical-consultation-cases",
            "view_name": "consultation_cases",
            "request_model": None,
            "response_model": contracts.ConsultationCaseListResponse,
            "success_status": 200,
            "errors": {
                403: ("login_required",),
            },
        },
        ("POST", "/api/cases/"): {
            "route_name": "canonical-consultation-cases",
            "view_name": "consultation_cases",
            "request_model": contracts.CreateConsultationCaseRequest,
            "response_model": contracts.CreateConsultationCaseResponse,
            "success_status": 201,
            "errors": {
                403: ("login_required", "case_owner_mismatch"),
                404: ("case_not_found",),
                409: ("case_conflict",),
                422: ("validation_error",),
            },
        },
        ("GET", "/api/cases/{case_id}/workspace/"): {
            "route_name": "canonical-consultation-case-workspace",
            "view_name": "consultation_case_workspace",
            "request_model": None,
            "response_model": contracts.ConsultationCaseWorkspaceResponse,
            "success_status": 200,
            "errors": {
                403: ("login_required", "object_access_denied"),
                404: ("case_not_found",),
            },
        },
        ("POST", "/api/cases/{case_id}/facts/confirm/"): {
            "route_name": "canonical-consultation-case-fact-confirmation",
            "view_name": "consultation_case_fact_confirmation",
            "request_model": contracts.ConfirmCaseFactsRequest,
            "response_model": contracts.ConfirmCaseFactsResponse,
            "success_status": 201,
            "errors": {
                403: (
                    "login_required",
                    "object_access_denied",
                    "case_owner_mismatch",
                ),
                404: ("case_not_found",),
                409: ("case_conflict",),
                422: ("validation_error",),
            },
        },
        ("POST", "/api/cases/{case_id}/analysis/jobs/"): {
            "route_name": "canonical-consultation-case-analysis-jobs",
            "view_name": "consultation_case_analysis_jobs",
            "request_model": contracts.StartCaseAnalysisRequest,
            "response_model": contracts.StartCaseAnalysisResponse,
            "success_status": 202,
            "errors": {
                403: (
                    "login_required",
                    "object_access_denied",
                    "case_owner_mismatch",
                ),
                404: ("case_not_found",),
                409: (
                    "case_conflict",
                    "confirmed_facts_required",
                    "fact_readiness_not_met",
                ),
                422: ("validation_error",),
            },
        },
    }

    actual = {(spec.method, spec.path): spec for spec in route_specs.CASE_API_ROUTE_SPECS}
    assert set(actual) == set(expected)
    assert route_specs.API_ROUTE_SPECS == (
        route_specs.CASE_API_ROUTE_SPECS
        + route_specs.AUTH_SESSION_API_ROUTE_SPECS
        + route_specs.FILE_API_ROUTE_SPECS
        + route_specs.ANALYSIS_JOB_API_ROUTE_SPECS
        + route_specs.REPORT_API_ROUTE_SPECS
    )

    for key, expected_spec in expected.items():
        spec = actual[key]
        assert spec.route_name == expected_spec["route_name"]
        assert spec.view_name == expected_spec["view_name"]
        assert spec.request_model is expected_spec["request_model"]
        assert spec.response_model is expected_spec["response_model"]
        assert spec.success_status == expected_spec["success_status"]
        assert {
            error.status: error.codes for error in spec.errors
        } == expected_spec["errors"]
        assert all(
            error.response_model is contracts.CaseApiErrorResponse
            for error in spec.errors
        )
        assert spec.auth_required is True
        assert spec.contract_status == "shadow"
        assert spec.tags == ("Cases",)

    route_keys = [(spec.method, spec.path) for spec in route_specs.API_ROUTE_SPECS]
    operation_ids = [spec.operation_id for spec in route_specs.API_ROUTE_SPECS]
    assert len(route_keys) == len(set(route_keys))
    assert len(operation_ids) == len(set(operation_ids))


def test_auth_session_api_route_specs_promote_existing_django_endpoints() -> None:
    auth_contracts = importlib.import_module("app.contracts.auth_session")
    route_specs = importlib.import_module("app.contracts.api_route_specs")

    actual = {
        (spec.method, spec.path): spec
        for spec in route_specs.AUTH_SESSION_API_ROUTE_SPECS
    }
    assert set(actual) == {
        ("POST", "/api/auth/guest-session/"),
        ("POST", "/api/auth/google/code/"),
        ("POST", "/api/auth/refresh/"),
        ("POST", "/api/auth/logout/"),
        ("GET", "/api/auth/me/"),
    }

    assert actual[("POST", "/api/auth/guest-session/")].response_model is (
        auth_contracts.GuestSessionResponse
    )
    assert actual[("POST", "/api/auth/google/code/")].request_model is (
        auth_contracts.GoogleAuthorizationCodeRequest
    )
    assert actual[("POST", "/api/auth/refresh/")].auth_optional is True
    assert actual[("POST", "/api/auth/logout/")].auth_optional is True
    assert actual[("GET", "/api/auth/me/")].auth_optional is True
    assert all(spec.contract_status == "shadow" for spec in actual.values())


def test_file_api_route_specs_promote_existing_django_endpoints() -> None:
    file_contracts = importlib.import_module("app.contracts.file_attachment")
    route_specs = importlib.import_module("app.contracts.api_route_specs")

    actual = {
        (spec.method, spec.path): spec for spec in route_specs.FILE_API_ROUTE_SPECS
    }
    assert set(actual) == {
        ("GET", "/api/files/"),
        ("POST", "/api/files/"),
        ("GET", "/api/files/{attachment_id}/"),
    }
    assert actual[("POST", "/api/files/")].request_model is (
        file_contracts.FileUploadRequest
    )
    assert actual[("POST", "/api/files/")].request_media_types == (
        "application/json",
        "multipart/form-data",
    )
    assert actual[("GET", "/api/files/{attachment_id}/")].path_parameters[0].name == (
        "attachment_id"
    )
    assert all(spec.contract_status == "shadow" for spec in actual.values())


def test_analysis_job_api_route_specs_promote_existing_django_endpoints() -> None:
    analysis_contracts = importlib.import_module("app.contracts.analysis_job")
    route_specs = importlib.import_module("app.contracts.api_route_specs")

    actual = {
        (spec.method, spec.path): spec for spec in route_specs.ANALYSIS_JOB_API_ROUTE_SPECS
    }
    assert set(actual) == {
        ("GET", "/api/analysis/jobs/"),
        ("POST", "/api/analysis/jobs/"),
        ("GET", "/api/analysis/jobs/{job_id}/"),
        ("GET", "/api/analysis/results/{job_id}/"),
    }
    assert actual[("POST", "/api/analysis/jobs/")].request_model is (
        analysis_contracts.AnalysisJobRequest
    )
    assert actual[("POST", "/api/analysis/jobs/")].response_model is (
        analysis_contracts.AnalysisJobAcceptedResponse
    )
    assert actual[("GET", "/api/analysis/jobs/")].response_model is (
        analysis_contracts.AnalysisJobListResponse
    )
    assert actual[("GET", "/api/analysis/jobs/{job_id}/")].response_model is (
        analysis_contracts.AnalysisJobDetailResponse
    )
    assert actual[("GET", "/api/analysis/results/{job_id}/")].response_model is (
        analysis_contracts.AnalysisResultResponse
    )
    assert actual[("GET", "/api/analysis/jobs/{job_id}/")].path_parameters[0].name == (
        "job_id"
    )
    assert actual[("GET", "/api/analysis/results/{job_id}/")].success_statuses == (200, 202)
    assert all(spec.auth_optional is True for spec in actual.values())
    assert all(spec.contract_status == "shadow" for spec in actual.values())


def test_report_get_routes_are_modeled_while_report_post_remains_deferred() -> None:
    report_contracts = importlib.import_module("app.contracts.report")
    route_specs = importlib.import_module("app.contracts.api_route_specs")

    modeled = {
        (spec.method, spec.path): spec for spec in route_specs.REPORT_API_ROUTE_SPECS
    }
    assert set(modeled) == {
        ("GET", "/api/reports/"),
        ("GET", "/api/reports/{report_id}/"),
        ("GET", "/api/reports/{report_id}/download/"),
    }
    assert modeled[("GET", "/api/reports/")].response_model is (
        report_contracts.ReportListResponse
    )
    assert modeled[("GET", "/api/reports/{report_id}/")].response_model is (
        report_contracts.ReportDetailResponse
    )
    download = modeled[("GET", "/api/reports/{report_id}/download/")]
    assert download.response_model is None
    assert download.success_content[0].media_type == "application/pdf"
    assert download.success_content[0].schema == {"type": "string", "format": "binary"}
    assert [
        (parameter.name, parameter.location)
        for parameter in modeled[("GET", "/api/reports/")].request_parameters
    ] == [
        ("X-Guest-Id", "header"),
        ("session_id", "query"),
    ]
    assert [
        (parameter.name, parameter.location)
        for parameter in download.request_parameters
    ] == [
        ("X-Guest-Id", "header"),
        ("session_id", "query"),
        ("document_type", "query"),
    ]
    assert [header.name for header in download.success_headers] == [
        "Content-Disposition",
        "X-API-Surface",
        "X-Execution-Mode",
        "X-Report-Document-Type",
    ]
    assert all(header.required is True for header in download.success_headers)
    for spec in modeled.values():
        unauthorized = next(error for error in spec.errors if error.status == 401)
        assert unauthorized.codes == (
            "auth_required",
            "token_invalid",
            "token_expired",
            "guest_session_invalid",
        )
    assert all(spec.auth_required is True for spec in modeled.values())

    deferred = {(spec.method, spec.path) for spec in route_specs.DEFERRED_ROUTE_SPECS}
    assert ("POST", "/api/reports/") in deferred
    assert ("GET", "/api/reports/") not in deferred
    assert ("GET", "/api/reports/{report_id}/") not in deferred
    assert ("GET", "/api/reports/{report_id}/download/") not in deferred


def test_success_content_and_header_specs_reject_ambiguous_contracts() -> None:
    contracts = importlib.import_module("app.contracts.consultation_case")
    route_specs = importlib.import_module("app.contracts.api_route_specs")

    with pytest.raises(ValueError):
        route_specs.ResponseContentSpec(
            media_type="",
            schema={"type": "string"},
        )
    with pytest.raises(ValueError):
        route_specs.ResponseContentSpec(
            media_type="application/json",
            response_model=contracts.ConsultationCaseListResponse,
            schema={"type": "object"},
        )
    with pytest.raises(ValueError):
        route_specs.ResponseHeaderSpec(
            name="",
            description="Invalid header",
            schema={"type": "string"},
        )
    with pytest.raises(ValueError):
        route_specs.RouteSpec(
            operation_id="missingSuccessContent",
            method="GET",
            path="/api/contracts/probe/",
            route_name="contract-probe",
            view_name="probe",
            request_model=None,
            response_model=None,
            success_status=200,
            errors=(),
            auth_required=False,
            contract_status="shadow",
            tags=("Contracts",),
            summary="Contract probe",
        )


def test_analysis_job_error_response_accepts_live_not_found_envelopes() -> None:
    analysis_contracts = importlib.import_module("app.contracts.analysis_job")

    for code in ("analysis_job_not_found", "analysis_result_not_found"):
        response = analysis_contracts.AnalysisJobErrorResponse.model_validate(
            {
                "error": {
                    "code": code,
                    "message": "Requested analysis resource was not found.",
                }
            }
        )
        assert response.error.code == code
        assert response.error.contract_version is None
        assert response.error.type is None
        assert response.error.status is None


def test_modeled_and_deferred_routes_are_complete_and_disjoint() -> None:
    route_specs = importlib.import_module("app.contracts.api_route_specs")

    modeled = {(spec.method, spec.path) for spec in route_specs.API_ROUTE_SPECS}
    deferred = {(spec.method, spec.path) for spec in route_specs.DEFERRED_ROUTE_SPECS}

    assert modeled.isdisjoint(deferred)
    assert deferred == {
        ("GET", "/api/health/"),
        ("GET", "/api/health/live/"),
        ("GET", "/api/health/ready/"),
        ("GET", "/api/capabilities/"),
        ("GET", "/api/mypage/summary/"),
        ("GET", "/api/history/"),
        ("POST", "/api/chat/sessions/"),
        ("POST", "/api/chat/messages/"),
        ("POST", "/api/chat/save-state/"),
        ("GET", "/api/agents/nodes/"),
        ("POST", "/api/reports/"),
    }
    assert all(spec.reason.strip() for spec in route_specs.DEFERRED_ROUTE_SPECS)
    assert all(spec.contract_status == "deferred" for spec in route_specs.DEFERRED_ROUTE_SPECS)


def test_case_response_models_reject_contract_drift() -> None:
    contracts = importlib.import_module("app.contracts.consultation_case")
    case = {
        "case_id": "case_123",
        "owner_id": "usr_123",
        "title": "Intersection collision",
        "case_type": "accident_fault",
        "status": "awaiting_fact_confirmation",
        "risk_level": "standard",
        "location": {},
        "current_fact_version": 0,
        "current_report_version": 0,
        "created_at": "2026-07-13T00:00:00+00:00",
        "updated_at": "2026-07-13T00:00:00+00:00",
    }

    response = contracts.CreateConsultationCaseResponse.model_validate(
        {
            "contract_version": "consultation_case.v2",
            "case": case,
        }
    )
    assert response.case.case_id == "case_123"

    with pytest.raises(ValidationError):
        contracts.CreateConsultationCaseResponse.model_validate(
            {
                "contract_version": "wrong-version",
                "case": case,
            }
        )


def test_case_success_models_reject_nested_contract_drift() -> None:
    contracts = importlib.import_module("app.contracts.consultation_case")
    case = {
        "case_id": "case_123",
        "owner_id": "usr_123",
        "title": "Intersection collision",
        "case_type": "accident_fault",
        "status": "awaiting_fact_confirmation",
        "risk_level": "standard",
        "location": {"city": "Seoul"},
        "current_fact_version": 0,
        "current_report_version": 0,
        "created_at": "2026-07-13T00:00:00+00:00",
        "updated_at": "2026-07-13T00:00:00+00:00",
    }
    fact_version = {
        "schema_version": "confirmed_facts.v1",
        "fact_version_id": "fact_123",
        "case_id": "case_123",
        "version_no": 1,
        "status": "confirmed",
        "facts": {"road_layout": "intersection"},
        "sources": [],
        "conflicts": [],
        "user_edit_history": [],
        "confirmed_by": "usr_123",
        "confirmed_at": "2026-07-13T00:01:00+00:00",
    }

    contracts.CreateConsultationCaseResponse.model_validate(
        {"contract_version": "consultation_case.v2", "case": case}
    )
    contracts.ConsultationCaseWorkspaceResponse.model_validate(
        {
            "workspace": {
                "contract_version": "case_workspace.v2",
                "case": case,
                "consultation_state": {},
                "confirmed_facts": [fact_version],
                "case_evidence": {
                    "schema_version": "case_evidence.v1",
                    "facts": {},
                    "claims": {},
                    "unknowns": [],
                    "evidence_source": {},
                },
                "analysis_jobs": [
                    {
                        "job_id": "job_123",
                        "status": "queued",
                        "active_node": "text_ml_case_search",
                        "updated_at": "2026-07-13T00:02:00+00:00",
                    }
                ],
                "reports": [
                    {
                        "report_id": "rep_123",
                        "report_type": "fault_ratio_analysis",
                        "version_no": 1,
                        "status": "ready",
                    }
                ],
                "attachments": [
                    {
                        "attachment_id": "att_123",
                        "status": "ready",
                        "purpose": "supporting_evidence",
                        "retention_expires_at": "2027-07-13T00:00:00+00:00",
                    }
                ],
            }
        }
    )
    contracts.StartCaseAnalysisResponse.model_validate(
        {
            "contract_version": "case_analysis_job.v2",
            "job": {"job_id": "job_123", "status": "queued"},
            "work_item": {"work_item_id": "work_123", "status": "queued"},
            "analysis_plan": {
                "plan_id": "plan_123",
                "node_codes": ["text_ml_case_search", "law_ground_search"],
            },
        }
    )

    with pytest.raises(ValidationError):
        contracts.CreateConsultationCaseResponse.model_validate(
            {
                "contract_version": "consultation_case.v2",
                "case": {**case, "unexpected_internal_field": "leak"},
            }
        )
    with pytest.raises(ValidationError):
        contracts.CreateConsultationCaseResponse.model_validate(
            {
                "contract_version": "consultation_case.v2",
                "case": {**case, "status": "made_up_status"},
            }
        )
    with pytest.raises(ValidationError):
        contracts.ConfirmCaseFactsResponse.model_validate(
            {
                "contract_version": "confirmed_facts.v1",
                "fact_version": {**fact_version, "fact_version_id": ""},
            }
        )
    with pytest.raises(ValidationError):
        contracts.StartCaseAnalysisResponse.model_validate(
            {
                "contract_version": "case_analysis_job.v2",
                "job": {"job_id": "job_123", "status": "unknown"},
                "work_item": {"work_item_id": "work_123", "status": "queued"},
                "analysis_plan": {"plan_id": "plan_123", "node_codes": []},
            }
        )


def test_case_error_response_model_accepts_live_envelopes_and_rejects_code_drift() -> None:
    contracts = importlib.import_module("app.contracts.consultation_case")

    envelopes = (
        {
            "error": {
                "contract_version": "login_required.v1",
                "type": "authorization",
                "code": "login_required",
                "status": 403,
                "message": "Login is required.",
                "required_action": "login",
                "action": "case_access",
                "reason": "case_requires_authenticated_user",
                "policy_version": "consultation_case_policy.v2",
                "subject": {"subject_type": "anonymous"},
            }
        },
        {
            "error": {
                "contract_version": "request_validation_error.v1",
                "type": "validation",
                "code": "validation_error",
                "status": 422,
                "message": "Check the request fields.",
                "details": [
                    {
                        "field": "session_id",
                        "type": "missing",
                        "message": "Field required",
                    }
                ],
            }
        },
        {
            "error": {
                "contract_version": "consultation_case_error.v2",
                "type": "case",
                "code": "case_conflict",
                "status": 409,
                "message": "Case state conflicts with the request.",
                "details": {"case_id": "case_123"},
            }
        },
        {
            "error": {
                "contract_version": "object_access.v1",
                "type": "object_access",
                "code": "object_access_denied",
                "status": 403,
                "message": "Access denied.",
                "required_action": "login_or_owner_match",
                "access": {"allowed": False, "reason": "owner_mismatch"},
            }
        },
    )

    for envelope in envelopes:
        assert contracts.CaseApiErrorResponse.model_validate(envelope).root is not None

    drifted = {
        "error": {
            **envelopes[2]["error"],
            "code": "login_required",
        }
    }
    with pytest.raises(ValidationError):
        contracts.CaseApiErrorResponse.model_validate(drifted)
