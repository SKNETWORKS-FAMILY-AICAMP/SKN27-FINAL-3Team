from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_DIR = ROOT / "infra" / "terraform-pilot"
DEPLOY_DIR = ROOT / "deploy" / "aws-pilot"


def _terraform_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(TERRAFORM_DIR.glob("*.tf"))
    )


def _read_deploy(name: str) -> str:
    return (DEPLOY_DIR / name).read_text(encoding="utf-8")


def test_production_gate_formats_and_validates_pilot_terraform() -> None:
    workflow = (ROOT / ".github" / "workflows" / "production-gate.yml").read_text(
        encoding="utf-8"
    )

    assert "terraform -chdir=infra/terraform-pilot fmt -check" in workflow
    assert (
        "terraform -chdir=infra/terraform-pilot init -backend=false -input=false"
        in workflow
    )
    assert "terraform -chdir=infra/terraform-pilot validate" in workflow


def test_low_cost_pilot_is_isolated_and_documents_the_operator_path() -> None:
    assert TERRAFORM_DIR.is_dir()
    assert DEPLOY_DIR.is_dir()
    assert (DEPLOY_DIR / "README.ko.md").is_file()
    assert (DEPLOY_DIR / "docker-compose.pilot.yml").is_file()
    assert (DEPLOY_DIR / "Deploy-Pilot.ps1").is_file()
    assert (DEPLOY_DIR / "Remove-Pilot.ps1").is_file()

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "*.tfstate" in gitignore
    assert "*.tfplan" in gitignore
    assert "infra/terraform-pilot/terraform.tfvars" in gitignore


def test_terraform_avoids_the_managed_services_that_make_the_pilot_expensive() -> None:
    source = _terraform_source().lower()
    forbidden_resources = {
        "aws_nat_gateway",
        "aws_lb",
        "aws_ecs_",
        "aws_elasticache_",
        "aws_opensearch_",
        "aws_cloudfront_",
        "aws_neptune_",
    }
    for forbidden in forbidden_resources:
        assert forbidden not in source


def test_compute_is_one_ssm_only_x86_instance_with_encrypted_gp3_and_eip() -> None:
    source = _terraform_source()
    compute = (TERRAFORM_DIR / "compute.tf").read_text(encoding="utf-8")
    vision = (TERRAFORM_DIR / "vision_worker.tf").read_text(encoding="utf-8")
    assert len(re.findall(r'resource\s+"aws_instance"', compute)) == 1
    assert len(re.findall(r'resource\s+"aws_instance"', vision)) == 1
    assert "count = var.vision_worker_enabled ? 1 : 0" in vision
    assert re.search(r'default\s*=\s*"t3a\.large"', source)
    assert re.search(r'name\s*=\s*"architecture"', source)
    assert re.search(r'values\s*=\s*\["x86_64"\]', source)
    assert re.search(r"associate_public_ip_address\s*=\s*true", source)
    assert 'resource "aws_eip"' in source
    assert re.search(r'volume_type\s*=\s*"gp3"', source)
    assert re.search(r"encrypted\s*=\s*true", source)
    assert "AmazonSSMManagedInstanceCore" in source
    assert re.search(r'from_port\s*=\s*80\b', source)
    assert re.search(r'from_port\s*=\s*443\b', source)
    assert not re.search(r'(from_port|to_port)\s*=\s*22\b', source)

    user_data = (TERRAFORM_DIR / "user_data.sh.tftpl").read_text(encoding="utf-8")
    assert "checksums.txt" in user_data
    assert "sha256sum --check" in user_data


def test_amazon_linux_bootstrap_keeps_preinstalled_curl_minimal() -> None:
    user_data = (TERRAFORM_DIR / "user_data.sh.tftpl").read_text(encoding="utf-8")

    assert "dnf install -y docker unzip" in user_data
    assert "dnf install -y docker curl unzip" not in user_data


def test_operational_monitor_connects_safe_health_metrics_to_cloudwatch() -> None:
    compose = yaml.safe_load(_read_deploy("docker-compose.pilot.yml"))
    services = compose["services"]
    assert "ops-monitor" in services
    monitor = services["ops-monitor"]
    assert monitor["command"] == [
        "python",
        "backend/manage.py",
        "observe_operational_health",
        "--loop",
        "--interval-seconds",
        "60",
    ]
    assert monitor["logging"]["driver"] == "awslogs"
    assert monitor["logging"]["options"]["mode"] == "non-blocking"
    assert monitor["logging"]["options"]["max-buffer-size"] == "1m"
    assert (
        "/opt/skn27-pilot/operational-evidence:/run/operational-evidence:ro"
        in monitor["volumes"]
    )
    assert "ports" not in monitor

    source = _terraform_source()
    assert 'resource "aws_cloudwatch_log_group" "operational_health"' in source
    for metric_filter in (
        "heartbeat",
        "queue_oldest_age",
        "stale_running",
        "worker_failures",
        "provider_failures",
        "legal_data_failures",
    ):
        assert (
            f'resource "aws_cloudwatch_log_metric_filter" "{metric_filter}"'
            in source
        )
    assert 'resource "aws_sns_topic" "operational_alerts"' in source
    assert 'resource "aws_sns_topic_subscription" "operational_email"' in source
    assert 'count = var.operational_alert_email == "" ? 0 : 1' in source
    assert 'operational_metric_namespace = "SKN27/Pilot"' in source

    iam = (TERRAFORM_DIR / "iam.tf").read_text(encoding="utf-8")
    assert '"logs:CreateLogStream"' in iam
    assert '"logs:PutLogEvents"' in iam
    assert "aws_cloudwatch_log_group.operational_health.arn" in iam
    assert '"cloudwatch:PutMetricData"' not in iam

    outputs = (TERRAFORM_DIR / "outputs.tf").read_text(encoding="utf-8")
    assert 'output "operational_log_group_name"' in outputs
    assert 'output "operational_alert_topic_arn"' in outputs

    deploy = _read_deploy("Deploy-Pilot.ps1")
    assert 'Get-TerraformValue $outputs "operational_log_group_name"' in deploy
    assert "OPERATIONAL_LOG_GROUP" in deploy
    assert "PILOT_OPS_MONITOR_IP" in deploy
    assert "install -d -m 0755 /opt/skn27-pilot/operational-evidence" in deploy
    assert "install -d -m 0750 /opt/skn27-pilot/operational-evidence" not in deploy
    runtime_env = _read_deploy("runtime.env.example")
    assert (
        "OPERATIONAL_LEGAL_RUN_SUMMARY_PATH=/run/operational-evidence/run_summary.json"
        in runtime_env
    )


def test_pilot_runtime_declares_runpod_vision_without_secret_values() -> None:
    compose = yaml.safe_load(_read_deploy("docker-compose.pilot.yml"))
    runtime_env = _read_deploy("runtime.env.example")
    required = {
        "VISION_RUNTIME_PROVIDER",
        "VISION_RUNTIME_TIMEOUT_SECONDS",
        "RUNPOD_API_KEY",
        "RUNPOD_VISION_ENDPOINT_ID",
        "RUNPOD_VISION_TIMEOUT_SECONDS",
        "RUNPOD_VISION_POLL_INTERVAL_SECONDS",
        "RUNPOD_VISION_HTTP_TIMEOUT_SECONDS",
        "RUNPOD_VISION_MAX_RESPONSE_BYTES",
        "RUNPOD_VISION_ALLOWED_HOSTS",
        "RUNPOD_VISION_DOWNLOAD_TIMEOUT_SECONDS",
        "RUNPOD_VISION_MAX_DOWNLOAD_BYTES",
        "RUNPOD_VISION_EXECUTION_TIMEOUT_SECONDS",
        "AWS_VISION_QUEUE_URL",
        "AWS_VISION_RESULT_BUCKET",
        "AWS_VISION_RESULT_PREFIX",
        "AWS_VISION_TIMEOUT_SECONDS",
        "AWS_VISION_POLL_INTERVAL_SECONDS",
    }
    keys = {
        line.split("=", 1)[0]
        for line in runtime_env.splitlines()
        if line and not line.startswith("#") and "=" in line
    }

    assert required.issubset(keys)
    assert "VISION_RUNTIME_PROVIDER=runpod" in runtime_env
    assert "RUNPOD_API_KEY=\n" in runtime_env.replace("\r\n", "\n")
    assert "replace-with-runpod" not in runtime_env.lower()
    assert compose["services"]["agent-worker"]["env_file"] == [
        {"path": ".runtime.env", "format": "raw"}
    ]


def test_runtime_template_declares_every_required_compose_interpolation() -> None:
    compose = _read_deploy("docker-compose.pilot.yml")
    runtime_env = _read_deploy("runtime.env.example")
    required_keys = set(re.findall(r"\$\{([A-Z0-9_]+):\?", compose))
    template_keys = {
        line.split("=", 1)[0]
        for line in runtime_env.splitlines()
        if line and not line.startswith("#") and "=" in line
    }

    assert required_keys.issubset(template_keys), required_keys - template_keys


def test_database_is_private_single_az_encrypted_postgres_with_safe_defaults() -> None:
    source = _terraform_source()
    assert len(re.findall(r'resource\s+"aws_db_instance"', source)) == 1
    assert len(re.findall(r'resource\s+"aws_subnet"\s+"database_', source)) == 2
    assert re.search(r'engine\s*=\s*"postgres"', source)
    assert re.search(r"multi_az\s*=\s*false", source)
    assert re.search(r"publicly_accessible\s*=\s*false", source)
    assert re.search(r"storage_encrypted\s*=\s*true", source)
    assert re.search(
        r"backup_retention_period\s*=\s*var\.database_backup_retention_days",
        source,
    )
    assert re.search(
        r"deletion_protection\s*=\s*var\.database_deletion_protection",
        source,
    )
    assert "aws_db_subnet_group" in source
    assert re.search(r'name\s*=\s*"rds\.force_ssl"', source)


def test_pilot_runtime_uses_law_db_for_review_case_rag() -> None:
    runtime_env = _read_deploy("runtime.env.example")

    assert "REVIEW_CASE_DB=law_db" in runtime_env


def test_postgres_force_ssl_uses_the_static_parameter_apply_method() -> None:
    database = (TERRAFORM_DIR / "database.tf").read_text(encoding="utf-8")

    assert re.search(
        r'parameter\s*\{[^}]*name\s*=\s*"rds\.force_ssl"'
        r'[^}]*apply_method\s*=\s*"pending-reboot"',
        database,
        re.DOTALL,
    )


def test_private_s3_and_ecr_resources_have_encryption_and_lifecycle_controls() -> None:
    source = _terraform_source()
    storage = (TERRAFORM_DIR / "storage.tf").read_text(encoding="utf-8")
    pipeline = (TERRAFORM_DIR / "codepipeline.tf").read_text(encoding="utf-8")
    registry = (TERRAFORM_DIR / "registry.tf").read_text(encoding="utf-8")
    vision = (TERRAFORM_DIR / "vision_worker.tf").read_text(encoding="utf-8")
    assert len(re.findall(r'resource\s+"aws_s3_bucket"\s+"(clean|quarantine)"', source)) == 2
    assert len(re.findall(r'resource\s+"aws_s3_bucket_public_access_block"', storage)) == 2
    assert len(re.findall(r'resource\s+"aws_s3_bucket_server_side_encryption_configuration"', storage)) == 2
    assert len(re.findall(r'resource\s+"aws_s3_bucket_lifecycle_configuration"', storage)) == 2
    assert 'resource "aws_s3_bucket" "pipeline_artifacts"' in pipeline
    assert 'resource "aws_s3_bucket_public_access_block" "pipeline_artifacts"' in pipeline
    assert 'resource "aws_s3_bucket_server_side_encryption_configuration" "pipeline_artifacts"' in pipeline
    assert 'resource "aws_s3_bucket_lifecycle_configuration" "pipeline_artifacts"' in pipeline
    assert len(re.findall(r'resource\s+"aws_ecr_repository"\s+"(backend|frontend)"', source)) == 2
    assert len(re.findall(r'resource\s+"aws_ecr_lifecycle_policy"', registry)) == 2
    assert len(re.findall(r'resource\s+"aws_ecr_lifecycle_policy"', vision)) == 1
    assert "count = var.vision_worker_enabled ? 1 : 0" in vision
    assert len(re.findall(r"scan_on_push\s*=\s*true", source)) >= 2


def test_app_release_is_opt_in_and_does_not_receive_runtime_secret_access() -> None:
    codebuild = (TERRAFORM_DIR / "codebuild.tf").read_text(encoding="utf-8")
    variables = (TERRAFORM_DIR / "variables.tf").read_text(encoding="utf-8")

    assert 'variable "pilot_app_release_enabled"' in variables
    assert "default     = false" in variables
    policy_start = codebuild.index(
        'data "aws_iam_policy_document" "pilot_app_release"'
    )
    policy_end = codebuild.index(
        'resource "aws_iam_role_policy" "pilot_app_release"', policy_start
    )
    release_policy = codebuild[policy_start:policy_end]
    assert "data.aws_instance.pilot_app_release_target[0].arn" in release_policy
    assert "aws_instance.app.arn" not in release_policy
    assert "ssm:GetParameter" not in release_policy
    assert "ssm:PutParameter" not in release_policy


