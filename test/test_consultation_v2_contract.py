import re
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
        '"reports/<str:report_id>/document-confirmation/"',
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


def test_chat_report_ready_notice_uses_a_locally_declared_gated_payload() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    chat_start = shell.index("function ChatScreenV2(")
    next_component = re.search(r"\nfunction [A-Za-z0-9_]+\(", shell[chat_start + 1 :])
    assert next_component is not None
    chat_end = chat_start + 1 + next_component.start()
    chat_screen = shell[chat_start:chat_end]

    assert (
        "const visibleReportingPayload = "
        "isReportingPayloadReady(reportingPayload, supervisorState) ? reportingPayload : null;"
    ) in chat_screen
    assert re.search(
        r"\{(?:canGenerateReport && )?visibleReportingPayload && \(\s*<ReportReadyNotice",
        chat_screen,
    )


def test_worker_report_actions_reuse_the_persisted_report_instead_of_reposting_it() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    action_start = shell.index('async function runCurrentReportAction')
    action_end = shell.index('async function triggerReportDownload', action_start)
    report_action = shell[action_start:action_end]

    assert "const persistedReportId = persistedAnalysisReportId(analysisResponse, currentReport);" in report_action
    assert "if (persistedReportId) {" in report_action
    assert "api.getReportDetail" in report_action
    assert "reportId: persistedReportId" in report_action
    persisted_branch = report_action[report_action.index("if (persistedReportId) {"):]
    save_state_call = persisted_branch.index("api.updateConversationSaveState")
    save_success = persisted_branch.index("setReportActionStatus", save_state_call)
    assert save_state_call < save_success
    assert 'conversation_save_state: "saved"' in persisted_branch
    assert 'conversation_save_source: "worker_report_save_action"' in persisted_branch
    assert "api.runReportAction" not in report_action
    assert "function persistedAnalysisReportId(analysisResponse, currentReport)" in shell
    helper_start = shell.index("function persistedAnalysisReportId(analysisResponse, currentReport)")
    helper_end = shell.index("function EntryScreen", helper_start)
    helper = shell[helper_start:helper_end]
    helper_return = next(line for line in helper.splitlines() if line.strip().startswith("return "))
    assert helper_return.index("currentReport?.report_id") < helper_return.index("analysisReportId")
    assert (
        "const activeReportingPayload = currentReport?.content?.reporting_payload || "
        "visibleReportingPayload;"
    ) in report_action
    assert (
        "let activeSessionId = currentReport?.session_id || "
        "analysisResponse?.session_id || sessionId;"
    ) in report_action

    submit_start = shell.index("async function submitServiceMessage")
    submit_end = shell.index("async function saveConversationWithGoogle", submit_start)
    assert "setCurrentReport(null);" in shell[submit_start:submit_end]


def test_frontend_report_download_actions_use_docx_api_without_pdf_printing() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    api_client = read_text(ROOT / "app" / "web" / "apiClient.js")
    action_start = shell.index("async function runCurrentReportAction")
    action_end = shell.index("async function triggerReportDownload", action_start)
    report_action = shell[action_start:action_end]

    assert "setPendingReportScreenDownload" not in shell
    assert "openReportScreenPrintWindow" not in shell
    assert "PDF" not in report_action
    assert 'const documentType = "objection_form";' in report_action
    assert "const appealGate = activeReportingPayload?.appeal_gate || null;" in report_action
    assert "if (appealGate?.blocked === true)" in report_action
    assert "document_confirmation" in report_action
    assert "api.confirmReportDocument" in shell
    assert 'onRunReportAction("download_report")' not in shell
    assert "분석 리포트 DOCX" not in shell
    ready_notice_start = shell.index("function ReportReadyNotice")
    ready_notice_end = shell.index("function DocumentConfirmationPanel", ready_notice_start)
    ready_notice = shell[ready_notice_start:ready_notice_end]
    assert "const hasOfficialDocument =" in ready_notice
    assert "{hasOfficialDocument && (" in ready_notice
    assert "const appealDownloadBlocked = reportingPayload?.appeal_gate?.blocked === true;" in shell
    assert "const appealDownloadBlocked = activeReportingPayload?.appeal_gate?.blocked === true;" in shell
    assert "appealDownloadBlocked || !confirmation.confirmed" in shell
    assert "DOCX" in shell
    assert "화면 PDF 저장" not in shell
    assert "이의신청서 PDF" not in shell
    assert "confirmReportDocument" in api_client
    assert 'const filename = file.filename || `${reportId}.docx`;' in shell


