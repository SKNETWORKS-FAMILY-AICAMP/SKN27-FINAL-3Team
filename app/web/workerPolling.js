import { buildAnalysisProgressUi } from "./analysisProgressUi.js";


const EXHAUSTED_NOTICE = {
  contract_version: "worker_polling_notice.v1",
  status: "delayed",
  retryable: true,
  polling_exhausted: true,
  polling_interrupted: false,
  message: "분석 상태 확인이 지연되고 있습니다. 잠시 후 다시 확인할 수 있습니다.",
};

const INTERRUPTED_NOTICE = {
  contract_version: "worker_polling_notice.v1",
  status: "interrupted",
  retryable: true,
  polling_exhausted: false,
  polling_interrupted: true,
  message: "분석 상태를 일시적으로 확인하지 못했습니다. 잠시 후 다시 확인해 주세요.",
};


export async function pollWorkerResult({
  initialResult,
  loadResult,
  wait,
  maxAttempts,
  onDiagnostic = () => {},
  onUpdate = () => {},
}) {
  let latestResult = isRecord(initialResult) ? { ...initialResult } : {};
  onUpdate(latestResult);
  let progressUi = buildAnalysisProgressUi(latestResult.analysis_progress);
  if (!isPending(progressUi)) {
    return latestResult;
  }

  const attempts = Math.max(0, Number(maxAttempts) || 0);
  try {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const response = await loadResult();
      const publicResult = normalizeResult(response);
      latestResult = {
        ...latestResult,
        ...publicResult,
      };
      onUpdate(latestResult);
      progressUi = buildAnalysisProgressUi(latestResult.analysis_progress);
      onDiagnostic(diagnostic("polling_update", progressUi));
      if (!isPending(progressUi)) {
        return latestResult;
      }
      if (attempt < attempts - 1) {
        await wait();
      }
    }
  } catch {
    const currentUi = buildAnalysisProgressUi(latestResult.analysis_progress);
    onDiagnostic(diagnostic("polling_interrupted", currentUi));
    const interruptedResult = {
      ...latestResult,
      polling_notice: { ...INTERRUPTED_NOTICE },
    };
    onUpdate(interruptedResult);
    return interruptedResult;
  }

  const currentUi = buildAnalysisProgressUi(latestResult.analysis_progress);
  onDiagnostic(diagnostic("polling_exhausted", currentUi));
  const exhaustedResult = {
    ...latestResult,
    polling_notice: { ...EXHAUSTED_NOTICE },
  };
  onUpdate(exhaustedResult);
  return exhaustedResult;
}


function normalizeResult(value) {
  if (!isRecord(value)) return {};
  if (isRecord(value.result)) return value.result;
  if (isRecord(value.job)) return value.job;
  return value;
}


function diagnostic(event, progressUi) {
  return {
    event,
    semanticStatus: progressUi?.semanticStatus || null,
    jobId: progressUi?.jobId || null,
    correlationId: progressUi?.correlationId || null,
  };
}


function isPending(progressUi) {
  return ["queued", "running"].includes(progressUi?.semanticStatus);
}


function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