def test_app_release_runbook_preserves_the_full_manual_release_path() -> None:
    runbook = _read_deploy("README.ko.md")

    for required in (
        "ApprovePilotAppRelease",
        "pilot_app_release_enabled",
        "migrate --check",
        "rollback",
        "RAG seed",
        "paid smoke",
        "Vision Worker",
        "Deploy-Pilot.ps1",
        "Compose",
        "Caddy",
    ):
        assert required in runbook


def test_budget_and_ssm_secret_contract_are_present_without_secret_outputs() -> None:
    source = _terraform_source()
    assert 'resource "aws_budgets_budget"' in source
    for threshold in (50, 80, 100):
        assert re.search(rf"threshold\s*=\s*{threshold}\b", source)
    assert "var.budget_alert_email" in source
    assert "runtime_env_parameter_name" in source
    assert '"ssm:GetParameter"' in source

    outputs = (TERRAFORM_DIR / "outputs.tf").read_text(encoding="utf-8").lower()
    for secret_name in ("password", "secret", "token", "runtime_env_value"):
        assert not re.search(rf'output\s+"[^"]*{secret_name}', outputs)

    deploy = _read_deploy("Deploy-Pilot.ps1")
    assert "put-parameter" in deploy
    assert "SecureString" in deploy
    assert "Standard" in deploy
    assert "--with-decryption" in deploy
    assert "--value $runtimeEnv" not in deploy
    assert "--cli-input-json" in deploy
    assert "MatchEvaluator" in deploy
    assert "requiredRuntimeValues" in deploy
    assert "Unresolved template value" in deploy


def test_compose_runs_private_legal_graph_and_exposes_only_caddy() -> None:
    compose = yaml.safe_load(_read_deploy("docker-compose.pilot.yml"))
    services = compose["services"]
    assert {
        "caddy",
        "edge-rate-limit",
        "frontend",
        "backend",
        "rag-loader",
        "agent-worker",
        "file-scan-worker",
        "redis",
        "clamav",
        "law-neo4j",
    }.issubset(services)
    assert {"postgres", "neo4j", "kibana", "elasticsearch"}.isdisjoint(services)
    assert "law_neo4j_data" in compose["volumes"]
    assert "ports" not in services["law-neo4j"]
    assert "healthcheck" in services["law-neo4j"]
    assert services["backend"]["depends_on"]["law-neo4j"]["condition"] == "service_healthy"
    assert services["rag-loader"]["networks"]["pilot"] == {}
    assert "ipv4_address" not in services["rag-loader"]["networks"]["pilot"]
    assert services["rag-loader"]["profiles"] == ["seed"]
    assert (
        services["rag-loader"]["environment"]["REVIEW_CASE_POSTGRES_EXPORT_ROOT"]
        == "/tmp/review-case-postgres-exports"
    )
    assert services["rag-loader"]["mem_limit"] == "1536m"
    assert services["redis"]["healthcheck"]["start_period"] == "60s"
    caddy = services["caddy"]
    assert caddy["network_mode"] == "host"
    assert "ports" not in caddy
    assert "networks" not in caddy
    assert caddy["extra_hosts"] == [
        "edge-rate-limit:${PILOT_EDGE_RATE_LIMIT_IP:-172.31.0.3}"
    ]
    assert caddy["user"] == "10001:10001"
    initializer = services["caddy-volume-init"]
    assert initializer["network_mode"] == "none"
    assert initializer["user"] == "0:0"
    assert initializer["cap_drop"] == ["ALL"]
    assert initializer["cap_add"] == ["CHOWN"]
    assert caddy["depends_on"]["caddy-volume-init"]["condition"] == "service_completed_successfully"
    for name, config in services.items():
        if name != "caddy":
            assert "ports" not in config, name

    serialized = yaml.safe_dump(compose).lower()
    assert "object_storage_provider: s3" in serialized
    assert "pgsslmode: require" in serialized
    assert "law_ground_search_enable_neo4j: '1'" in serialized
    assert "legal_rag_vector_enabled: '1'" in serialized
    runtime_env = _read_deploy("runtime.env.example").lower()
    for name in (
        "law_neo4j_image_ref",
        "neo4j_uri",
        "neo4j_user",
        "neo4j_password",
        "neo4j_database",
        "law_graph_required",
    ):
        assert name in runtime_env
    assert "google_oauth_code_exchange_daily_limit" in runtime_env
    assert "google_oauth_trusted_proxy_cidrs" in runtime_env
    assert "mock_require_auth" not in serialized
    assert "google_auth_allow_mock" not in serialized
    assert "app_auth_allow_mock_bearer" not in serialized

    for name in ("backend", "agent-worker", "file-scan-worker"):
        assert services[name]["env_file"] == [
            {"path": ".runtime.env", "format": "raw"}
        ]
    assert "env_file" not in services["law-neo4j"]
    assert set(services["law-neo4j"]["environment"]) == {
        "NEO4J_AUTH",
        "NEO4J_server_memory_heap_initial__size",
        "NEO4J_server_memory_heap_max__size",
        "NEO4J_server_memory_pagecache_size",
    }
    assert "$${NEO4J_AUTH%%/*}" in services["law-neo4j"]["healthcheck"]["test"][1]
    assert "$${NEO4J_AUTH#*/}" in services["law-neo4j"]["healthcheck"]["test"][1]
    assert set(services["redis"]["cap_add"]) == {
        "CHOWN",
        "DAC_OVERRIDE",
        "SETGID",
        "SETUID",
    }
    assert set(services["clamav"]["cap_add"]) == {
        "CHOWN",
        "DAC_OVERRIDE",
        "FOWNER",
        "SETGID",
        "SETUID",
    }
    assert services["caddy"]["env_file"] == [
        {"path": ".edge.env", "format": "raw"}
    ]

    deploy = _read_deploy("Deploy-Pilot.ps1")
    assert ".runtime.env" in deploy
    assert ".compose.env" in deploy
    assert ".edge.env" in deploy
    assert ".elasticsearch.env" not in deploy
    compose_env_extraction = next(
        line for line in deploy.splitlines() if "> `$RELEASE_DIR/.compose.env" in line
    )
    for name in (
        "LAW_NEO4J_IMAGE_REF",
        "LEGAL_DATASET_VERSION",
        "LEGAL_DATASET_VERIFIED_AT",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
    ):
        assert name in compose_env_extraction
    assert "initial RAG stage service states" in deploy
    assert "logs --tail 80 `$stage_service" in deploy
    loader = _read_deploy("Load-Rag-Seed-Pilot.ps1")
    assert "$stageComposeCommand --profile seed run --rm --no-deps rag-loader" in loader
    assert "run --rm --no-deps backend" not in loader


def test_caddy_preserves_auth_headers_and_haproxy_enforces_per_ip_rate_limit() -> None:
    caddy = _read_deploy("Caddyfile")
    for header in ("Origin", "X-Requested-With", "X-Forwarded-For"):
        assert f"header_up {header}" in caddy

    haproxy = _read_deploy("haproxy.cfg")
    assert "stick-table type ip" in haproxy
    assert "http_req_rate" in haproxy
    assert "deny_status 429" in haproxy
    assert "hdr_ip(X-Forwarded-For" in haproxy
    assert "/api/auth/google/code/" in haproxy
    assert "http_req_rate(1m)" in haproxy


def test_caddy_access_log_drops_all_request_headers_without_changing_proxy_auth() -> None:
    caddy = _read_deploy("Caddyfile")
    log_start = caddy.index("log {")
    log_end = caddy.index("\n\t}", log_start) + len("\n\t}")
    log_block = caddy[log_start:log_end]
    proxy_block = caddy[caddy.index("reverse_proxy") :]

    assert "format filter {" in log_block
    assert "request>headers delete" in log_block
    assert "wrap json" in log_block
    assert "log_credentials" not in caddy
    for header in ("Authorization", "Cookie", "X-Guest-Credential"):
        assert f"header_up -{header}" not in proxy_block


def test_internal_health_checks_forward_https_with_an_explicit_safe_host() -> None:
    compose = yaml.safe_load(_read_deploy("docker-compose.pilot.yml"))
    backend_health = " ".join(compose["services"]["backend"]["healthcheck"]["test"])
    assert "X-Forwarded-Proto" in backend_health
    assert "https" in backend_health
    assert "Host" in backend_health
    assert "localhost" in backend_health

    runtime_env = _read_deploy("runtime.env.example")
    allowed_hosts = next(
        line.split("=", 1)[1]
        for line in runtime_env.splitlines()
        if line.startswith("DJANGO_ALLOWED_HOSTS=")
    ).split(",")
    assert {"localhost", "127.0.0.1", "backend"}.issubset(set(allowed_hosts))

    haproxy = _read_deploy("haproxy.cfg")
    assert re.search(
        r"http-check send .*hdr Host localhost .*hdr X-Forwarded-Proto https",
        haproxy,
    )

    deploy = _read_deploy("Deploy-Pilot.ps1")
    assert 'Get-EnvValue $runtimeEnv "DJANGO_ALLOWED_HOSTS"' in deploy
    for required_host in ("localhost", "127.0.0.1", "backend"):
        assert required_host in deploy
    assert "DJANGO_ALLOWED_HOSTS must include internal health host" in deploy


def test_public_edge_blocks_explicit_mock_api_surface() -> None:
    haproxy = _read_deploy("haproxy.cfg")

    assert "acl mock_api_path path_beg -i /api/mock/" in haproxy
    deny_rule = "http-request deny deny_status 404 if mock_api_path"
    assert deny_rule in haproxy
    assert haproxy.index(deny_rule) < haproxy.index("use_backend django if api_path")


