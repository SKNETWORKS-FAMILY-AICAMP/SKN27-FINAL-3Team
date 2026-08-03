import assert from "node:assert/strict";
import test from "node:test";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { CaseReadyPanel } from "./CaseReadyPanel.js";
import { buildCaseReadyViewModel } from "./caseReadyWorkflow.js";


function eligibleModel() {
  return buildCaseReadyViewModel(
    {
      status: "case_ready",
      session_id: "ses_panel",
      consultation_state: {
        v2: {
          schema_version: "consultation_state.v2",
          risk_gate: { level: "standard" },
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
    },
    [{ attachment_id: "att_panel", status: "ready" }],
  );
}


test("renders four confirmed facts and one guest start action", () => {
  const markup = renderToStaticMarkup(
    React.createElement(CaseReadyPanel, {
      model: eligibleModel(),
      progress: { step: "idle", error: "" },
      authenticated: false,
      onStart: () => {},
    }),
  );

  assert.match(markup, /사건 생성 준비 완료/);
  for (const label of [
    "도로 형태",
    "양쪽 차량 행동",
    "신호·우선권",
    "충돌 부위",
  ]) {
    assert.match(markup, new RegExp(label));
  }
  assert.equal((markup.match(/<button/g) || []).length, 1);
  assert.match(markup, /로그인 후 사건 생성·분석 시작/);
  assert.doesNotMatch(markup, /disabled=""/);
});


test("disables the authenticated action while analysis is active", () => {
  const markup = renderToStaticMarkup(
    React.createElement(CaseReadyPanel, {
      model: eligibleModel(),
      progress: { step: "polling", error: "" },
      authenticated: true,
      onStart: () => {},
    }),
  );

  assert.match(markup, /사건 생성·분석 시작/);
  assert.match(markup, /과실 쟁점과 법률 근거를 분석하고 있습니다/);
  assert.match(markup, /<button[^>]*disabled=""/);
});


test("renders no panel for an ineligible consultation", () => {
  const markup = renderToStaticMarkup(
    React.createElement(CaseReadyPanel, {
      model: buildCaseReadyViewModel({ status: "needs_input" }),
      progress: { step: "idle", error: "" },
      authenticated: false,
      onStart: () => {},
    }),
  );

  assert.equal(markup, "");
});
