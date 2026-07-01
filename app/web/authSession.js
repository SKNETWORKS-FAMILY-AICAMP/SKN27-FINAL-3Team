export const AUTH_TOKEN_STORAGE_KEY = "skn27.auth.accessToken";
export const GOOGLE_PROFILE_STORAGE_KEY = "skn27.auth.googleProfile";
export const GOOGLE_IDENTITY_SCRIPT_SRC = "https://accounts.google.com/gsi/client";
export const GOOGLE_LOGIN_SCOPE = "openid email profile";

export function buildAuthContext({ authState, guestId, authSessionId, sessionId, userId }) {
  return {
    auth_state: authState || "anonymous",
    user_id: userId || null,
    guest_id: guestId || null,
    auth_session_id: authSessionId || null,
    session_id: sessionId || null,
  };
}

export function buildDevGoogleProfile({ guestId }) {
  const suffix = String(guestId || "guest").replace(/^gst_/, "") || Date.now();
  return {
    google_sub: `dev-google-${suffix}`,
    email: `driver.${suffix}@example.com`,
    display_name: "Google Demo User",
  };
}

export function buildDevGoogleCodePayload({ guestId, purpose = "LOGIN" }) {
  const profile = buildDevGoogleProfile({ guestId });
  const suffix = String(guestId || profile.google_sub || "guest").replace(/^gst_/, "") || Date.now();
  return {
    auth_flow: "google_authorization_code_mock",
    code: `mock_google_code:${suffix}`,
    purpose,
    scope: GOOGLE_LOGIN_SCOPE,
    redirect_uri: browserOrigin(),
    ...profile,
  };
}

export async function buildGoogleLoginPayload({ googleClientId, guestId, purpose = "LOGIN" }) {
  if (!googleClientId) {
    return buildDevGoogleCodePayload({ guestId, purpose });
  }

  const code = await requestGoogleAuthorizationCode({
    clientId: googleClientId,
    scope: GOOGLE_LOGIN_SCOPE,
  });
  return {
    auth_flow: "google_authorization_code_popup",
    code,
    purpose,
    scope: GOOGLE_LOGIN_SCOPE,
    redirect_uri: browserOrigin(),
  };
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
      prompt: "consent",
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
  return readStoredValue(AUTH_TOKEN_STORAGE_KEY) || "";
}

export function readStoredGoogleProfile() {
  return readStoredJson(GOOGLE_PROFILE_STORAGE_KEY);
}

export function persistAuthSession({ accessToken, googleProfile }) {
  if (accessToken) {
    writeStoredValue(AUTH_TOKEN_STORAGE_KEY, accessToken);
  }
  writeStoredJson(GOOGLE_PROFILE_STORAGE_KEY, googleProfile || null);
}

export function clearStoredAuthSession() {
  removeStoredValue(AUTH_TOKEN_STORAGE_KEY);
  removeStoredValue(GOOGLE_PROFILE_STORAGE_KEY);
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