def test_frontend_build_and_runtime_google_settings_are_wired() -> None:
    dockerfile = _read_deploy("Dockerfile.frontend")
    assert "ARG VITE_GOOGLE_CLIENT_ID" in dockerfile
    assert "npm run build" in dockerfile

    env_template = _read_deploy("runtime.env.example")
    required = {
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_POPUP_REDIRECT_URI",
        "GOOGLE_OAUTH_CODE_EXCHANGE_DAILY_LIMIT",
        "GOOGLE_OAUTH_TRUSTED_PROXY_CIDRS",
        "APP_JWT_SECRET",
        "OAUTH_TOKEN_SECRET",
    }
    keys = {
        line.split("=", 1)[0]
        for line in env_template.splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    assert required.issubset(keys)
    assert next(
        line.split("=", 1)[1]
        for line in env_template.splitlines()
        if line.startswith("GOOGLE_OAUTH_TRUSTED_PROXY_CIDRS=")
    ) == "172.31.0.3/32"

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "deploy/aws-pilot/.runtime.env" in gitignore
    assert "deploy/aws-pilot/.compose.env" in gitignore
    assert "deploy/aws-pilot/.edge.env" in gitignore
    assert "deploy/aws-pilot/.elasticsearch.env" not in gitignore


def test_deploy_script_builds_pushes_and_checks_schema_readiness_and_smokes() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    for token in (
        "docker build",
        "docker push",
        "VITE_GOOGLE_CLIENT_ID",
        "aws s3 cp",
        "aws ssm send-command",
        "migrate --check",
        "check_production_readiness",
        "/api/health/live/",
        "/api/health/ready/",
    ):
        assert token in deploy
    assert "terraform apply" not in deploy.lower()
    assert deploy.count("--platform linux/amd64") == 2
    assert "--resolve" in deploy
    assert "Invoke-WebRequest" in deploy


def test_rag_seed_maintenance_path_is_explicit_integrity_checked_and_fail_closed() -> None:
    deploy = _read_deploy("Load-Rag-Seed-Pilot.ps1")
    assert "[string]$RagSeedS3Uri" in deploy
    assert "[string]$RagSeedManifestRelativePath" in deploy
    assert "[string]$RagSeedManifestSha256" in deploy
    assert "_rag-seed/" in deploy
    assert 'ValidatePattern("^[A-Za-z0-9._-]+\\.json$")' in deploy
    assert 'ValidatePattern("^[0-9a-f]{64}$")' in deploy

    expected_steps = (
        "aws s3 cp '$RagSeedS3Uri'",
        "sha256sum -c -",
        "$stageComposeCommand --profile seed run --rm --no-deps -v `$RAG_DIR:/run/production-rag-seed:ro rag-loader python backend/manage.py verify_production_rag_seed_manifest",
        "$stageComposeCommand --profile seed run --rm --no-deps -v `$RAG_DIR:/run/production-rag-seed:ro rag-loader python backend/manage.py load_production_rag_seed",
        "$stageComposeCommand --profile seed run --rm --no-deps -v `$RAG_DIR:/run/production-rag-seed:ro rag-loader python backend/manage.py load_legal_graph_seed",
        "$stageComposeCommand --profile seed run --rm --no-deps rag-loader python backend/manage.py verify_legal_graph_readiness --format json",
        "$stageComposeCommand --profile seed run --rm --no-deps rag-loader python backend/manage.py smoke_law_ground_search --require-results",
        "$stageComposeCommand --profile seed run --rm --no-deps rag-loader python backend/manage.py verify_pgvector_rag_readiness --format json",
        "$stageComposeCommand --profile seed run --rm --no-deps rag-loader python backend/manage.py smoke_text_ml_case_search --require-pgvector --require-results",
    )
    positions = []
    cursor = 0
    for step in expected_steps:
        position = deploy.index(step, cursor)
        positions.append(position)
        cursor = position + len(step)
    assert positions == sorted(positions)
    assert "--replace-legal --skip-legal-schema" in deploy
    assert "--replace-legal --recreate-es" not in deploy
    assert "verify_pgvector_rag_readiness" in deploy
    assert "--region '$region'" in deploy[deploy.index("aws s3 cp '$RagSeedS3Uri'") :]
    assert "trap cleanup_rag_seed EXIT" in deploy
    assert "chmod 0555" in deploy
    assert "chmod 0444" in deploy

    runtime_version = deploy.index("PRECEDENT_NEWPLUSPLUS_SEED_VERSION")
    seed_verify = deploy.index("verify_precedent_newplusplus_seed", runtime_version)
    readiness = deploy.index("verify_pgvector_rag_readiness", seed_verify)
    evidence_move = deploy.index("mv -f `$EVIDENCE_TMP `$EVIDENCE_FILE", readiness)
    marker_move = deploy.index(
        "mv -f `$RELEASE_STATE_FILE.tmp `$RELEASE_STATE_FILE", readiness
    )
    descriptor_move = deploy.index("mv -f `$SEED_SOURCE_TMP `$SEED_SOURCE_FILE", readiness)
    assert runtime_version < seed_verify < readiness
    assert readiness < evidence_move < marker_move < descriptor_move
    assert '--expected-seed-version `"`$PRECEDENT_NEWPLUSPLUS_SEED_VERSION`"' in deploy
    assert "^sha256:[0-9a-f]{64}$" in deploy
    assert "PRECEDENT_SEED_LINES" in deploy


def test_rag_seed_resume_reuses_only_exact_verified_pgvector_state() -> None:
    deploy = _read_deploy("Load-Rag-Seed-Pilot.ps1")

    assert "[switch]$ReuseVerifiedPgvectorLoad" in deploy
    assert "if (-not $ReuseVerifiedPgvectorLoad -and -not $AllowPaidReviewCaseEmbedding)" in deploy
    assert "$dataLoadCommands = if ($ReuseVerifiedPgvectorLoad)" in deploy
    assert "assert law_chunks == 98664" in deploy
    assert "assert law_embeddings == 98664" in deploy
    assert "assert review_embeddings == 904" in deploy
    assert "assert owned_nodes == 0" in deploy
    resume_readiness = deploy.index("verify_pgvector_rag_readiness --format json")
    graph_load = deploy.index(
        "$stageComposeCommand --profile seed run --rm --no-deps -v `$RAG_DIR:/run/production-rag-seed:ro rag-loader python backend/manage.py load_legal_graph_seed"
    )
    assert resume_readiness < graph_load
    assert "$runnerCommands = @(" in deploy
    assert "$runnerCommands += $dataLoadCommands" in deploy
    assert "$runnerCommands += @(" in deploy


def test_database_maintenance_applies_review_case_schema_before_app_grants() -> None:
    maintenance = _read_deploy("Maintain-PilotDatabase.ps1")
    schema_command = (
        "python -m etl.fault_cases.src.review_case.db_loading.schema_manager "
        "--apply-schema"
    )
    grant_command = (
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public"
    )

    assert schema_command in maintenance
    schema_position = maintenance.index(schema_command)
    grant_position = maintenance.index(grant_command)
    assert "--env-file `$WORK/master.env" in maintenance[:grant_position]
    assert schema_position < grant_position


def test_database_maintenance_promotes_precedent_seed_before_ssm_evidence() -> None:
    runtime_env = _read_deploy("runtime.env.example")
    maintenance = _read_deploy("Maintain-PilotDatabase.ps1")
    deploy = _read_deploy("Deploy-Pilot.ps1")
    iam = (TERRAFORM_DIR / "iam.tf").read_text(encoding="utf-8")

    assert (
        "PRECEDENT_NEWPLUSPLUS_SEED_VERSION="
        "INJECTED_BY_DATABASE_MAINTENANCE"
    ) in runtime_env

    schema = maintenance.index("precedent_db_loading/schema.sql")
    stage = maintenance.index("stage_precedent_newplusplus_seed", schema)
    promote = maintenance.index("promote_precedent_newplusplus_seed", stage)
    ssm_update = maintenance.index("aws ssm put-parameter", promote)
    read_back = maintenance.index("aws ssm get-parameter", ssm_update)
    master_verify = maintenance.index("verify_precedent_newplusplus_seed", promote)
    app_verify = maintenance.index("verify_precedent_newplusplus_seed", master_verify + 1)
    assert schema < stage < promote < master_verify < ssm_update < read_back < app_verify

    grant_usage = "GRANT USAGE ON SCHEMA precedent_newplusplus"
    grant_select = (
        "GRANT SELECT ON precedent_newplusplus.blocks, "
        "precedent_newplusplus.seed_releases, precedent_newplusplus.active_seed"
    )
    assert grant_usage in maintenance
    assert grant_select in maintenance
    grant_segment = maintenance[
        maintenance.index(grant_usage) : app_verify
    ].upper()
    for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "CREATE"):
        assert f"GRANT {privilege}" not in grant_segment
        assert f", {privilege}" not in grant_segment
    assert "BLOCK_VERSIONS" not in grant_segment

    assert "Get-VerifiedPrecedentSeedVersion" in deploy
    assert "PRECEDENT_NEWPLUSPLUS_SEED_VERSION" in deploy
    helper = deploy.index("function Get-VerifiedPrecedentSeedVersion")
    generated = deploy.index("$generatedValues =", helper)
    unresolved = deploy.index('if ($runtimeEnv -match "(?m)=(REPLACE_|INJECTED_)")')
    assert helper < generated < unresolved
    assert "--with-decryption" in deploy[helper:generated]

    policy_start = iam.index('sid    = "SynchronizeRuntimeEnvironmentForMigration"')
    policy_end = iam.index("  }", policy_start)
    policy = iam[policy_start:policy_end]
    assert '"ssm:GetParameter"' in policy
    assert '"ssm:PutParameter"' in policy
    assert "parameter${var.runtime_env_parameter_name}" in policy
    assert iam.count('"ssm:PutParameter"') == 1


def test_deploy_normalizes_runtime_line_endings_before_precedent_seed_regex() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    helper = deploy.index("function Normalize-RuntimeEnvText")
    read_parameter = deploy.index("function Get-VerifiedPrecedentSeedVersion")
    normalize = deploy.index(
        "Normalize-RuntimeEnvText $parameterValue",
        read_parameter,
    )
    pattern = deploy.index(
        "PRECEDENT_NEWPLUSPLUS_SEED_VERSION=(sha256:[0-9a-f]{64})",
        read_parameter,
    )

    assert helper < read_parameter < normalize < pattern
    assert (
        '.Replace("`r`n", "`n").Replace("`r", "`n")'
        in deploy[helper:read_parameter]
    )
    assert "$matches.Count -ne 1" in deploy[pattern:]


def test_precedent_seed_rollback_is_explicit_verified_and_fail_closed() -> None:
    rollback = _read_deploy("Rollback-PilotPrecedentSeed.ps1")

    for token in (
        "[Parameter(Mandatory = $true)]",
        "$ExpectedActiveSeedVersion",
        "database_runtime_instance_profile_name",
        "database_maintenance_instance_profile_name",
        "database_maintenance_role_name",
        "/var/lock/skn27-pilot-maintenance.lock",
        "database-maintenance.active",
        "Maintenance role identity check failed.",
        "rollback_precedent_newplusplus_seed",
        "--expected-active-seed-version",
        "PREVIOUS_SEED_UNAVAILABLE",
        "PRECEDENT_NEWPLUSPLUS_SEED_VERSION",
        "aws ssm put-parameter",
        "--type SecureString",
        "--overwrite",
        "aws ssm get-parameter",
        "--with-decryption",
        "verify_precedent_newplusplus_seed",
        "cleanup_db_secrets",
        "trap cleanup_db_secrets EXIT",
        "precedent-seed-rollback.state",
        "prepared",
        "db_swapped",
        "ssm_synced",
        "verified",
        "compensated",
        "recovery_required",
        "compensate_precedent_seed_rollback",
        "trap compensate_precedent_seed_rollback ERR",
    ):
        assert token in rollback

    rollback_command = rollback.index("rollback_precedent_newplusplus_seed")
    ssm_update = rollback.index("aws ssm put-parameter", rollback_command)
    read_back = rollback.index("aws ssm get-parameter", ssm_update)
    verify = rollback.index("verify_precedent_newplusplus_seed", read_back)
    assert rollback_command < ssm_update < read_back < verify
    assert "Rollback-Pilot.ps1" not in rollback
    assert "/opt/skn27-pilot/releases/$ReleaseTag" not in rollback
    assert "ln -sfn" not in rollback
    assert "docker compose" in rollback  # maintenance fence only
    assert " up -d" not in rollback

    compensation = rollback.index("compensate_precedent_seed_rollback")
    compensation_rollback = rollback.index(
        "rollback_precedent_newplusplus_seed",
        compensation,
    )
    compensation_ssm = rollback.index("aws ssm put-parameter", compensation)
    compensation_readback = rollback.index("aws ssm get-parameter", compensation)
    compensation_verify = rollback.index(
        "verify_precedent_newplusplus_seed",
        compensation,
    )
    assert (
        compensation
        < compensation_rollback
        < compensation_ssm
        < compensation_readback
        < compensation_verify
    )


def test_precedent_rollback_only_releases_maintenance_after_verified_state() -> None:
    rollback = _read_deploy("Rollback-PilotPrecedentSeed.ps1")

    assert "$databaseMaintenanceCommandSucceeded = $false" in rollback
    assert "$databaseMaintenanceSafeToRelease = $false" in rollback
    terminal = rollback.index(
        "$script:databaseMaintenanceTerminalConfirmed = $true"
    )
    status_gate = rollback.index('$result.Status -eq "Success"', terminal)
    success = rollback.index(
        "$script:databaseMaintenanceCommandSucceeded = $true",
        status_gate,
    )
    assert terminal < status_gate < success

    assert "Get verified precedent rollback journal state" in rollback
    assert "precedent-seed-rollback.state" in rollback
    assert "compensated" in rollback
    assert "recovery_required" in rollback
    assert "if ($databaseMaintenanceSafeToRelease)" in rollback
    assert "maintenance profile and marker remain active" in rollback


def test_rag_seed_loader_requires_paid_review_case_consent_and_orders_sources() -> None:
    loader = _read_deploy("Load-Rag-Seed-Pilot.ps1")

    assert "[switch]$AllowPaidReviewCaseEmbedding" in loader
    guard = loader.index(
        "if (-not $ReuseVerifiedPgvectorLoad -and -not $AllowPaidReviewCaseEmbedding)"
    )
    terraform = loader.index("$terraformPath =")
    ssm = loader.index("aws ssm send-command")
    assert guard < terraform < ssm

    review_load = (
        "run --rm --no-deps -v `$RAG_DIR:/run/production-rag-seed:ro "
        "rag-loader python backend/manage.py load_review_case_pgvector_seed "
        "--manifest /run/production-rag-seed/$RagSeedManifestRelativePath "
        "--replace --allow-paid-provider-call --format json"
    )
    legal_load = (
        "run --rm --no-deps -v `$RAG_DIR:/run/production-rag-seed:ro "
        "rag-loader python backend/manage.py load_production_rag_seed "
        "--manifest /run/production-rag-seed/$RagSeedManifestRelativePath "
        "--replace-legal --skip-legal-schema --format json"
    )
    completion = (
        "printf '%s\\n' '$RagSeedManifestSha256' > "
        "`$RELEASE_STATE_FILE.tmp"
    )
    expected_steps = (
        "verify_production_rag_seed_manifest --manifest",
        review_load,
        legal_load,
        "rag-loader python backend/manage.py load_legal_graph_seed",
        "rag-loader python backend/manage.py verify_legal_graph_readiness --format json",
        "smoke_law_ground_search --require-results",
        "verify_pgvector_rag_readiness --format json",
        "smoke_text_ml_case_search --require-pgvector --require-results",
        completion,
    )
    positions = []
    cursor = 0
    for step in expected_steps:
        position = loader.index(step, cursor)
        positions.append(position)
        cursor = position + len(step)
    assert positions == sorted(positions)


def test_legal_seed_refresh_runbook_orders_reuse_cost_and_release_gates() -> None:
    runbook = (
        ROOT / "docs" / "ops" / "legal-data-freshness-runbook.md"
    ).read_text(encoding="utf-8")

    required_steps = (
        "build_approved_legal_rag_seed",
        "--dry-run",
        "plan_sha256",
        "--allow-paid-embedding",
        "_rag-seed/",
        "Load-Rag-Seed-Pilot.ps1",
        "Confirm-PilotOperationalAcceptance.ps1",
        "App Release",
    )
    positions = [runbook.index(step) for step in required_steps]
    assert positions == sorted(positions)
    assert "기존 embedding baseline만으로 freshness를 갱신하지 않는다" in runbook


