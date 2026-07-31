import test from "node:test";
import assert from "node:assert/strict";

import {
  ATTACHMENT_WORKFLOW_COPY,
  buildAttachmentWorkflowUi,
} from "./attachmentWorkflowUi.js";

const EXPECTED_STATES = [
  "scan_running",
  "classification_running",
  "classified_waiting_confirmation",
  "ocr_running",
  "ocr_needs_confirmation",
  "analysis_ready",
  "partial",
  "failed",
];

test("maps every server workflow state to explicit user-facing copy", () => {
  assert.deepEqual(Object.keys(ATTACHMENT_WORKFLOW_COPY), EXPECTED_STATES);

  const ui = buildAttachmentWorkflowUi(
    EXPECTED_STATES.map((state) => ({
      contract_version: "attachment_workflow.v1",
      attachment_id: `att_${state}`,
      state,
      next_action: `action_${state}`,
      retryable: state === "partial" || state === "failed",
      missing_fields: [],
      limitations: [],
    }))
  );

  assert.equal(ui.length, EXPECTED_STATES.length);
  assert.equal(new Set(ui.map((item) => item.title)).size, EXPECTED_STATES.length);
  for (const item of ui) {
    assert.ok(item.title);
    assert.ok(item.description);
    assert.ok(item.tone);
    if (item.state !== "analysis_ready") {
      assert.notEqual(item.tone, "success");
      assert.doesNotMatch(item.description, /완료|성공/);
    }
  }
});

test("renders OCR confirmation without copying private server fields", () => {
  const [item] = buildAttachmentWorkflowUi([
    {
      contract_version: "attachment_workflow.v1",
      attachment_id: "att_notice",
      state: "ocr_needs_confirmation",
      next_action: "confirm_ocr_fields",
      retryable: false,
      missing_fields: ["response_deadline"],
      limitations: [],
      storage_uri: "s3://private/notices/att_notice",
      raw_ocr_text: "private OCR text",
      filename: "private-notice.pdf",
    },
  ]);

  assert.deepEqual(Object.keys(item), [
    "attachmentId",
    "state",
    "tone",
    "title",
    "description",
    "action",
    "retryable",
    "missingFields",
    "limitations",
  ]);
  assert.equal(item.state, "ocr_needs_confirmation");
  assert.equal(item.action, "confirm_ocr_fields");
  assert.match(item.title, /OCR/);
  assert.doesNotMatch(item.description, /완료|성공/);
  assert.doesNotMatch(JSON.stringify(item), /s3:\/\/|private OCR|private-notice/);
});

test("retains safe limitations and next action for partial and failed states", () => {
  const ui = buildAttachmentWorkflowUi([
    {
      contract_version: "attachment_workflow.v1",
      attachment_id: "att_partial",
      state: "partial",
      next_action: "provide_missing_information",
      retryable: true,
      missing_fields: ["issuing_authority"],
      limitations: ["일부 고지서 정보를 추가로 확인해야 합니다."],
    },
    {
      contract_version: "attachment_workflow.v1",
      attachment_id: "att_failed",
      state: "failed",
      next_action: "reattach_file",
      retryable: true,
      missing_fields: [],
      limitations: ["현재 파일은 안전한 분석 대상으로 사용할 수 없습니다."],
    },
  ]);

  assert.equal(ui[0].action, "provide_missing_information");
  assert.deepEqual(ui[0].limitations, [
    "일부 고지서 정보를 추가로 확인해야 합니다.",
  ]);
  assert.equal(ui[1].action, "reattach_file");
  assert.deepEqual(ui[1].limitations, [
    "현재 파일은 안전한 분석 대상으로 사용할 수 없습니다.",
  ]);
});

test("drops unknown versions and states instead of inventing success", () => {
  assert.deepEqual(
    buildAttachmentWorkflowUi([
      {
        contract_version: "attachment_workflow.v0",
        attachment_id: "att_old",
        state: "analysis_ready",
      },
      {
        contract_version: "attachment_workflow.v1",
        attachment_id: "att_unknown",
        state: "mystery",
      },
    ]),
    []
  );
});
