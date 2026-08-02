import assert from "node:assert/strict";
import test from "node:test";

import {
  guestConversationFailureState,
  shouldPromptGuestConversationSave,
} from "./guestConversationPolicy.js";

test("keeps a guest conversation open while the assistant is asking follow-up questions", () => {
  assert.equal(
    shouldPromptGuestConversationSave({
      authSessionId: "",
      result: {
        status: "partial",
        persistence: { job_id: "job_waiting_for_facts" },
      },
    }),
    false,
  );
});

test("asks a guest to save only after a completed analysis", () => {
  assert.equal(
    shouldPromptGuestConversationSave({
      authSessionId: "",
      result: {
        status: "success",
        persistence: { job_id: "job_completed" },
      },
    }),
    true,
  );
});

test("does not show the guest save prompt for an authenticated conversation", () => {
  assert.equal(
    shouldPromptGuestConversationSave({
      authSessionId: "auth_123",
      result: {
        status: "success",
        persistence: { job_id: "job_completed" },
      },
    }),
    false,
  );
});

test("does not present a failed guest submission as saveable or report-ready", () => {
  assert.deepEqual(guestConversationFailureState(), {
    analysisResponse: null,
    guestDetailedReportUsed: false,
    savePromptVisible: false,
  });
});
