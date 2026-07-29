import test from "node:test";
import assert from "node:assert/strict";

import { buildAppealDecisionUi } from "./appealDecisionUi.js";

const combinations = [
  [false, "강함", "safe", "strong", false],
  [false, "보류", "safe", "pending", false],
  [false, "낮음", "safe", "low", false],
  [true, "강함", "risky", "strong", true],
  [true, "보류", "risky", "pending", true],
  [true, "낮음", "risky", "low", true],
];

test("maps all RG and MG combinations without treating execution success as safety", () => {
  for (const [riskFlag, merit, riskStatus, meritStatus, requiresAcknowledgement] of combinations) {
    const ui = buildAppealDecisionUi({
      risk_flag: riskFlag,
      risk_judgment_failed: false,
      merit,
      merit_judgment_failed: false,
      merit_basis: "검증된 조문과 제출 자료 기준",
      merit_relief_type: merit === "강함" ? "감경" : null,
      guide: { disclaimer: "종합 안내" },
    });

    assert.equal(ui.risk.status, riskStatus);
    assert.equal(ui.merit.status, meritStatus);
    assert.equal(ui.requiresAcknowledgement, requiresAcknowledgement);
    assert.equal(ui.merit.basis, "검증된 조문과 제출 자료 기준");
  }
});

test("distinguishes RG technical failure from an actually risky statement", () => {
  const ui = buildAppealDecisionUi({
    risk_flag: true,
    risk_judgment_failed: true,
    merit: "강함",
    merit_judgment_failed: false,
  });

  assert.equal(ui.risk.status, "failed");
  assert.equal(ui.risk.label, "위험 판정 실패");
  assert.equal(ui.requiresAcknowledgement, true);
  assert.equal(ui.canRetry, true);
});

test("distinguishes MG technical failure and relief classification failure", () => {
  const meritFailure = buildAppealDecisionUi({
    risk_flag: false,
    merit: "보류",
    merit_judgment_failed: true,
  });
  const reliefFailure = buildAppealDecisionUi({
    risk_flag: false,
    merit: "강함",
    merit_judgment_failed: false,
    relief_type_judgment_failed: true,
  });

  assert.equal(meritFailure.merit.status, "failed");
  assert.equal(meritFailure.merit.label, "인정 가능성 판정 실패");
  assert.equal(meritFailure.canRetry, true);
  assert.equal(reliefFailure.merit.reliefLabel, "면제·감경 구분 필요");
  assert.equal(reliefFailure.canRetry, true);
});

test("returns no UI model when appeal decision data is absent", () => {
  assert.equal(buildAppealDecisionUi(null), null);
  assert.equal(buildAppealDecisionUi({}), null);
});
