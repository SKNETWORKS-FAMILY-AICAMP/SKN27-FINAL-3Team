export const GOOGLE_PROFILE_STORAGE_KEY = "skn27.auth.googleProfile";
export const AUTH_SESSION_STORAGE_KEY = "skn27.auth.session";
export const GOOGLE_IDENTITY_SCRIPT_SRC = "https://accounts.google.com/gsi/client";
export const GOOGLE_LOGIN_SCOPE = "openid email profile";
export const APP_JWT_REFRESH_EARLY_MS = 5 * 60 * 1000;

export function millisecondsUntilAppJwtRefresh(
  token,
  { nowMs = Date.now(), refreshEarlyMs = APP_JWT_REFRESH_EARLY_MS } = {}
) {
  const expiresAtMs = readUnverifiedJwtExpirationMs(token);
  if (expiresAtMs === null) {
    return null;
  }
  return Math.max(0, expiresAtMs - Number(nowMs) - Number(refreshEarlyMs));
}

export function scheduleAppJwtRefresh({
  token,
  refresh,
  nowMs = Date.now(),
  setTimer = (callback, delayMs) => window.setTimeout(callback, delayMs),
  clearTimer = (timerId) => window.clearTimeout(timerId),
} = {}) {
  const delayMs = millisecondsUntilAppJwtRefresh(token, { nowMs });
  if (delayMs === null || typeof refresh !== "function") {
    return () => {};
  }

  let disposed = false;
  let refreshInFlight = null;
  const runRefresh = () => {
    if (disposed) {
      return Promise.resolve();
    }
    if (refreshInFlight) {
      return refreshInFlight;
    }
    refreshInFlight = Promise.resolve()
      .then(refresh)
      .finally(() => {
        refreshInFlight = null;
      });
    return refreshInFlight;
  };
  const timerId = setTimer(runRefresh, delayMs);

  return () => {
    disposed = true;
    clearTimer(timerId);
  };
}

function readUnverifiedJwtExpirationMs(token) {
  const payloadSegment = String(token || "").split(".")[1];
  if (!payloadSegment) {
    return null;
  }
  try {
    const base64 = payloadSegment.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
    const bytes = Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
    const payload = JSON.parse(new TextDecoder().decode(bytes));
    const expiresAtSeconds = Number(payload?.exp);
    if (!Number.isFinite(expiresAtSeconds) || expiresAtSeconds <= 0) {
      return null;
    }
    // This unverified claim controls only refresh timing. The backend still verifies the JWT.
    return expiresAtSeconds * 1000;
  } catch (_error) {
    return null;
  }
}

export function buildAuthContext({ authState, guestId, authSessionId, sessionId, userId }) {
  return {
    auth_state: authState || "anonymous",
    user_id: userId || null,
    guest_id: guestId || null,
    auth_session_id: authSessionId || null,
    session_id: sessionId || null,
  };
}

export function resolveGuestBootstrapSessionId({
  boundSessionId,
  sessionId,
  guestId,
  guestCredential,
  nowMs = Date.now(),
} = {}) {
  if (boundSessionId) {
    return String(boundSessionId);
  }
  if (guestId && guestCredential && sessionId) {
    return String(sessionId);
  }
  return `ses_web_${Number(nowMs)}`;
}

export async function buildGoogleLoginPayload({
  googleClientId,
  purpose = "LOGIN",
} = {}) {
  const code = await requestGoogleAuthorizationCode({
    clientId: googleClientId,
    scope: GOOGLE_LOGIN_SCOPE,
  });
  return {
    auth_flow: "google_authorization_code_popup",
    client_id: String(googleClientId || "").trim(),
    code,
    purpose,
    scope: GOOGLE_LOGIN_SCOPE,
    redirect_uri: browserOrigin(),
  };
}

