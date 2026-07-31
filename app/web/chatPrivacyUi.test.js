import assert from "node:assert/strict";
import test from "node:test";

import {
  shouldDiscardRejectedChatInput,
} from "./chatPrivacyUi.js";


test("discards user text rejected by the privacy gateway", () => {
  assert.equal(
    shouldDiscardRejectedChatInput({
      code: "chat_input_rejected",
      requiredAction: "remove_sensitive_input",
    }),
    true,
  );
});


test("retains user text for unrelated transient failures", () => {
  assert.equal(
    shouldDiscardRejectedChatInput({
      code: "service_unavailable",
      requiredAction: "retry",
    }),
    false,
  );
});
