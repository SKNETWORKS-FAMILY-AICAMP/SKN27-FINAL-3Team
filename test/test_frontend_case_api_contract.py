from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_case_route_catalog_matches_shadow_route_specs() -> None:
    catalog_path = ROOT / "app" / "web" / "caseApiRoutes.json"
    assert catalog_path.exists(), "frontend Case route catalog must exist"

    route_specs = importlib.import_module("app.contracts.api_route_specs")
    expected = {
        spec.operation_id: {
            "method": spec.method,
            "path": spec.path.removeprefix("/api/"),
        }
        for spec in route_specs.CASE_API_ROUTE_SPECS
    }
    actual = json.loads(catalog_path.read_text(encoding="utf-8"))

    assert actual == expected


def test_frontend_case_route_catalog_rendering_is_deterministic() -> None:
    module_path = ROOT / "app" / "contracts" / "frontend_case_routes.py"
    assert module_path.exists(), "frontend Case route generator must exist"

    generator = importlib.import_module("app.contracts.frontend_case_routes")
    first = generator.render_frontend_case_routes_json()
    second = generator.render_frontend_case_routes_json()

    assert first == second
    assert first.endswith("\n")
    assert json.loads(first) == generator.build_frontend_case_route_catalog()


def test_frontend_case_route_cli_detects_missing_and_stale_generated_file(
    tmp_path: Path,
) -> None:
    script = ROOT / "scripts" / "generate_frontend_case_routes.py"
    assert script.exists(), "frontend Case route generation CLI must exist"

    output = tmp_path / "caseApiRoutes.json"
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
    assert json.loads(output.read_text(encoding="utf-8"))["listConsultationCases"] == {
        "method": "GET",
        "path": "cases/",
    }

    current = subprocess.run(
        [*base_command, "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert current.returncode == 0

    output.write_text(output.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    stale = subprocess.run(
        [*base_command, "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert stale.returncode == 1
    assert "out of date" in stale.stderr


def test_repository_keeps_generated_frontend_case_routes_current_in_ci() -> None:
    generator = importlib.import_module("app.contracts.frontend_case_routes")
    generated_file = ROOT / "app" / "web" / "caseApiRoutes.json"
    workflow_file = ROOT / ".github" / "workflows" / "production-gate.yml"

    assert (
        generated_file.read_text(encoding="utf-8")
        == generator.render_frontend_case_routes_json()
    )
    workflow = yaml.safe_load(workflow_file.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["offline-verification"]["steps"]
    assert {
        "name": "Frontend Case route contract drift",
        "run": "python scripts/generate_frontend_case_routes.py --check",
    } in steps


def test_frontend_api_client_exposes_every_case_operation_from_the_catalog() -> None:
    api_client = (ROOT / "app" / "web" / "apiClient.js").read_text(encoding="utf-8")
    methods = {
        "listConsultationCases": "listConsultationCases",
        "createConsultationCase": "createConsultationCase",
        "getConsultationCaseWorkspace": "getConsultationCaseWorkspace",
        "confirmConsultationCaseFacts": "confirmConsultationCaseFacts",
        "startConsultationCaseAnalysis": "startConsultationCaseAnalysis",
    }

    assert 'import caseApiRoutes from "./caseApiRoutes.json";' in api_client
    assert "function requestCaseApi(" in api_client
    assert 'route.method === "GET"' in api_client
    assert 'route.method === "POST"' in api_client
    assert 'route.path.replace("{case_id}"' in api_client

    for method_name, operation_id in methods.items():
        assert f"{method_name}(" in api_client
        assert api_client.count(f'"{operation_id}"') == 1
