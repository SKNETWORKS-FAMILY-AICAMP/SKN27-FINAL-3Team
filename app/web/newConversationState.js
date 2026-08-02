export async function issueNewConversationSession({
  currentSessionId,
  createSession,
} = {}) {
  if (typeof createSession !== "function") {
    throw new TypeError("A chat-session issuer is required.");
  }
  const response = await createSession();
  const nextSessionId = String(response?.session_id || "").trim();
  if (!nextSessionId) {
    throw conversationSessionError(
      "chat_session_missing",
      "The server did not issue a chat session."
    );
  }
  if (currentSessionId && nextSessionId === String(currentSessionId)) {
    throw conversationSessionError(
      "chat_session_not_rotated",
      "The server returned the current chat session."
    );
  }
  return nextSessionId;
}

export async function submitWithGuestSessionRecovery({
  currentSessionId,
  identity = {},
  payload = {},
  createSession,
  submitMessage,
} = {}) {
  if (typeof submitMessage !== "function") {
    throw new TypeError("A chat-message submitter is required.");
  }

  try {
    return {
      recovered: false,
      result: await submitMessage(payload),
      sessionId: currentSessionId,
    };
  } catch (error) {
    if (!isRecoverableGuestSessionAccessError(error, identity, currentSessionId)) {
      throw error;
    }

    const nextSessionId = await issueNewConversationSession({
      currentSessionId,
      createSession,
    });
    const retryPayload = {
      ...payload,
      session_id: nextSessionId,
      auth_context: {
        ...(payload.auth_context || {}),
        session_id: nextSessionId,
      },
    };
    return {
      recovered: true,
      result: await submitMessage(retryPayload),
      sessionId: nextSessionId,
    };
  }
}

export function createNewConversationResetState() {
  return {
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
  };
}

function conversationSessionError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function isRecoverableGuestSessionAccessError(error, identity, currentSessionId) {
  return Boolean(
    currentSessionId &&
    identity?.guestId &&
    identity?.guestCredential &&
    !identity?.authSessionId &&
    Number(error?.status) === 403 &&
    error?.code === "object_access_denied" &&
    error?.requiredAction === "login_or_owner_match"
  );
}
