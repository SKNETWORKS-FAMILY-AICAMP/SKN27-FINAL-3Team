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
        "clearStoredAuthSession",
    ]

    missing = [token for token in required_tokens if token not in content]
    assert missing == []
    assert 'joinApiPath(apiBase, "chat/messages/")' in api_client
    assert 'joinApiPath(apiBase, "files/")' in api_client
    assert 'joinApiPath(apiBase, "reports/")' in api_client
    assert "uploadFile" in api_client
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
    ]:
        assert token in shell or token in api_client

    assert "fine-result" not in shell
    assert "FineResult" not in shell
    assert 'const effectiveAuthToken = authSessionId ? activeAuthToken || authToken : "";' in shell
    assert "authToken: effectiveAuthToken" in shell
    assert "conversation_history" in shell
    assert "SupervisorFlowPanel" in shell
    assert "ReportingPreviewPanel" in shell
    assert "DEMO_PERSONAS" in shell
    assert "persona-control-panel" in shell
    assert "registerFileMetadata" in shell
    assert "runReportAction" in shell
    assert "ReportActionPanel" in shell
    assert "registeredAttachments" in shell
    assert "selectedUploadFile" in shell
    assert 'type="file"' in shell
    assert "파일 업로드" in shell
    assert "supervisorState" in shell
    assert "NodeResultPill" in shell
    assert "adapter_execution_mode" in shell
    assert "normalizeExecutionMode" in shell


def test_vite_proxy_does_not_capture_frontend_api_client_module():
    config = read_text(ROOT / "app" / "web" / "vite.config.js")

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
