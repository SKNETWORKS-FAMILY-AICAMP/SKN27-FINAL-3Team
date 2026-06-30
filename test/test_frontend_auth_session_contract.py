from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_chatbot_mock_flow_connects_auth_session_contract():
    content = read_text(ROOT / "app" / "web" / "ChatbotMockFlow.jsx")

    required_tokens = [
        "auth/guest-session/",
        "auth/me/",
        '"X-Guest-Id"',
        '"X-Auth-Session-Id"',
        "auth_context",
        "guest_id",
        "auth_session_id",
        "chat_session_id",
        "toCanonicalApiBase",
    ]

    missing = [token for token in required_tokens if token not in content]
    assert missing == []
    assert 'joinApiPath(apiBase, "chat/messages/")' in content
    assert 'joinApiPath(apiBase, "reports/")' in content


def test_react_mock_flow_doc_mentions_auth_session_headers():
    content = read_text(ROOT / "docs" / "issues" / "57-react-chatbot-mock-flow.md")

    assert "POST /api/auth/guest-session/" in content
    assert "GET /api/auth/me/" in content
    assert "X-Guest-Id" in content
    assert "X-Auth-Session-Id" in content
    assert "auth_context" in content
