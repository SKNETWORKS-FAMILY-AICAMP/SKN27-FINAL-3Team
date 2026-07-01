export const AUTH_TOKEN_STORAGE_KEY = "skn27.auth.accessToken";
export const GOOGLE_PROFILE_STORAGE_KEY = "skn27.auth.googleProfile";

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
