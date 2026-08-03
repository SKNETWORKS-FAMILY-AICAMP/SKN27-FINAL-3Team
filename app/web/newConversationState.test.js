import test from "node:test";
import assert from "node:assert/strict";

import {
  createNewConversationResetState,
  issueNewConversationSession,
  submitWithGuestSessionRecovery,
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

test("recovers a guest chat submission when the stored session owner is stale", async () => {
  const submittedSessions = [];
  const staleSessionError = Object.assign(new Error("Access denied."), {
    status: 403,
    code: "object_access_denied",
    requiredAction: "login_or_owner_match",
    payload: {
      error: {
        access: { reason: "owner_mismatch" },
      },
    },
  });

  const outcome = await submitWithGuestSessionRecovery({
    currentSessionId: "ses_stale",
    identity: {
      authSessionId: "",
      guestCredential: "signed-guest-credential",
      guestId: "gst_current",
    },
    payload: {
      session_id: "ses_stale",
      auth_context: {
        auth_state: "guest",
        guest_id: "gst_current",
        session_id: "ses_stale",
      },
      user_text: "교차로에서 충돌했는데 과실비율이 궁금합니다.",
    },
    createSession: async () => ({ session_id: "ses_fresh" }),
    submitMessage: async (payload) => {
      submittedSessions.push({
        authContextSessionId: payload.auth_context.session_id,
        sessionId: payload.session_id,
      });
      if (submittedSessions.length === 1) {
        throw staleSessionError;
      }
      return {
        status: "needs_input",
        execution_mode: "input_collection",
        assistant_message: { core_answer: "사고 장소의 도로 형태를 알려주세요." },
        pending_questions: ["사고 장소의 도로 형태를 알려주세요."],
      };
    },
  });

  assert.deepEqual(submittedSessions, [
    { authContextSessionId: "ses_stale", sessionId: "ses_stale" },
    { authContextSessionId: "ses_fresh", sessionId: "ses_fresh" },
  ]);
  assert.equal(outcome.recovered, true);
  assert.equal(outcome.sessionId, "ses_fresh");
  assert.equal(outcome.result.status, "needs_input");
  assert.equal(outcome.result.execution_mode, "input_collection");
});

test("creates complete fresh conversation-owned reset values on every call", () => {
  const first = createNewConversationResetState();
  const second = createNewConversationResetState();

  assert.deepEqual(first, {
    acknowledgedAppealKey: "",
    analysisResponse: null,
    attachmentPurpose: "fine_notice",
    chatMessages: [],
    currentSessionReport: null,
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
    reportWorkspaceLoadError: "",
    saveDecision: "undecided",
    savePromptVisible: false,
    selectedUploadFile: null,
    selectedSavedReport: null,
    submittedQuestion: "",
  });
  assert.notEqual(first.chatMessages, second.chatMessages);
  assert.notEqual(first.registeredAttachments, second.registeredAttachments);
  assert.notEqual(first.ocrConfirmationFields, second.ocrConfirmationFields);
});
