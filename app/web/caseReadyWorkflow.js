import { pollWorkerResult } from "./workerPolling.js";


export const CASE_READY_FACTS = [
  ["road_layout", "도로 형태"],
  ["vehicle_actions", "양쪽 차량 행동"],
  ["signal_priority", "신호·우선권"],
  ["collision_location", "충돌 부위"],
];

const CASE_READY_ACTIVE_STEPS = new Set([
  "creating_case",
  "confirming_facts",
  "starting_analysis",
  "polling",
  "loading_report",
  "ready",
]);

const CASE_READY_PROGRESS_MESSAGES = {
  idle: "핵심 사실 4건을 확인한 뒤 사건 분석을 시작합니다.",
  creating_case: "상담 내용을 사건으로 저장하고 있습니다.",
  confirming_facts: "확인한 사실을 사건 기록에 반영하고 있습니다.",
  starting_analysis: "사건 분석 작업을 시작하고 있습니다.",
  polling: "과실 쟁점과 법률 근거를 분석하고 있습니다.",
  loading_report: "완료된 리포트를 불러오고 있습니다.",
  ready: "사건 분석 리포트가 준비되었습니다.",
  failed: "사건 분석 리포트를 완료하지 못했습니다.",
};


export function buildCaseReadyActionUi({
  model,
  progress = {},
  authenticated = false,
}) {
  const step = text(progress.step) || "idle";
  return {
    visible: model?.eligible === true,
    facts: Array.isArray(model?.facts) ? model.facts : [],
    buttonLabel: authenticated
      ? "사건 생성·분석 시작"
      : "로그인 후 사건 생성·분석 시작",
    disabled: CASE_READY_ACTIVE_STEPS.has(step),
    progressMessage: CASE_READY_PROGRESS_MESSAGES[step]
      || CASE_READY_PROGRESS_MESSAGES.idle,
    error: text(progress.error),
  };
}


export function caseReadyWorkflowErrorMessage(error) {
  if (error?.code === "fact_readiness_not_met") {
    return "첨부 자료의 안전 검사를 완료한 뒤 사건 분석을 다시 시도해 주세요.";
  }
  return "사건 분석 리포트를 완료하지 못했습니다. 입력과 자료 상태를 확인해 주세요.";
}


export function buildCaseReadyViewModel(
  analysisResponse = {},
  registeredAttachments = [],
) {
  const consultationState = record(analysisResponse?.consultation_state?.v2);
  const factState = record(analysisResponse?.consultation_state?.fact_state);
  const factRecords = record(factState.facts);
  const conflicts = Array.isArray(factState.conflicts)
    ? factState.conflicts.filter((item) => item && typeof item === "object")
    : [];
  const facts = CASE_READY_FACTS.map(([field, label]) => {
    const fact = record(factRecords[field]);
    return {
      field,
      label,
      value: fact.value,
      confirmed: fact.confirmed === true,
    };
  });
  const readyAttachmentIds = (Array.isArray(registeredAttachments) ? registeredAttachments : [])
    .filter((item) => (
      item
      && typeof item === "object"
      && item.status === "ready"
      && nonEmpty(item.attachment_id)
    ))
    .map((item) => String(item.attachment_id).trim());
  const restoredReadyAttachmentIds = (
    Array.isArray(analysisResponse?.attachments) ? analysisResponse.attachments : []
  )
    .filter((item) => (
      item
      && typeof item === "object"
      && item.scan_status === "clean"
      && nonEmpty(item.attachment_id)
    ))
    .map((item) => String(item.attachment_id).trim());
  const trafficAccidentOcr = record(
    analysisResponse?.structured_results?.traffic_accident_confirmation_ocr,
  );
  const ocrEvidenceIds =
    trafficAccidentOcr.document_check?.is_target_document === true
      && Array.isArray(trafficAccidentOcr.ocr_evidence)
      ? trafficAccidentOcr.ocr_evidence
        .map((item) => text(item?.attachment_id))
        .filter(Boolean)
      : [];
  const sources = [
    ...new Set([
      ...readyAttachmentIds,
      ...restoredReadyAttachmentIds,
      ...ocrEvidenceIds,
    ]),
  ]
    .map((attachmentId) => ({
      source_type: "official_document",
      source_ref: attachmentId,
    }));
  const eligible = Boolean(
    analysisResponse?.status === "case_ready"
      && consultationState?.risk_gate?.level !== "high_risk"
      && conflicts.length === 0
      && facts.every((fact) => fact.confirmed && nonEmpty(fact.value))
      && sources.length > 0,
  );

  return {
    eligible,
    facts,
    casePayload: {
      session_id: nonEmpty(analysisResponse?.session_id)
        ? String(analysisResponse.session_id).trim()
        : "",
      title: "교통사고 과실 상담",
      case_type: "accident_fault",
      consultation_state: consultationState,
      location: {},
    },
    confirmationPayload: {
      facts: Object.fromEntries(facts.map((fact) => [fact.field, fact.value])),
      sources,
      conflicts,
      user_edit_history: [],
    },
  };
}


