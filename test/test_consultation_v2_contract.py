from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_case_domain_schema_contains_canonical_v2_entities_and_links() -> None:
    models = read_text(ROOT / "backend" / "chatbot" / "models.py")

    for token in (
        "class CaseStatus",
        "class Case(",
        "class ConfirmedFactVersion(",
        'INITIAL_CONSULTATION = "initial_consultation"',
        'EXPERT_HANDOFF = "expert_handoff"',
        "retention_expires_at",
        "deleted_at",
        "source_fact_version",
        "version_no",
        "report_case_version_uniq",
    ):
        assert token in models


def test_public_v2_case_routes_are_exposed() -> None:
    urls = read_text(ROOT / "backend" / "chatbot" / "urls.py")

    for token in (
        '"cases/"',
        '"cases/<str:case_id>/workspace/"',
        '"cases/<str:case_id>/facts/confirm/"',
        '"cases/<str:case_id>/analysis/jobs/"',
        '"reports/<str:report_id>/"',
    ):
        assert token in urls


def test_frontend_uses_canonical_capability_and_async_result_contracts() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    api_client = read_text(ROOT / "app" / "web" / "apiClient.js")

    for token in ("api.getCapabilities()", "capabilityCatalog", "capabilityError"):
        assert token in shell
    for token in ("getCapabilities", "getAnalysisResult", "listReports", "downloadReport"):
        assert token in api_client

    assert "DEMO_PERSONAS" not in shell
    assert "agents/work-items/process/" not in api_client
    assert "/scan/" not in api_client


def test_deferred_vision_and_aws_ops_are_not_runtime_modules() -> None:
    assert not (ROOT / "app" / "services" / "vision_pipeline_service.py").exists()
    assert not (ROOT / "app" / "services" / "aws_ops_mcp_service.py").exists()


def test_evidence_mcp_boundary_is_source_aware() -> None:
    evidence = read_text(ROOT / "app" / "services" / "evidence_mcp_service.py")

    for token in (
        "traffic_context_mcp",
        "police_context_mcp",
        "court_law_mcp",
        "source_url",
        "retrieved_at",
        "data_revision",
        "limitation",
        '"taas": "disabled"',
        '"supreme_court": "disabled"',
    ):
        assert token in evidence

    assert "aws_ops_mcp" not in evidence


def test_design_doc_and_feature_flags_are_versioned() -> None:
    design = read_text(
        ROOT
        / "docs"
        / "architecture"
        / "ai-traffic-dispute-consultation-v2-implementation-design-2026-07-10.md"
    )
    env_example = read_text(ROOT / ".env.example")

    for token in (
        "CASE_WORKSPACE_V2_ENABLED",
        "EVIDENCE_MCP_ENABLED",
        "RAW_MEDIA_RETENTION_DAYS",
        "USER_RETENTION_DAYS",
    ):
        assert token in design
        assert token in env_example

    assert "VISION_PIPELINE_ENABLED" not in env_example
    assert "AWS_OPS_MCP_ENABLED" not in env_example


def test_retention_policy_documents_physical_db_and_s3_purge_worker() -> None:
    retention_doc = read_text(ROOT / "docs" / "ops" / "retention-enforcement-follow-up.md")

    for token in (
        "anonymous 1일",
        "guest 7일",
        "인증 사용자 문서 365일",
        "원본 이미지·영상 30일",
        "retention_expires_at",
        "DB·S3 실제 삭제 worker",
        "purge_expired_uploads",
        "retryable",
        "tombstone",
        "사용자 명시 삭제",
    ):
        assert token in retention_doc

    assert "다음 PR에서 구현" not in retention_doc
