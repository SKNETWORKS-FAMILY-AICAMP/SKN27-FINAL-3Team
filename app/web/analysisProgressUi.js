const IDENTIFIER_PATTERN = /^[A-Za-z][A-Za-z0-9_-]{2,63}$/;
const NEXT_ACTION_PATTERN = /^[a-z][a-z0-9_]*$/;

const PRESENTATION = {
  queued: {
    label: "대기",
    tone: "neutral",
    message: "분석 요청이 대기 중입니다. 순서가 되면 자동으로 진행됩니다.",
  },
  running: {
    label: "분석 중",
    tone: "active",
    message: "분석이 진행 중입니다. 확인된 결과는 완료되는 대로 표시됩니다.",
  },
  partial: {
    label: "일부 결과",
    tone: "attention",
    message: "확인된 결과만 표시했습니다. 한계와 추가 확인 사항을 검토해 주세요.",
  },
  failed: {
    label: "완료하지 못함",
    tone: "danger",
    message: "분석을 완료하지 못했습니다. 표시된 다음 행동을 확인해 주세요.",
  },
  needs_input: {
    label: "확인 필요",
    tone: "attention",
    message: "분석을 계속하려면 표시된 확인 항목에 답해 주세요.",
  },
  success: {
    label: "분석 완료",
    tone: "complete",
    message: "분석이 완료되었습니다.",
  },
};


export function buildAnalysisProgressUi(value) {
  if (
    !value ||
    value.contract_version !== "analysis_progress.v1" ||
    !Object.hasOwn(PRESENTATION, value.semantic_status)
  ) {
    return null;
  }

  const presentation = PRESENTATION[value.semantic_status];
  const nextAction = String(value.next_action || "").trim();
  return {
    semanticStatus: value.semantic_status,
    terminal: value.terminal === true,
    retryable: value.retryable === true,
    nextAction: NEXT_ACTION_PATTERN.test(nextAction) ? nextAction : null,
    message: presentation.message,
    label: presentation.label,
    tone: presentation.tone,
    jobId: safeIdentifier(value.job_id),
    correlationId: safeIdentifier(value.correlation_id),
  };
}


function safeIdentifier(value) {
  const identifier = String(value || "").trim();
  return IDENTIFIER_PATTERN.test(identifier) ? identifier : null;
}