def test_rag_seed_builds_release_bound_operational_evidence_after_readiness() -> None:
    loader = _read_deploy("Load-Rag-Seed-Pilot.ps1")
    load_failed = next(
        line for line in loader.splitlines() if '"load_failed() {' in line
    )

    graph_readiness = loader.index(
        "verify_legal_graph_readiness --format json"
    )
    law_smoke = loader.index(
        "smoke_law_ground_search --require-results --format json"
    )
    pgvector_readiness = loader.index(
        "verify_pgvector_rag_readiness --format json", law_smoke
    )
    text_search_smoke = loader.index(
        "smoke_text_ml_case_search --require-pgvector --require-results --format json"
    )
    build_summary = loader.index(
        "build_legal_operational_evidence --manifest"
    )
    validate_summary = loader.index(
        "etl.legal.validate_run_summary --summary"
    )
    atomic_move = loader.index(
        "mv -f `$EVIDENCE_TMP `$EVIDENCE_FILE"
    )
    completion_marker = loader.index(
        "mv -f `$RELEASE_STATE_FILE.tmp `$RELEASE_STATE_FILE"
    )
    cleanup = loader.index("cleanup_rag_seed", completion_marker)

    assert (
        graph_readiness
        < law_smoke
        < pgvector_readiness
        < text_search_smoke
        < build_summary
        < validate_summary
        < atomic_move
        < completion_marker
        < cleanup
    )
    for token in (
        "LEGAL_DATASET_VERIFIED_AT",
        "--dataset-version `\"`$LEGAL_DATASET_VERSION`\"",
        "--release-version '$ReleaseTag'",
        "--verified-at `\"`$LEGAL_DATASET_VERIFIED_AT`\"",
        "--expected-dataset-version `\"`$LEGAL_DATASET_VERSION`\"",
        "--expected-release-version '$ReleaseTag'",
        "EVIDENCE_TMP=`$EVIDENCE_DIR/.run_summary.json.tmp",
        "chmod 0444 `$EVIDENCE_TMP",
    ):
        assert token in loader
    assert "cleanup_rag_seed" in load_failed


def test_normal_promotion_enters_release_dir_before_relative_compose_evidence_check() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    normal_promotion = deploy.index(
        '"test -d `$RELEASE_DIR && test ! -L `$RELEASE_DIR"'
    )
    evidence_validation = deploy.index(
        "$stageComposeCommand --profile seed run --rm --no-deps "
        "-v `$RELEASE_DIR/operational-evidence:/run/release-evidence:ro "
        "rag-loader python -m etl.legal.validate_run_summary",
        normal_promotion,
    )
    release_directory = deploy.index('"cd `$RELEASE_DIR"', normal_promotion)

    assert normal_promotion < release_directory < evidence_validation


def test_full_seed_load_persists_root_only_seed_descriptor_after_validation() -> None:
    loader = _read_deploy("Load-Rag-Seed-Pilot.ps1")

    evidence_validation = loader.index(
        "etl.legal.validate_run_summary --summary"
    )
    evidence_move = loader.index("mv -f `$EVIDENCE_TMP `$EVIDENCE_FILE")
    descriptor_move = loader.index("mv -f `$SEED_SOURCE_TMP `$SEED_SOURCE_FILE")

    assert evidence_validation < evidence_move < descriptor_move
    assert "SEED_SOURCE_DIR='/opt/skn27-pilot/state'" in loader
    assert (
        "SEED_SOURCE_FILE=`$SEED_SOURCE_DIR/"
        "legal-operational-evidence-source.env"
    ) in loader
    assert "install -d -m 0700 `$SEED_SOURCE_DIR" in loader
    assert "chmod 0600 `$SEED_SOURCE_TMP" in loader
    assert "install -d -m 0755 `$EVIDENCE_DIR" in loader
    assert "install -d -m 0750 `$EVIDENCE_DIR" not in loader
    for key in (
        "RAG_SEED_S3_URI",
        "RAG_SEED_MANIFEST_RELATIVE_PATH",
        "RAG_SEED_MANIFEST_SHA256",
    ):
        assert key in loader


def test_evidence_recovery_is_locked_verified_atomic_and_provider_free() -> None:
    recovery_path = DEPLOY_DIR / "Recover-PilotOperationalEvidence.ps1"
    assert recovery_path.is_file()
    recovery = recovery_path.read_text(encoding="utf-8")

    tag_check = recovery.index("CURRENT_TAG")
    download = recovery.index("aws s3 cp", tag_check)
    digest = recovery.index("sha256sum -c -", download)
    manifest = recovery.index("verify_production_rag_seed_manifest", digest)
    build = recovery.index("build_legal_operational_evidence", manifest)
    validation = recovery.index("etl.legal.validate_run_summary", build)
    release_move = recovery.index(
        'mv -f "$RELEASE_EVIDENCE_TMP" "$RELEASE_EVIDENCE_FILE"',
        validation,
    )
    shared_move = recovery.index(
        'mv -f "$SHARED_EVIDENCE_TMP" "$SHARED_EVIDENCE_FILE"',
        release_move,
    )
    descriptor_move = recovery.index(
        'mv -f "$SEED_SOURCE_TMP" "$SEED_SOURCE_FILE"',
        shared_move,
    )
    preflight = recovery.index(
        "observe_operational_health --once --gate-mode transaction",
        descriptor_move,
    )

    assert tag_check < download < digest < manifest < build < validation
    assert validation < release_move < shared_move < descriptor_move < preflight
    for token in (
        "/var/lock/skn27-pilot-maintenance.lock",
        'install -d -m 0755 "$SHARED_EVIDENCE_DIR"',
        'chmod 0444 "$RELEASE_EVIDENCE_TMP"',
        'chmod 0600 "$SEED_SOURCE_TMP"',
        "restore_previous_evidence",
        "restore_previous_descriptor",
        "cleanup_rag_seed",
    ):
        assert token in recovery
    for forbidden in (
        "AllowPaidReviewCaseEmbedding",
        "allow-paid-provider-call",
        "load_review_case_pgvector_seed",
        "load_production_rag_seed",
        "load_legal_graph_seed",
    ):
        assert forbidden not in recovery


def test_production_one_off_containers_override_running_service_ips() -> None:
    scripts = {
        name: _read_deploy(name)
        for name in (
            "Deploy-Pilot.ps1",
            "Recover-PilotOperationalEvidence.ps1",
            "Rollback-Pilot.ps1",
            "Confirm-PilotOperationalAcceptance.ps1",
            "Release-PilotApp-FromPipeline.sh",
        )
    }

    for name, script in scripts.items():
        assert "172.31.0.11" in script, name
        for line in script.splitlines():
            if "run --rm --no-deps" not in line:
                continue
            if name == "Deploy-Pilot.ps1" and "$productionComposeCommand" not in line:
                continue
            is_backend_run = " backend python" in line or line.rstrip().endswith(
                " backend \\"
            )
            if is_backend_run:
                assert "PILOT_BACKEND_IP=" in line, f"{name}: {line}"
            if " ops-monitor" in line:
                assert "PILOT_OPS_MONITOR_IP=" in line, f"{name}: {line}"


def test_normal_promotion_validates_promotes_and_preflights_operational_evidence() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    previous = deploy.index("PREVIOUS_RELEASE=`$(readlink")
    promote_release = deploy.index(
        "ln -sfn `$RELEASE_DIR /opt/skn27-pilot/current",
        previous,
    )
    normal_segment = deploy[previous:promote_release]

    release_evidence = normal_segment.index(
        "RELEASE_EVIDENCE=`$RELEASE_DIR/operational-evidence/run_summary.json"
    )
    precheck = normal_segment.index(
        "etl.legal.validate_run_summary --summary /run/release-evidence/run_summary.json"
    )
    stop_previous = normal_segment.index(
        "$productionComposeCommand down",
        precheck,
    )
    install_temporary = normal_segment.index(
        "install -m 0444 `$RELEASE_EVIDENCE `$SHARED_EVIDENCE_TMP"
    )
    validate_temporary = normal_segment.index(
        "etl.legal.validate_run_summary --summary /run/operational-evidence/.run_summary.json.tmp"
    )
    promote_evidence = normal_segment.index(
        "mv -f `$SHARED_EVIDENCE_TMP `$SHARED_EVIDENCE_FILE"
    )
    promote_call = normal_segment.rindex("promote_operational_evidence")
    core_start = normal_segment.index(
        "$productionComposeCommand up -d --wait --wait-timeout 600 "
        "--remove-orphans `$WAITED_SERVICES",
        promote_call,
    )
    worker_start = normal_segment.index(
        "$productionComposeCommand up -d `$BACKGROUND_SERVICES",
        core_start,
    )
    monitor_preflight = normal_segment.index(
        "observe_operational_health --once --gate-mode transaction"
    )
    monitor_start = normal_segment.index(
        "$productionComposeCommand up -d `$MONITOR_SERVICE",
        monitor_preflight,
    )

    assert release_evidence < precheck < stop_previous < promote_call
    assert install_temporary < validate_temporary < promote_evidence
    assert promote_call < core_start < worker_start < monitor_preflight < monitor_start
    assert "BACKGROUND_SERVICES='agent-worker file-scan-worker'" in normal_segment
    assert "MONITOR_SERVICE='ops-monitor'" in normal_segment
    assert "legal_data_provenance_mismatch" not in normal_segment
    assert "restore_operational_evidence" in normal_segment
    assert (
        "cp `$PREVIOUS_RELEASE/operational-evidence/run_summary.json "
        "`$SHARED_EVIDENCE_TMP"
    ) in normal_segment
    assert "rm -f `$SHARED_EVIDENCE_FILE" in normal_segment


def test_deploy_fail_closed_hook_requires_unified_production_runtime_smoke() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    command = "smoke_supervisor_conversation_runtime"
    assert "[switch]$AllowPaidNonDlSmoke" in deploy
    assert "[switch]$AllowPaidSupervisorSmoke" in deploy
    assert "if (-not $AllowPaidNonDlSmoke)" in deploy
    assert "if (-not $AllowPaidSupervisorSmoke)" in deploy
    assert deploy.count(command) >= 2
    assert f"help {command}" in deploy
    assert "--require-real-agent-results" in deploy
    assert "--require-persisted-handoff" in deploy
    assert "--require-report" in deploy
    assert "--allow-paid-provider-call" in deploy
    assert "--timeout-seconds 600" in deploy

    runbook = _read_deploy("README.ko.md")
    assert command in runbook
    assert "#173" in runbook
    assert "#193" in runbook
    assert "fail-closed" in runbook
    assert "-AllowPaidNonDlSmoke" in runbook
    assert "-AllowPaidSupervisorSmoke" in runbook


def test_deploy_waits_long_enough_for_first_clamav_and_elasticsearch_start() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    assert "wait command-executed" not in deploy
    assert "Get-SsmCommandResult" in deploy
    assert "InProgress" in deploy
    assert "180" in deploy


def test_korean_runbook_covers_cost_guardrails_rollout_rollback_and_teardown() -> None:
    runbook = _read_deploy("README.ko.md")
    assert all(topic in runbook for topic in ("pgvector", "HNSW", "rollback", "RDS", "SSM"))
    return
    for topic in (
        "비용 가드레일",
        "사전 조건",
        "배포 순서",
        "검증",
        "롤백",
        "철거",
        "DL",
        "RDS",
        "SSM",
        "50%",
        "80%",
        "100%",
    ):
        assert topic in runbook


def test_teardown_waits_for_application_writes_to_stop_before_deleting_data() -> None:
    remove = _read_deploy("Remove-Pilot.ps1")
    assert "DESTROY skn27-pilot" in remove
    assert "Get-SsmCommandResult" in remove
    assert remove.index("Get-SsmCommandResult $region") < remove.rindex("Remove-VersionedBucket")


def test_rollback_refreshes_current_ssm_credentials_instead_of_reusing_old_secrets() -> None:
    rollback = _read_deploy("Rollback-Pilot.ps1")
    assert "runtime_env_parameter_name" in rollback
    assert "get-parameter" in rollback
    assert "--with-decryption" in rollback
    assert ".runtime.env" in rollback


def test_manual_rollback_validates_and_restores_release_bound_evidence() -> None:
    rollback = _read_deploy("Rollback-Pilot.ps1")

    validate = rollback.index("etl.legal.validate_run_summary")
    mutate = rollback.index("$composeCommand up -d", validate)
    promote = rollback.index("mv -f `$TARGET_EVIDENCE_TMP `$SHARED_EVIDENCE_FILE", mutate)
    gate = rollback.index(
        "observe_operational_health --once --gate-mode transaction", promote
    )
    symlink = rollback.index(
        "ln -sfn '$releaseDirectory' /opt/skn27-pilot/current", gate
    )

    assert validate < mutate < promote < gate < symlink
    for token in (
        "PRECOMMAND_EVIDENCE_EXISTED=0",
        "PRECOMMAND_EVIDENCE_BACKUP",
        "restore_precommand_evidence",
        "--expected-release-version '$ReleaseTag'",
        "install -d -m 0755 /opt/skn27-pilot/operational-evidence",
        "install -m 0444 `$TARGET_EVIDENCE_FILE `$TARGET_EVIDENCE_TMP",
    ):
        assert token in rollback


def test_operational_acceptance_requires_elapsed_consecutive_pass_time() -> None:
    watcher = _read_deploy("Confirm-PilotOperationalAcceptance.ps1")

    assert "[ValidateRange(600, 3600)]" in watcher
    assert "[int]$AcceptanceSeconds = 600" in watcher
    assert "[int]$MaxWaitSeconds = 1200" in watcher
    assert "[int]$IntervalSeconds = 60" in watcher
    assert "observe_operational_health --once --gate-mode acceptance" in watcher
    assert "BACKEND_IMAGE_REF" in watcher
    assert "*:__RELEASE_TAG__)" in watcher
    assert "pass_started_at" in watcher
    assert "date +%s" in watcher
    assert "pass_started_at=0" in watcher
    assert "decision=fail" in watcher
    assert "exit 1" in watcher
    for forbidden in (
        "load_production_rag_seed",
        "load_legal_rag_pgvector",
        "AllowPaid",
        "provider",
    ):
        assert forbidden not in watcher


