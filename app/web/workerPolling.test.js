import assert from "node:assert/strict";
import test from "node:test";

import { pollWorkerResult } from "./workerPolling.js";


function result(semanticStatus, extra = {}) {
  return {
    status: semanticStatus,
    analysis_progress: {
      contract_version: "analysis_progress.v1",
      semantic_status: semanticStatus,
      terminal: !["queued", "running"].includes(semanticStatus),
      retryable: ["queued", "running"].includes(semanticStatus),
      next_action: ["queued", "running"].includes(semanticStatus)
        ? "continue_polling"
        : "review_result",
      job_id: "job_polling",
      correlation_id: "awork_job_polling",
    },
    ...extra,
  };
}


test("polls queued and running states until semantic success", async () => {
  const responses = [
    { result: result("running", { progress_marker: "running" }) },
    { result: result("success", { assistant_message: { answer: "완료" } }) },
  ];
  let waits = 0;
  const updates = [];

  const finalResult = await pollWorkerResult({
    initialResult: result("queued"),
    loadResult: async () => responses.shift(),
    wait: async () => {
      waits += 1;
    },
    maxAttempts: 3,
    onDiagnostic: () => {},
    onUpdate: (value) => {
      updates.push(value.analysis_progress.semantic_status);
    },
  });

  assert.equal(finalResult.analysis_progress.semantic_status, "success");
  assert.equal(finalResult.assistant_message.answer, "완료");
  assert.equal(waits, 1);
  assert.deepEqual(updates, ["queued", "running", "success"]);
});


for (const semanticStatus of ["needs_input", "partial", "failed"]) {
  test(`stops polling immediately on ${semanticStatus}`, async () => {
    let calls = 0;
    const finalResult = await pollWorkerResult({
      initialResult: result(semanticStatus),
      loadResult: async () => {
        calls += 1;
        return { result: result("success") };
      },
      wait: async () => {},
      maxAttempts: 3,
      onDiagnostic: () => {},
    });

    assert.equal(finalResult.analysis_progress.semantic_status, semanticStatus);
    assert.equal(calls, 0);
  });
}


test("poll budget exhaustion preserves the last running result", async () => {
  const diagnostics = [];
  const updates = [];
  let calls = 0;
  const finalResult = await pollWorkerResult({
    initialResult: result("queued", { accepted_marker: "keep" }),
    loadResult: async () => {
      calls += 1;
      return {
        result: result("running", {
          latest_marker: `attempt-${calls}`,
        }),
      };
    },
    wait: async () => {},
    maxAttempts: 2,
    onDiagnostic: (event) => diagnostics.push(event),
    onUpdate: (value) => updates.push(value),
  });

  assert.equal(calls, 2);
  assert.equal(finalResult.latest_marker, "attempt-2");
  assert.equal(finalResult.analysis_progress.semantic_status, "running");
  assert.deepEqual(finalResult.polling_notice, {
    contract_version: "worker_polling_notice.v1",
    status: "delayed",
    retryable: true,
    polling_exhausted: true,
    polling_interrupted: false,
    next_action: "check_status",
    job_id: "job_polling",
    correlation_id: "awork_job_polling",
    message: "분석 상태 확인이 지연되고 있습니다. 잠시 후 다시 확인할 수 있습니다.",
  });
  assert.equal(JSON.stringify(finalResult).includes("상담 내용을 접수했습니다"), false);
  assert.deepEqual(diagnostics.at(-1), {
    event: "polling_exhausted",
    semanticStatus: "running",
    jobId: "job_polling",
    correlationId: "awork_job_polling",
  });
  assert.equal(updates.at(-1).polling_notice.status, "delayed");
});


test("transport interruption preserves the latest result without raw error", async () => {
  const diagnostics = [];
  const updates = [];
  const finalResult = await pollWorkerResult({
    initialResult: result("running", { retained: "yes" }),
    loadResult: async () => {
      throw new Error("Authorization bearer-secret private transport detail");
    },
    wait: async () => {},
    maxAttempts: 2,
    onDiagnostic: (event) => diagnostics.push(event),
    onUpdate: (value) => updates.push(value),
  });

  assert.equal(finalResult.retained, "yes");
  assert.equal(finalResult.analysis_progress.semantic_status, "running");
  assert.deepEqual(finalResult.polling_notice, {
    contract_version: "worker_polling_notice.v1",
    status: "interrupted",
    retryable: true,
    polling_exhausted: false,
    polling_interrupted: true,
    message: "분석 상태를 일시적으로 확인하지 못했습니다. 잠시 후 다시 확인해 주세요.",
  });
  assert.equal(JSON.stringify(finalResult).includes("bearer-secret"), false);
  assert.deepEqual(diagnostics, [
    {
      event: "polling_interrupted",
      semanticStatus: "running",
      jobId: "job_polling",
      correlationId: "awork_job_polling",
    },
  ]);
  assert.equal(updates.at(-1).polling_notice.status, "interrupted");
});
