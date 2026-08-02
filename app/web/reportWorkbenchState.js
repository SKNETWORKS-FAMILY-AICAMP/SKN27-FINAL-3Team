const MISSING_ITEM_FALLBACK = "추가 확인이 필요한 항목";
const MISSING_ITEM_TEXT_KEYS = ["question", "label", "description", "title"];

function missingItemText(value, visited = new Set()) {
  if (typeof value === "string") {
    return value.trim();
  }
  if (!value || typeof value !== "object" || visited.has(value)) {
    return "";
  }
  visited.add(value);

  if (Array.isArray(value)) {
    for (const item of value) {
      const nestedText = missingItemText(item, visited);
      if (nestedText) return nestedText;
    }
    return "";
  }

  for (const key of MISSING_ITEM_TEXT_KEYS) {
    const prioritizedText = missingItemText(value[key], visited);
    if (prioritizedText) return prioritizedText;
  }
  for (const [key, nestedValue] of Object.entries(value)) {
    if (MISSING_ITEM_TEXT_KEYS.includes(key)) continue;
    const nestedText = missingItemText(nestedValue, visited);
    if (nestedText) return nestedText;
  }
  return MISSING_ITEM_FALLBACK;
}

export function compactUniqueStrings(values, limit = 5) {
  const seen = new Set();
  const items = [];

  for (const value of Array.isArray(values) ? values : []) {
    const normalized = missingItemText(value);
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    items.push(normalized);
    if (items.length >= limit) break;
  }

  return items;
}

export function deriveReportWorkbenchState({
  hasReport = false,
  hasSavedReports = false,
  canGenerateReport = false,
  isAuthenticated = false,
  isPersistedReport = false,
  reportingPayload = null,
  savedReportDetailLoaded = true,
  supervisorState = null,
} = {}) {
  if (hasSavedReports && !savedReportDetailLoaded && !reportingPayload) {
    return {
      kind: "loading_saved_report",
      stageLabel: "저장 리포트 불러오는 중",
      title: "저장된 리포트를 작업대에 연결하고 있습니다.",
      description: "목록 요약이 아니라 리포트 본문과 근거를 확인한 뒤 표시합니다.",
      missingItems: [],
      ctaLabel: "목록 새로고침",
    };
  }

  if (reportingPayload && !isPersistedReport) {
    return {
      kind: "temporary_preview",
      stageLabel: "임시 리포트 미리보기",
      title: "현재 상담의 분석 리포트를 검토할 수 있습니다.",
      description: isAuthenticated
        ? "저장 처리 후 내 사건과 작업대에서 다시 확인할 수 있습니다."
        : "현재 접속 중에는 검토할 수 있지만 저장과 제출용 문서는 Google 로그인 후 사용할 수 있습니다.",
      missingItems: [],
      ctaLabel: "AI 상담으로 이동",
    };
  }

  if (hasReport || hasSavedReports) {
    return {
      kind: "available",
      stageLabel: "리포트 확인 가능",
      title: "리포트가 준비되었습니다.",
      description: "리포트 미리보기와 저장·다운로드 작업을 계속할 수 있습니다.",
      missingItems: [],
      ctaLabel: "AI 상담으로 이동",
    };
  }

  const missingFields = compactUniqueStrings(supervisorState?.missing_fields);
  const nextQuestions = compactUniqueStrings(supervisorState?.next_questions);
  if (missingFields.length || nextQuestions.length) {
    return {
      kind: "needs_information",
      stageLabel: "상담·자료 보완 필요",
      title: "리포트 생성을 위해 확인할 정보가 있습니다.",
      description: "상담에서 아래 항목을 보완하면 분석과 리포트 준비를 이어갈 수 있습니다.",
      missingItems: missingFields.length ? missingFields : nextQuestions,
      ctaLabel: "AI 상담으로 이동",
    };
  }

  const stage = typeof supervisorState?.stage === "string" ? supervisorState.stage.trim() : "";
  if (canGenerateReport && stage) {
    return {
      kind: "persisting",
      stageLabel: "리포트 준비 중",
      title: "분석 결과를 리포트에 연결하고 있습니다.",
      description: "처리가 완료되면 이 작업대에서 근거를 검토하고 저장하거나 DOCX를 준비할 수 있습니다.",
      missingItems: [],
      ctaLabel: "AI 상담으로 이동",
    };
  }

  if (stage) {
    return {
      kind: "not_reportable",
      stageLabel: stage === "agent_execution_ready" ? "절차 안내 완료" : "상담 분석 중",
      title:
        stage === "agent_execution_ready"
          ? "이번 상담은 별도 리포트 문서를 만들지 않습니다."
          : "상담 분석이 진행 중입니다.",
      description:
        stage === "agent_execution_ready"
          ? "일반 법령·절차 안내는 상담 결과에서 바로 확인할 수 있습니다."
          : "상담 화면에서 현재 진행 상태와 다음 안내를 확인할 수 있습니다.",
      missingItems: [],
      ctaLabel: "AI 상담으로 이동",
    };
  }

  return {
    kind: "not_started",
    stageLabel: "상담 시작 전",
    title: "아직 생성된 리포트가 없습니다.",
    description: "상담 유형을 선택하고 사고 상황이나 고지서 정보를 입력하면 리포트 준비 상태를 이곳에서 확인할 수 있습니다.",
    missingItems: [],
    ctaLabel: "AI 상담 시작",
  };
}
