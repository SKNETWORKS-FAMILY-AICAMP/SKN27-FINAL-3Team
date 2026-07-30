import test from "node:test";
import assert from "node:assert/strict";

import { resolveGuestBootstrapSessionId } from "./authSession.js";

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