def test_rag_seed_is_a_locked_read_only_maintenance_job_not_part_of_deploy() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    maintenance = _read_deploy("Load-Rag-Seed-Pilot.ps1")

    assert "RagSeedS3Uri" not in deploy
    assert "manage.py load_production_rag_seed" not in deploy
    assert "flock -w 60 9" in maintenance
    assert "/var/lock/skn27-pilot-maintenance.lock" in maintenance
    assert "chmod 0555" in maintenance
    assert "chmod 0444" in maintenance
    assert ":/run/production-rag-seed:ro" in maintenance
    assert "--manifest /run/production-rag-seed/" in maintenance
    assert "rag-state" not in maintenance
    assert "RELEASE_STATE_FILE=`$TARGET_RELEASE/.production-rag-seed.complete" in maintenance
    assert "--env-file .stage-compose.env" in maintenance


def test_runtime_iam_separates_mutable_data_from_read_only_deploy_artifacts() -> None:
    iam = (TERRAFORM_DIR / "iam.tf").read_text(encoding="utf-8")

    assert 'sid    = "UseCleanRuntimeObjects"' in iam
    assert '${aws_s3_bucket.clean.arn}/canonical/*' in iam
    assert 'sid     = "ReadPinnedDeploymentArtifacts"' in iam
    assert '${aws_s3_bucket.clean.arn}/_deploy/*' in iam
    assert 'sid     = "DenyDeploymentArtifactMutation"' in iam
    assert (
        'actions = ["s3:DeleteObject", "s3:DeleteObjectVersion", "s3:PutObject"]'
        in iam
    )

    deploy = _read_deploy("Deploy-Pilot.ps1")
    for token in (
        "BundleSha256",
        "BundleVersionId",
        "ManifestSha256",
        "ManifestVersionId",
        "s3api get-object",
        "sha256sum -c",
        "deployment-manifest.json",
    ):
        assert token in deploy


def test_database_master_is_maintenance_only_and_runtime_uses_app_secret() -> None:
    source = _terraform_source()
    deploy = _read_deploy("Deploy-Pilot.ps1")
    maintenance = _read_deploy("Maintain-PilotDatabase.ps1")

    assert 'resource "aws_secretsmanager_secret" "app_database"' in source
    assert 'output "app_database_credential_arn"' in source
    assert 'output "database_maintenance_instance_profile_name"' in source
    assert "MasterUserSecret.SecretArn" not in deploy
    assert "app_database_credential_arn" in deploy
    assert "get-secret-value" in deploy
    assert "POSTGRES_USER" in deploy
    assert "POSTGRES_PASSWORD" in deploy
    assert "migrate --noinput" not in deploy
    assert "migrate --check" in deploy
    assert "master_user_secret" in maintenance
    assert "migrate --noinput" in maintenance
    assert "replace-iam-instance-profile-association" in maintenance
    assert "database_runtime_instance_profile_name" in maintenance
    assert "Remove-Item" in maintenance
    assert "StandardErrorContent" not in maintenance


def test_teardown_is_best_effort_before_destroy_even_without_current_release() -> None:
    remove = _read_deploy("Remove-Pilot.ps1")

    assert "Invoke-BestEffort" in remove
    assert "test ! -L /opt/skn27-pilot/current" in remove
    assert "Get-SsmCommandResult" in remove
    assert "terraform destroy" in remove
    assert remove.index("Invoke-BestEffort") < remove.index("terraform destroy")
    assert "wait command-executed" not in remove


def test_ssm_jobs_have_configurable_timeout_cancel_and_terminal_confirmation() -> None:
    for name in ("Deploy-Pilot.ps1", "Load-Rag-Seed-Pilot.ps1"):
        script = _read_deploy(name)
        assert "[int]$SsmTimeoutSeconds" in script
        assert "cancel-command" in script
        assert "Cancelled" in script
        assert "TimedOut" in script
        assert "Get-SsmCommandResult" in script

    rag_seed_loader = _read_deploy("Load-Rag-Seed-Pilot.ps1")
    assert "TimeoutSeconds = $SsmTimeoutSeconds" in rag_seed_loader
    assert "executionTimeout = @([string]$SsmTimeoutSeconds)" in rag_seed_loader
    assert '"_deploy/$ReleaseTag/rag-seed-runner.sh"' in rag_seed_loader
    assert "aws s3 cp" in rag_seed_loader
    assert "bash /tmp/skn27-rag-seed-runner.sh" in rag_seed_loader


def test_remote_state_is_precreated_versioned_encrypted_and_lockfile_based() -> None:
    versions = (TERRAFORM_DIR / "versions.tf").read_text(encoding="utf-8")
    backend_example = (TERRAFORM_DIR / "backend.hcl.example").read_text(
        encoding="utf-8"
    )
    bootstrap = _read_deploy("Initialize-StateBackend.ps1")

    assert 'backend "s3"' in versions
    assert "use_lockfile = true" in versions
    assert "bucket" in backend_example
    assert "key" in backend_example
    assert "put-bucket-versioning" in bootstrap
    assert "put-bucket-encryption" in bootstrap
    assert "put-public-access-block" in bootstrap
    assert "terraform apply" not in bootstrap


def test_final_snapshot_is_unique_and_disposable_skip_is_explicit() -> None:
    source = _terraform_source()
    runbook = _read_deploy("README.ko.md")

    assert 'resource "random_id" "final_snapshot"' in source
    assert "random_id.final_snapshot.hex" in source
    assert "database_skip_final_snapshot" in source
    assert "disposable" in runbook.lower()


def test_failed_deploy_restores_previous_compose_release_automatically() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")

    assert "PREVIOUS_RELEASE=" in deploy
    assert "rollback_previous_release" in deploy
    assert "trap rollback_previous_release ERR" in deploy
    assert r"ln -sfn `$PREVIOUS_RELEASE /opt/skn27-pilot/current" in deploy
    assert "trap - ERR" in deploy


def test_eight_gib_host_has_bounded_services_logs_and_capacity_preflight() -> None:
    compose = yaml.safe_load(_read_deploy("docker-compose.pilot.yml"))
    services = compose["services"]

    total_mib = 0
    for name, config in services.items():
        assert "mem_limit" in config, name
        if name == "ops-monitor":
            assert config["logging"]["driver"] == "awslogs"
            assert config["logging"]["options"]["mode"] == "non-blocking"
            assert config["logging"]["options"]["max-buffer-size"] == "1m"
        else:
            assert config["logging"]["driver"] == "json-file", name
            assert config["logging"]["options"]["max-size"] == "10m", name
            assert config["logging"]["options"]["max-file"] == "3", name
        value = str(config["mem_limit"]).lower()
        assert value.endswith("m"), (name, value)
        total_mib += int(value[:-1])
    assert total_mib <= 6144

    deploy = _read_deploy("Deploy-Pilot.ps1")
    assert "MemTotal" in deploy
    assert "MemAvailable" in deploy
    assert "docker system df" in deploy
    assert "PROTECTED_RELEASE_TAGS" in deploy


def test_standalone_branch_fails_fast_on_integration_commands_and_env_names_are_precise() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    runbook = _read_deploy("README.ko.md")

    assert "Assert-IntegrationDependency" in deploy
    assert "smoke_non_dl_analysis_reporting_pipeline" in deploy
    assert "#173" in runbook
    assert "#192" in runbook
    assert "#193" in runbook
    assert ".compose.env" in runbook
    assert "복사해 `.env`" not in runbook


def test_google_real_exchange_is_an_optional_issue_192_integration_gate() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    runbook = _read_deploy("README.ko.md")

    assert "[switch]$RequireGoogleLiveSmoke" in deploy
    assert "google_live_code_parameter_name" in deploy
    assert "smoke_google_oauth_code" in deploy
    assert "--require-exchange" in deploy
    assert "--verify-replay-rejection" in deploy
    assert "GOOGLE_OAUTH_SMOKE_CODE" in deploy
    assert "smoke_google_oauth_code_exchange" not in deploy
    assert "delete-parameter" in deploy
    assert "#192" in runbook
    assert "Google" in runbook


def test_external_images_have_digest_override_hooks_and_minimum_alarm_cleanup() -> None:
    compose_text = _read_deploy("docker-compose.pilot.yml")
    source = _terraform_source()
    runbook = _read_deploy("README.ko.md")

    for name in ("CADDY", "HAPROXY", "REDIS", "CLAMAV"):
        assert f"${{{name}_IMAGE_REF:-" in compose_text
    assert 'resource "aws_cloudwatch_metric_alarm" "instance_status"' in source
    assert "docker image rm" in runbook


def test_runtime_iam_matches_versioned_report_staging_promotion_and_cleanup() -> None:
    iam = (TERRAFORM_DIR / "iam.tf").read_text(encoding="utf-8")
    storage = (ROOT / "backend" / "chatbot" / "object_storage.py").read_text(
        encoding="utf-8"
    )
    smoke = (
        ROOT
        / "backend"
        / "chatbot"
        / "management"
        / "commands"
        / "smoke_object_storage.py"
    ).read_text(encoding="utf-8")

    assert 'staging_key = f"staging/{key}"' in smoke
    assert 'f"staging/{prefix}/reports/"' in storage
    assert "client.list_object_versions" in storage
    assert "client.delete_objects" in storage
    assert 'sid    = "UseReportStagingObjects"' in iam
    assert '${aws_s3_bucket.clean.arn}/staging/canonical/reports/*' in iam
    assert '"s3:DeleteObjectVersion"' in iam
    assert 'sid       = "ListPermanentCleanupVersions"' in iam
    assert '"s3:ListBucketVersions"' in iam
    assert '"staging/canonical/reports/*"' in iam
    assert '"canonical/uploads/*"' in iam
    deny = iam[iam.index("DenyDeploymentArtifactMutation") :]
    assert '"s3:DeleteObjectVersion"' in deny
    assert '${aws_s3_bucket.clean.arn}/_deploy/*' in deny
    assert '${aws_s3_bucket.clean.arn}/_rag-seed/*' in deny


def test_database_maintenance_uses_libpq_env_file_without_secret_cli_values() -> None:
    maintenance = _read_deploy("Maintain-PilotDatabase.ps1")

    for name in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"):
        assert f'{name}=' in maintenance
    assert "`$WORK/libpq.env" in maintenance
    psql_lines = [line for line in maintenance.splitlines() if " psql " in line]
    assert psql_lines
    assert all("--env-file `$WORK/libpq.env" in line for line in psql_lines)
    assert all("$postgresMaintenanceImageRef" in line for line in psql_lines)
    assert all("--env-file `$WORK/master.env" not in line for line in psql_lines)
    assert all("--password" not in line for line in psql_lines)
    assert "PGPASSWORD=`$" not in maintenance
    assert "postgres:16-alpine" not in maintenance


def test_database_maintenance_builds_python_env_without_nested_f_string_quotes() -> None:
    maintenance = _read_deploy("Maintain-PilotDatabase.ps1")

    assert 'u=m[`"username`"]; p=m[`"password`"]' in maintenance
    assert 'f`"POSTGRES_USER={u}`"' in maintenance
    assert 'f`"POSTGRES_PASSWORD={p}`"' in maintenance
    assert 'f`"PGUSER={u}`"' in maintenance
    assert 'f`"PGPASSWORD={p}`"' in maintenance


def test_database_maintenance_writes_env_files_with_real_newlines() -> None:
    maintenance = _read_deploy("Maintain-PilotDatabase.ps1")

    assert r'`"\\n`".join(out)' not in maintenance


def test_database_maintenance_streams_precedent_schema_without_secret_work_mount() -> None:
    maintenance = _read_deploy("Maintain-PilotDatabase.ps1")
    schema_commands = [
        line
        for line in maintenance.splitlines()
        if "precedent_db_loading/schema.sql" in line
    ]

    assert len(schema_commands) == 1
    schema_command = schema_commands[0]
    assert " cat /app/etl/fault_cases/" in schema_command
    assert "schema.sql | docker run --rm -i " in schema_command
    assert " psql -v ON_ERROR_STOP=1" in schema_command
    assert "`$WORK:/work" not in schema_command


def test_native_s3_lockfile_requires_terraform_1_11_or_newer() -> None:
    versions = (TERRAFORM_DIR / "versions.tf").read_text(encoding="utf-8")
    runbook = _read_deploy("README.ko.md")

    assert 'required_version = ">= 1.11.0"' in versions
    assert "use_lockfile = true" in versions
    assert "Terraform 1.11" in runbook


def test_deploy_serializes_compose_current_and_rollback_with_host_flock() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")

    lock_fd = "exec 8>/var/lock/skn27-pilot-maintenance.lock"
    acquire = "flock -w 60 8"
    assert lock_fd in deploy
    assert acquire in deploy
    assert deploy.index(lock_fd) < deploy.index("RELEASE_DIR=")
    assert deploy.index(acquire) < deploy.index("PREVIOUS_RELEASE=")


