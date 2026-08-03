import assert from "node:assert/strict";
import test from "node:test";

import { runAttachmentScanWorkflow } from "./attachmentScanWorkflow.js";


test("polls the server-owned scan state before starting attachment analysis", async () => {
  const calls = [];
  const scanStates = [
    {
      attachment_id: "att_notice",
      purpose: "fine_notice",
      status: "scanning",
      scan_status: "scanning",
    },
    {
      attachment_id: "att_notice",
      purpose: "fine_notice",
      status: "ready",
      scan_status: "clean",
    },
  ];
  const identity = { authToken: "token" };
  const updates = [];
  const waits = [];
  const analysisCalls = [];

  const result = await runAttachmentScanWorkflow({
    api: {
      getAttachment: async (request) => {
        calls.push(request);
        return { attachment: scanStates.shift() };
      },
    },
    attachment: {
      attachment_id: "att_notice",
      purpose: "fine_notice",
      status: "uploaded",
      scan_status: "not_started",
    },
    sessionId: "ses_notice",
    identity,
    wait: async () => waits.push("wait"),
    maxAttempts: 3,
    onUpdate: (attachment) => updates.push(attachment.scan_status),
    startAnalysis: async (request) => {
      analysisCalls.push(request);
      return { status: "queued" };
    },
  });

  assert.deepEqual(calls, [
    { attachmentId: "att_notice", sessionId: "ses_notice", identity },
    { attachmentId: "att_notice", sessionId: "ses_notice", identity },
  ]);
  assert.deepEqual(updates, ["not_started", "scanning", "clean"]);
  assert.deepEqual(waits, ["wait"]);
  assert.deepEqual(analysisCalls, [
    {
      attachment: {
        attachment_id: "att_notice",
        purpose: "fine_notice",
        status: "ready",
        scan_status: "clean",
      },
      userText: "첨부한 자료를 확인해 주세요.",
    },
  ]);
  assert.equal(result.attachment.scan_status, "clean");
  assert.deepEqual(result.analysis, { status: "queued" });
});


test("does not start attachment analysis after scan rejection", async () => {
  let analysisCalls = 0;

  await assert.rejects(
    runAttachmentScanWorkflow({
      api: {
        getAttachment: async () => ({
          attachment: {
            attachment_id: "att_rejected",
            status: "rejected",
            scan_status: "rejected",
          },
        }),
      },
      attachment: {
        attachment_id: "att_rejected",
        status: "uploaded",
        scan_status: "not_started",
      },
      sessionId: "ses_rejected",
      identity: {},
      wait: async () => {},
      maxAttempts: 1,
      startAnalysis: async () => {
        analysisCalls += 1;
      },
    }),
    /attachment_scan_rejected/,
  );

  assert.equal(analysisCalls, 0);
});


test("does not start attachment analysis when scan polling is exhausted", async () => {
  let analysisCalls = 0;

  await assert.rejects(
    runAttachmentScanWorkflow({
      api: {
        getAttachment: async () => ({
          attachment: {
            attachment_id: "att_delayed",
            status: "uploaded",
            scan_status: "not_started",
          },
        }),
      },
      attachment: {
        attachment_id: "att_delayed",
        status: "uploaded",
        scan_status: "not_started",
      },
      sessionId: "ses_delayed",
      identity: {},
      wait: async () => {},
      maxAttempts: 2,
      startAnalysis: async () => {
        analysisCalls += 1;
      },
    }),
    /attachment_scan_timeout/,
  );

  assert.equal(analysisCalls, 0);
});
