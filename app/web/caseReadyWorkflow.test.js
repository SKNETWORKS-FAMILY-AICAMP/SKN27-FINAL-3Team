import assert from "node:assert/strict";
import test from "node:test";
import * as caseReadyWorkflowModule from "./caseReadyWorkflow.js";

import {
  buildCaseReadyActionUi,
  buildCaseReadyViewModel,
  pollCaseReadyReport,
  runCaseReadyWorkflow,
} from "./caseReadyWorkflow.js";


function completeResponse() {
  return {
    status: "case_ready",
    session_id: "ses_case_ready",
    consultation_state: {
      v2: {
        schema_version: "consultation_state.v2",
        risk_gate: { level: "standard" },
        next_action: "confirm_facts",
      },
      fact_state: {
        facts: {
          road_layout: { value: "four_way_intersection", confirmed: true },
          vehicle_actions: { value: "ego_straight_other_left_turn", confirmed: true },
          signal_priority: { value: "ego_green", confirmed: true },
          collision_location: { value: "front_left", confirmed: true },
        },
        conflicts: [],
      },
    },
  };
}


function eligibleModel() {
  return buildCaseReadyViewModel(completeResponse(), [
    { attachment_id: "att_case_ready", status: "ready", scan_status: "clean" },
  ]);
}


test("requires material evidence before offering case analysis", () => {
  const withoutEvidence = buildCaseReadyViewModel(completeResponse());
  const scanningEvidence = buildCaseReadyViewModel(completeResponse(), [
    { attachment_id: "att_scanning", status: "scanning", scan_status: "scanning" },
  ]);

  assert.equal(withoutEvidence.eligible, false);
  assert.deepEqual(withoutEvidence.confirmationPayload.sources, []);
  assert.equal(scanningEvidence.eligible, false);
});


test("accepts a restored clean attachment without a new attachment API call", () => {
  const response = completeResponse();
  response.attachments = [
    {
      attachment_id: "att_restored_clean",
      purpose: "traffic_accident_confirmation",
      scan_status: "clean",
    },
  ];

  const model = buildCaseReadyViewModel(response, []);

  assert.equal(model.eligible, true);
  assert.deepEqual(model.confirmationPayload.sources, [
    { source_type: "official_document", source_ref: "att_restored_clean" },
  ]);
});


test("maps fact readiness rejection to fixed safe public copy", () => {
  assert.equal(typeof caseReadyWorkflowModule.caseReadyWorkflowErrorMessage, "function");
  assert.equal(
    caseReadyWorkflowModule.caseReadyWorkflowErrorMessage({
      code: "fact_readiness_not_met",
    }),
    "첨부 자료의 안전 검사를 완료한 뒤 사건 분석을 다시 시도해 주세요.",
  );
  assert.equal(
    caseReadyWorkflowModule.caseReadyWorkflowErrorMessage(
      new Error("private backend detail"),
    ),
    "사건 분석 리포트를 완료하지 못했습니다. 입력과 자료 상태를 확인해 주세요.",
  );
});


test("builds existing Case API payloads from four confirmed facts", () => {
  const model = buildCaseReadyViewModel(completeResponse(), [
    { attachment_id: "att_accident_confirmation", status: "ready" },
    { attachment_id: "att_not_ready", status: "scanning" },
  ]);

  assert.equal(model.eligible, true);
  assert.equal(model.casePayload.session_id, "ses_case_ready");
  assert.equal(model.casePayload.case_type, "accident_fault");
  assert.deepEqual(model.confirmationPayload.facts, {
    road_layout: "four_way_intersection",
    vehicle_actions: "ego_straight_other_left_turn",
    signal_priority: "ego_green",
    collision_location: "front_left",
  });
  assert.deepEqual(model.confirmationPayload.sources, [
    {
      source_type: "official_document",
      source_ref: "att_accident_confirmation",
    },
  ]);
});


test("uses only target-document OCR evidence when upload state is still stale", () => {
  const targetResponse = completeResponse();
  targetResponse.public_results = {
    contract_version: "public_agent_results.v1",
    traffic_accident_confirmation_ocr: {
      document_check: { is_target_document: true },
      ocr_evidence: [
        {
          attachment_id: "att_scanned_confirmation",
          storage_uri: "s3://must-not-enter-case-payload/private.png",
        },
      ],
    },
  };
  const targetModel = buildCaseReadyViewModel(targetResponse, [
    {
      attachment_id: "att_scanned_confirmation",
      status: "uploaded",
      scan_status: "not_started",
    },
  ]);

  assert.deepEqual(targetModel.confirmationPayload.sources, [
    {
      source_type: "official_document",
      source_ref: "att_scanned_confirmation",
    },
  ]);
  assert.equal(
    JSON.stringify(targetModel.confirmationPayload).includes("storage_uri"),
    false,
  );

  const nonTargetResponse = completeResponse();
  nonTargetResponse.public_results = {
    contract_version: "public_agent_results.v1",
    traffic_accident_confirmation_ocr: {
      document_check: { is_target_document: false },
      ocr_evidence: [{ attachment_id: "att_wrong_document" }],
    },
  };

  assert.deepEqual(
    buildCaseReadyViewModel(nonTargetResponse).confirmationPayload.sources,
    [],
  );
});


