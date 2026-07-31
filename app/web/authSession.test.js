import test from "node:test";
import assert from "node:assert/strict";

import {
  googleLoginFailureMessage,
  resolveGuestBootstrapSessionId,
} from "./authSession.js";

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