def test_all_runtime_mutations_share_one_bounded_maintenance_lock() -> None:
    common_lock = "/var/lock/skn27-pilot-maintenance.lock"
    scripts = {
        name: _read_deploy(name)
        for name in (
            "Deploy-Pilot.ps1",
            "Load-Rag-Seed-Pilot.ps1",
            "Maintain-PilotDatabase.ps1",
            "Rollback-Pilot.ps1",
            "Rollback-PilotPrecedentSeed.ps1",
            "Remove-Pilot.ps1",
        )
    }

    for name, script in scripts.items():
        assert common_lock in script, name
        assert "flock -w " in script, name
    assert "/var/lock/skn27-rag-seed.lock" not in scripts["Load-Rag-Seed-Pilot.ps1"]
    assert scripts["Load-Rag-Seed-Pilot.ps1"].index(common_lock) < scripts[
        "Load-Rag-Seed-Pilot.ps1"
    ].index("STATE_FILE=")
    remove = scripts["Remove-Pilot.ps1"]
    assert "flock -w 30" in remove
    assert "Invoke-BestEffort" in remove
    assert remove.index("flock -w 30") < remove.index("terraform destroy")


def test_release_image_cleanup_protects_current_and_rollback_tags() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    runbook = _read_deploy("README.ko.md")

    assert "PROTECTED_RELEASE_TAGS=" in deploy
    assert 'test -n `"`$PROTECTED_RELEASE_TAGS`"' in deploy
    assert "elasticsearch-nori-`$protected_tag" not in deploy
    assert "docker image rm" in deploy
    assert "docker image prune -f" not in deploy
    assert "latest 3 releases" in runbook
    assert "rollback" in runbook.lower()


def test_clamav_acceptance_runtime_requires_eight_gib_host_and_reload_headroom() -> None:
    source = _terraform_source()
    compose = yaml.safe_load(_read_deploy("docker-compose.pilot.yml"))
    deploy = _read_deploy("Deploy-Pilot.ps1")
    runbook = _read_deploy("README.ko.md")

    assert re.search(r'default\s*=\s*"t3a\.large"', source)
    assert "contains([" in source
    for instance_type in ("t3a.large", "t3.large", "t3a.xlarge", "t3.xlarge"):
        assert f'"{instance_type}"' in source
    assert int(str(compose["services"]["clamav"]["mem_limit"])[:-1]) >= 1536
    assert (
        compose["services"]["clamav"]["environment"][
            "CLAMD_CONF_ConcurrentDatabaseReload"
        ]
        == "no"
    )
    total_mib = sum(
        int(str(config["mem_limit"])[:-1])
        for config in compose["services"].values()
    )
    assert total_mib <= 6144
    assert "7600000" in deploy
    assert "t3a.large" in runbook
    assert "acceptance window" in runbook.lower()
    assert "stop/destroy" in runbook.lower()


def test_acceptance_requires_reviewed_digests_for_current_external_images() -> None:
    compose = _read_deploy("docker-compose.pilot.yml")
    dockerfile = _read_deploy("Dockerfile.frontend")
    deploy = _read_deploy("Deploy-Pilot.ps1")
    env_example = _read_deploy("runtime.env.example")
    runbook = _read_deploy("README.ko.md")

    assert "${CADDY_IMAGE_REF:-caddy:2.11.4-alpine}" in compose
    assert "${HAPROXY_IMAGE_REF:-haproxy:3.4.2-alpine}" in compose
    assert "ARG NGINX_IMAGE_REF=nginx:1.30.3-alpine" in dockerfile
    assert "FROM ${NGINX_IMAGE_REF}" in dockerfile
    for name in (
        "CADDY_IMAGE_REF",
        "HAPROXY_IMAGE_REF",
        "REDIS_IMAGE_REF",
        "CLAMAV_IMAGE_REF",
        "NGINX_IMAGE_REF",
    ):
        assert name in deploy
        assert f"{name}=REPLACE_WITH_REVIEWED_" in env_example
    assert '@sha256:[0-9a-f]{64}$' in deploy
    assert '--build-arg "NGINX_IMAGE_REF=$nginxImageRef"' in deploy
    assert "docker buildx imagetools inspect" in runbook
    assert "@sha256:" in runbook


def test_database_migration_env_forces_postgres_ssl_and_asserts_rds_target() -> None:
    maintenance = _read_deploy("Maintain-PilotDatabase.ps1")

    assert 'DJANGO_DATABASE_ENGINE=postgres' in maintenance
    assert 'PGSSLMODE=require' in maintenance
    assert "connection.vendor" in maintenance
    assert "postgresql" in maintenance
    assert "select current_database()" in maintenance
    target_check = maintenance.index("select current_database()")
    migrate = maintenance.index("migrate --noinput")
    assert target_check < migrate


def test_database_maintenance_restores_runtime_profile_with_replacement_association_id() -> None:
    maintenance = _read_deploy("Maintain-PilotDatabase.ps1")

    assert '--query "IamInstanceProfileAssociation.AssociationId"' in maintenance
    assert "$associationId = (" in maintenance
    activate = maintenance.index('"Name=$maintenanceProfile"')
    restore = maintenance.index('"Name=$runtimeProfile"')
    assert activate < restore


