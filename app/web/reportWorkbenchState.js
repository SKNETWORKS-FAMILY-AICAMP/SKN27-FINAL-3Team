function compactUniqueStrings(values, limit = 3) {
  const seen = new Set();
  const items = [];

  for (const value of Array.isArray(values) ? values : []) {
    const normalized = String(value || "").trim();
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
  reportingPayload = null,
  supervisorState = null,
} = {}) {
  if (hasReport || hasSavedReports || reportingPayload) {
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

  const stage = String(supervisorState?.stage || "").trim();
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
