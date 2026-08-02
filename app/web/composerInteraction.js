export function composerKeyAction(event = {}, state = {}) {
  if (event.key !== "Enter") return "ignore";
  if (
    event.isComposing ||
    event.nativeEvent?.isComposing ||
    event.keyCode === 229 ||
    event.which === 229
  ) {
    return "ignore";
  }
  if (event.shiftKey) return "newline";
  if (!state.hasContent || state.isSubmitting) return "ignore";
  return "submit";
}
