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
    assert route_specs.API_ROUTE_SPECS == route_specs.CASE_API_ROUTE_SPECS

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


def test_case_response_models_reject_contract_drift() -> None:
    contracts = importlib.import_module("app.contracts.consultation_case")

    response = contracts.CreateConsultationCaseResponse.model_validate(
        {
            "contract_version": "consultation_case.v2",
            "case": {"case_id": "case_123"},
        }
    )
    assert response.case["case_id"] == "case_123"

    with pytest.raises(ValidationError):
        contracts.CreateConsultationCaseResponse.model_validate(
            {
                "contract_version": "wrong-version",
                "case": {"case_id": "case_123"},
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
