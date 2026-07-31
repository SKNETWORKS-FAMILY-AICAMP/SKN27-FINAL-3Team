from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


REQUIRED_DOCS = [
    ROOT / "docs" / "deployment-readiness-review-2026-06-22.md",
    ROOT / "docs" / "ops" / "release-checklist.md",
    ROOT / "docs" / "ops" / "rollback-plan.md",
    ROOT / "docs" / "ops" / "incident-response.md",
    ROOT / "docs" / "ops" / "secret-management.md",
    ROOT / "docs" / "ops" / "production-env.md",
    ROOT / "docs" / "ops" / "backup-and-recovery.md",
    ROOT / "docs" / "ops" / "legal-data-freshness-runbook.md",
    ROOT / "docs" / "ops" / "analysis-execution-provenance.md",
    ROOT / "docs" / "ops" / "caddy-credential-log-incident-runbook.md",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_required_operations_documents_exist():
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_DOCS if not path.exists()]
    assert missing == []


def test_deployment_readiness_review_has_required_sections():
    content = read_text(ROOT / "docs" / "deployment-readiness-review-2026-06-22.md")
    required_sections = [
        "## 1. 프로젝트 요약",
        "## 2. 최종 판정",
        "## 4. 즉시 배포 차단 항목",
        "## 6. 영역별 검토 결과",
        "## 8. 최종 추천",
        "## 10. 최종 배포 승인 체크리스트",
    ]
    missing = [section for section in required_sections if section not in content]
    assert missing == []


def test_release_readiness_recommends_standard_operations():
    content = read_text(ROOT / "docs" / "deployment-readiness-review-2026-06-22.md")
    assert "**배포 불가**" in content
    assert "1순위: 표준 운영형" in content
    assert "최소 운영형" in content
    assert "고신뢰 운영형" in content


def test_static_mvp_html_is_utf8_korean_service_screen():
    html = read_text(ROOT / "app" / "screen-design-mvp-flow.html")
    assert '<meta charset="UTF-8">' in html
    assert 'lang="ko"' in html
    assert "교통분쟁 AI" in html


def test_secret_management_document_defines_rotation_and_logging_rules():
    content = read_text(ROOT / "docs" / "ops" / "secret-management.md")
    assert "## 2. 로그 원칙" in content
    assert "## 3. 교체 절차" in content
    assert "Authorization" in content
    assert "Cookie" in content


def test_caddy_credential_log_incident_runbook_is_complete_and_redacted():
    content = read_text(
        ROOT / "docs" / "ops" / "caddy-credential-log-incident-runbook.md"
    )
    for token in (
        "Authorization",
        "Cookie",
        "X-Guest-Credential",
        "caddy_logs",
        "CloudWatch",
        "backup",
        "replication",
        "APP_JWT_SECRET",
        "SSM",
        "backend",
        "agent-worker",
        "file-scan-worker",
        "ops-monitor",
        "401",
        "credential canary",
        "zero match",
        "release SHA",
        "dataset version",
        "운영 승인",
    ):
        assert token in content

    assert "실제 token 값을 증적" in content
    assert "실제 token 값을 명령행" in content


def test_production_env_template_contains_readiness_keys():
    content = read_text(ROOT / ".env.production.example")
    required_keys = [
        "DJANGO_DEBUG=0",
        "DJANGO_SECRET_KEY=",
        "DJANGO_ALLOWED_HOSTS=",
        "DJANGO_DATABASE_ENGINE=postgres",
        "CORS_ALLOWED_ORIGINS=",
        "CSRF_TRUSTED_ORIGINS=",
        "GOOGLE_CLIENT_ID=",
        "GOOGLE_CLIENT_SECRET=",
        "GOOGLE_POPUP_REDIRECT_URI=",
        "APP_JWT_SECRET=",
        "OAUTH_TOKEN_SECRET=",
        "POSTGRES_IMAGE=pgvector/pgvector:pg16",
        "REDIS_URL=",
        "AGENT_WORKER_STALE_AFTER_SECONDS=",
        "AGENT_WORKER_RETRY_BACKOFF_SECONDS=",
        "AGENT_WORKER_LOOP_SLEEP_SECONDS=",
        "SUPERVISOR_LLM_ENABLED=",
        "LEGAL_RAG_VECTOR_ENABLED=1",
        "APP_RELEASE_VERSION=",
        "LEGAL_DATASET_VERSION=",
        "LEGAL_DATASET_VERIFIED_AT=",
        "TEXT_ML_CASE_SEARCH_PGVECTOR_TOP_K=5",
        "TEXT_ML_CASE_SEARCH_V2_REVIEW_CASE_QUOTA=5",
        "TEXT_ML_CASE_SEARCH_V2_FAULT_RATIO_PRECEDENT_QUOTA=5",
        "TEXT_ML_CASE_SEARCH_V2_FINAL_TOP_K=10",
        "OBJECT_STORAGE_PROVIDER=s3",
    ]
    missing = [key for key in required_keys if key not in content]
    assert missing == []


