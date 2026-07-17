from __future__ import annotations

import importlib
from pathlib import Path
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_openapi_v1_is_generated_from_promoted_route_specs() -> None:
    module_path = ROOT / "app" / "contracts" / "openapi_v1.py"
    assert module_path.exists(), "OpenAPI v1 generator must exist"

    generator = importlib.import_module("app.contracts.openapi_v1")
    document = generator.build_openapi_document()

    assert document["openapi"] == "3.2.0"
    assert document["info"]["version"] == "1.0.0"
    assert document["x-contract-mode"] == "shadow"
    assert set(document["paths"]) == {
        "/api/auth/guest-session/",
        "/api/auth/google/code/",
        "/api/auth/refresh/",
        "/api/auth/logout/",
        "/api/auth/me/",
        "/api/files/",
        "/api/files/{attachment_id}/",
        "/api/analysis/jobs/",
        "/api/analysis/jobs/{job_id}/",
        "/api/analysis/results/{job_id}/",
        "/api/cases/",
        "/api/cases/{case_id}/workspace/",
        "/api/cases/{case_id}/facts/confirm/",
        "/api/cases/{case_id}/analysis/jobs/",
    }

    case_collection = document["paths"]["/api/cases/"]
    assert set(case_collection) == {"get", "post"}
    assert case_collection["post"]["operationId"] == "createConsultationCase"
    assert case_collection["post"]["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CreateConsultationCaseRequest"
    }
    assert case_collection["post"]["responses"]["201"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/CreateConsultationCaseResponse"}
    assert case_collection["post"]["responses"]["403"] == {
        "description": "Typed API error response",
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/CaseApiErrorResponse"}
            }
        },
        "x-error-codes": ["login_required", "case_owner_mismatch"],
    }
    assert case_collection["post"]["responses"]["404"]["x-error-codes"] == [
        "case_not_found"
    ]
    assert case_collection["post"]["responses"]["409"]["x-error-codes"] == [
        "case_conflict"
    ]
    assert case_collection["post"]["responses"]["422"]["x-error-codes"] == [
        "validation_error"
    ]

    analysis_errors = document["paths"]["/api/cases/{case_id}/analysis/jobs/"]["post"][
        "responses"
    ]
    assert analysis_errors["409"]["x-error-codes"] == [
        "case_conflict",
        "confirmed_facts_required",
        "fact_readiness_not_met",
    ]

    for path, path_item in document["paths"].items():
        if path.startswith("/api/auth/"):
            continue
        for operation in path_item.values():
            assert operation["x-contract-status"] == "shadow"
            assert operation["x-django-route-name"].startswith("canonical-")
            expected_security = (
                [{}, {"bearerAuth": []}]
                if path.startswith(("/api/files/", "/api/analysis/"))
                else [{"bearerAuth": []}]
            )
            assert operation["security"] == expected_security

    schemas = document["components"]["schemas"]
    for schema_name in (
        "CreateConsultationCaseRequest",
        "CreateConsultationCaseResponse",
        "ConsultationCaseListResponse",
        "ConsultationCaseWorkspaceResponse",
        "ConfirmCaseFactsRequest",
        "ConfirmCaseFactsResponse",
        "StartCaseAnalysisRequest",
        "StartCaseAnalysisResponse",
        "CaseApiErrorResponse",
        "GuestSessionRequest",
        "GuestSessionResponse",
        "GoogleAuthorizationCodeRequest",
        "GoogleAuthorizationCodeResponse",
        "AuthTokenRefreshRequest",
        "AuthTokenRefreshResponse",
        "AuthLogoutRequest",
        "AuthLogoutResponse",
        "AuthSubjectResponse",
        "AuthErrorResponse",
        "RateLimitErrorResponse",
        "FileUploadRequest",
        "FileAttachmentResponse",
        "FileAttachmentListResponse",
        "FileAttachmentDetailResponse",
        "FileUploadValidationErrorResponse",
        "FileUploadTooLargeErrorResponse",
        "FileAttachmentNotFoundErrorResponse",
        "AnalysisJobRequest",
        "AnalysisJobAcceptedResponse",
        "AnalysisJobListResponse",
        "AnalysisJobDetailResponse",
        "AnalysisResultResponse",
    ):
        assert schema_name in schemas


