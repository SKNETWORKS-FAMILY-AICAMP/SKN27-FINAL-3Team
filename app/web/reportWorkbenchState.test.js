import assert from "node:assert/strict";
import test from "node:test";
import * as reportWorkbenchStateModule from "./reportWorkbenchState.js";

import { compactUniqueStrings, deriveReportWorkbenchState } from "./reportWorkbenchState.js";

test("rejects empty and skeletal temporary reporting payloads", () => {
  assert.equal(typeof reportWorkbenchStateModule.hasMeaningfulReportingPayload, "function");
  assert.equal(reportWorkbenchStateModule.hasMeaningfulReportingPayload(null), false);
  assert.equal(reportWorkbenchStateModule.hasMeaningfulReportingPayload({}), false);
  assert.equal(
    reportWorkbenchStateModule.hasMeaningfulReportingPayload({
      report_type: "general",
      sections: [],
    }),
    false,
  );
  assert.equal(
    reportWorkbenchStateModule.hasMeaningfulReportingPayload({ summary: "   " }),
    false,
  );
});

test("accepts temporary payloads with visible report content", () => {
  assert.equal(typeof reportWorkbenchStateModule.hasMeaningfulReportingPayload, "function");
  assert.equal(
    reportWorkbenchStateModule.hasMeaningfulReportingPayload({
      summary: "사고 분석 요약",
    }),
    true,
  );
  assert.equal(
    reportWorkbenchStateModule.hasMeaningfulReportingPayload({
      sections: [{ title: "사고 개요", items: ["직진 중 충돌"] }],
    }),
    true,
  );
  assert.equal(
    reportWorkbenchStateModule.hasMeaningfulReportingPayload({
      document_cards: [{ type: "objection_draft" }],
    }),
    true,
  );
});

test("does not turn a skeletal live payload into an active report canvas", () => {
  const state = deriveReportWorkbenchState({
    hasReport: true,
    hasSavedReports: false,
    canGenerateReport: false,
    isPersistedReport: false,
    reportingPayload: { report_type: "general", sections: [] },
    supervisorState: {
      stage: "agent_execution_ready",
      missing_fields: [],
      next_questions: [],
    },
  });

  assert.equal(state.kind, "not_reportable");
});

test("normalizes structured missing items without object coercion", () => {
  const items = compactUniqueStrings([
    "보험사",
    { question: "사고 일시는 언제인가요?" },
    { label: "차량 번호" },
    { description: "현장 사진" },
    { unexpected: true },
  ]);

  assert.deepEqual(items, [
    "보험사",
    "사고 일시는 언제인가요?",
    "차량 번호",
    "현장 사진",
    "추가 확인이 필요한 항목",
  ]);
  assert.ok(items.every((item) => !item.includes("[object Object]")));
});

test("normalizes nested text, skips empty values, and keeps stable unique order", () => {
  const items = compactUniqueStrings([
    null,
    "  ",
    { question: { label: "진입 순서" } },
    { description: "진입 순서" },
    { metadata: { title: "보험사 주장" } },
    [],
    {},
    { label: "차량 번호" },
  ], 10);

  assert.deepEqual(items, [
    "진입 순서",
    "보험사 주장",
    "추가 확인이 필요한 항목",
    "차량 번호",
  ]);
});

test("describes unresolved supervisor facts as the next workbench action", () => {
  const state = deriveReportWorkbenchState({
    hasReport: false,
    hasSavedReports: false,
    canGenerateReport: true,
    reportingPayload: null,
    supervisorState: {
      stage: "follow_up_required",
      missing_fields: ["충돌 부위", "진입 순서", "충돌 부위"],
      next_questions: ["양쪽 차량의 충돌 부위를 알려주세요."],
    },
  });

  assert.deepEqual(state, {
    kind: "needs_information",
    stageLabel: "상담·자료 보완 필요",
    title: "리포트 생성을 위해 확인할 정보가 있습니다.",
    description: "상담에서 아래 항목을 보완하면 분석과 리포트 준비를 이어갈 수 있습니다.",
    missingItems: ["충돌 부위", "진입 순서"],
    ctaLabel: "AI 상담으로 이동",
  });
});

test("keeps completed general guidance out of the report generation path", () => {
  const state = deriveReportWorkbenchState({
    hasReport: false,
    hasSavedReports: false,
    canGenerateReport: false,
    reportingPayload: null,
    supervisorState: {
      stage: "agent_execution_ready",
      missing_fields: [],
      next_questions: [],
    },
  });

  assert.equal(state.kind, "not_reportable");
  assert.equal(state.stageLabel, "절차 안내 완료");
  assert.match(state.title, /아직 생성되지 않았습니다/);
  assert.match(state.description, /OCR/);
  assert.match(state.description, /초안/);
  assert.equal(state.ctaLabel, "AI 상담으로 이동");
});

test("shows an initial workspace before a user has started any consultation", () => {
  const state = deriveReportWorkbenchState({
    hasReport: false,
    hasSavedReports: false,
    canGenerateReport: false,
    reportingPayload: null,
    supervisorState: null,
  });

  assert.deepEqual(state.missingItems, []);
  assert.equal(state.kind, "not_started");
  assert.equal(state.ctaLabel, "AI 상담 시작");
});

test("distinguishes an empty current consultation from existing saved reports", () => {
  const state = deriveReportWorkbenchState({
    hasCurrentSessionReport: false,
    hasSelectedSavedReport: false,
    hasSavedReports: true,
    reportingPayload: null,
    supervisorState: null,
  });

  assert.equal(state.kind, "saved_reports_only");
  assert.match(state.title, /현재 상담에는.*리포트가 없습니다/);
  assert.match(state.description, /저장된 리포트/);
  assert.equal(state.ctaLabel, "저장 리포트 선택");
});

test("does not replace an existing report with an empty-state instruction", () => {
  const state = deriveReportWorkbenchState({
    hasReport: true,
    hasSavedReports: true,
    hasCurrentSessionReport: true,
    canGenerateReport: true,
    isPersistedReport: true,
    reportingPayload: { report_id: "report_123" },
    supervisorState: {
      stage: "agent_execution_ready",
      missing_fields: [],
      next_questions: [],
    },
  });

  assert.equal(state.kind, "available");
});

test("waits for persisted report detail instead of rendering a list summary as a completed report", () => {
  const state = deriveReportWorkbenchState({
    hasReport: false,
    hasSavedReports: true,
    hasSelectedSavedReport: true,
    savedReportDetailLoaded: false,
  });

  assert.equal(state.kind, "loading_saved_report");
  assert.equal(state.ctaLabel, "목록 새로고침");
});

test("labels an in-session report payload as temporary until a signed-in user saves it", () => {
  const state = deriveReportWorkbenchState({
    hasReport: true,
    reportingPayload: {
      report_type: "fault_ratio_analysis",
      sections: [{ title: "사고 개요", items: ["확인된 사고 사실"] }],
    },
    isAuthenticated: false,
    isPersistedReport: false,
  });

  assert.equal(state.kind, "temporary_preview");
  assert.match(state.description, /로그인/);
});