def test_production_defaults_enable_local_pgvector_retrieval():
    compose = read_text(ROOT / "docker-compose.yml")
    production_env = read_text(ROOT / ".env.production.example")

    assert "--provider sentence-transformers" in compose
    assert "--provider openai" not in compose
    assert 'profiles: ["seed"]' in compose
    assert "LEGAL_RAG_VECTOR_ENABLED=1" in production_env


def test_production_env_doc_references_readiness_command_and_secret_rules():
    content = read_text(ROOT / "docs" / "ops" / "production-env.md")
    assert "check_production_readiness" in content
    assert "--fail-on-error" in content
    assert ".env.production.example" in content
    assert "secret store" in content
    assert "law_chunks" in content
    assert "law_embeddings" in content
    assert "load_legal_rag_pgvector" in content
    assert "load_legal_rag_smoke_fixture" not in content
    assert "legal_rag_smoke_chunks.jsonl" not in content
    assert "verify_pgvector_rag_readiness" in content
    assert "smoke_text_ml_case_search" in content
    assert "TEXT_ML_CASE_SEARCH_PGVECTOR_TOP_K" in content
    assert "TEXT_ML_CASE_SEARCH_SYNC_USE_ES" not in content
    assert "FAULT_RATIO_PRECEDENT_ES_BM25_INDEX" not in content
    assert "process_agent_work_items --loop" in content
    assert "smoke_supervisor_conversation_runtime" in content
    assert "--require-llm-used" in content
    assert "--require-real-agent-results" in content
    assert "--require-persisted-handoff" in content
    assert "--require-report" in content
    assert "smoke_google_oauth_code" in content
    assert "smoke_object_storage" in content
    assert "smoke_persona_catalog" in content


def test_legal_freshness_runbook_has_bounded_validation_and_failure_actions():
    content = read_text(ROOT / "docs" / "ops" / "legal-data-freshness-runbook.md")

    assert "python -m etl.legal.ingestion.run" in content
    assert "validate_run_summary.py" in content
    assert "--max-age-hours" in content
    assert "missing_sources" in content
    assert "failed_sources" in content
    assert "stale_sources" in content
    assert "배포를 중단" in content
    assert "reports/run_summary.json" in content


def test_operational_health_runtime_settings_are_documented_without_secrets():
    setting_names = {
        "OPERATIONAL_HEALTH_INTERVAL_SECONDS",
        "OPERATIONAL_HEALTH_WINDOW_MINUTES",
        "OPERATIONAL_QUEUE_AGE_WARN_SECONDS",
        "OPERATIONAL_LEASE_STALE_SECONDS",
        "OPERATIONAL_LEGAL_RUN_SUMMARY_PATH",
        "OPERATIONAL_LEGAL_MAX_AGE_HOURS",
        "OPERATIONAL_LEGAL_REQUIRED_SOURCES",
    }
    settings_source = read_text(ROOT / "backend" / "config" / "settings.py")
    for name in setting_names:
        assert name in settings_source

    for relative_path in (
        ".env.example",
        ".env.production.example",
        "deploy/aws-pilot/runtime.env.example",
    ):
        content = read_text(ROOT / relative_path)
        keys = {
            line.split("=", 1)[0]
            for line in content.splitlines()
            if line and not line.startswith("#") and "=" in line
        }
        assert setting_names.issubset(keys)
        assert "OPERATIONAL_ALERT_EMAIL" not in keys


def test_operational_observability_runbook_maps_safe_alerts_to_actions():
    runbook = read_text(ROOT / "docs" / "ops" / "operational-observability-runbook.md")
    for token in (
        "observe_operational_health --once",
        "show_analysis_job_provenance --job-id",
        "queue_backlog",
        "queue_oldest_age_exceeded",
        "worker_lease_stale",
        "worker_failure",
        "worker_timeout",
        "provider_failure",
        "legal_data_missing",
        "legal_data_stale",
        "legal_data_refresh_failed",
        "legal_data_provenance_mismatch",
        "monitor_configuration_invalid",
        "SNS",
        "구독 확인",
        "terraform.tfvars",
        "실제 부하",
    ):
        assert token in runbook

    checklist = read_text(ROOT / "docs" / "ops" / "project-readiness-master-checklist.md")
    assert "2026-07-23-runpod-serverless-vision-design.md" in checklist
    assert "VISION_RUNTIME_PROVIDER=runpod" in checklist
    assert "RunPod Endpoint" in checklist


