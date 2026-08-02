import React from "react";

import { buildCaseReadyActionUi } from "./caseReadyWorkflow.js";


export function CaseReadyPanel({
  model,
  progress,
  authenticated,
  onStart,
}) {
  const ui = buildCaseReadyActionUi({
    model,
    progress,
    authenticated,
  });
  if (!ui.visible) {
    return null;
  }

  return React.createElement(
    "section",
    {
      className: "case-ready-panel",
      "aria-label": "사건 생성 준비",
    },
    React.createElement(
      "div",
      { className: "case-ready-panel__header" },
      React.createElement("span", null, "사실 확인"),
      React.createElement("h3", null, "사건 생성 준비 완료"),
      React.createElement(
        "p",
        null,
        "아래 사실을 기준으로 사건을 만들고 분석을 시작합니다.",
      ),
    ),
    React.createElement(
      "dl",
      { className: "case-ready-facts" },
      ...ui.facts.map((fact) => React.createElement(
        "div",
        { className: "case-ready-fact", key: fact.field },
        React.createElement("dt", null, fact.label),
        React.createElement("dd", null, String(fact.value ?? "")),
      )),
    ),
    React.createElement(
      "div",
      { className: "case-ready-actions" },
      React.createElement(
        "p",
        { className: "case-ready-progress", role: "status" },
        ui.progressMessage,
      ),
      React.createElement(
        "button",
        {
          className: "button primary",
          type: "button",
          onClick: onStart,
          disabled: ui.disabled,
        },
        ui.buttonLabel,
      ),
      ui.error
        ? React.createElement(
          "p",
          { className: "case-ready-error", role: "alert" },
          ui.error,
        )
        : null,
    ),
  );
}
