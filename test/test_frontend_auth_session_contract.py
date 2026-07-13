from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_frontend_uses_only_the_canonical_auth_and_job_contracts() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    api_client = read_text(ROOT / "app" / "web" / "apiClient.js")
    auth_session = read_text(ROOT / "app" / "web" / "authSession.js")
    content = "\n".join([shell, api_client, auth_session])

    for token in (
        "auth/guest-session/",
        "auth/google/code/",
        "auth/me/",
        "auth/refresh/",
        "auth/logout/",
        "capabilities/",
        "analysis/results/",
        '"X-Guest-Id"',
        '"X-Auth-Session-Id"',
        "requestGoogleAuthorizationCode",
        "accounts?.oauth2",
    ):
        assert token in content

    for removed in (
        "auth/login/",
        "agents/work-items/process/",
        "/scan/",
        "mock_google",
        "VITE_GOOGLE_LOCAL_AUTH_MODE",
        "VITE_DEV_AUTH_TOKEN",
        "AUTH_TOKEN_STORAGE_KEY",
    ):
        assert removed not in content


def test_frontend_catalog_drives_supported_attachments_without_demo_personas() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")

    assert "api.getCapabilities()" in shell
    assert "capabilityCatalog?.capabilities" in shell
    assert "capabilityError" in shell
    assert 'const EXECUTION_MODE = "async_worker"' in shell
    assert 'accept="image/*,application/pdf"' in shell
    assert "scan_pending" in shell
    assert "pollQueuedWorkerResult" in shell
    assert "api.getAnalysisResult" in shell
    assert "DEMO_PERSONAS" not in shell
    assert "persona-control-panel" not in shell
    assert "accident_scene" not in shell
    assert "blackbox_video" not in shell
    assert 'accept="image/*,application/pdf,video/*"' not in shell


def test_vite_proxy_does_not_capture_frontend_api_client_module() -> None:
    config = read_text(ROOT / "app" / "web" / "vite.config.js")

    assert 'const repoRoot = resolve(appWebDir, "../..");' in config
    assert 'loadEnv(mode, repoRoot, "VITE_")' in config
    assert "envDir: repoRoot" in config
    assert '"http://127.0.0.1:8010"' in config
    assert '"http://127.0.0.1:8000"' not in config
    assert 'const apiProxyPrefix = "^/api(/|$)";' in config
    assert "[apiProxyPrefix]: apiProxyTarget" in config
    assert '"/api": apiProxyTarget' not in config


def test_production_auth_document_requires_real_google_code_flow() -> None:
    content = read_text(ROOT / "docs" / "ops" / "production-env.md")

    assert "GOOGLE_CLIENT_ID" in content
    assert "GOOGLE_CLIENT_SECRET" in content
    assert "GOOGLE_POPUP_REDIRECT_URI" in content
    assert "GOOGLE_AUTH_ALLOW_MOCK" not in content
    assert "APP_AUTH_ALLOW_MOCK_BEARER" not in content
