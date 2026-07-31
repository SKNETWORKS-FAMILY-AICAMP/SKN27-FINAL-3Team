import assert from "node:assert/strict";
import test from "node:test";

import { deriveReportWorkbenchState } from "./reportWorkbenchState.js";

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

test("does not replace an existing report with an empty-state instruction", () => {
  const state = deriveReportWorkbenchState({
    hasReport: true,
    hasSavedReports: true,
    canGenerateReport: true,
    reportingPayload: { report_id: "report_123" },
    supervisorState: {
      stage: "agent_execution_ready",
      missing_fields: [],
      next_questions: [],
    },
  });

  assert.equal(state.kind, "available");
});
