import assert from "node:assert/strict";
import test from "node:test";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { TrafficAccidentOcrPanel } from "./TrafficAccidentOcrPanel.js";


test("renders only confirmed safe accident OCR values", () => {
  const markup = renderToStaticMarkup(
    React.createElement(TrafficAccidentOcrPanel, {
      ui: {
        status: "partial",
        targetDocument: true,
        maskingApplied: true,
        attachmentId: "att_accident_confirmation",
        imageQuality: "readable",
        fields: [
          { field: "accident_datetime", label: "사고 일시", value: "2022-11-18 14:10" },
          { field: "accident_location", label: "사고 장소", value: "경기도 안산시" },
          { field: "accident_type", label: "사고 유형", value: "차대차" },
          { field: "accident_cause", label: "사고 원인", value: "신호 또는 지시 위반" },
          { field: "damage", label: "피해 내용", value: "부상 1명" },
          { field: "accident_description", label: "사고 내용", value: "교차로에서 충돌한 사고" },
        ],
        failureReason: null,
        nextActions: ["누락 필드를 확인해 주세요."],
      },
    }),
  );

  assert.match(markup, /교통사고 사실확인원 OCR 결과/);
  assert.match(markup, /민감정보를 제외한 항목만 표시합니다/);
  assert.match(markup, /개인정보 마스킹 적용/);
  assert.match(markup, /att_accident_confirmation/);
  assert.match(markup, /사고 일시/);
  assert.match(markup, /2022-11-18 14:10/);
  assert.match(markup, /사고 내용/);
  assert.match(markup, /교차로에서 충돌한 사고/);
  assert.match(markup, /누락 필드를 확인해 주세요/);
  assert.doesNotMatch(markup, /storage_uri|resident_registration_number/);
});


test("renders a safe retry instruction without empty invented values", () => {
  const markup = renderToStaticMarkup(
    React.createElement(TrafficAccidentOcrPanel, {
      ui: {
        status: "failed",
        targetDocument: false,
        maskingApplied: false,
        attachmentId: "att_crop",
        imageQuality: null,
        fields: [
          { field: "accident_datetime", label: "사고 일시", value: null },
          { field: "accident_location", label: "사고 장소", value: null },
        ],
        failureReason: "not_target_document",
        nextActions: ["전체 1페이지 이미지를 다시 업로드해 주세요."],
      },
    }),
  );

  assert.match(markup, /문서를 확인하지 못했습니다/);
  assert.match(markup, /전체 1페이지 이미지를 다시 업로드해 주세요/);
  assert.doesNotMatch(markup, /<dt>|<dd>/);
});


test("renders no panel without an OCR presentation model", () => {
  const markup = renderToStaticMarkup(
    React.createElement(TrafficAccidentOcrPanel, { ui: null }),
  );

  assert.equal(markup, "");
});
