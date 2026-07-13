from __future__ import annotations

import importlib
from pathlib import Path
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_openapi_v1_is_generated_from_case_route_specs() -> None:
    module_path = ROOT / "app" / "contracts" / "openapi_v1.py"
    assert module_path.exists(), "OpenAPI v1 generator must exist"

    generator = importlib.import_module("app.contracts.openapi_v1")
    document = generator.build_openapi_document()

    assert document["openapi"] == "3.2.0"
    assert document["info"]["version"] == "1.0.0"
    assert document["x-contract-mode"] == "shadow"
    assert set(document["paths"]) == {
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

    for path_item in document["paths"].values():
        for operation in path_item.values():
            assert operation["x-contract-status"] == "shadow"
            assert operation["x-django-route-name"].startswith("canonical-consultation-")
            assert operation["security"] == [{"bearerAuth": []}]

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
    ):
        assert schema_name in schemas


def test_openapi_v1_yaml_rendering_is_deterministic_and_parseable() -> None:
    module_path = ROOT / "app" / "contracts" / "openapi_v1.py"
    assert module_path.exists(), "OpenAPI v1 generator must exist"

    generator = importlib.import_module("app.contracts.openapi_v1")
    first = generator.render_openapi_yaml()
    second = generator.render_openapi_yaml()

    assert first == second
    assert yaml.safe_load(first) == generator.build_openapi_document()
    assert "openapi-v0" not in first


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