def test_runpod_vision_runtime_is_documented_without_committed_secrets():
    required_keys = {
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
    }
    env_by_path = {}
    for relative_path in (
        ".env.example",
        ".env.production.example",
        "deploy/aws-pilot/runtime.env.example",
    ):
        content = read_text(ROOT / relative_path)
        env_by_path[relative_path] = content
        keys = {
            line.split("=", 1)[0]
            for line in content.splitlines()
            if line and not line.startswith("#") and "=" in line
        }
        assert required_keys.issubset(keys)
        assert "RUNPOD_API_KEY=" in content
        assert "RUNPOD_API_KEY=replace-" not in content
        assert "JUPYTER" not in "\n".join(
            line for line in content.splitlines() if line.startswith("VISION_")
        )

    assert "VISION_RUNTIME_PROVIDER=local" in env_by_path[".env.example"]
    assert (
        "VISION_RUNTIME_PROVIDER=runpod"
        in env_by_path[".env.production.example"]
    )
    assert (
        "VISION_RUNTIME_PROVIDER=runpod"
        in env_by_path["deploy/aws-pilot/runtime.env.example"]
    )

    compose = read_text(ROOT / "docker-compose.yml")
    for key in required_keys:
        assert key in compose
    assert 'VISION_RUNTIME_PROVIDER: "${VISION_RUNTIME_PROVIDER:-local}"' in compose

    runbook = read_text(ROOT / "docs" / "ops" / "vision-media-adapter-runbook.md")
    for token in (
        "VISION_RUNTIME_PROVIDER=runpod",
        "vision_remote_execution_failed",
        "vision_remote_cancelled",
        "vision_remote_timeout",
        "vision_remote_unavailable",
        "vision_remote_invalid_response",
        "restricted",
        "workersMin=0",
        "workersMax=1",
        "비식별",
        "실제 영상",
    ):
        assert token in runbook
    assert "Jupyter proxy" in runbook
    assert "운영 API로 사용하지" in runbook

    checklist = read_text(ROOT / "docs" / "ops" / "project-readiness-master-checklist.md")
    assert "PR #303" in checklist
    assert "5f3728e" in checklist
    assert "feat-runpod-serverless-vision" in checklist
    assert "restricted key" in checklist
    assert "실영상" in checklist


def test_analysis_execution_provenance_is_wired_to_runtime_and_runbook():
    root_compose = read_text(ROOT / "docker-compose.yml")
    pilot_compose = read_text(ROOT / "deploy" / "aws-pilot" / "docker-compose.pilot.yml")
    pilot_env = read_text(ROOT / "deploy" / "aws-pilot" / "runtime.env.example")
    runbook = read_text(ROOT / "docs" / "ops" / "analysis-execution-provenance.md")

    for key in (
        "APP_RELEASE_VERSION",
        "LEGAL_DATASET_VERSION",
        "LEGAL_DATASET_VERIFIED_AT",
    ):
        assert key in root_compose
        assert key in pilot_compose
    assert "RELEASE_TAG=INJECTED_BY_DEPLOY_SCRIPT" in pilot_env
    assert "LEGAL_DATASET_VERSION" in pilot_env
    assert "LEGAL_DATASET_VERIFIED_AT" in pilot_env
    assert "show_analysis_job_provenance" in runbook
    assert "--job-id" in runbook
    assert "query 원문" in runbook


def test_repository_text_files_do_not_contain_obvious_secret_assignments():
    scanned_suffixes = {".md", ".py", ".html", ".txt", ".yml", ".yaml", ".json"}
    excluded_parts = {".git", ".venv", ".pytest_cache", ".worktrees", ".deps", ".test-deps", ".superpowers", "assets"}
    secret_pattern = re.compile(
        r"(?i)(?P<name>api[_-]?key|secret|token|password)\s*[:=]\s*"
        r"['\"](?P<value>[^'\"\n]{8,})['\"]"
    )
    safe_sentinels = {"[MASKED]"}

    matches = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in scanned_suffixes:
            continue
        if any(part in excluded_parts for part in path.parts):
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for match in secret_pattern.finditer(content):
            if match.group("value") in safe_sentinels:
                continue
            matches.append(f"{path.relative_to(ROOT)}:{match.group('name')}")

    assert matches == []