export function googleLoginFailureMessage(error) {
  const trustedMessage = String(error?.publicMessage || "").trim();
  if (trustedMessage) {
    return trustedMessage;
  }
  const detail = [error?.message, error?.code, error?.reason, error]
    .filter(Boolean)
    .map((value) => String(value).toLowerCase())
    .join(" ");
  if (detail.includes("redirect_uri_mismatch")) {
    return "Google 로그인 설정이 현재 서비스 주소와 일치하지 않습니다. 앱 관리자에게 리디렉션 주소 설정을 확인해 달라고 요청해 주세요.";
  }
  if (detail.includes("popup_failed_to_open") || detail.includes("popup blocked")) {
    return "Google 로그인 창을 열지 못했습니다. 브라우저의 팝업 차단을 해제한 뒤 다시 시도해 주세요.";
  }
  if (detail.includes("popup_closed") || detail.includes("popup closed")) {
    return "Google 로그인 창이 닫혔거나 서비스 화면으로 돌아오지 못했습니다. 팝업 차단을 해제하고 다시 시도해 주세요.";
  }
  if (detail.includes("timed out")) {
    return "Google 로그인 응답을 받지 못했습니다. 팝업 차단 여부를 확인한 뒤 다시 시도해 주세요.";
  }
  if (detail.includes("client id") || detail.includes("google oauth") || detail.includes("authorization code")) {
    return "Google 로그인 연결에 실패했습니다. 잠시 후 다시 시도해 주세요.";
  }
  return "Google 로그인 연결에 실패했습니다. 잠시 후 다시 시도해 주세요.";
}

export async function requestGoogleAuthorizationCode({ clientId, scope = GOOGLE_LOGIN_SCOPE, timeoutMs = 60000 }) {
  const normalizedClientId = String(clientId || "").trim();
  if (!normalizedClientId) {
    throw new Error("Google client id is required.");
  }
  if (typeof window === "undefined") {
    throw new Error("Google Identity Services requires a browser window.");
  }

  await loadGoogleIdentityScript();
  const googleOAuth = window.google?.accounts?.oauth2;
  if (!googleOAuth?.initCodeClient) {
    throw new Error("Google OAuth code client did not load.");
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    const settle = (callback, value) => {
      if (settled) {
        return;
      }
      settled = true;
      window.clearTimeout(timer);
      callback(value);
    };
    const timer = window.setTimeout(() => {
      settle(reject, new Error("Google authorization code request timed out."));
    }, timeoutMs);

    const codeClient = googleOAuth.initCodeClient({
      client_id: normalizedClientId,
      scope,
      ux_mode: "popup",
      include_granted_scopes: true,
      select_account: true,
      callback: (response) => {
        if (response?.code) {
          settle(resolve, response.code);
          return;
        }
        settle(reject, new Error(response?.error || "Google authorization code was not returned."));
      },
      error_callback: (error) => {
        settle(reject, new Error(error?.type || "google_authorization_failed"));
      },
    });
    codeClient.requestCode();
  });
}

export async function requestGoogleCredential({ clientId, timeoutMs = 60000 }) {
  const normalizedClientId = String(clientId || "").trim();
  if (!normalizedClientId) {
    throw new Error("Google client id is required.");
  }
  if (typeof window === "undefined") {
    throw new Error("Google Identity Services requires a browser window.");
  }

  await loadGoogleIdentityScript();
  const googleIdentity = window.google?.accounts?.id;
  if (!googleIdentity) {
    throw new Error("Google Identity Services did not load.");
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    const settle = (callback, value) => {
      if (settled) {
        return;
      }
      settled = true;
      window.clearTimeout(timer);
      callback(value);
    };
    const timer = window.setTimeout(() => {
      settle(reject, new Error("Google credential request timed out."));
    }, timeoutMs);

    googleIdentity.initialize({
      client_id: normalizedClientId,
      callback: (response) => {
        if (response?.credential) {
          settle(resolve, response.credential);
          return;
        }
        settle(reject, new Error("Google credential was not returned."));
      },
    });

    googleIdentity.prompt((notification) => {
      if (!notification) {
        return;
      }
      const unavailable =
        notification.isNotDisplayed?.() || notification.isSkippedMoment?.() || notification.isDismissedMoment?.();
      if (unavailable) {
        const reason =
          notification.getNotDisplayedReason?.() ||
          notification.getSkippedReason?.() ||
          notification.getDismissedReason?.() ||
          "google_prompt_unavailable";
        settle(reject, new Error(reason));
      }
    });
  });
}

