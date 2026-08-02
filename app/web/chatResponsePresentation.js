const PRESENTATION_STATUSES = new Set([
  "queued",
  "running",
  "partial",
  "failed",
  "needs_input",
  "needs_clarification",
  "success",
]);

const STATE_FALLBACKS = {
  queued: "분석을 준비하고 있습니다.",
  running: "분석 상태를 확인하고 있습니다.",
  partial: "일부 결과만 확인되었습니다. 확인 사항을 검토한 뒤 다시 시도해 주세요.",
  failed: "분석을 완료하지 못했습니다. 입력 내용을 확인한 뒤 다시 시도해 주세요.",
  needs_input: "추가 확인이 필요합니다. 아래 질문에 답해 주세요.",
  needs_clarification: "요청을 정확히 이해하려면 내용을 조금 더 알려 주세요.",
  success: "완료된 답변을 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.",
};

const TONES = {
  queued: "info",
  running: "info",
  partial: "warning",
  failed: "danger",
  needs_input: "warning",
  needs_clarification: "warning",
  success: "success",
};

export function asNonEmptyText(value) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function firstText(values) {
  for (const value of values) {
    const text = asNonEmptyText(value);
    if (text) return text;
  }
  return "";
}

function normalizeQuestion(value) {
  if (typeof value === "string") return asNonEmptyText(value);
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  return firstText([value.question, value.label, value.description]);
}

function normalizePendingQuestions(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  const questions = [];
  for (const item of value) {
    const question = normalizeQuestion(item);
    if (!question || seen.has(question)) continue;
    seen.add(question);
    questions.push(question);
  }
  return questions;
}

export function selectPrimaryFollowUpQuestion({
  pendingQuestions = [],
  followUp = null,
  supervisorQuestions = [],
} = {}) {
  const pending = Array.isArray(pendingQuestions)
    ? pendingQuestions.map(normalizeQuestion).find(Boolean)
    : "";
  if (pending) return pending;

  const followUpMessage = asNonEmptyText(followUp?.message);
  if (followUpMessage) return followUpMessage;

  return Array.isArray(supervisorQuestions)
    ? supervisorQuestions.map(normalizeQuestion).find(Boolean) || ""
    : "";
}

function normalizeReportLink(result) {
  const links = Array.isArray(result?.report_links) ? result.report_links : [];
  for (const link of links) {
    if (typeof link === "string") {
      const href = asNonEmptyText(link);
      if (href) return { href, label: "현재 리포트 보기" };
      continue;
    }
    if (!link || typeof link !== "object" || Array.isArray(link)) continue;
    const href = firstText([link.href, link.url]);
    if (!href) continue;
    return {
      href,
      label: firstText([link.label, link.title]) || "현재 리포트 보기",
    };
  }

  const hasReportingPayload = Boolean(
    result?.reporting_payload ||
    result?.supervisor_state?.reporting_payload,
  );
  return hasReportingPayload
    ? { href: "", label: "현재 리포트 보기" }
    : null;
}

export function normalizeChatResponsePresentation(result = {}) {
  const safeResult = result && typeof result === "object" && !Array.isArray(result)
    ? result
    : {};
  const assistant = safeResult.assistant_message &&
    typeof safeResult.assistant_message === "object" &&
    !Array.isArray(safeResult.assistant_message)
    ? safeResult.assistant_message
    : {};
  const statusCandidate = firstText([safeResult.status, safeResult.semantic_status]);
  const requestedStatus = PRESENTATION_STATUSES.has(statusCandidate)
    ? statusCandidate
    : "partial";
  const directAnswer = firstText([
    assistant.core_answer,
    assistant.answer,
    assistant.summary,
    typeof safeResult.assistant_message === "string"
      ? safeResult.assistant_message
      : "",
  ]);
  const semanticStatus = requestedStatus === "success" && !directAnswer
    ? "partial"
    : requestedStatus;
  const answerMarkdown = directAnswer || firstText([
    safeResult.polling_notice?.message,
    safeResult.analysis_progress?.user_message,
  ]) || STATE_FALLBACKS[requestedStatus];

  return {
    semanticStatus,
    tone: TONES[semanticStatus],
    answerMarkdown,
    followUp: firstText([assistant.follow_up, safeResult.follow_up]),
    pendingQuestions: normalizePendingQuestions(
      safeResult.pending_questions || assistant.pending_questions,
    ),
    retryAction: ["failed", "partial"].includes(semanticStatus)
      ? {
          kind: "refocus-input",
          label: "입력 내용을 확인하고 다시 보내기",
        }
      : null,
    reportLink: normalizeReportLink(safeResult),
  };
}
