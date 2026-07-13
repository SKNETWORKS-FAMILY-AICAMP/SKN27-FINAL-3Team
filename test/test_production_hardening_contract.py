from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_pytest_defaults_are_offline_and_live_tests_are_opt_in() -> None:
    config = read("pytest.ini")
    conftest = read("conftest.py")

    for marker in ("unit", "integration", "live", "aws"):
        assert f"{marker}:" in config
    assert "--run-live" in conftest
    assert "--run-aws" in conftest


def test_manual_optional_input_runner_is_not_collected_as_a_test() -> None:
    old_path = ROOT / "etl/fault_cases/src/review_case/search/schema_search/run_full_optional_input_test.py"
    new_path = ROOT / "etl/fault_cases/src/review_case/search/schema_search/run_full_optional_input_check.py"

    assert not old_path.exists()
    assert new_path.exists()


def test_runtime_dependencies_cover_production_server_auth_and_opensearch() -> None:
    requirements = read("requirements.txt").lower()

    for package in ("gunicorn", "pyjwt", "pydantic", "opensearch-py"):
        assert package in requirements


def test_docker_image_contains_all_runtime_code_and_uses_gunicorn() -> None:
    dockerfile = read("Dockerfile")

    for source in ("app", "backend", "ai", "etl", "storage"):
        assert f"COPY {source} ./{source}" in dockerfile
    assert "gunicorn" in dockerfile
    assert "runserver" not in dockerfile
    assert "USER app" in dockerfile
    assert "HEALTHCHECK" in dockerfile


def test_runtime_auth_and_frontend_do_not_expose_development_bypass_paths() -> None:
    settings = read("backend/config/settings.py")
    middleware = read("backend/config/middleware.py")
    auth_session = read("app/web/authSession.js")
    frontend = read("app/web/FrontendAppShell.jsx")
    api_client = read("app/web/apiClient.js")
    main = read("app/web/main.jsx")
    google_auth = read("app/services/google_auth_service.py")

    for removed_setting in (
        "MOCK_REQUIRE_AUTH",
        "GOOGLE_AUTH_ALLOW_MOCK",
        "APP_AUTH_ALLOW_MOCK_BEARER",
        "MockJwtAuthMiddleware",
    ):
        assert removed_setting not in settings
        assert removed_setting not in middleware
    assert "mock_google" not in auth_session
    assert "buildDevGoogle" not in auth_session
    assert "mock_google" not in google_auth
    assert "_google_auth_allow_mock" not in google_auth
    assert "hmac.new" not in google_auth
    assert "jwt.encode" in google_auth
    assert "jwt.decode" in google_auth
    assert '"mock"' not in frontend
    assert 'endsWith("/mock")' not in api_client
    assert "VITE_DEV_AUTH_TOKEN" not in main
    assert "AUTH_TOKEN_STORAGE_KEY" not in auth_session


def test_terraform_defines_the_approved_aws_managed_topology() -> None:
    terraform = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "infra/terraform").rglob("*.tf"))
    )

    required_resources = [
        "aws_cloudfront_distribution",
        "aws_lb",
        "aws_ecs_service",
        "aws_db_instance",
        "aws_elasticache_replication_group",
        "aws_opensearch_domain",
        "aws_s3_bucket",
        "aws_secretsmanager_secret",
        "aws_wafv2_web_acl",
        "aws_cloudwatch_metric_alarm",
    ]
    for resource in required_resources:
        assert f'resource "{resource}"' in terraform
    assert 'engine_version = "OpenSearch_3.5"' in terraform
    assert "multi_az" in terraform.lower()


def test_pull_request_gate_runs_offline_runtime_build_and_infrastructure_checks() -> None:
    workflow = read(".github/workflows/production-gate.yml")

    for command in (
        "python -m pytest",
        "backend/manage.py test chatbot",
        "npm run build",
        "ruff check",
        "terraform fmt -check",
        "terraform validate",
        "docker build",
    ):
        assert command in workflow
    assert "--run-live" not in workflow
    assert "--run-aws" not in workflow


def test_docker_runtime_exposes_repo_and_backend_python_packages() -> None:
    dockerfile = read("Dockerfile")

    assert "PYTHONPATH=/app:/app/backend" in dockerfile


def test_docker_frontend_proxy_host_is_allowed_by_backend() -> None:
    compose = read("docker-compose.yml")

    assert 'VITE_API_PROXY_TARGET: "http://backend:8000"' in compose
    match = re.search(r'DJANGO_ALLOWED_HOSTS:\s*"([^"]+)"', compose)
    assert match is not None
    allowed_hosts = {host.strip() for host in match.group(1).split(",")}
    assert "backend" in allowed_hosts


def test_docker_backend_waits_for_tcp_postgres_and_migrates_before_serving() -> None:
    compose = read("docker-compose.yml")
    backend_service = compose.split("\n  backend:\n", 1)[1].split("\n  frontend:\n", 1)[0]
    postgres_service = compose.split("\n  postgres:\n", 1)[1].split("\n  neo4j:\n", 1)[0]

    command_match = re.search(r'^    command: sh -c "([^"]+)"$', backend_service, re.MULTILINE)
    assert command_match is not None
    assert command_match.group(1).startswith(
        "python backend/manage.py migrate --noinput && exec gunicorn "
    )
    assert re.search(
        r"^    depends_on:\n(?:.*\n)*?^      postgres:\n^        condition: service_healthy$",
        backend_service,
        re.MULTILINE,
    )
    for dependency in ("redis", "neo4j"):
        assert re.search(
            rf"^      {dependency}:\n^        condition: service_started$",
            backend_service,
            re.MULTILINE,
        )
    assert "pg_isready -h 127.0.0.1 " in postgres_service