for (const [name, mutate] of [
  ["non-case-ready response", (value) => {
    value.status = "needs_input";
  }],
  ["unconfirmed fact", (value) => {
    value.consultation_state.fact_state.facts.road_layout.confirmed = false;
  }],
  ["fact conflict", (value) => {
    value.consultation_state.fact_state.conflicts = [{ field: "road_layout" }];
  }],
  ["high-risk state", (value) => {
    value.consultation_state.v2.risk_gate.level = "high_risk";
  }],
]) {
  test(`does not offer case creation for a ${name}`, () => {
    const response = completeResponse();
    mutate(response);

    const model = buildCaseReadyViewModel(response);

    assert.equal(model.eligible, false);
  });
}


test("runs case creation, fact confirmation, and analysis start in order", async () => {
  const calls = [];
  const identity = { authToken: "token" };
  const api = {
    createConsultationCase: async (payload, requestIdentity) => {
      calls.push({ operation: "create", payload, requestIdentity });
      return {
        contract_version: "consultation_case.v2",
        case: { case_id: "case_1" },
      };
    },
    confirmConsultationCaseFacts: async (request) => {
      calls.push({ operation: "confirm", request });
      return {
        contract_version: "confirmed_facts.v1",
        fact_version: { fact_version_id: "fact_1" },
      };
    },
    startConsultationCaseAnalysis: async (request) => {
      calls.push({ operation: "start", request });
      return {
        contract_version: "case_analysis_job.v2",
        job: { job_id: "job_1", status: "queued" },
        work_item: { work_item_id: "work_1", status: "queued" },
        analysis_plan: {
          plan_id: "plan_1",
          node_codes: [
            "text_ml_case_search",
            "law_ground_search",
            "objection_report_generation",
          ],
        },
      };
    },
  };
  const steps = [];
  const model = eligibleModel();

  const result = await runCaseReadyWorkflow({
    api,
    identity,
    model,
    onStep: (step) => steps.push(step),
  });

  assert.deepEqual(calls.map((call) => call.operation), [
    "create",
    "confirm",
    "start",
  ]);
  assert.equal(calls[0].payload.session_id, "ses_case_ready");
  assert.equal(calls[0].requestIdentity, identity);
  assert.equal(calls[1].request.caseId, "case_1");
  assert.equal(calls[1].request.identity, identity);
  assert.deepEqual(calls[2].request.payload, { fact_version_id: "fact_1" });
  assert.deepEqual(steps, [
    "creating_case",
    "confirming_facts",
    "starting_analysis",
  ]);
  assert.deepEqual(
    {
      caseId: result.caseId,
      factVersionId: result.factVersionId,
      jobId: result.jobId,
      workItemId: result.workItemId,
    },
    {
      caseId: "case_1",
      factVersionId: "fact_1",
      jobId: "job_1",
      workItemId: "work_1",
    },
  );
});


test("does not call later Case APIs after case creation fails", async () => {
  const calls = [];
  const api = {
    createConsultationCase: async () => {
      calls.push("create");
      throw new Error("create_failed");
    },
    confirmConsultationCaseFacts: async () => {
      calls.push("confirm");
    },
    startConsultationCaseAnalysis: async () => {
      calls.push("start");
    },
  };

  await assert.rejects(
    runCaseReadyWorkflow({
      api,
      identity: {},
      model: eligibleModel(),
    }),
    /create_failed/,
  );
  assert.deepEqual(calls, ["create"]);
});


test("does not start analysis after fact confirmation fails", async () => {
  const calls = [];
  const api = {
    createConsultationCase: async () => {
      calls.push("create");
      return { case: { case_id: "case_1" } };
    },
    confirmConsultationCaseFacts: async () => {
      calls.push("confirm");
      throw new Error("confirm_failed");
    },
    startConsultationCaseAnalysis: async () => {
      calls.push("start");
    },
  };

  await assert.rejects(
    runCaseReadyWorkflow({
      api,
      identity: {},
      model: eligibleModel(),
    }),
    /confirm_failed/,
  );
  assert.deepEqual(calls, ["create", "confirm"]);
});


test("rejects an ineligible response before calling a Case API", async () => {
  let calls = 0;
  const api = {
    createConsultationCase: async () => {
      calls += 1;
    },
  };

  await assert.rejects(
    runCaseReadyWorkflow({
      api,
      identity: {},
      model: buildCaseReadyViewModel({ status: "needs_input" }),
    }),
    /case_ready_required/,
  );
  assert.equal(calls, 0);
});


function queuedStartResponse() {
  return {
    contract_version: "case_analysis_job.v2",
    job: { job_id: "job_1", status: "queued" },
    work_item: { work_item_id: "work_1", status: "queued" },
    analysis_plan: {
      plan_id: "plan_1",
      node_codes: [
        "text_ml_case_search",
        "law_ground_search",
        "objection_report_generation",
      ],
    },
  };
}


