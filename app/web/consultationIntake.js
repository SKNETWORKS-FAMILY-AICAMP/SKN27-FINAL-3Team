export const CONSULTATION_TYPE_OPTIONS = [
  { value: "", label: "선택 안 함" },
  { value: "intersection", label: "교차로 사고" },
  { value: "lane_change", label: "차선 변경·끼어들기" },
  { value: "rear_end", label: "추돌 사고" },
  { value: "parking", label: "주정차·출차 사고" },
  { value: "pedestrian_bicycle", label: "보행자·자전거 사고" },
  { value: "fine_notice", label: "과태료·범칙금 상담" },
  { value: "other", label: "기타 사고" },
];

export const CONSULTATION_FACT_FIELDS = [
  {
    key: "roadLayout",
    label: "도로 형태",
    question: "사고 장소의 도로 형태",
  },
  {
    key: "vehicleActions",
    label: "양쪽 차량 행동",
    question: "충돌 직전 양쪽 차량의 진행 방향과 행동",
  },
  {
    key: "signalPriority",
    label: "신호·우선권",
    question: "당시 신호나 우선권 상황",
  },
  {
    key: "collisionLocation",
    label: "충돌 부위",
    question: "각 차량의 어느 부위가 충돌했는지",
  },
];

const ACCIDENT_CONSULTATION_TYPES = new Set([
  "intersection",
  "lane_change",
  "rear_end",
  "parking",
  "pedestrian_bicycle",
  "other",
]);

export function createEmptyConsultationIntake() {
  return {
    consultationType: "",
    roadLayout: "",
    vehicleActions: "",
    signalPriority: "",
    collisionLocation: "",
    confirmedFacts: "",
    userClaims: "",
    missingDetails: "",
  };
}

export function hasConsultationIntakeData(value) {
  const intake = normalizeConsultationIntake(value);
  return Object.values(intake).some(Boolean);
}

export function listConsultationIntakeMissingFields(value) {
  const intake = normalizeConsultationIntake(value);
  if (!shouldCollectAccidentFacts(intake)) {
    return [];
  }
  return CONSULTATION_FACT_FIELDS.filter((field) => !intake[field.key]).map((field) => ({
    key: field.key,
    label: field.question,
  }));
}

export function buildStructuredConsultationMessage({ freeText = "", intake } = {}) {
  const normalizedFreeText = normalizeText(freeText);
  const normalizedIntake = normalizeConsultationIntake(intake);
  if (!hasConsultationIntakeData(normalizedIntake)) {
    return normalizedFreeText;
  }

  const sections = [];
  const typeLabel = consultationTypeLabel(normalizedIntake.consultationType);
  if (typeLabel) {
    sections.push(`[상담 유형]\n${typeLabel}`);
  }

  const factLines = CONSULTATION_FACT_FIELDS.flatMap((field) =>
    normalizedIntake[field.key] ? [`- ${field.label}: ${normalizedIntake[field.key]}`] : []
  );
  const extraFacts = normalizeMultiline(normalizedIntake.confirmedFacts).map((item) => `- ${item}`);
  if (factLines.length || extraFacts.length) {
    sections.push(`[확인된 사실]\n${[...factLines, ...extraFacts].join("\n")}`);
  }

  const userClaims = normalizeMultiline(normalizedIntake.userClaims);
  if (userClaims.length) {
    sections.push(`[사용자 주장]\n${userClaims.map((item) => `- ${item}`).join("\n")}`);
  }

  const missingDetails = normalizeMultiline(normalizedIntake.missingDetails);
  if (missingDetails.length) {
    sections.push(`[추가 확인이 필요한 점]\n${missingDetails.map((item) => `- ${item}`).join("\n")}`);
  }

  if (normalizedFreeText) {
    sections.push(`[자유 입력]\n${normalizedFreeText}`);
  }
  return sections.join("\n\n").trim();
}

function shouldCollectAccidentFacts(intake) {
  return (
    ACCIDENT_CONSULTATION_TYPES.has(intake.consultationType) ||
    CONSULTATION_FACT_FIELDS.some((field) => intake[field.key]) ||
    Boolean(intake.confirmedFacts || intake.userClaims || intake.missingDetails)
  );
}

function consultationTypeLabel(value) {
  const match = CONSULTATION_TYPE_OPTIONS.find((option) => option.value === value);
  return match ? match.label : "";
}

function normalizeConsultationIntake(value) {
  const base = createEmptyConsultationIntake();
  const source = value && typeof value === "object" ? value : {};
  return Object.fromEntries(
    Object.keys(base).map((key) => [key, normalizeText(source[key])])
  );
}

function normalizeMultiline(value) {
  return normalizeText(value)
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeText(value) {
  return typeof value === "string" ? value.trim() : "";
}