export async function runCaseReadyWorkflow({
  api,
  identity,
  model,
  onStep = () => {},
}) {
  if (!model?.eligible) {
    throw new Error("case_ready_required");
  }

  onStep("creating_case");
  const created = await api.createConsultationCase(model.casePayload, identity);
  const caseId = text(created?.case?.case_id);
  if (!caseId) {
    throw new Error("case_id_missing");
  }

  onStep("confirming_facts");
  const confirmed = await api.confirmConsultationCaseFacts({
    caseId,
    payload: model.confirmationPayload,
    identity,
  });
  const factVersionId = text(confirmed?.fact_version?.fact_version_id);
  if (!factVersionId) {
    throw new Error("fact_version_id_missing");
  }

  onStep("starting_analysis");
  const startResponse = await api.startConsultationCaseAnalysis({
    caseId,
    payload: { fact_version_id: factVersionId },
    identity,
  });
  const jobId = text(startResponse?.job?.job_id);
  if (!jobId) {
    throw new Error("analysis_job_id_missing");
  }

  return {
    caseId,
    factVersionId,
    jobId,
    workItemId: text(startResponse?.work_item?.work_item_id),
    startResponse,
  };
}


export function initialCaseAnalysisResult(startResponse = {}) {
  const jobId = text(startResponse?.job?.job_id);
  const status = text(startResponse?.job?.status) || "queued";
  return {
    status,
    analysis_progress: {
      contract_version: "analysis_progress.v1",
      semantic_status: status,
      terminal: false,
      retryable: true,
      next_action: "continue_polling",
      job_id: jobId,
      correlation_id: text(startResponse?.work_item?.work_item_id) || null,
    },
  };
}


export async function pollCaseReadyReport({
  api,
  identity,
  sessionId,
  startResponse,
  wait,
  maxAttempts,
  onUpdate = () => {},
  onStep = () => {},
}) {
  const jobId = text(startResponse?.job?.job_id);
  const workerResult = await pollWorkerResult({
    initialResult: initialCaseAnalysisResult(startResponse),
    loadResult: () => api.getAnalysisResult({ jobId, identity }),
    wait,
    maxAttempts,
    onDiagnostic: () => {},
    onUpdate,
  });
  const reportId = text(
    (Array.isArray(workerResult?.report_links) ? workerResult.report_links : [])
      .find((link) => text(link?.report_id))
      ?.report_id,
  );
  if (!reportId) {
    return { workerResult, report: null };
  }

  onStep("loading_report");
  const detail = await api.getReportDetail({
    reportId,
    sessionId,
    identity,
  });
  const report = record(detail?.report);
  if (!text(report.report_id) || !record(report.content).reporting_payload) {
    return { workerResult, report: null };
  }
  return { workerResult, report };
}


function record(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}


function text(value) {
  return typeof value === "string" ? value.trim() : "";
}


function nonEmpty(value) {
  return typeof value === "string"
    ? Boolean(value.trim())
    : value !== undefined && value !== null;
}
