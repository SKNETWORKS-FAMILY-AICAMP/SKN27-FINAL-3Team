const OCR_FIELDS = [
  ["accident_datetime", "사고 일시", (fields) => fields.accident_datetime],
  ["accident_location", "사고 장소", (fields) => fields.accident_location],
  ["accident_type", "사고 유형", (fields) => fields.accident_type?.value],
  ["accident_cause", "사고 원인", (fields) => fields.accident_cause],
  ["damage", "피해 내용", (fields) => fields.damage?.raw_text],
  ["accident_description", "사고 내용", (fields) => fields.accident_description],
];

function safeText(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function buildTrafficAccidentOcrUi(input) {
  const structuredResult = input?.structuredResult;
  if (!structuredResult || typeof structuredResult !== "object") {
    return null;
  }

  const extractedFields =
    structuredResult.extracted_fields &&
    typeof structuredResult.extracted_fields === "object"
      ? structuredResult.extracted_fields
      : {};
  const evidence = Array.isArray(structuredResult.ocr_evidence)
    ? structuredResult.ocr_evidence
    : [];

  return {
    status: safeText(input?.semanticStatus) || "completed",
    targetDocument: structuredResult.document_check?.is_target_document === true,
    maskingApplied: structuredResult.privacy?.masking_applied === true,
    attachmentId: safeText(evidence[0]?.attachment_id),
    imageQuality: safeText(structuredResult.quality?.image_quality),
    fields: OCR_FIELDS.map(([field, label, read]) => ({
      field,
      label,
      value: safeText(read(extractedFields)),
    })),
    failureReason: safeText(structuredResult.failure_reason),
    nextActions: Array.isArray(input?.nextActions)
      ? input.nextActions.map(safeText).filter(Boolean)
      : [],
  };
}
