import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def run_auth_session_node_contract(source: str) -> None:
    module_url = (ROOT / "app" / "web" / "authSession.js").as_uri()
    completed = subprocess.run(
        [
            "node",
            "--input-type=module",
            "--eval",
            f'const authSession = await import("{module_url}");\n{source}',
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


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


def test_guest_credential_is_persisted_and_sent_only_in_a_header() -> None:
    api_client = read_text(ROOT / "app" / "web" / "apiClient.js")
    auth_session = read_text(ROOT / "app" / "web" / "authSession.js")
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")

    assert '"X-Guest-Credential": guestCredential' in api_client
    assert '"guest_credential"' not in api_client
    assert "guestCredential" in auth_session
    assert "guestCredential" in shell
    assert "guest_credential" in auth_session


def test_frontend_catalog_drives_supported_attachments_without_demo_personas() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")

    assert "api.getCapabilities()" in shell
    assert "capabilityCatalog?.capabilities" in shell
    assert "capabilityError" in shell
    assert 'const EXECUTION_MODE = "async_worker"' in shell
    assert 'const ATTACHMENT_ACCEPT = "image/jpeg,image/png,image/webp,application/pdf,video/mp4,video/quicktime";' in shell
    assert "scan_pending" in shell
    assert "pollQueuedWorkerResult" in shell
    assert "api.getAnalysisResult" in shell
    assert "DEMO_PERSONAS" not in shell
    assert "persona-control-panel" not in shell
    assert "blackbox_video" in shell
    assert 'accept="image/*,application/pdf,video/*"' not in shell


def test_frontend_attachment_intake_supports_drag_drop_and_video() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")

    assert 'accept={ATTACHMENT_ACCEPT}' in shell
    assert "onDragOver={onAttachmentDragOver}" in shell
    assert "onDrop={onAttachmentDrop}" in shell
    assert "handleAttachmentFile" in shell
    assert 'setAttachmentPurpose("blackbox_video")' in shell
    assert "handleAttachmentDrop" in shell
    assert "handleAttachmentDragOver" in shell


def test_frontend_renders_editable_ocr_confirmation_before_follow_up() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")

    assert "ocr_confirmation" in shell
    assert "requires_confirmation" in shell
    assert "OCR 추출값 확인 후 후속 절차 진행" in shell
    assert "fine_type" in shell
    assert "notice_stage" in shell


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


def test_memory_only_app_jwt_does_not_restore_stale_authenticated_ui() -> None:
    auth_session = read_text(ROOT / "app" / "web" / "authSession.js")
    persistence = auth_session.split("export function persistAuthSession", 1)[1].split(
        "export function clearStoredAuthSession", 1
    )[0]

    assert "auth_session_id: authSessionId || null" not in persistence
    assert "user_id: userId || null" not in persistence
    assert "writeStoredJson(GOOGLE_PROFILE_STORAGE_KEY, googleProfile || null)" not in persistence
    assert "removeStoredValue(GOOGLE_PROFILE_STORAGE_KEY)" in auth_session


def test_app_jwt_refresh_scheduler_uses_exp_for_timing_and_cleans_up() -> None:
    run_auth_session_node_contract(
        r"""
        const assert = (await import("node:assert/strict")).default;
        const payload = Buffer.from(JSON.stringify({ exp: 1000 })).toString("base64url");
        const token = `header.${payload}.signature`;

        assert.equal(
          authSession.millisecondsUntilAppJwtRefresh(token, { nowMs: 100000 }),
          600000,
        );
        assert.equal(
          authSession.millisecondsUntilAppJwtRefresh(token, { nowMs: 800000 }),
          0,
        );
        assert.equal(authSession.millisecondsUntilAppJwtRefresh("not-a-jwt"), null);

        let scheduled = null;
        let clearedTimerId = null;
        let refreshCalls = 0;
        let finishRefresh;
        const cleanup = authSession.scheduleAppJwtRefresh({
          token,
          nowMs: 100000,
          setTimer(callback, delayMs) {
            scheduled = { callback, delayMs };
            return 17;
          },
          clearTimer(timerId) {
            clearedTimerId = timerId;
          },
          refresh() {
            refreshCalls += 1;
            return new Promise((resolve) => {
              finishRefresh = resolve;
            });
          },
        });

        assert.equal(scheduled.delayMs, 600000);
        const firstRun = scheduled.callback();
        const duplicateRun = scheduled.callback();
        await Promise.resolve();
        assert.equal(refreshCalls, 1);
        finishRefresh();
        await Promise.all([firstRun, duplicateRun]);
        cleanup();
        assert.equal(clearedTimerId, 17);

        let cancelledRefreshCalls = 0;
        let cancelledCallback = null;
        const cancelBeforeRun = authSession.scheduleAppJwtRefresh({
          token,
          nowMs: 100000,
          setTimer(callback) {
            cancelledCallback = callback;
            return 18;
          },
          clearTimer() {},
          refresh() {
            cancelledRefreshCalls += 1;
          },
        });
        cancelBeforeRun();
        await cancelledCallback();
        assert.equal(cancelledRefreshCalls, 0);
        """
    )


def test_frontend_refreshes_app_jwt_and_clears_stale_auth_ui_on_failure() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")

    for required in (
        "scheduleAppJwtRefresh",
        "api.refreshAuthToken(",
        "setActiveAuthToken(nextToken)",
        "setAuthSessionId(nextAuthSessionId)",
        "clearStoredAuthSession()",
        'setActiveAuthToken("")',
        'setAuthSessionId("")',
        "다시 로그인",
    ):
        assert required in shell
