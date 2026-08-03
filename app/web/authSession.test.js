import test from "node:test";
import assert from "node:assert/strict";
import * as authSession from "./authSession.js";

import {
  googleLoginFailureMessage,
  recoverStoredAuthSession,
  resolveGuestBootstrapSessionId,
  shouldClearAuthentication,
} from "./authSession.js";

function appJwtWithExpiration(expiresAtSeconds) {
  const encode = (value) => Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${encode({ alg: "HS256", typ: "JWT" })}.${encode({ exp: expiresAtSeconds })}.signature`;
}

test("recovers a stored authenticated session only after auth/me verifies it", async () => {
  const nowMs = 1770000000000;
  const storedToken = appJwtWithExpiration(Math.floor(nowMs / 1000) + 1800);
  const calls = [];

  const result = await recoverStoredAuthSession({
    storedSession: {
      access_token: storedToken,
      auth_session_id: "auth_verified",
      user_id: "usr_verified",
      guest_id: "gst_lineage",
      guest_credential: "signed-guest-credential",
      session_id: "ses_current",
    },
    nowMs,
    getCurrentAuthSubject: async ({ sessionId, identity }) => {
      calls.push({ operation: "auth_me", sessionId, identity });
      return {
        auth_state: "authenticated",
        subject: {
          auth_session_id: "auth_verified",
          guest_id: "gst_lineage",
          is_authenticated: true,
          user_id: "usr_verified",
        },
      };
    },
    refreshAuthToken: async () => {
      calls.push({ operation: "refresh" });
      throw new Error("refresh should not run outside the early-refresh window");
    },
  });

  assert.equal(result.status, "authenticated");
  assert.equal(result.refreshed, false);
  assert.equal(result.session.access_token, storedToken);
  assert.equal(result.session.auth_session_id, "auth_verified");
  assert.equal(result.session.user_id, "usr_verified");
  assert.equal(result.session.guest_credential, "signed-guest-credential");
  assert.deepEqual(calls.map(({ operation }) => operation), ["auth_me"]);
  assert.equal(calls[0].identity.authToken, storedToken);
  assert.equal(calls[0].sessionId, "ses_current");
});

test("refreshes a still-valid token in the early window before auth/me verification", async () => {
  const nowMs = 1770000000000;
  const storedToken = appJwtWithExpiration(Math.floor(nowMs / 1000) + 240);
  const refreshedToken = appJwtWithExpiration(Math.floor(nowMs / 1000) + 3600);
  const calls = [];

  const result = await recoverStoredAuthSession({
    storedSession: {
      access_token: storedToken,
      auth_session_id: "auth_before_refresh",
      user_id: "usr_verified",
      guest_id: "gst_lineage",
      guest_credential: "signed-guest-credential",
      session_id: "ses_current",
    },
    nowMs,
    refreshAuthToken: async (payload, identity) => {
      calls.push({ operation: "refresh", payload, identity });
      return {
        access_token: refreshedToken,
        subject: {
          auth_session_id: "auth_after_refresh",
          guest_id: "gst_lineage",
          user_id: "usr_verified",
        },
      };
    },
    getCurrentAuthSubject: async ({ sessionId, identity }) => {
      calls.push({ operation: "auth_me", sessionId, identity });
      return {
        auth_state: "authenticated",
        subject: {
          auth_session_id: "auth_after_refresh",
          guest_id: "gst_lineage",
          is_authenticated: true,
          user_id: "usr_verified",
        },
      };
    },
  });

  assert.equal(result.status, "authenticated");
  assert.equal(result.refreshed, true);
  assert.equal(result.session.access_token, refreshedToken);
  assert.equal(result.session.auth_session_id, "auth_after_refresh");
  assert.deepEqual(calls.map(({ operation }) => operation), ["refresh", "auth_me"]);
  assert.equal(calls[1].identity.authToken, refreshedToken);
  assert.equal(calls[1].identity.authSessionId, "auth_after_refresh");
});

test("preserves authenticated and chat recovery context when proactive refresh has a transient failure", async () => {
  const nowMs = 1770000000000;
  const storedToken = appJwtWithExpiration(Math.floor(nowMs / 1000) - 1);
  let authMeCalled = false;
  const refreshError = Object.assign(new Error("expired"), {
    code: "token_expired",
    reason: "expired_token",
  });

  const result = await recoverStoredAuthSession({
    storedSession: {
      access_token: storedToken,
      auth_session_id: "auth_expired",
      user_id: "usr_previous",
      guest_id: "gst_lineage",
      guest_credential: "signed-guest-credential",
      session_id: "ses_current",
    },
    nowMs,
    refreshAuthToken: async () => {
      throw refreshError;
    },
    getCurrentAuthSubject: async () => {
      authMeCalled = true;
      throw new Error("auth/me should not run with an unusable token");
    },
  });

  assert.equal(result.status, "verification_unavailable");
  assert.equal(result.reason, "auth_verification_unavailable");
  assert.equal(result.session.access_token, storedToken);
  assert.equal(result.session.auth_session_id, "auth_expired");
  assert.equal(result.session.user_id, "usr_previous");
  assert.equal(result.session.guest_id, "gst_lineage");
  assert.equal(result.session.guest_credential, "signed-guest-credential");
  assert.equal(result.session.session_id, "ses_current");
  assert.equal(authMeCalled, true);
});

test("does not clear storage when auth/me returns a mismatched authenticated session", async () => {
  const nowMs = 1770000000000;
  const storedToken = appJwtWithExpiration(Math.floor(nowMs / 1000) + 1800);

  const result = await recoverStoredAuthSession({
    storedSession: {
      access_token: storedToken,
      auth_session_id: "auth_expected",
      user_id: "usr_expected",
      guest_id: "gst_lineage",
      guest_credential: "signed-guest-credential",
      session_id: "ses_current",
    },
    nowMs,
    refreshAuthToken: async () => {
      throw new Error("refresh should not run");
    },
    getCurrentAuthSubject: async () => ({
      auth_state: "authenticated",
      subject: {
        auth_session_id: "auth_other",
        is_authenticated: true,
        user_id: "usr_expected",
      },
    }),
  });

  assert.equal(result.status, "verification_unavailable");
  assert.equal(result.reason, "auth_session_mismatch");
  assert.equal(result.session.access_token, storedToken);
  assert.equal(result.session.auth_session_id, "auth_expected");
  assert.equal(result.session.guest_id, "gst_lineage");
  assert.equal(result.session.session_id, "ses_current");
});

test("clears authentication only for explicit HTTP 401 or 403 responses", () => {
  assert.equal(shouldClearAuthentication({ status: 401 }), true);
  assert.equal(shouldClearAuthentication({ status: 403 }), true);
  assert.equal(shouldClearAuthentication({ status: 503, code: "auth_required" }), false);
  assert.equal(shouldClearAuthentication({ code: "token_expired" }), false);
  assert.equal(shouldClearAuthentication(new TypeError("network unavailable")), false);
});

test("does not reuse a stale chat session without a valid guest credential", () => {
  assert.equal(
    resolveGuestBootstrapSessionId({
      sessionId: "ses_owned_by_previous_guest",
      guestId: "gst_previous_guest",
      guestCredential: "",
      nowMs: 1770000000000,
    }),
    "ses_web_1770000000000"
  );
});

test("reuses the current chat session only with the matching guest credential", () => {
  assert.equal(
    resolveGuestBootstrapSessionId({
      sessionId: "ses_current_guest",
      guestId: "gst_current_guest",
      guestCredential: "signed-guest-credential",
      nowMs: 1770000000000,
    }),
    "ses_current_guest"
  );
});

test("explains a Google redirect mismatch without exposing the raw OAuth error", () => {
  assert.equal(
    googleLoginFailureMessage(new Error("redirect_uri_mismatch")),
    "Google 로그인 설정이 현재 서비스 주소와 일치하지 않습니다. 앱 관리자에게 리디렉션 주소 설정을 확인해 달라고 요청해 주세요."
  );
});

test("explains a blocked or closed Google popup with a retry action", () => {
  assert.equal(
    googleLoginFailureMessage(new Error("popup_failed_to_open")),
    "Google 로그인 창을 열지 못했습니다. 브라우저의 팝업 차단을 해제한 뒤 다시 시도해 주세요."
  );
  assert.equal(
    googleLoginFailureMessage(new Error("popup_closed")),
    "Google 로그인 창이 닫혔거나 서비스 화면으로 돌아오지 못했습니다. 팝업 차단을 해제하고 다시 시도해 주세요."
  );
});

test("explains a session ownership rejection even when the API supplied a generic 403 message", () => {
  assert.equal(
    googleLoginFailureMessage({
      publicMessage: "요청한 리소스에 접근할 권한이 없습니다.",
      reason: "google_session_already_owned",
    }),
    "이 상담은 이미 다른 계정에 저장되어 있습니다. 새 상담을 시작한 뒤 Google 로그인을 다시 시도해 주세요."
  );
});

test("retains the structured Google login rejection reason for the caller", () => {
  assert.equal(typeof authSession.toGoogleLoginError, "function");
  const error = authSession.toGoogleLoginError({
    publicMessage: "요청한 리소스에 접근할 권한이 없습니다.",
    reason: "google_session_already_owned",
    status: 403,
  });

  assert.equal(error.publicMessage, "이 상담은 이미 다른 계정에 저장되어 있습니다. 새 상담을 시작한 뒤 Google 로그인을 다시 시도해 주세요.");
  assert.equal(error.reason, "google_session_already_owned");
  assert.equal(error.status, 403);
});
