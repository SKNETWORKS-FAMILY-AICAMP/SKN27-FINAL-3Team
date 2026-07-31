import assert from "node:assert/strict";
import test from "node:test";

import { buildAnalysisProgressUi } from "./analysisProgressUi.js";


const STATUS_CASES = [
  ["queued", "대기", "neutral"],
  ["running", "분석 중", "active"],
  ["partial", "일부 결과", "attention"],
  ["failed", "완료하지 못함", "danger"],
  ["needs_input", "확인 필요", "attention"],
  ["success", "분석 완료", "complete"],
];


test("maps all semantic statuses to distinct safe presentation", () => {
  const presentations = STATUS_CASES.map(([semanticStatus, label, tone]) => {
    const ui = buildAnalysisProgressUi({
      contract_version: "analysis_progress.v1",
      semantic_status: semanticStatus,
      terminal: !["queued", "running"].includes(semanticStatus),
      retryable: ["queued", "running"].includes(semanticStatus),
      next_action: semanticStatus === "success" ? "review_result" : "continue_polling",
      user_message: "server supplied text must not bypass the safe copy map",
      job_id: "job_semantic",
      correlation_id: "awork_job_semantic",
    });

    assert.equal(ui.label, label);
    assert.equal(ui.tone, tone);
    assert.equal(ui.semanticStatus, semanticStatus);
    assert.equal(ui.message.includes("server supplied"), false);
    return `${ui.label}:${ui.message}`;
  });

  assert.equal(new Set(presentations).size, STATUS_CASES.length);
});


test("keeps only the public progress UI contract", () => {
  const ui = buildAnalysisProgressUi({
    contract_version: "analysis_progress.v1",
    semantic_status: "running",
    terminal: false,
    retryable: true,
    next_action: "continue_polling",
    user_message: "ignored",
    job_id: "job_public",
    correlation_id: "awork_job_public",
    worker_payload: { authorization: "must-not-leak" },
  });

  assert.deepEqual(ui, {
    semanticStatus: "running",
    terminal: false,
    retryable: true,
    nextAction: "continue_polling",
    message: "분석이 진행 중입니다. 확인된 결과는 완료되는 대로 표시됩니다.",
    label: "분석 중",
    tone: "active",
    jobId: "job_public",
    correlationId: "awork_job_public",
  });
  assert.equal(JSON.stringify(ui).includes("authorization"), false);
});


test("fails closed for unknown contracts and malformed identifiers", () => {
  assert.equal(
    buildAnalysisProgressUi({
      contract_version: "analysis_progress.v0",
      semantic_status: "running",
    }),
    null
  );
  assert.equal(
    buildAnalysisProgressUi({
      contract_version: "analysis_progress.v1",
      semantic_status: "invented",
    }),
    null
  );

  const ui = buildAnalysisProgressUi({
    contract_version: "analysis_progress.v1",
    semantic_status: "failed",
    terminal: true,
    retryable: false,
    next_action: "review_failure_guidance",
    job_id: "https://private.example/job",
    correlation_id: "C:\\private\\work",
  });
  assert.equal(ui.jobId, null);
  assert.equal(ui.correlationId, null);
  assert.equal(ui.message.includes("private"), false);
});