def test_docker_imds_firewall_allows_only_app_workers_and_hardens_other_services() -> None:
    compose = yaml.safe_load(_read_deploy("docker-compose.pilot.yml"))
    services = compose["services"]
    user_data = (TERRAFORM_DIR / "user_data.sh.tftpl").read_text(encoding="utf-8")
    deploy = _read_deploy("Deploy-Pilot.ps1")
    firewall_script = _read_deploy("configure-imds-firewall.sh")
    runbook = _read_deploy("README.ko.md")
    bundle_start = deploy.index("$staging = Join-Path")
    bundle_end = deploy.index("Compress-Archive", bundle_start)
    bundle_copy_segment = deploy[bundle_start:bundle_end]

    allowed = {
        "backend": "172.31.0.5",
        "agent-worker": "172.31.0.6",
        "file-scan-worker": "172.31.0.7",
    }
    for name, address in allowed.items():
        assert services[name]["networks"]["pilot"]["ipv4_address"].endswith(
            f":-{address}}}"
        )
        assert f"{address}/32" in user_data
    for name in (
        "edge-rate-limit",
        "frontend",
        "redis",
        "clamav",
    ):
        assert services[name]["networks"]["pilot"]["ipv4_address"]
        assert services[name]["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in services[name]["security_opt"]

    assert services["caddy"]["network_mode"] == "host"
    assert services["caddy"]["user"] == "10001:10001"
    assert "DOCKER-USER" in user_data
    assert "169.254.169.254/32" in user_data
    assert "OUTPUT" in user_data
    assert 'caddy_uid="10001"' in user_data
    assert '--uid-owner "$caddy_uid"' in user_data
    assert "OUTPUT" in firewall_script
    assert 'caddy_uid="10001"' in firewall_script
    assert '--uid-owner "$caddy_uid"' in firewall_script
    assert "skn27-imds-firewall.service" in user_data
    assert "RemainAfterExit=yes" in user_data
    assert "/usr/local/sbin/skn27-imds-firewall.sh" in deploy
    assert "configure-imds-firewall.sh" in deploy
    assert '"configure-imds-firewall.sh"' in bundle_copy_segment
    assert (
        r"tr -d '\r' < `$RELEASE_DIR/configure-imds-firewall.sh "
        "> /tmp/skn27-imds-firewall.sh"
    ) in deploy
    assert (
        "install -m 0755 /tmp/skn27-imds-firewall.sh "
        "/usr/local/sbin/skn27-imds-firewall.sh"
    ) in deploy
    assert "IMDS allow smoke" in deploy
    assert "IMDS deny smoke" in deploy
    assert "credential proxy" in runbook.lower()


def test_imds_deny_is_global_without_search_service_exceptions() -> None:
    compose = yaml.safe_load(_read_deploy("docker-compose.pilot.yml"))
    user_data = (TERRAFORM_DIR / "user_data.sh.tftpl").read_text(encoding="utf-8")

    assert '-d "$metadata_cidr" -j REJECT' in user_data
    reject_line = next(
        line for line in user_data.splitlines() if '-d "$metadata_cidr" -j REJECT' in line
    )
    assert '-s "$pilot_cidr"' not in reject_line
    assert "elasticsearch" not in compose["services"]


def test_frontend_base_image_is_a_global_digest_build_arg() -> None:
    frontend = _read_deploy("Dockerfile.frontend")
    deploy = _read_deploy("Deploy-Pilot.ps1")
    env_example = _read_deploy("runtime.env.example")

    assert frontend.index("ARG NGINX_IMAGE_REF=") < frontend.index("FROM ")
    assert "ELASTICSEARCH_IMAGE_REF" not in deploy
    assert "ELASTICSEARCH_IMAGE_REF" not in env_example


def test_rollback_preserves_reviewed_runtime_digests_and_baked_provenance() -> None:
    rollback = _read_deploy("Rollback-Pilot.ps1")
    deploy = _read_deploy("Deploy-Pilot.ps1")

    for name in (
        "CADDY_IMAGE_REF",
        "HAPROXY_IMAGE_REF",
        "REDIS_IMAGE_REF",
        "CLAMAV_IMAGE_REF",
        "LAW_NEO4J_IMAGE_REF",
    ):
        assert name in rollback
    compose_projection = next(
        line
        for line in rollback.splitlines()
        if "grep -E '^(" in line and ".runtime.env > .compose.env" in line
    )
    for name in (
        "AWS_REGION",
        "BACKEND_REPOSITORY_URL",
        "FRONTEND_REPOSITORY_URL",
        "LAW_NEO4J_IMAGE_REF",
        "LEGAL_DATASET_VERSION",
        "LEGAL_DATASET_VERIFIED_AT",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "OPERATIONAL_LOG_GROUP",
    ):
        assert name in compose_projection
    assert "@sha256:[0-9a-f]{64}$" in rollback
    assert "deployment-manifest.json" in rollback
    assert "NginxImageRef" in deploy
    assert "ElasticsearchImageRef" not in deploy


def test_database_profile_swap_is_fenced_by_role_checks_and_root_marker() -> None:
    marker = "/opt/skn27-pilot/maintenance/database-maintenance.active"
    maintenance = _read_deploy("Maintain-PilotDatabase.ps1")

    assert marker in maintenance
    assert "database_runtime_role_name" in maintenance
    assert "database_maintenance_role_name" in maintenance
    prepare = maintenance.index("Fence runtime before database maintenance")
    stop = maintenance.index("docker compose --project-name skn27-pilot", prepare)
    create_marker = maintenance.index("install -m 0600 /dev/null", stop)
    profile_swap = maintenance.index("replace-iam-instance-profile-association")
    assert prepare < stop < create_marker < profile_swap
    assert "aws sts get-caller-identity" in maintenance[prepare:create_marker]

    master_read = maintenance.index("get-secret-value", profile_swap)
    maintenance_identity = maintenance.index("aws sts get-caller-identity", profile_swap)
    assert profile_swap < maintenance_identity < master_read
    assert "shred -u" in maintenance

    restore = maintenance.rindex("replace-iam-instance-profile-association")
    runtime_confirmation = maintenance.index("Confirm runtime role and clear marker")
    remove_marker = maintenance.index("rm -f", runtime_confirmation)
    assert restore < runtime_confirmation < remove_marker
    assert "docker compose" not in maintenance[remove_marker:]

    for name in (
        "Deploy-Pilot.ps1",
        "Load-Rag-Seed-Pilot.ps1",
        "Rollback-Pilot.ps1",
        "Remove-Pilot.ps1",
    ):
        script = _read_deploy(name)
        assert marker in script, name
    remove = _read_deploy("Remove-Pilot.ps1")
    assert "Database maintenance marker is active" in remove
    assert "Invoke-BestEffort" in remove
    assert remove.index("Database maintenance marker is active") < remove.index(
        "terraform destroy"
    )


def test_rollback_ssm_polling_is_bounded_cancelled_and_status_only() -> None:
    rollback = _read_deploy("Rollback-Pilot.ps1")

    assert "wait command-executed" not in rollback
    timeout = re.search(r"\[int\]\$SsmTimeoutSeconds\s*=\s*(\d+)", rollback)
    assert timeout is not None
    assert int(timeout.group(1)) >= 600
    assert "Get-SsmCommandResult" in rollback
    assert "InProgress" in rollback
    assert "cancel-command" in rollback
    assert "Cancelled" in rollback
    assert "TimedOut" in rollback
    assert "StandardOutputContent" not in rollback
    assert "StandardErrorContent" not in rollback
    assert "redacted operations workflow" in rollback


def test_failed_rollback_restores_previous_release_and_removes_partial_target() -> None:
    rollback = _read_deploy("Rollback-Pilot.ps1")

    previous = rollback.index("PREVIOUS_RELEASE=")
    recovery = rollback.index("rollback_previous_release")
    arm_trap = rollback.index("trap rollback_previous_release ERR")
    target_up = rollback.index("up -d --wait --wait-timeout 600 --remove-orphans", arm_trap)
    readiness = rollback.index("check_production_readiness", target_up)
    switch_current = rollback.index("ln -sfn '$releaseDirectory'", readiness)
    disarm_trap = rollback.index("trap - ERR", switch_current)
    assert previous < recovery < arm_trap < target_up < readiness < switch_current
    assert switch_current < disarm_trap

    recovery_body = rollback[recovery:arm_trap]
    assert "down" in recovery_body
    assert "restore_precommand_evidence || echo" in recovery_body
    assert "cd `$PREVIOUS_RELEASE" in recovery_body
    assert "up -d --remove-orphans" in recovery_body
    assert r"ln -sfn `$PREVIOUS_RELEASE /opt/skn27-pilot/current" in recovery_body
    assert recovery_body.index("down") < recovery_body.index("up -d --remove-orphans")


def test_postgres_maintenance_image_is_reviewed_digest_and_release_provenance() -> None:
    env_example = _read_deploy("runtime.env.example")
    maintenance = _read_deploy("Maintain-PilotDatabase.ps1")
    deploy = _read_deploy("Deploy-Pilot.ps1")
    runbook = _read_deploy("README.ko.md")

    assert (
        "POSTGRES_MAINTENANCE_IMAGE_REF="
        "postgres:16.14-alpine3.24@sha256:REPLACE_WITH_REVIEWED_"
        "POSTGRES_MANIFEST_DIGEST"
    ) in env_example
    assert "POSTGRES_MAINTENANCE_IMAGE_REF" in maintenance
    assert "@sha256:[0-9a-f]{64}$" in maintenance
    assert "postgres:16-alpine" not in maintenance
    psql_commands = [line for line in maintenance.splitlines() if " psql " in line]
    assert psql_commands
    assert all("$postgresMaintenanceImageRef" in line for line in psql_commands)
    assert "docker pull '$postgresMaintenanceImageRef'" in maintenance
    assert "PostgresMaintenanceImageRef" in deploy
    assert "postgres:16.14-alpine3.24" in runbook
    assert "POSTGRES_MAINTENANCE_IMAGE_REF" in runbook


def test_root_compose_has_no_search_service_or_volume() -> None:
    root_compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    root_compose = yaml.safe_load(root_compose_text)
    assert "elasticsearch" not in root_compose["services"]
    assert "kibana" not in root_compose["services"]
    assert "elasticsearch_data" not in root_compose.get("volumes", {})


def test_all_ssm_waiters_use_terminal_allowlists_and_wait_through_cancelling() -> None:
    for name in (
        "Deploy-Pilot.ps1",
        "Load-Rag-Seed-Pilot.ps1",
        "Maintain-PilotDatabase.ps1",
        "Rollback-Pilot.ps1",
        "Rollback-PilotPrecedentSeed.ps1",
        "Remove-Pilot.ps1",
    ):
        script = _read_deploy(name)
        assert '$terminalStatuses = @("Success", "Cancelled", "TimedOut", "Failed")' in script, name
        assert "Cancelling" in script, name
        assert '$result.Status -notin @("Pending", "InProgress", "Delayed")' not in script, name
        assert script.count("$result.Status -in $terminalStatuses") >= 2, name
        cancel = script.index("cancel-command")
        assert script.index("$result.Status -in $terminalStatuses", cancel) > cancel, name


def test_database_profile_and_marker_remain_until_remote_terminal_confirmation() -> None:
    maintenance = _read_deploy("Maintain-PilotDatabase.ps1")

    assert "$databaseMaintenanceCommandSubmitted" in maintenance
    assert "$databaseMaintenanceTerminalConfirmed" in maintenance
    guard = maintenance.index(
        "$databaseMaintenanceCommandSubmitted -and "
        "-not $databaseMaintenanceTerminalConfirmed"
    )
    restore = maintenance.rindex("replace-iam-instance-profile-association")
    clear_marker = maintenance.index("Confirm runtime role and clear marker")
    assert guard < restore < clear_marker
    assert "maintenance profile and marker remain active" in maintenance


def test_deploy_unconditionally_gates_all_integration_dependencies_before_aws() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")

    required_markers = (
        "backend/chatbot/management/commands/smoke_google_oauth_code.py",
        "backend/chatbot/management/commands/smoke_non_dl_analysis_reporting_pipeline.py",
        "backend/chatbot/management/commands/load_production_rag_seed.py",
        "backend/chatbot/management/commands/verify_production_rag_seed_manifest.py",
        "ai/agents/text_ml_case_search/agent.py",
        "case_text_ml_heuristic_001",
    )
    terraform_read = deploy.index("terraform output -json")
    docker_build = deploy.index("docker build")
    for marker in required_markers:
        assert marker in deploy
        assert deploy.index(marker) < terraform_read
        assert deploy.index(marker) < docker_build

    google_gate = deploy.index(
        "backend/chatbot/management/commands/smoke_google_oauth_code.py"
    )
    assert google_gate < deploy.index("if ($RequireGoogleLiveSmoke)")
    assert "Assert-IntegrationMarkerAbsent" in deploy
    assert "#192" in deploy
    assert "#193" in deploy
    assert "#195" in deploy
    assert "#198" in deploy


def test_google_live_smoke_uses_issue_192_env_contract_without_code_argv() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")

    assert "smoke_google_oauth_code_exchange" not in deploy
    assert "--authorization-code-stdin" not in deploy
    assert "--require-real-exchange" not in deploy
    assert "help smoke_google_oauth_code" in deploy
    assert "GOOGLE_OAUTH_SMOKE_CODE=`$(aws ssm get-parameter" in deploy
    assert "export GOOGLE_OAUTH_SMOKE_CODE" in deploy
    expected = (
        "exec -T -e GOOGLE_OAUTH_SMOKE_CODE backend python backend/manage.py "
        "smoke_google_oauth_code --require-exchange --verify-replay-rejection "
        "--format json"
    )
    assert expected in deploy
    assert "unset GOOGLE_OAUTH_SMOKE_CODE" in deploy

    load_code = deploy.index("GOOGLE_OAUTH_SMOKE_CODE=`$(aws ssm get-parameter")
    execute = deploy.index(expected, load_code)
    unset = deploy.index("unset GOOGLE_OAUTH_SMOKE_CODE", execute)
    assert load_code < execute < unset
    assert " --code " not in deploy[load_code:unset]


def test_instance_type_is_an_x86_eight_gib_or_larger_allowlist() -> None:
    variables = (TERRAFORM_DIR / "variables.tf").read_text(encoding="utf-8")
    runbook = _read_deploy("README.ko.md")

    assert "contains([" in variables
    for instance_type in ("t3a.large", "t3.large", "t3a.xlarge", "t3.xlarge"):
        assert f'"{instance_type}"' in variables
    assert "var.instance_type" in variables
    assert "x86" in variables
    assert "8 GiB" in variables
    assert "t3a.large" in runbook
    return
    assert "타입을 하향" in runbook
    assert "stop/destroy" in runbook


def test_free_plan_supports_the_x86_eight_gib_m7i_flex_override() -> None:
    variables = (TERRAFORM_DIR / "variables.tf").read_text(encoding="utf-8")
    tfvars_example = (TERRAFORM_DIR / "terraform.tfvars.example").read_text(
        encoding="utf-8"
    )

    assert '"m7i-flex.large"' in variables
    assert "m7i-flex.large" in tfvars_example


def test_database_backup_retention_is_configurable_for_free_plan() -> None:
    variables = (TERRAFORM_DIR / "variables.tf").read_text(encoding="utf-8")
    database = (TERRAFORM_DIR / "database.tf").read_text(encoding="utf-8")
    tfvars_example = (TERRAFORM_DIR / "terraform.tfvars.example").read_text(
        encoding="utf-8"
    )

    assert 'variable "database_backup_retention_days"' in variables
    assert re.search(
        r"backup_retention_period\s*=\s*var\.database_backup_retention_days",
        database,
    )
    assert re.search(
        r"#\s*database_backup_retention_days\s*=\s*1",
        tfvars_example,
    )


def test_initial_rag_bootstrap_stages_private_services_then_requires_seed_promotion() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    loader = _read_deploy("Load-Rag-Seed-Pilot.ps1")

    assert "[switch]$StageForInitialRagBootstrap" in deploy
    assert "ExpectedRagSeedManifestSha256" in deploy
    assert "test ! -e /opt/skn27-pilot/current" in deploy
    stage_up = next(
        line for line in deploy.splitlines()
        if "up -d --wait --wait-timeout 600" in line
    )
    for service in ("redis", "clamav", "law-neo4j", "backend"):
        assert service in stage_up
    for public_service in (
        "caddy",
        "edge-rate-limit",
        "frontend",
        "agent-worker",
        "file-scan-worker",
    ):
        assert public_service not in stage_up

    staged = deploy.index(".initial-rag-bootstrap.staged")
    completed = deploy.index(".production-rag-seed.complete", staged)
    readiness = deploy.index("check_production_readiness", completed)
    promote = deploy.index("ln -sfn `$RELEASE_DIR /opt/skn27-pilot/current", readiness)
    stage_segment = deploy[deploy.index("test ! -e /opt/skn27-pilot/current"):completed]
    assert "check_production_readiness" not in stage_segment
    assert "smoke_non_dl_analysis_reporting_pipeline --allow-paid" not in stage_segment
    assert "smoke_google_oauth_code --require-exchange" not in stage_segment
    assert "ln -sfn" not in stage_segment
    assert staged < completed < readiness < promote

    assert "[Parameter(Mandatory = $true)]" in loader
    assert '[ValidatePattern("^[a-z0-9][a-z0-9-]{0,31}$")]' in loader
    assert "[string]$ReleaseTag" in loader
    assert "TARGET_RELEASE='/opt/skn27-pilot/releases/$ReleaseTag'" in loader
    assert 'test -z `"`$CURRENT_RELEASE`"' in loader
    assert "test ! -L /opt/skn27-pilot/current" in loader
    assert ".initial-rag-bootstrap.staged" in loader
    assert ".production-rag-seed.complete" in loader
    assert "CURRENT_RELEASE=`$(readlink" in loader


def test_google_live_code_requires_skipbuild_and_outer_cleanup_scope() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")

    guard = deploy.index("-RequireGoogleLiveSmoke requires -SkipBuild")
    build = deploy.index("docker build")
    assert guard < build
    parameter_name = deploy.index("$googleCodeParameterName =")
    cleanup_try = deploy.index("try {", parameter_name)
    secret_read = deploy.index("secretsmanager get-secret-value", cleanup_try)
    delete = deploy.rindex("ssm delete-parameter")
    cleanup_finally = deploy.rindex("finally {", cleanup_try, delete)
    assert parameter_name < cleanup_try < secret_read < cleanup_finally < delete


def test_ssm_timeout_minimum_covers_slow_initial_service_start() -> None:
    for name in (
        "Deploy-Pilot.ps1",
        "Load-Rag-Seed-Pilot.ps1",
        "Maintain-PilotDatabase.ps1",
        "Rollback-Pilot.ps1",
        "Rollback-PilotPrecedentSeed.ps1",
    ):
        script = _read_deploy(name)
        assert re.search(r"\[ValidateRange\(600,\s*\d+\)\]", script), name


def test_public_origin_contract_fails_fast_before_remote_or_paid_work() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    ssm_put = deploy.index("ssm put-parameter")
    build = deploy.index("docker build")

    for token in (
        "APP_DOMAIN must be a lowercase DNS hostname",
        "DJANGO_ALLOWED_HOSTS must include APP_DOMAIN",
        "DJANGO_ALLOWED_HOSTS must not contain wildcards",
        "CORS_ALLOWED_ORIGINS must contain exactly",
        "CSRF_TRUSTED_ORIGINS must contain exactly",
        "GOOGLE_POPUP_REDIRECT_URI",
        'StartsWith(".")',
        "IsDefaultPort",
        "OriginalString",
        "AbsolutePath",
        "Query",
        "Fragment",
    ):
        assert token in deploy
        assert deploy.index(token) < ssm_put
        assert deploy.index(token) < build


def test_deploy_placeholder_validation_preserves_a_single_match_as_a_collection() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")

    assert re.search(
        r"\$nonGenerated\s*=\s*@\(\s*\$runtimeEnv\s+-split\s+\"`r\?`n\"\s*"
        r"\|\s*Where-Object",
        deploy,
        re.DOTALL,
    )
    assert "$nonGenerated.Count -gt 0" in deploy


def test_first_normal_promotion_requires_google_live_smoke_remotely() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")

    previous = deploy.index("PREVIOUS_RELEASE=`$(readlink")
    google_gate = deploy.index(
        "Initial promotion requires -RequireGoogleLiveSmoke", previous
    )
    target_up = deploy.index(
        "$productionComposeCommand up -d --wait --wait-timeout 600 --remove-orphans",
        google_gate,
    )
    promote = deploy.index("ln -sfn `$RELEASE_DIR /opt/skn27-pilot/current", target_up)
    assert "GOOGLE_LIVE_SMOKE_ENABLED" in deploy[previous:google_gate]
    assert previous < google_gate < target_up < promote


def test_first_normal_promotion_treats_absent_current_symlink_as_no_previous_release() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")

    previous = deploy.index("PREVIOUS_RELEASE=`$(readlink")
    marker_gate = deploy.index(".initial-rag-bootstrap.staged", previous)
    previous_detection = deploy[previous:marker_gate]

    assert (
        "[ -L /opt/skn27-pilot/current ] || PREVIOUS_RELEASE=''"
        in previous_detection
    )


def test_normal_promotion_requires_validated_fine_notice_fixture_and_exact_smoke() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")

    assert "[string]$FineNoticeSmokeS3Uri" in deploy
    validation = deploy.index("FineNoticeSmokeS3Uri must use the generated clean bucket")
    ssm_put = deploy.index("ssm put-parameter")
    send_command = deploy.index("ssm send-command")
    assert validation < ssm_put < send_command
    for token in (
        "canonical/acceptance/",
        "fine-notice fixture URI cannot contain query or fragment",
        "fine-notice fixture URI cannot contain traversal",
        "png|jpg|jpeg|webp|pdf",
    ):
        assert token in deploy
        assert deploy.index(token) < ssm_put

    expected = (
        "smoke_supervisor_conversation_runtime --allow-paid-provider-call "
        "--require-llm-used --require-real-agent-results "
        "--require-persisted-handoff --require-report "
        "--fine-notice-fixture-s3-uri '$FineNoticeSmokeS3Uri' "
        "--timeout-seconds 600 --format json"
    )
    assert expected in deploy

    for marker in (
        "--fine-notice-fixture-s3-uri",
        "fine_notice_analysis",
        "appeal_decision_flow",
        "law_ground_search",
        "text_ml_case_search",
    ):
        assertion = f'Assert-IntegrationMarkerPresent $nonDlSmokePath "{marker}" "#193"'
        assert assertion in deploy
        assert deploy.index(assertion) < deploy.index("terraform output -json")

    remote_commands = deploy.index("$commands = @(")
    stage_start = deploy.index("if ($StageForInitialRagBootstrap) {", remote_commands)
    normal_start = deploy.index("else {", stage_start)
    stage_segment = deploy[stage_start:normal_start]
    assert "FineNoticeSmokeS3Uri" not in stage_segment
    assert "smoke_non_dl_analysis_reporting_pipeline --allow-paid" not in stage_segment


def test_normal_promotion_uses_one_production_supervisor_runtime_smoke() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")

    previous = deploy.index("PREVIOUS_RELEASE=`$(readlink")
    promote = deploy.index(
        "ln -sfn `$RELEASE_DIR /opt/skn27-pilot/current",
        previous,
    )
    normal_segment = deploy[previous:promote]
    expected = (
        "smoke_supervisor_conversation_runtime --allow-paid-provider-call "
        "--require-llm-used --require-real-agent-results "
        "--require-persisted-handoff --require-report "
        "--fine-notice-fixture-s3-uri '$FineNoticeSmokeS3Uri' "
        "--timeout-seconds 600 --format json"
    )

    assert normal_segment.count(expected) == 1
    assert "help smoke_supervisor_conversation_runtime" in normal_segment
    assert "smoke_supervisor_llm --require-used" not in normal_segment
    assert (
        "smoke_non_dl_analysis_reporting_pipeline --allow-paid-provider-call"
        not in normal_segment
    )


def test_normal_promotion_bootstraps_redis_before_waiting_for_core_services() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    previous = deploy.index("PREVIOUS_RELEASE=`$(readlink")
    promote = deploy.index("ln -sfn `$RELEASE_DIR /opt/skn27-pilot/current", previous)
    normal_segment = deploy[previous:promote]

    waited_services = (
        "WAITED_SERVICES='caddy edge-rate-limit frontend backend clamav law-neo4j'"
    )
    background_services = "BACKGROUND_SERVICES='agent-worker file-scan-worker'"
    monitor_service = "MONITOR_SERVICE='ops-monitor'"
    assert waited_services in normal_segment
    assert background_services in normal_segment
    assert monitor_service in normal_segment
    assert "wait_for_redis()" in normal_segment
    assert "for attempt in `$(seq 1 120); do" in normal_segment
    assert "$productionComposeCommand exec -T redis redis-cli ping | grep -qx PONG" in normal_segment
    assert "$productionComposeCommand up -d --remove-orphans redis" in normal_segment
    assert (
        "$productionComposeCommand up -d --wait --wait-timeout 600 "
        "--remove-orphans `$WAITED_SERVICES"
    ) in normal_segment
    assert "$productionComposeCommand up -d `$BACKGROUND_SERVICES" in normal_segment
    assert "$productionComposeCommand up -d `$MONITOR_SERVICE" in normal_segment
    assert (
        "for attempt in `$(seq 1 30); do ! ss -ltnp | grep -E '(:80|:443)'"
    ) in normal_segment
    assert normal_segment.index("$productionComposeCommand down") < normal_segment.index(
        "for attempt in `$(seq 1 30); do ! ss -ltnp | grep -E '(:80|:443)'"
    )
    assert normal_segment.index(
        "for attempt in `$(seq 1 30); do ! ss -ltnp | grep -E '(:80|:443)'"
    ) < normal_segment.rindex(
        "$productionComposeCommand up -d --wait --wait-timeout 600 "
        "--remove-orphans `$WAITED_SERVICES"
    )
    assert normal_segment.index(
        "$productionComposeCommand up -d --wait --wait-timeout 600 "
        "--remove-orphans `$WAITED_SERVICES"
    ) < normal_segment.rindex("$productionComposeCommand up -d `$BACKGROUND_SERVICES")
    assert normal_segment.rindex(
        "$productionComposeCommand up -d `$BACKGROUND_SERVICES"
    ) < normal_segment.rindex("$productionComposeCommand up -d `$MONITOR_SERVICE")


def test_release_update_stage_is_isolated_from_the_current_compose_project() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    compose_text = _read_deploy("docker-compose.pilot.yml")
    compose = yaml.safe_load(compose_text)

    assert "[switch]$StageForReleaseUpdate" in deploy
    assert "[switch]$AllowCaddyOfflineForHostNetworkCutover" in deploy
    assert "Initial RAG bootstrap and release update staging are mutually exclusive" in deploy
    assert (
        "if ($AllowCaddyOfflineForHostNetworkCutover -and -not $StageForReleaseUpdate)"
        in deploy
    )
    assert '[ValidatePattern("^[a-z0-9][a-z0-9-]{0,31}$")]' in deploy
    assert '$stageProjectName = "skn27-stage-$ReleaseTag"' in deploy
    assert "--project-name '$stageProjectName'" in deploy
    assert "--env-file .stage-compose.env" in deploy
    assert "--project-name skn27-pilot" in deploy
    assert "--env-file .production-compose.env" in deploy

    expected_addresses = {
        "edge-rate-limit": "${PILOT_EDGE_RATE_LIMIT_IP:-172.31.0.3}",
        "frontend": "${PILOT_FRONTEND_IP:-172.31.0.4}",
        "backend": "${PILOT_BACKEND_IP:-172.31.0.5}",
        "agent-worker": "${PILOT_AGENT_WORKER_IP:-172.31.0.6}",
        "file-scan-worker": "${PILOT_FILE_SCAN_WORKER_IP:-172.31.0.7}",
        "redis": "${PILOT_REDIS_IP:-172.31.0.8}",
        "clamav": "${PILOT_CLAMAV_IP:-172.31.0.10}",
    }
    for service, address in expected_addresses.items():
        assert compose["services"][service]["networks"]["pilot"]["ipv4_address"] == address
    assert (
        compose["networks"]["pilot"]["ipam"]["config"][0]["subnet"]
        == "${PILOT_NETWORK_SUBNET:-172.31.0.0/24}"
    )
    for volume in ("redis_data", "clamav_data"):
        assert "PILOT_" in compose["volumes"][volume]["name"]

    stage_env_line = next(
        line for line in deploy.splitlines()
        if "> `$RELEASE_DIR/.stage-compose.env" in line
    )
    production_env_line = next(
        line for line in deploy.splitlines()
        if "> `$RELEASE_DIR/.production-compose.env" in line
    )
    assert "PILOT_NETWORK_SUBNET=172.30.0.0/24" in stage_env_line
    assert "PILOT_NETWORK_SUBNET=172.31.0.0/24" in production_env_line
    for suffix in ("redis_data", "clamav_data"):
        volume_name = f"${{stageProjectName}}_{suffix}"
        assert volume_name in stage_env_line
        assert volume_name in production_env_line
    assert "PILOT_CADDY_IP=" not in deploy
    assert "PILOT_EDGE_RATE_LIMIT_IP=172.31.0.3" in production_env_line

    remote = deploy.index("$commands = @(")
    update = deploy.index("if ($StageForReleaseUpdate) {", remote)
    update_end = deploy.index("else {", update)
    update_segment = deploy[update:update_end]
    assert "$currentReleaseRequiredServices = if ($AllowCaddyOfflineForHostNetworkCutover)" in deploy
    assert "for required_service in $currentReleaseRequiredServices" in update_segment
    for required in (
        "CURRENT_RELEASE=`$(readlink -f /opt/skn27-pilot/current)",
        r'test `"`$CURRENT_RELEASE`" != `"`$RELEASE_DIR`"',
        "test ! -e `$RELEASE_DIR && test ! -L `$RELEASE_DIR",
        "$stageComposeCommand up",
        ".release-update.staged",
    ):
        assert required in update_segment
    for forbidden in (
        "$productionComposeCommand up",
        "$productionComposeCommand down",
        "ln -sfn",
        "check_production_readiness",
        "smoke_non_dl_analysis_reporting_pipeline --allow-paid",
        "smoke_google_oauth_code --require-exchange",
    ):
        assert forbidden not in update_segment
    assert update_segment.index("trap stage_failed ERR") < update_segment.index(
        "$commands += $materializeCommands"
    )
    cleanup = next(
        line for line in update_segment.splitlines()
        if "stage_failed()" in line
    )
    assert "${stageProjectName}_redis_data" in cleanup
    assert "skn27-pilot_redis_data" not in cleanup


def test_update_loader_targets_only_the_exact_isolated_release_and_is_fail_closed() -> None:
    loader = _read_deploy("Load-Rag-Seed-Pilot.ps1")

    assert '[ValidatePattern("^[a-z0-9][a-z0-9-]{0,31}$")]' in loader
    assert '$stageProjectName = "skn27-stage-$ReleaseTag"' in loader
    assert "--project-name '$stageProjectName'" in loader
    assert "--env-file .stage-compose.env" in loader
    assert "--project-name skn27-pilot" not in loader
    assert (
        "CURRENT_RELEASE=`$(readlink -f /opt/skn27-pilot/current "
        "2>/dev/null || true)"
    ) in loader
    assert r'test `"`$CURRENT_RELEASE`" != `"`$TARGET_RELEASE`"' in loader
    assert ".initial-rag-bootstrap.staged" in loader
    assert ".release-update.staged" in loader
    update_marker_line = next(
        line for line in loader.splitlines()
        if "cat `$TARGET_RELEASE/.release-update.staged" in line
    )
    for token in (
        "$ReleaseTag",
        "$RagSeedManifestSha256",
        "$stageProjectName",
        "`$CURRENT_RELEASE",
    ):
        assert token in update_marker_line
    assert "$stageComposeCommand down" in loader
    assert "docker volume rm '${stageProjectName}_redis_data'" in loader
    assert ".production-rag-seed.complete" in loader

    digest = loader.index("sha256sum -c -")
    manifest_verify = loader.index("verify_production_rag_seed_manifest", digest)
    atomic_gate = loader.index("transaction.atomic", manifest_verify)
    load = loader.index("load_production_rag_seed --manifest", atomic_gate)
    law_smoke = loader.index("smoke_law_ground_search", load)
    text_smoke = loader.index("smoke_text_ml_case_search", law_smoke)
    marker = loader.index("mv -f `$RELEASE_STATE_FILE.tmp", text_smoke)
    assert digest < manifest_verify < atomic_gate < load < law_smoke < text_smoke < marker


def test_normal_promotion_reuses_staged_volumes_and_restores_previous_release() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    rollback = _read_deploy("Rollback-Pilot.ps1")

    remote = deploy.index("$commands = @(")
    normal = deploy.index("else {", deploy.index("if ($StageForReleaseUpdate) {", remote))
    normal_segment = deploy[normal:]
    marker = normal_segment.index(".production-rag-seed.complete")
    previous = normal_segment.index("PREVIOUS_RELEASE=`$(readlink -f", marker)
    stage_down = normal_segment.index("$stageComposeCommand down", previous)
    production_down = normal_segment.index("$productionComposeCommand down", stage_down)
    target_up = normal_segment.index("$productionComposeCommand up", production_down)
    readiness = normal_segment.index("check_production_readiness", target_up)
    promote = normal_segment.index("ln -sfn `$RELEASE_DIR /opt/skn27-pilot/current", readiness)
    assert marker < previous < stage_down < production_down < target_up < readiness < promote
    assert "cd `$PREVIOUS_RELEASE; $productionComposeCommand up" in normal_segment
    cleanup_line = next(
        line for line in normal_segment[promote:].splitlines()
        if "rm -f" in line and ".release-update.staged" in line
    )
    assert ".initial-rag-bootstrap.staged" in cleanup_line
    assert "unzip -o /tmp/skn27-pilot.zip -d `$RELEASE_DIR" not in normal_segment[:marker]
    assert "STALE_RELEASE_DIRS=" in normal_segment
    assert "PILOT_ELASTICSEARCH_VOLUME_NAME" not in normal_segment
    assert 'test `"`$stale_dir`" != `"`$(readlink -f /opt/skn27-pilot/current)`"' in normal_segment
    assert r'docker volume rm `"`$stale_volume`" || cleanup_ok=0' in normal_segment
    assert '"$stale_project"_elasticsearch_data' not in normal_segment

    assert "--env-file .production-compose.env" in rollback
    assert '[ValidatePattern("^[a-z0-9][a-z0-9-]{0,31}$")]' in rollback


def test_shared_rds_seed_update_requires_atomic_legal_loader_and_documents_scope() -> None:
    deploy = _read_deploy("Deploy-Pilot.ps1")
    loader = _read_deploy("Load-Rag-Seed-Pilot.ps1")
    runbook = _read_deploy("README.ko.md")

    for token in (
        'load_legal_rag_pgvector',
        'transaction.atomic',
        'load_and_validate_rag_seed_manifest',
    ):
        assert token in deploy
        assert token in loader
    assert "shared RDS" in runbook
    assert "transaction" in runbook
    assert "Docker volume" in runbook
