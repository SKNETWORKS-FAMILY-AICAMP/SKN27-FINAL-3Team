from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_chatbot_mock_flow_connects_auth_session_contract():
    chatbot = read_text(ROOT / "app" / "web" / "ChatbotMockFlow.jsx")
    api_client = read_text(ROOT / "app" / "web" / "apiClient.js")
    auth_session = read_text(ROOT / "app" / "web" / "authSession.js")
    content = "\n".join([chatbot, api_client, auth_session])

    required_tokens = [
        "auth/guest-session/",
        "auth/login/",
        "auth/me/",
        "auth/refresh/",
        "auth/logout/",
        '"X-Guest-Id"',
        '"X-Auth-Session-Id"',
        "auth_context",
        "guest_id",
        "user_id",
        "auth_session_id",
        "chat_session_id",
        "activeAuthToken",
        "Google로 계속하기",
        "google.accounts.id",
        "toCanonicalApiBase",
        "createFrontendApi",
        "buildRequestHeaders",
        "persistAuthSession",
        "readStoredAuthSession",
        "clearStoredAuthSession",
        "AUTH_SESSION_STORAGE_KEY",
    ]

    missing = [token for token in required_tokens if token not in content]
    assert missing == []
    assert 'joinApiPath(apiBase, "chat/messages/")' in api_client
    assert 'joinApiPath(apiBase, "agents/work-items/process/")' in api_client
    assert "analysis/jobs/${encodeURIComponent(jobId || \"\")}/" in api_client
    assert 'joinApiPath(apiBase, "files/")' in api_client
    assert 'files/${encodeURIComponent(attachmentId || "")}/scan/' in api_client
    assert 'joinApiPath(apiBase, "reports/")' in api_client
    assert "uploadFile" in api_client
    assert "processFileScan" in api_client
    assert "processAgentWorkItems" in api_client
    assert "getAnalysisJobDetail" in api_client
    assert "FormData" in api_client
    assert "postFormData" in api_client
    assert 'from "./apiClient.js"' in chatbot
    assert 'from "./authSession.js"' in chatbot


