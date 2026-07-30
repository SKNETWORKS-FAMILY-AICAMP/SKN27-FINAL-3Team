export function shouldPromptGuestConversationSave({ authSessionId = "", result = null } = {}) {
  if (authSessionId || result?.status !== "success") {
    return false;
  }

  return Boolean(
    result?.persistence?.job_id || result?.session_id || result?.message_id,
  );
}