def test_download_report_never_returns_pdf_for_the_legacy_non_api_path() -> None:
    views = read_text(ROOT / "backend" / "chatbot" / "views.py")
    function_start = views.index("def download_report(")
    function_end = views.index("def _report_auth_error_response", function_start)
    download_view = views[function_start:function_end]

    assert "application/pdf" not in download_view
    assert "document_download_not_available" in download_view
    assert "render_report_docx(" not in download_view


def test_frontend_normalizes_assistant_message_payloads_before_rendering() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")

    for token in (
        'function assistantMessageText(value, fallback = "")',
        'typeof value === "string"',
        "value.answer || value.summary",
        "analysisResponse?.assistant_message?.core_answer ||",
        "assistantMessageText(analysisResponse?.assistant_message);",
        "workerResult?.assistant_message?.core_answer ||",
        'assistantMessageText(workerResult?.assistant_message, "상담 내용을 접수했습니다."),',
        "const assistantMessage = assistantMessageText(",
        "assistant_message: assistantMessageText(",
    ):
        assert token in shell


def test_frontend_polls_guest_worker_jobs_until_a_terminal_result() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    poll_start = shell.index("async function pollQueuedWorkerResult")
    poll_end = shell.index("async function submitServiceMessage", poll_start)
    polling = shell[poll_start:poll_end]

    assert "const WORKER_POLL_MAX_ATTEMPTS = 60;" in shell
    assert "setChatMessages(conversationHistory);" in shell
    assert "if (!requestIdentity?.authToken)" not in polling
    assert (
        "for (let attempt = 0; attempt < WORKER_POLL_MAX_ATTEMPTS; attempt += 1)"
        in polling
    )
    assert "await api.getAnalysisResult" in polling
    assert "...jobDetail," in polling
    assert "await waitForWorkerPoll();" in polling


def test_repeated_analysis_cards_use_unique_react_keys() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")

    assert "function analysisCardKey(card, index)" in shell
    card_map_pattern = re.compile(
        r"\{(?:analysisCards(?:\.slice\([^)]*\))?|supportCards)"
        r"\.map\(\(card, index\) => \("
    )
    keyed_card_map_pattern = re.compile(
        r"\{(?:analysisCards(?:\.slice\([^)]*\))?|supportCards)"
        r"\.map\(\(card, index\) => \(\s*<[^>]+"
        r"key=\{analysisCardKey\(card, index\)\}"
    )

    card_maps = card_map_pattern.findall(shell)
    keyed_card_maps = keyed_card_map_pattern.findall(shell)
    assert card_maps
    assert len(keyed_card_maps) == len(card_maps)


def test_frontend_renders_canonical_law_ground_results_and_retrieval_status() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    styles = read_text(ROOT / "app" / "web" / "styles.css")

    for token in (
        "function LawGroundInsightPanel",
        'node?.node_code !== "law_ground_search"',
        "structuredResult.matched_laws",
        "item.source_reference",
        "retrieval.backend",
        "retrieval.status",
        "retrieval.attempted_backends",
    ):
        assert token in shell
    assert shell.count("<LawGroundInsightPanel") == 2
    for class_name in (
        "agent-insight-panel",
        "agent-insight-head",
        "agent-insight-grid",
        "agent-insight-section",
    ):
        assert class_name in shell
        assert f".{class_name}" in styles
    assert "fault-ratio-insight-" not in shell
    assert "fault-ratio-insight-" not in styles


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
