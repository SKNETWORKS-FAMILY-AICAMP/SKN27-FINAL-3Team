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
    assert 'joinApiPath(apiBase, "reports/")' in api_client
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


def test_react_mock_flow_doc_mentions_auth_session_headers():
    content = read_text(ROOT / "docs" / "issues" / "57-react-chatbot-mock-flow.md")

    assert "POST /api/auth/guest-session/" in content
    assert "POST /api/auth/login/" in content
    assert "GET /api/auth/me/" in content
    assert "X-Guest-Id" in content
    assert "X-Auth-Session-Id" in content
    assert "auth_context" in content
    assert "app Bearer token" in content
