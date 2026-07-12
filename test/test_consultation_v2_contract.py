from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_case_domain_schema_contains_additive_v2_entities_and_links():
    models = read_text(ROOT / "backend" / "chatbot" / "models.py")

    for token in [
        "class CaseStatus",
        "class Case(",
        "class ConfirmedFactVersion(",
        "class MediaArtifact(",
        "class CaseNotificationPreference(",
        "class NotificationDelivery(",
        'INITIAL_CONSULTATION = "initial_consultation"',
        'EXPERT_HANDOFF = "expert_handoff"',
        "retention_expires_at",
        "deleted_at",
        "source_fact_version",
        "version_no",
    ]:
        assert token in models


def test_public_v2_case_report_and_file_delete_routes_are_exposed():
    urls = read_text(ROOT / "backend" / "chatbot" / "urls.py")
    views = read_text(ROOT / "backend" / "chatbot" / "views.py")

    for token in [
        'path("cases/"',
        'path("cases/<str:case_id>/workspace/"',
        'path("cases/<str:case_id>/facts/confirm/"',
        'path("cases/<str:case_id>/analysis/jobs/"',
        'path("reports/<str:report_id>/"',
    ]:
        assert token in urls

    assert '@require_http_methods(["GET", "DELETE", "OPTIONS"])' in views


def test_frontend_contract_exposes_case_workspace_and_v2_api_calls():
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    api_client = read_text(ROOT / "app" / "web" / "apiClient.js")

    for token in [
        "CaseWorkspaceScreen",
        "consultation_state",
        "fact_cards",
        "fault_range_allowed",
        "즉시 행동",
        "현재 판단",
        "자료 충족도",
        "분석 상태",
    ]:
        assert token in shell

    for token in [
        "createCase",
        "listCases",
        "getCaseWorkspace",
        "confirmCaseFacts",
        "startCaseAnalysis",
        "deleteFile",
        "listReports",
        "getReport",
    ]:
        assert token in api_client


def test_vision_pipeline_uses_redacted_frames_responses_api_and_strict_v2_schema():
    vision = read_text(ROOT / "app" / "services" / "vision_pipeline_service.py")

    for token in [
        "vision_media_result.v2",
        "gpt-5.6-terra",
        "client.responses.create",
        '"store": False',
        '"strict": True',
        '"detail": "high"',
        '"detail": "original"',
        "selected_redacted_frames",
        "MAX_VIDEO_BYTES = 50 * 1024 * 1024",
        "audio_removed",
        "RT-DETRv2-S",
        "YOLO26n",
    ]:
        assert token in vision


def test_evidence_and_ops_mcp_boundaries_are_separate_and_source_aware():
    evidence = read_text(ROOT / "app" / "services" / "evidence_mcp_service.py")
    ops = read_text(ROOT / "app" / "services" / "aws_ops_mcp_service.py")

    for token in [
        "traffic_context_mcp",
        "police_context_mcp",
        "court_law_mcp",
        "source_url",
        "retrieved_at",
        "data_revision",
        "limitation",
        '"taas": "disabled"',
        '"supreme_court": "disabled"',
    ]:
        assert token in evidence

    for token in [
        "staging",
        "approval_token",
        "ecs_status",
        "cloudwatch_errors",
        "sqs_dlq_depth",
        "restart_worker",
        "replay_failed_work_item",
        "production changes are not allowed",
    ]:
        assert token in ops

    assert "aws_ops_mcp" not in evidence
    assert "consultation" not in ops


def test_design_doc_and_feature_flags_are_versioned():
    design = read_text(
        ROOT
        / "docs"
        / "architecture"
        / "ai-traffic-dispute-consultation-v2-implementation-design-2026-07-10.md"
    )
    env_example = read_text(ROOT / ".env.example")

    for token in [
        "CASE_WORKSPACE_V2_ENABLED",
        "VISION_PIPELINE_ENABLED",
        "EVIDENCE_MCP_ENABLED",
        "SQS_WORKER_ENABLED",
        "EMAIL_NOTIFICATION_ENABLED",
    ]:
        assert token in design
        assert token in env_example