test("hydrates a persisted report after case analysis succeeds", async () => {
  const api = {
    getAnalysisResult: async () => ({
      result: {
        status: "success",
        analysis_progress: {
          contract_version: "analysis_progress.v1",
          semantic_status: "success",
          terminal: true,
          retryable: false,
          next_action: "review_result",
          job_id: "job_1",
          correlation_id: "work_1",
        },
        report_links: [{ report_id: "rep_1" }],
      },
    }),
    getReportDetail: async () => ({
      report: {
        report_id: "rep_1",
        session_id: "ses_case_ready",
        status: "ready",
        content: {
          reporting_payload: {
            report_type: "fault_ratio_analysis",
          },
        },
      },
    }),
  };
  const updates = [];
  const steps = [];

  const result = await pollCaseReadyReport({
    api,
    identity: { authToken: "token" },
    sessionId: "ses_case_ready",
    startResponse: queuedStartResponse(),
    wait: async () => {},
    maxAttempts: 2,
    onUpdate: (value) => updates.push(value.status),
    onStep: (step) => steps.push(step),
  });

  assert.equal(result.workerResult.status, "success");
  assert.equal(result.report.report_id, "rep_1");
  assert.equal(
    result.report.content.reporting_payload.report_type,
    "fault_ratio_analysis",
  );
  assert.deepEqual(updates, ["queued", "success"]);
  assert.deepEqual(steps, ["loading_report"]);
});


test("does not accept an in-session reporting payload as a persisted report", async () => {
  let detailCalls = 0;
  const api = {
    getAnalysisResult: async () => ({
      result: {
        status: "success",
        analysis_progress: {
          contract_version: "analysis_progress.v1",
          semantic_status: "success",
          terminal: true,
          retryable: false,
          next_action: "review_result",
          job_id: "job_1",
          correlation_id: "work_1",
        },
        reporting_payload: { report_type: "fault_ratio_analysis" },
        report_links: [],
      },
    }),
    getReportDetail: async () => {
      detailCalls += 1;
      return {};
    },
  };

  const result = await pollCaseReadyReport({
    api,
    identity: {},
    sessionId: "ses_case_ready",
    startResponse: queuedStartResponse(),
    wait: async () => {},
    maxAttempts: 1,
  });

  assert.equal(result.report, null);
  assert.equal(detailCalls, 0);
});


test("rejects report detail without a server reporting payload", async () => {
  const api = {
    getAnalysisResult: async () => ({
      result: {
        status: "success",
        analysis_progress: {
          contract_version: "analysis_progress.v1",
          semantic_status: "success",
          terminal: true,
          retryable: false,
          next_action: "review_result",
          job_id: "job_1",
          correlation_id: "work_1",
        },
        report_links: [{ report_id: "rep_1" }],
      },
    }),
    getReportDetail: async () => ({
      report: {
        report_id: "rep_1",
        session_id: "ses_case_ready",
        status: "ready",
        content: {},
      },
    }),
  };

  const result = await pollCaseReadyReport({
    api,
    identity: {},
    sessionId: "ses_case_ready",
    startResponse: queuedStartResponse(),
    wait: async () => {},
    maxAttempts: 1,
  });

  assert.equal(result.report, null);
});


test("offers one explicit case start action for an eligible idle consultation", () => {
  const model = eligibleModel();

  const guestUi = buildCaseReadyActionUi({
    model,
    progress: { step: "idle", error: "" },
    authenticated: false,
  });
  const authenticatedUi = buildCaseReadyActionUi({
    model,
    progress: { step: "idle", error: "" },
    authenticated: true,
  });

  assert.equal(guestUi.visible, true);
  assert.equal(guestUi.buttonLabel, "로그인 후 사건 생성·분석 시작");
  assert.equal(guestUi.disabled, false);
  assert.equal(guestUi.facts.length, 4);
  assert.equal(authenticatedUi.buttonLabel, "사건 생성·분석 시작");
});


test("disables case start while a server workflow stage is active", () => {
  const model = eligibleModel();

  for (const step of [
    "creating_case",
    "confirming_facts",
    "starting_analysis",
    "polling",
    "loading_report",
    "ready",
  ]) {
    const ui = buildCaseReadyActionUi({
      model,
      progress: { step, error: "" },
      authenticated: true,
    });

    assert.equal(ui.disabled, true, step);
    assert.ok(ui.progressMessage, step);
  }
});


test("hides case start for an ineligible consultation and permits a failed retry", () => {
  const hidden = buildCaseReadyActionUi({
    model: buildCaseReadyViewModel({ status: "needs_input" }),
    progress: { step: "idle", error: "" },
    authenticated: false,
  });
  const retry = buildCaseReadyActionUi({
    model: eligibleModel(),
    progress: { step: "failed", error: "다시 시도해 주세요." },
    authenticated: true,
  });

  assert.equal(hidden.visible, false);
  assert.equal(retry.visible, true);
  assert.equal(retry.disabled, false);
  assert.equal(retry.error, "다시 시도해 주세요.");
});