def test_auth_session_routes_document_runtime_auth_boundary() -> None:
    generator = importlib.import_module("app.contracts.openapi_v1")
    document = generator.build_openapi_document()
    paths = document["paths"]

    guest_session = paths["/api/auth/guest-session/"]["post"]
    assert guest_session["operationId"] == "createGuestSession"
    assert guest_session["security"] == []
    assert guest_session["requestBody"]["required"] is False

    google_code = paths["/api/auth/google/code/"]["post"]
    assert google_code["operationId"] == "exchangeGoogleAuthorizationCode"
    assert google_code["security"] == []
    assert google_code["parameters"] == [
        {
            "name": "Origin",
            "in": "header",
            "required": True,
            "description": "Exact frontend origin configured for Google code exchange.",
            "schema": {"type": "string", "format": "uri"},
        },
        {
            "name": "X-Requested-With",
            "in": "header",
            "required": True,
            "description": "Browser request marker required before Google provider exchange.",
            "schema": {"type": "string", "enum": ["XmlHttpRequest"]},
        },
    ]
    assert google_code["responses"]["429"]["x-error-codes"] == [
        "rate_limit_exceeded"
    ]

    for path in ("/api/auth/refresh/", "/api/auth/logout/"):
        operation = paths[path]["post"]
        assert operation["security"] == [{}, {"bearerAuth": []}]
        assert operation["requestBody"]["required"] is False
        assert operation["responses"]["401"]["x-error-codes"] == [
            "auth_required",
            "token_invalid",
            "token_expired",
        ]

    current_subject = paths["/api/auth/me/"]["get"]
    assert current_subject["operationId"] == "getCurrentAuthSubject"
    assert current_subject["security"] == [{}, {"bearerAuth": []}]
    assert current_subject["parameters"] == [
        {
            "name": "X-Guest-Id",
            "in": "header",
            "required": False,
            "description": "Optional guest identity header when no Bearer token is supplied.",
            "schema": {"type": "string"},
        },
        {
            "name": "guest_id",
            "in": "query",
            "required": False,
            "description": "Optional query fallback for the guest identity.",
            "schema": {"type": "string"},
        },
        {
            "name": "session_id",
            "in": "query",
            "required": False,
            "description": "Optional chat session binding identifier.",
            "schema": {"type": "string"},
        },
    ]
    assert current_subject["responses"]["401"]["x-error-codes"] == [
        "token_invalid",
        "token_expired",
    ]


def test_file_routes_document_canonical_upload_and_owner_boundary() -> None:
    generator = importlib.import_module("app.contracts.openapi_v1")
    document = generator.build_openapi_document()
    paths = document["paths"]

    collection = paths["/api/files/"]
    assert set(collection) == {"get", "post"}
    upload = collection["post"]
    assert upload["operationId"] == "uploadFileAttachment"
    assert upload["security"] == [{}, {"bearerAuth": []}]
    assert set(upload["requestBody"]["content"]) == {
        "application/json",
        "multipart/form-data",
    }
    assert upload["requestBody"]["content"]["multipart/form-data"]["schema"] == {
        "$ref": "#/components/schemas/FileUploadRequest"
    }
    assert upload["responses"]["400"]["x-error-codes"] == [
        "session_id_required"
    ]
    assert upload["responses"]["413"]["x-error-codes"] == ["file_too_large"]
    assert upload["responses"]["429"]["x-error-codes"] == [
        "rate_limit_exceeded"
    ]
    assert upload["responses"]["503"]["x-error-codes"] == [
        "upload_storage_unavailable"
    ]

    file_detail = paths["/api/files/{attachment_id}/"]["get"]
    assert file_detail["operationId"] == "getFileAttachment"
    assert file_detail["parameters"][0] == {
        "name": "attachment_id",
        "in": "path",
        "required": True,
        "description": "Canonical uploaded-file identifier",
        "schema": {"type": "string", "minLength": 1, "maxLength": 128},
    }
    assert file_detail["responses"]["403"]["x-error-codes"] == [
        "object_access_denied"
    ]
    assert file_detail["responses"]["404"]["x-error-codes"] == [
        "attachment_not_found"
    ]


def test_analysis_job_routes_document_async_owner_scoped_contract() -> None:
    generator = importlib.import_module("app.contracts.openapi_v1")
    paths = generator.build_openapi_document()["paths"]

    jobs = paths["/api/analysis/jobs/"]
    assert set(jobs) == {"get", "post"}
    assert jobs["post"]["operationId"] == "queueAnalysisJob"
    assert jobs["post"]["security"] == [{}, {"bearerAuth": []}]
    assert jobs["post"]["responses"]["202"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AnalysisJobAcceptedResponse"
    }
    assert jobs["post"]["responses"]["400"]["x-error-codes"] == [
        "analysis_job_session_required",
        "chat_input_rejected",
    ]
    assert jobs["post"]["responses"]["409"]["x-error-codes"] == [
        "analysis_plan_not_executable",
        "attachment_scan_blocked",
        "analysis_job_id_conflict",
        "analysis_job_reservation_pending",
    ]

    detail = paths["/api/analysis/jobs/{job_id}/"]["get"]
    assert detail["parameters"][0]["name"] == "job_id"
    assert detail["responses"]["404"]["x-error-codes"] == ["analysis_job_not_found"]

    result = paths["/api/analysis/results/{job_id}/"]["get"]
    assert result["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AnalysisResultResponse"
    }
    assert result["responses"]["202"]["description"] == "Successful response"
    assert result["responses"]["404"]["x-error-codes"] == ["analysis_result_not_found"]


