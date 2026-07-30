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


def test_frontend_attachment_failure_shows_the_safe_server_retry_message() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    api_client = read_text(ROOT / "app" / "web" / "apiClient.js")
    registration_start = shell.index("async function registerAttachmentMetadata")
    registration_end = shell.index("function handleAttachmentFile", registration_start)
    registration = shell[registration_start:registration_end]

    assert "requestError.publicMessage = publicMessage" in api_client
    assert "const publicMessage = _error?.publicMessage" in registration
    assert "setStatusMessage(publicMessage || \"첨부 등록에 실패했습니다. 다시 시도해 주세요.\")" in registration


def test_frontend_renders_editable_ocr_confirmation_before_follow_up() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")

    assert "ocr_confirmation" in shell
    assert "requires_confirmation" in shell
    assert "OCR 추출값 확인 후 후속 절차 진행" in shell
    assert "fine_type" in shell
    assert "notice_stage" in shell


def test_start_new_conversation_clears_the_previous_session_id() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    start = shell.index("function startNewConversation() {")
    end = shell.index("async function loadMyPageSummary", start)
    block = shell[start:end]

    assert 'setSessionId("");' in block


def test_prepare_missing_evidence_upload_keeps_the_current_session_binding() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    start = shell.index("function prepareMissingEvidenceUpload() {")
    end = shell.index("function prepareDraftRegeneration()", start)
    block = shell[start:end]

    assert 'setSessionId("");' not in block


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


def test_app_auth_session_persists_authenticated_identity_for_reload_and_report_flows() -> None:
    auth_session = read_text(ROOT / "app" / "web" / "authSession.js")
    persistence = auth_session.split("export function persistAuthSession", 1)[1].split(
        "export function clearStoredAuthSession", 1
    )[0]

    for required in (
        "auth_session_id: authSessionId || null",
        "user_id: userId || null",
        "session_id: sessionId || null",
        "access_token: accessToken || null",
        "writeStoredJson(GOOGLE_PROFILE_STORAGE_KEY, googleProfile || null)",
    ):
        assert required in persistence


def test_auth_session_storage_round_trip_restores_authenticated_state() -> None:
    run_auth_session_node_contract(
        r"""
        const assert = (await import("node:assert/strict")).default;
        const storage = new Map();
        global.window = {
          localStorage: {
            getItem(key) {
              return storage.has(key) ? storage.get(key) : null;
            },
            setItem(key, value) {
              storage.set(key, String(value));
            },
            removeItem(key) {
              storage.delete(key);
            },
          },
        };

        const profile = { email: "driver@example.com", name: "Driver" };
        const storedAuthValue = "header." + "payload.signature";
        authSession.persistAuthSession({
          guestId: "gst_roundtrip",
          guestCredential: "guest-cred",
          authSessionId: "auth_roundtrip",
          userId: "usr_roundtrip",
          sessionId: "ses_roundtrip",
          accessToken: storedAuthValue,
          googleProfile: profile,
        });

        assert.equal(authSession.readStoredAuthToken(), storedAuthValue);
        assert.deepEqual(authSession.readStoredGoogleProfile(), profile);
        assert.deepEqual(authSession.readStoredAuthSession(), {
          guest_id: "gst_roundtrip",
          guest_credential: "guest-cred",
          auth_session_id: "auth_roundtrip",
          user_id: "usr_roundtrip",
          session_id: "ses_roundtrip",
          access_token: storedAuthValue,
        });

        authSession.clearStoredAuthSession();
        assert.equal(authSession.readStoredAuthToken(), "");
        assert.equal(authSession.readStoredGoogleProfile(), null);
        assert.deepEqual(authSession.readStoredAuthSession(), {});
        """
    )


def test_api_client_preserves_auth_error_metadata_for_frontend_recovery() -> None:
    api_client = read_text(ROOT / "app" / "web" / "apiClient.js")

    for required in (
        "requestError.status = response.status;",
        "requestError.code = error?.code || null;",
        "requestError.reason = reason || null;",
        "requestError.requiredAction = error?.required_action || null;",
        "requestError.payload = payload;",
        "requestError.publicMessage = publicMessage;",
    ):
        assert required in api_client


def test_guest_bootstrap_rebinds_server_session_before_follow_up_workflows() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    start = shell.index("async function bootstrapGuestSession")
    end = shell.index("async function ensureGuestSession", start)
    block = shell[start:end]

    assert block.count("api.createGuestSession(") >= 2
    assert "resolveGuestBootstrapSessionId({" in block
    assert "boundSessionId: initialGuest?.session_binding?.session_id," in block
    assert "guestCredential," in block
    assert "const reboundGuest = await api.createGuestSession(" in block
    assert "guest_id: initialGuestId," in block
    assert "session_id: ensuredSessionId," in block
    assert "{ guestId: initialGuestId, guestCredential: initialGuestCredential }" in block


def test_chat_submit_recovery_uses_structured_auth_error_metadata() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    submit_start = shell.index("async function submitServiceMessage({")
    submit_end = shell.index("async function streamAssistantMessage", submit_start)
    block = shell[submit_start:submit_end]

    for required in (
        '_error?.requiredAction === "login"',
        '_error?.requiredAction === "refresh_guest_session"',
        '_error?.code === "guest_session_invalid"',
        'setAnalysisResponse(isRateLimitExceeded ? null : { cards: FALLBACK_ANALYSIS_CARDS })',
    ):
        assert required in block


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
