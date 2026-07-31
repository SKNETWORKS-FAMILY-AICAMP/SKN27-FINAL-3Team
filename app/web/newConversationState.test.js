import test from "node:test";
import assert from "node:assert/strict";

import {
  createNewConversationResetState,
  issueNewConversationSession,
} from "./newConversationState.js";

test("accepts a distinct server-issued chat session", async () => {
  const calls = [];

  const sessionId = await issueNewConversationSession({
    currentSessionId: "ses_previous",
    createSession: async () => {
      calls.push("create");
      return { session_id: "ses_next" };
    },
  });

  assert.equal(sessionId, "ses_next");
  assert.deepEqual(calls, ["create"]);
});

test("rejects missing or unchanged server session ids", async () => {
  await assert.rejects(
    issueNewConversationSession({
      currentSessionId: "ses_previous",
      createSession: async () => ({}),
    }),
    { code: "chat_session_missing" }
  );
  await assert.rejects(
    issueNewConversationSession({
      currentSessionId: "ses_previous",
      createSession: async () => ({ session_id: "ses_previous" }),
    }),
    { code: "chat_session_not_rotated" }
  );
});

test("creates complete fresh conversation-owned reset values on every call", () => {
  const first = createNewConversationResetState();
  const second = createNewConversationResetState();

  assert.deepEqual(first, {
    acknowledgedAppealKey: "",
    analysisResponse: null,
    attachmentPurpose: "fine_notice",
    chatMessages: [],
    currentReport: null,
    guestDetailedReportUsed: false,
    historyEvents: null,
    isRegisteringAttachment: false,
    isReportWorkspaceLoading: false,
    isSavingConversation: false,
    isSubmitting: false,
    mypageSummary: null,
    ocrConfirmationFields: {},
    pendingAuthAction: null,
    pendingOcrConfirmation: null,
    question: "",
    registeredAttachments: [],
    reportActionStatus: "",
    reportList: [],
    reportWorkspaceLoadError: "",
    saveDecision: "undecided",
    savePromptVisible: false,
    selectedUploadFile: null,
    submittedQuestion: "",
  });
  assert.notEqual(first.chatMessages, second.chatMessages);
  assert.notEqual(first.registeredAttachments, second.registeredAttachments);
  assert.notEqual(first.reportList, second.reportList);
  assert.notEqual(first.ocrConfirmationFields, second.ocrConfirmationFields);
});