def test_openapi_v1_yaml_rendering_is_deterministic_and_parseable() -> None:
    module_path = ROOT / "app" / "contracts" / "openapi_v1.py"
    assert module_path.exists(), "OpenAPI v1 generator must exist"

    generator = importlib.import_module("app.contracts.openapi_v1")
    first = generator.render_openapi_yaml()
    second = generator.render_openapi_yaml()

    assert first == second
    assert yaml.safe_load(first) == generator.build_openapi_document()
    assert "openapi-v0" not in first


def test_case_success_schemas_are_structural_in_openapi() -> None:
    generator = importlib.import_module("app.contracts.openapi_v1")
    schemas = generator.build_openapi_document()["components"]["schemas"]

    expected_properties = {
        "ConsultationCaseRecord": {
            "case_id",
            "owner_id",
            "title",
            "case_type",
            "status",
            "risk_level",
            "location",
            "current_fact_version",
            "current_report_version",
            "created_at",
            "updated_at",
        },
        "ConfirmedFactRecord": {
            "schema_version",
            "fact_version_id",
            "case_id",
            "version_no",
            "status",
            "facts",
            "sources",
            "conflicts",
            "user_edit_history",
            "confirmed_by",
            "confirmed_at",
        },
        "CaseWorkspace": {
            "contract_version",
            "case",
            "consultation_state",
            "confirmed_facts",
            "case_evidence",
            "analysis_jobs",
            "reports",
            "attachments",
        },
        "CaseAnalysisJob": {"job_id", "status"},
        "CaseAnalysisWorkItem": {"work_item_id", "status"},
        "CaseAnalysisPlanSummary": {"plan_id", "node_codes"},
    }

    for schema_name, properties in expected_properties.items():
        schema = schemas[schema_name]
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == properties


def test_path_parameters_are_declared_by_route_specs_not_case_id_special_cases() -> None:
    route_specs = importlib.import_module("app.contracts.api_route_specs")
    contracts = importlib.import_module("app.contracts.consultation_case")
    generator = importlib.import_module("app.contracts.openapi_v1")

    spec = route_specs.RouteSpec(
        operation_id="getAnalysisResultContractProbe",
        method="GET",
        path="/api/analysis/results/{job_id}/",
        route_name="canonical-analysis-result",
        view_name="analysis_result",
        request_model=None,
        response_model=contracts.StartCaseAnalysisResponse,
        success_status=200,
        errors=(),
        auth_required=True,
        contract_status="shadow",
        tags=("Analysis",),
        summary="Contract probe",
        path_parameters=(
            route_specs.PathParameterSpec(
                name="job_id",
                description="Canonical analysis job identifier",
                max_length=64,
            ),
        ),
    )

    operation = generator.build_openapi_document((spec,))["paths"][spec.path]["get"]

    assert operation["parameters"] == [
        {
            "name": "job_id",
            "in": "path",
            "required": True,
            "description": "Canonical analysis job identifier",
            "schema": {"type": "string", "minLength": 1, "maxLength": 64},
        }
    ]


def test_openapi_v1_cli_detects_missing_and_stale_generated_file(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "generate_openapi_v1.py"
    assert script.exists(), "OpenAPI v1 generation CLI must exist"

    output = tmp_path / "openapi-v1.yaml"
    base_command = [sys.executable, str(script), "--output", str(output)]

    missing = subprocess.run(
        [*base_command, "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 1
    assert "out of date" in missing.stderr

    generated = subprocess.run(
        base_command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert generated.returncode == 0
    assert yaml.safe_load(output.read_text(encoding="utf-8"))["info"]["version"] == "1.0.0"

    current = subprocess.run(
        [*base_command, "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert current.returncode == 0

    output.write_text(output.read_text(encoding="utf-8") + "# stale\n", encoding="utf-8")
    stale = subprocess.run(
        [*base_command, "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert stale.returncode == 1
    assert "out of date" in stale.stderr


def test_repository_keeps_generated_openapi_v1_current_in_ci() -> None:
    generator = importlib.import_module("app.contracts.openapi_v1")
    generated_file = ROOT / "docs" / "api" / "openapi-v1.yaml"
    workflow_file = ROOT / ".github" / "workflows" / "production-gate.yml"

    assert generated_file.read_text(encoding="utf-8") == generator.render_openapi_yaml()
    workflow = yaml.safe_load(workflow_file.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["offline-verification"]["steps"]
    assert {
        "name": "OpenAPI v1 contract drift",
        "run": "python scripts/generate_openapi_v1.py --check",
    } in steps
