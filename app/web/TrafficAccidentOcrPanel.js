import React from "react";


const STATUS_COPY = {
  completed: "문서 확인 완료",
  partial: "일부 항목 확인 완료",
  failed: "문서를 확인하지 못했습니다",
};

export function TrafficAccidentOcrPanel({ ui }) {
  if (!ui) {
    return null;
  }

  const visibleFields = Array.isArray(ui.fields)
    ? ui.fields.filter((field) => field?.value)
    : [];
  const nextActions = Array.isArray(ui.nextActions) ? ui.nextActions : [];

  return React.createElement(
    "section",
    {
      className: `traffic-accident-ocr is-${ui.status}`,
      "aria-label": "교통사고 사실확인원 OCR 결과",
    },
    React.createElement(
      "div",
      { className: "traffic-accident-ocr__header" },
      React.createElement("span", null, "사고 자료 OCR"),
      React.createElement("h3", null, "교통사고 사실확인원 OCR 결과"),
      React.createElement(
        "p",
        { role: "status" },
        STATUS_COPY[ui.status] || STATUS_COPY.completed,
      ),
      React.createElement(
        "small",
        null,
        "민감정보를 제외한 항목만 표시합니다.",
      ),
    ),
    ui.maskingApplied || ui.attachmentId
      ? React.createElement(
        "div",
        { className: "traffic-accident-ocr__meta" },
        ui.maskingApplied
          ? React.createElement("span", null, "개인정보 마스킹 적용")
          : null,
        ui.attachmentId
          ? React.createElement("span", null, `첨부 ID ${ui.attachmentId}`)
          : null,
      )
      : null,
    visibleFields.length > 0
      ? React.createElement(
        "dl",
        { className: "traffic-accident-ocr__fields" },
        ...visibleFields.map((field) => React.createElement(
          "div",
          { className: "traffic-accident-ocr__field", key: field.field },
          React.createElement("dt", null, field.label),
          React.createElement("dd", null, field.value),
        )),
      )
      : null,
    nextActions.length > 0
      ? React.createElement(
        "div",
        { className: "traffic-accident-ocr__next" },
        React.createElement("strong", null, "다음 확인"),
        React.createElement(
          "ul",
          null,
          ...nextActions.map((action) => React.createElement(
            "li",
            { key: action },
            action,
          )),
        ),
      )
      : null,
  );
}
