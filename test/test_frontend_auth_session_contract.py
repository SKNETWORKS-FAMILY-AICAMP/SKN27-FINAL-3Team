from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_frontend_app_shell_connects_auth_session_contract():
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    api_client = read_text(ROOT / "app" / "web" / "apiClient.js")
    auth_session = read_text(ROOT / "app" / "web" / "authSession.js")
    content = "\n".join([shell, api_client, auth_session])

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
        "session_id",
        "activeAuthToken",
        "Google로 계속하기",
        "requestGoogleAuthorizationCode",
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
    assert "downloadReport" in api_client
    assert "FormData" in api_client
    assert 'from "./apiClient.js"' in shell
    assert 'from "./authSession.js"' in shell


def test_frontend_app_shell_covers_current_case_and_report_routes():
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    api_client = read_text(ROOT / "app" / "web" / "apiClient.js")
    content = "\n".join([shell, api_client])

    required_tokens = [
        "FrontendAppShell",
        'id: "entry"',
        'id: "chatbot"',
        'id: "mypage"',
        'id: "history"',
        'id: "reporting"',
        "getMyPageSummary",
        "listHistoryEvents",
        "readStoredAuthToken",
        "readStoredAuthSession",
        "loginAndBindCurrentSession",
        "ensureGuestSession",
        "conversation_history",
        "registerFileMetadata",
        "processFileScan",
        "scan_status",
        "processAgentWorkItems",
        "getAnalysisJobDetail",
        "downloadReport",
        "CaseWorkspaceScreen",
        "AdaptiveIntakePanel",
        "consultation_state",
        "fact_cards",
        "fault_range_allowed",
        "ReportingPreviewPanel",
        "FaultRatioInsightPanel",
        "ReportActionPanel",
        "createCase",
        "getCaseWorkspace",
        "confirmCaseFacts",
        "startCaseAnalysis",
        "deleteFile",
        "listReports",
        "getReport",
    ]

    missing = [token for token in required_tokens if token not in content]
    assert missing == []
    assert "fine-result" not in shell
    assert "FineResult" not in shell
    assert 'const effectiveAuthToken = authSessionId ? activeAuthToken || authToken : "";' in shell
    assert 'accept="image/*,application/pdf,video/*"' in shell
    assert "URL.createObjectURL" in shell
    assert "VISION" not in shell or "limitations" in shell


def test_vite_proxy_does_not_capture_frontend_api_client_module():
    config = read_text(ROOT / "app" / "web" / "vite.config.js")

    assert 'const repoRoot = resolve(appWebDir, "../..");' in config
    assert 'loadEnv(mode, repoRoot, "VITE_")' in config
    assert "envDir: repoRoot" in config
    assert '"http://127.0.0.1:8010"' in config
    assert '"http://127.0.0.1:8000"' not in config
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