def test_frontend_app_shell_covers_common_routes_without_fine_result_screen():
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    api_client = read_text(ROOT / "app" / "web" / "apiClient.js")

    for token in [
        "FrontendAppShell",
        "ChatbotMockFlow",
        "entry",
        "chatbot",
        "mypage",
        "history",
        "getMyPageSummary",
        "listHistoryEvents",
        "readStoredAuthToken",
        "readStoredAuthSession",
    ]:
        assert token in shell or token in api_client

    assert "fine-result" not in shell
    assert "FineResult" not in shell
    assert 'const effectiveAuthToken = authSessionId ? activeAuthToken || authToken : "";' in shell
    assert "storedAuthSession.session_id" in shell
    assert "storedAuthSession.guest_id" in shell
    assert "storedAuthSession.auth_session_id" in shell
    assert "loginAndBindCurrentSession" in shell
    assert "ensureGuestSession" in shell
    assert "pendingAuthAction" in shell
    assert 'source: "attachment_upload"' in shell
    assert "report_${action}" in shell
    assert "authSessionId={authSessionId}" in shell
    assert "authToken: effectiveAuthToken" in shell
    assert "conversation_history" in shell
    assert "SupervisorFlowPanel" in shell
    assert "ReportingPreviewPanel" in shell
    assert "FaultRatioInsightPanel" in shell
    assert "fault-ratio-insight-panel" in shell
    assert "similar_cases" in shell
    assert "ratio_range_label" in shell
    assert "recommended_evidence" in shell
    assert "retrieval.adapter_source" in shell
    assert "DEMO_PERSONAS" in shell
    assert "persona-control-panel" in shell
    assert "registerFileMetadata" in shell
    assert "processFileScan" in shell
    assert "scan_status" in shell
    assert "runReportAction" in shell
    assert "ReportActionPanel" in shell
    assert "registeredAttachments" in shell
    assert "selectedUploadFile" in shell
    assert 'type="file"' in shell
    assert 'accept="image/*,application/pdf,video/*"' in shell
    assert "Google 로그인 후 업로드" in shell
    assert "파일 선택 필요" in shell
    assert "disabled={isRegisteringAttachment || !selectedUploadFile}" in shell
    assert "자료 분석은 로그인 후 현재 상담 세션에 이어서 진행됩니다." in shell
    assert "disabled={!isAuthenticated}" not in shell
    assert "파일 업로드" in shell
    assert "supervisorState" in shell
    assert "NodeResultPill" in shell
    assert "workItem" in shell
    assert "async_worker" in shell
    assert "adapter_execution_mode" in shell
    assert "normalizeExecutionMode" in shell
    assert "executionMode" in shell
    assert "setExecutionMode" in shell
    assert "execution_mode: executionMode" in shell
    assert "execution-mode-control" in shell
    assert 'const [executionMode, setExecutionMode] = useState("sync");' in shell
    assert '["sync", "async_worker", "mock"]' in shell
    assert "processQueuedWorkerResult" in shell
    assert "pollQueuedWorkerResult" in shell
    assert "const workerResult = await pollQueuedWorkerResult(result, submitIdentity);" in shell
    assert "canSaveGuestConversation" in shell
    assert "workerResult?.persistence?.job_id || workerResult?.session_id || workerResult?.message_id" in shell
    assert "guestDetailedReportUsed" in shell
    assert 'source: "guest_followup_question"' in shell
    assert "비로그인 상담은 1회 리포팅까지 제공됩니다." in shell
    assert "saveConversationWithGoogle" in shell
    assert "현재 상태로 저장하거나 답변을 이어갈 수 있습니다." in shell
    assert "getAnalysisJobDetail" in shell
    assert "worker_progress_polling.v1" in shell
    assert "processAgentWorkItems" in shell
    assert "workerActionStatus" in shell
    assert "worker progress" in shell
    assert "reportQuality" in shell
    assert "report-quality-panel" in shell
    assert "openSavedCase" in shell
    assert "onOpenCase={openSavedCase}" in shell
    assert "restoreConversationMessages" in shell
    assert "restoreAnalysisResponse" in shell
    assert "restoreCurrentReport" in shell
    assert "저장된 상담을 현재 대화로 다시 열었습니다." in shell
    assert "latest_report_id" in shell
    assert "내 사건에서 저장된 리포트를 열었습니다." in shell
    assert 'const [selectedPersonaId, setSelectedPersonaId] = useState("");' in shell
    assert "<details className=\"persona-control-panel\"" in shell
    assert "개발용 Agent 점검" in shell
    assert "Traffic Dispute AI" in shell
    assert "비회원 1회 리포팅 가능" in shell
    assert "reportingPayload || analysisCards.length || supervisorExecution || currentReport" in shell
    assert "data-partial-report" in shell
    assert "partial_report" in shell
    assert "ready_report" in shell
    assert "analysis_job_status" in shell
    assert "agent_status_counts" in shell
    assert "reportLimitations" in shell
    assert "Partial analysis report" in shell
    assert "Ready analysis report" in shell
    assert "Review required before final submission." in shell
    assert "report-quality-warning" in shell
    assert "report-quality-limitations" in shell


def test_vite_proxy_does_not_capture_frontend_api_client_module():
    config = read_text(ROOT / "app" / "web" / "vite.config.js")

    assert 'const repoRoot = resolve(appWebDir, "../..");' in config
    assert 'loadEnv(mode, repoRoot, "VITE_")' in config
    assert "envDir: repoRoot" in config
    assert 'const apiProxyPrefix = "^/api(/|$)";' in config
    assert "[apiProxyPrefix]: apiProxyTarget" in config
    assert '"/api": apiProxyTarget' not in config


def test_react_mock_flow_doc_mentions_auth_session_headers():
    content = read_text(ROOT / "docs" / "issues" / "57-react-chatbot-mock-flow.md")

    assert "POST /api/auth/guest-session/" in content
    assert "POST /api/auth/login/" in content
    assert "GET /api/auth/me/" in content
    assert "X-Guest-Id" in content
    assert "X-Auth-Session-Id" in content
    assert "auth_context" in content
    assert "app Bearer token" in content
