const MERIT_STATUS = {
  강함: "strong",
  보류: "pending",
  낮음: "low",
};

export function buildAppealDecisionUi(value) {
  if (!value || typeof value !== "object") return null;
  const hasDecision = [
    "risk_flag",
    "risk_judgment_failed",
    "merit",
    "merit_judgment_failed",
  ].some((key) => Object.hasOwn(value, key));
  if (!hasDecision) return null;

  const riskFailed = value.risk_judgment_failed === true;
  const risky = value.risk_flag === true;
  const meritFailed = value.merit_judgment_failed === true;
  const reliefFailed = value.relief_type_judgment_failed === true;
  const meritStatus = meritFailed ? "failed" : MERIT_STATUS[value.merit] || "pending";

  return {
    risk: {
      status: riskFailed ? "failed" : risky ? "risky" : "safe",
      label: riskFailed ? "위험 판정 실패" : risky ? "운전자 신원 노출 위험" : "신원 노출 위험 없음",
      message: riskFailed
        ? "시스템이 위험 여부를 판단하지 못해 임시로 위험 상태로 표시했습니다."
        : risky
          ? "이의 사유에 실제 운전자를 특정하거나 본인 운전을 인정하는 진술이 포함될 수 있습니다."
          : "현재 입력에서는 운전자 신원 노출 위험 진술이 감지되지 않았습니다.",
      category: value.risk_trigger_category || "",
      confidence: Number.isFinite(Number(value.risk_confidence)) ? Number(value.risk_confidence) : null,
    },
    merit: {
      status: meritStatus,
      label: meritFailed ? "인정 가능성 판정 실패" : `사유 인정 가능성 · ${value.merit || "보류"}`,
      level: value.merit || "보류",
      basis: value.merit_basis || "판단 근거를 추가로 확인해야 합니다.",
      reliefLabel: reliefFailed
        ? "면제·감경 구분 필요"
        : value.merit_relief_type
          ? `예상 효과 · ${value.merit_relief_type}`
          : "",
    },
    combinedMessage:
      typeof value.guide?.disclaimer === "string"
        ? value.guide.disclaimer
        : "위험과 인정 가능성을 함께 확인한 뒤 진행 여부를 결정해 주세요.",
    canRetry: riskFailed || meritFailed || reliefFailed,
    requiresAcknowledgement: risky || riskFailed,
  };
}
