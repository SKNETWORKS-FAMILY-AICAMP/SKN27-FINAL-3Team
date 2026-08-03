export const ATTACHMENT_ANALYSIS_USER_TEXT = "첨부한 자료를 확인해 주세요.";


export async function runAttachmentScanWorkflow({
  api,
  attachment,
  sessionId,
  identity,
  wait,
  maxAttempts,
  onUpdate = () => {},
  startAnalysis,
}) {
  const attachmentId = text(attachment?.attachment_id);
  if (!attachmentId) {
    throw new Error("attachment_id_missing");
  }

  let latestAttachment = { ...attachment };
  onUpdate(latestAttachment);
  if (isRejected(latestAttachment)) {
    throw new Error("attachment_scan_rejected");
  }

  const attempts = Math.max(0, Number(maxAttempts) || 0);
  for (let attempt = 0; !isReady(latestAttachment) && attempt < attempts; attempt += 1) {
    const response = await api.getAttachment({
      attachmentId,
      sessionId,
      identity,
    });
    latestAttachment = record(response?.attachment);
    onUpdate(latestAttachment);
    if (isRejected(latestAttachment)) {
      throw new Error("attachment_scan_rejected");
    }
    if (!isReady(latestAttachment) && attempt < attempts - 1) {
      await wait();
    }
  }

  if (!isReady(latestAttachment)) {
    throw new Error("attachment_scan_timeout");
  }

  const analysis = await startAnalysis({
    attachment: latestAttachment,
    userText: ATTACHMENT_ANALYSIS_USER_TEXT,
  });
  return { attachment: latestAttachment, analysis };
}


function isReady(attachment) {
  return attachment?.status === "ready" && attachment?.scan_status === "clean";
}


function isRejected(attachment) {
  return attachment?.status === "rejected" || attachment?.scan_status === "rejected";
}


function record(value) {
  return value && typeof value === "object" && !Array.isArray(value)
    ? { ...value }
    : {};
}


function text(value) {
  return typeof value === "string" ? value.trim() : "";
}
