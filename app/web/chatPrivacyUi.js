export function shouldDiscardRejectedChatInput(error = {}) {
  return (
    error?.code === "chat_input_rejected" ||
    error?.requiredAction === "remove_sensitive_input"
  );
}
