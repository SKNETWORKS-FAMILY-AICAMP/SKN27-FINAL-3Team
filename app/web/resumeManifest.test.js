import test from "node:test";
import assert from "node:assert/strict";

import { hydrateResumeManifest } from "./resumeManifest.js";

test("hydrates the latest owned consultation into safe UI state", () => {
  const hydrated = hydrateResumeManifest({
    contract_version: "resume_manifest.v1",
    has_resume: true,
    session: { session_id: "ses_resume", status: "active" },
    conversation_messages: [
      { message_id: "msg_user", role: "user", content: "서울시에서 받았어요" },
      { message_id: "msg_assistant", role: "assistant", content: "기한을 알려주세요" },
    ],
    pending_questions: [{ field: "response_deadline", question: "기한은 언제인가요?" }],
    facts: { issuing_authority: "서울시" },
    fine_notice_intake: {
      contract_version: "fine_notice_intake.v1",
      slots: { response_deadline: "2026-08-12" },
    },
    attachments: [
      {
        attachment_id: "att_notice",
        purpose: "fine_notice",
        filename: "notice.pdf",
        status: "ready",
        scan_status: "clean",
        storage_uri: "s3://private-bucket/notice.pdf",
      },
    ],
    latest_analysis: {
      job_id: "job_resume",
      session_id: "ses_resume",
      status: "partial",
      assistant_message: "기한을 알려주세요",
      attachment_processing: {
        contract_version: "attachment_processing.v1",
        classification: { status: "completed" },
      },
      raw_ocr_text: "private OCR",
    },
    reports: [
      {
        report_id: "rep_resume",
        report_type: "fine_notice_analysis",
        status: "ready",
        title: "과태료 분석",
      },
    ],
  });

  assert.equal(hydrated.hasResume, true);
  assert.equal(hydrated.sessionId, "ses_resume");
  assert.deepEqual(hydrated.chatMessages.map(({ role, content }) => ({ role, content })), [
    { role: "user", content: "서울시에서 받았어요" },
    { role: "assistant", content: "기한을 알려주세요" },
  ]);
  assert.equal(hydrated.chatMessages[1].pending_questions[0].field, "response_deadline");
  assert.equal(hydrated.consultationIntake.consultationType, "fine_notice");
  assert.equal(hydrated.consultationIntake.issuingAuthority, "서울시");
  assert.equal(hydrated.consultationIntake.responseDeadline, "2026-08-12");
  assert.equal(hydrated.registeredAttachments[0].filename, "notice.pdf");
  assert.equal(hydrated.analysisResponse.job_id, "job_resume");
  assert.equal(hydrated.analysisResponse.attachment_processing.classification.status, "completed");
  assert.equal(hydrated.currentReport.report_id, "rep_resume");
  assert.equal(hydrated.reportList.length, 1);
  assert.doesNotMatch(JSON.stringify(hydrated), /s3:\/\/|private OCR|raw_ocr_text|storage_uri/);
});

test("returns an empty state for an absent or invalid resume manifest", () => {
  for (const manifest of [null, {}, { contract_version: "other.v1", has_resume: true }]) {
    const hydrated = hydrateResumeManifest(manifest);
    assert.equal(hydrated.hasResume, false);
    assert.equal(hydrated.sessionId, "");
    assert.deepEqual(hydrated.chatMessages, []);
    assert.equal(hydrated.analysisResponse, null);
    assert.equal(hydrated.currentReport, null);
  }
});