export function loadGoogleIdentityScript() {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return Promise.reject(new Error("Google Identity Services requires a browser document."));
  }
  if (window.google?.accounts?.id || window.google?.accounts?.oauth2) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    const existingScript = document.querySelector(`script[src="${GOOGLE_IDENTITY_SCRIPT_SRC}"]`);
    if (existingScript) {
      existingScript.addEventListener("load", () => resolve(), { once: true });
      existingScript.addEventListener("error", () => reject(new Error("Failed to load Google Identity Services.")), {
        once: true,
      });
      return;
    }

    const script = document.createElement("script");
    script.src = GOOGLE_IDENTITY_SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Google Identity Services."));
    document.head.appendChild(script);
  });
}

export function browserOrigin() {
  if (typeof window === "undefined" || !window.location?.origin) {
    return "";
  }
  return window.location.origin;
}

export function readStoredAuthToken() {
  const storedSession = readStoredJson(AUTH_SESSION_STORAGE_KEY) || {};
  return String(storedSession.access_token || "");
}

export function readStoredAuthSession() {
  const storedSession = readStoredJson(AUTH_SESSION_STORAGE_KEY) || {};
  const normalizedSession = {
    guest_id: storedSession.guest_id || null,
    guest_credential: storedSession.guest_credential || null,
    auth_session_id: storedSession.auth_session_id || null,
    user_id: storedSession.user_id || null,
    session_id: storedSession.session_id || null,
    access_token: storedSession.access_token || null,
  };
  return Object.values(normalizedSession).some((value) => Boolean(value)) ? normalizedSession : {};
}

export function readStoredGoogleProfile() {
  return readStoredJson(GOOGLE_PROFILE_STORAGE_KEY);
}

export function persistAuthSession({
  accessToken,
  authSessionId,
  guestId,
  guestCredential,
  googleProfile,
  sessionId,
  userId,
}) {
  writeStoredJson(AUTH_SESSION_STORAGE_KEY, {
    guest_id: guestId || null,
    guest_credential: guestCredential || null,
    auth_session_id: authSessionId || null,
    user_id: userId || null,
    session_id: sessionId || null,
    access_token: accessToken || null,
  });
  writeStoredJson(GOOGLE_PROFILE_STORAGE_KEY, googleProfile || null);
}

export function clearStoredAuthSession() {
  removeStoredValue(GOOGLE_PROFILE_STORAGE_KEY);
  removeStoredValue(AUTH_SESSION_STORAGE_KEY);
}

export function readStoredValue(key) {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.localStorage.getItem(key);
  } catch (_error) {
    return null;
  }
}

export function writeStoredValue(key, value) {
  if (typeof window === "undefined" || !value) {
    return;
  }
  try {
    window.localStorage.setItem(key, value);
  } catch (_error) {
    // Ignore storage failures; in-memory auth state still works for this session.
  }
}

export function removeStoredValue(key) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.removeItem(key);
  } catch (_error) {
    // Ignore storage failures.
  }
}

export function readStoredJson(key) {
  const value = readStoredValue(key);
  if (!value) {
    return null;
  }
  try {
    return JSON.parse(value);
  } catch (_error) {
    return null;
  }
}

export function writeStoredJson(key, value) {
  if (!value) {
    removeStoredValue(key);
    return;
  }
  writeStoredValue(key, JSON.stringify(value));
}
