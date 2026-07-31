export const ATTACHMENT_WORKFLOW_COPY = Object.freeze({
  scan_running: Object.freeze({
    tone: "pending",
    title: "파일 안전 검사 중",
    description: "검사가 끝난 뒤 자료 분류를 진행합니다.",
  }),
  classification_running: Object.freeze({
    tone: "pending",
    title: "자료 종류 확인 중",
    description: "분류 결과를 확인하기 전에는 OCR을 시작하지 않습니다.",
  }),
  classified_waiting_confirmation: Object.freeze({
    tone: "attention",
    title: "자료 분류 확인 필요",
    description: "자료 종류를 확인하면 다음 분석을 진행합니다.",
  }),
  ocr_running: Object.freeze({
    tone: "pending",
    title: "고지서 항목 추출 중",
    description: "추출값 확인 전에는 법령·이의 절차 판단을 진행하지 않습니다.",
  }),
  ocr_needs_confirmation: Object.freeze({
    tone: "attention",
    title: "OCR 추출값 확인 필요",
    description: "추출된 고지서 항목을 확인하거나 수정해 주세요.",
  }),
  analysis_ready: Object.freeze({
    tone: "success",
    title: "고지서 분석 준비 완료",
    description: "확인된 정보와 누락 정보, 근거와 한계를 검토해 주세요.",
  }),
  partial: Object.freeze({
    tone: "attention",
    title: "일부 정보 확인 필요",
    description: "확보하지 못한 정보를 보완한 뒤 계속할 수 있습니다.",
  }),
  failed: Object.freeze({
    tone: "danger",
    title: "자료 처리 확인 필요",
    description: "안내된 다음 행동으로 다시 진행해 주세요.",
  }),
});

function safeStringList(value) {
  return Array.isArray(value)
    ? value.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim())
    : [];
}

export function buildAttachmentWorkflowUi(workflows) {
  if (!Array.isArray(workflows)) {
    return [];
  }

  return workflows.flatMap((workflow) => {
    if (
      !workflow ||
      workflow.contract_version !== "attachment_workflow.v1" ||
      typeof workflow.attachment_id !== "string" ||
      !workflow.attachment_id.trim()
    ) {
      return [];
    }
    const copy = ATTACHMENT_WORKFLOW_COPY[workflow.state];
    if (!copy) {
      return [];
    }
    return [
      {
        attachmentId: workflow.attachment_id.trim(),
        state: workflow.state,
        tone: copy.tone,
        title: copy.title,
        description: copy.description,
        action:
          typeof workflow.next_action === "string" ? workflow.next_action.trim() : "",
        retryable: workflow.retryable === true,
        missingFields: safeStringList(workflow.missing_fields),
        limitations: safeStringList(workflow.limitations),
      },
    ];
  });
}
