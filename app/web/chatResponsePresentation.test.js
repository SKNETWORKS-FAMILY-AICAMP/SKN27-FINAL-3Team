import assert from "node:assert/strict";
import test from "node:test";

import {
  asNonEmptyText,
  normalizeChatResponsePresentation,
  selectPrimaryFollowUpQuestion,
} from "./chatResponsePresentation.js";

test("asNonEmptyText accepts only trimmed strings", () => {
  assert.equal(asNonEmptyText("  답변  "), "답변");
  assert.equal(asNonEmptyText("   "), "");
  assert.equal(asNonEmptyText({ answer: "객체 답변" }), "");
  assert.equal(asNonEmptyText(null), "");
});

test("response presentation uses the approved answer priority", () => {
  const result = normalizeChatResponsePresentation({
    status: "success",
    assistant_message: {
      core_answer: "핵심 답변",
      answer: "일반 답변",
      summary: "요약",
    },
    polling_notice: { message: "폴링 안내" },
    analysis_progress: { user_message: "진행 안내" },
  });

  assert.equal(result.answerMarkdown, "핵심 답변");
  assert.equal(result.semanticStatus, "success");
  assert.equal(result.tone, "success");
});

test("response presentation supports a legacy string assistant message", () => {
  const result = normalizeChatResponsePresentation({
    status: "success",
    assistant_message: "저장된 상담 답변",
  });

  assert.equal(result.answerMarkdown, "저장된 상담 답변");
  assert.equal(result.semanticStatus, "success");
});

test("response presentation preserves semantic state fallbacks", () => {
  const expected = {
    queued: "분석을 준비하고 있습니다.",
    running: "분석 상태를 확인하고 있습니다.",
    partial: "일부 결과만 확인되었습니다. 확인 사항을 검토한 뒤 다시 시도해 주세요.",
    failed: "분석을 완료하지 못했습니다. 입력 내용을 확인한 뒤 다시 시도해 주세요.",
    needs_input: "추가 확인이 필요합니다. 아래 질문에 답해 주세요.",
    needs_clarification: "요청을 정확히 이해하려면 내용을 조금 더 알려 주세요.",
  };

  for (const [status, answer] of Object.entries(expected)) {
    const result = normalizeChatResponsePresentation({ status });
    assert.equal(result.semanticStatus, status);
    assert.equal(result.answerMarkdown, answer);
  }
});

test("an empty successful response is demoted to a recoverable partial response", () => {
  const result = normalizeChatResponsePresentation({ status: "success" });

  assert.equal(result.semanticStatus, "partial");
  assert.equal(
    result.answerMarkdown,
    "완료된 답변을 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.",
  );
  assert.deepEqual(result.retryAction, {
    kind: "refocus-input",
    label: "입력 내용을 확인하고 다시 보내기",
  });
});

test("object-valued text never leaks object Object", () => {
  const result = normalizeChatResponsePresentation({
    status: "needs_input",
    assistant_message: {
      core_answer: { unexpected: true },
      answer: ["잘못된 값"],
      summary: null,
    },
    polling_notice: { message: { internal: true } },
  });

  assert.doesNotMatch(result.answerMarkdown, /\[object Object\]/);
  assert.equal(result.answerMarkdown, "추가 확인이 필요합니다. 아래 질문에 답해 주세요.");
});

test("pending questions use safe fields, stable order, and de-duplication", () => {
  const result = normalizeChatResponsePresentation({
    status: "needs_input",
    pending_questions: [
      "사고 일시는 언제인가요?",
      { question: "차량 번호를 알려 주세요." },
      { label: "보험사" },
      { description: "현장 사진을 첨부해 주세요." },
      { question: "차량 번호를 알려 주세요." },
      { unexpected: true },
    ],
  });

  assert.deepEqual(result.pendingQuestions, [
    "사고 일시는 언제인가요?",
    "차량 번호를 알려 주세요.",
    "보험사",
    "현장 사진을 첨부해 주세요.",
  ]);
});

test("follow-up and report link are normalized without changing routes", () => {
  const direct = normalizeChatResponsePresentation({
    status: "success",
    assistant_message: {
      answer: "답변",
      follow_up: "추가로 확인할 사항입니다.",
    },
    report_links: [{ url: "/reports/report-1", label: "상세 리포트" }],
  });
  assert.equal(direct.followUp, "추가로 확인할 사항입니다.");
  assert.deepEqual(direct.reportLink, {
    href: "/reports/report-1",
    label: "상세 리포트",
  });

  const internal = normalizeChatResponsePresentation({
    status: "success",
    assistant_message: { answer: "답변" },
    reporting_payload: { report_id: "report-2" },
  });
  assert.deepEqual(internal.reportLink, {
    href: "",
    label: "현재 리포트 보기",
  });
});

test("primary follow-up uses one safe question in the approved priority", () => {
  assert.equal(
    selectPrimaryFollowUpQuestion({
      pendingQuestions: ["첫 번째 질문", "두 번째 질문"],
      followUp: { message: "후속 안내" },
      supervisorQuestions: [{ question: "Supervisor 질문" }],
    }),
    "첫 번째 질문",
  );
  assert.equal(
    selectPrimaryFollowUpQuestion({
      followUp: { message: "후속 안내" },
      supervisorQuestions: [{ question: "Supervisor 질문" }],
    }),
    "후속 안내",
  );
  assert.equal(
    selectPrimaryFollowUpQuestion({
      followUp: { message: { unsafe: true } },
      supervisorQuestions: [{ question: "Supervisor 질문" }],
    }),
    "Supervisor 질문",
  );
  assert.equal(
    selectPrimaryFollowUpQuestion({
      pendingQuestions: [{ unexpected: true }],
      followUp: { message: null },
      supervisorQuestions: [{ unexpected: true }],
    }),
    "",
  );
});
