import assert from "node:assert/strict";
import test from "node:test";

import { buildTrafficAccidentOcrUi } from "./trafficAccidentOcrPresentation.js";


test("keeps only allow-listed accident OCR fields and a safe attachment ID", () => {
  const ui = buildTrafficAccidentOcrUi({
    semanticStatus: "partial",
    structuredResult: {
      document_check: {
        is_target_document: true,
        document_name: "교통사고사실확인원",
      },
      extracted_fields: {
        accident_datetime: "2022-11-18 14:10",
        accident_location: "경기도 안산시",
        accident_type: {
          value: "차대차",
          raw_text: "차대차",
        },
        accident_cause: "신호 또는 지시 위반",
        damage: {
          raw_text: "부상 1명",
          injury_count: 1,
        },
        accident_description: "교차로에서 충돌한 사고",
        resident_registration_number: "must-not-appear",
      },
      missing_fields: ["issue_number"],
      quality: {
        image_quality: "readable",
        ocr_confidence: 0.91,
      },
      privacy: {
        masking_applied: true,
        excluded_sensitive_fields: ["resident_registration_number"],
      },
      ocr_evidence: [
        {
          attachment_id: "att_accident_confirmation",
          storage_uri: "s3://must-not-appear/private.png",
          content_type: "image/png",
        },
      ],
      raw_text_redacted: "must-not-appear",
    },
    nextActions: ["누락 필드를 확인해 주세요."],
  });
  const serialized = JSON.stringify(ui);

  assert.equal(ui.status, "partial");
  assert.equal(ui.targetDocument, true);
  assert.equal(ui.maskingApplied, true);
  assert.equal(ui.attachmentId, "att_accident_confirmation");
  assert.equal(ui.imageQuality, "readable");
  assert.deepEqual(ui.fields, [
    { field: "accident_datetime", label: "사고 일시", value: "2022-11-18 14:10" },
    { field: "accident_location", label: "사고 장소", value: "경기도 안산시" },
    { field: "accident_type", label: "사고 유형", value: "차대차" },
    { field: "accident_cause", label: "사고 원인", value: "신호 또는 지시 위반" },
    { field: "damage", label: "피해 내용", value: "부상 1명" },
    { field: "accident_description", label: "사고 내용", value: "교차로에서 충돌한 사고" },
  ]);
  assert.equal(serialized.includes("must-not-appear"), false);
  assert.equal(serialized.includes("resident_registration_number"), false);
  assert.equal(serialized.includes("storage_uri"), false);
  assert.equal(serialized.includes("raw_text_redacted"), false);
});


test("returns a failed safe model without inventing OCR values", () => {
  const ui = buildTrafficAccidentOcrUi({
    semanticStatus: "failed",
    structuredResult: {
      document_check: { is_target_document: false },
      extracted_fields: {},
      missing_fields: [],
      failure_reason: "not_target_document",
      ocr_evidence: [{ attachment_id: "att_crop" }],
    },
    nextActions: ["전체 1페이지 이미지를 다시 업로드해 주세요."],
  });

  assert.equal(ui.status, "failed");
  assert.equal(ui.targetDocument, false);
  assert.equal(ui.fields.every((field) => field.value === null), true);
  assert.deepEqual(ui.nextActions, [
    "전체 1페이지 이미지를 다시 업로드해 주세요.",
  ]);
});


test("returns no OCR UI when the traffic-accident result is absent", () => {
  assert.equal(buildTrafficAccidentOcrUi({}), null);
  assert.equal(buildTrafficAccidentOcrUi(null), null);
});
