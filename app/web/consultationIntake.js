export const CONSULTATION_TYPE_OPTIONS = [
  { value: "", label: "선택 안 함" },
  { value: "general", label: "일반 상담" },
  { value: "fine_notice", label: "과태료·범칙금" },
  { value: "fault_ratio", label: "사고 과실비율" },
];

export const ACCIDENT_TYPE_OPTIONS = [
  { value: "", label: "사고 유형 선택" },
  { value: "intersection", label: "교차로 사고" },
  { value: "lane_change", label: "차선 변경·끼어들기" },
  { value: "rear_end", label: "추돌 사고" },
  { value: "parking", label: "주정차·출차 사고" },
  { value: "pedestrian_bicycle", label: "보행자·자전거 사고" },
  { value: "other", label: "기타 사고" },
];

export const FINE_NOTICE_FIELDS = [
  {
    key: "documentDispositionType",
    serverKey: "document_disposition_type",
    label: "문서명·처분 유형",
    question: "받은 문서의 이름 또는 처분 유형",
  },
  {
    key: "issuingAuthority",
    serverKey: "issuing_authority",
    label: "발급기관",
    question: "고지서를 발급한 기관",
  },
  {
    key: "responseDeadline",
    serverKey: "response_deadline",
    label: "제출 기한",
    question: "의견제출 또는 이의신청 기한",
  },
  {
    key: "attachmentAvailable",
    serverKey: "attachment_available",
    label: "첨부 가능 여부",
    question: "고지서 사진이나 파일을 첨부할 수 있는지",
  },
];

export const CONSULTATION_FACT_FIELDS = [
  {
    key: "roadLayout",
    serverKey: "road_layout",
    label: "도로 형태",
    question: "사고 장소의 도로 형태",
  },
  {
    key: "vehicleActions",
    serverKey: "vehicle_actions",
    label: "양쪽 차량 행동",
    question: "충돌 직전 양쪽 차량의 진행 방향과 행동",
  },
  {
    key: "signalPriority",
    serverKey: "signal_priority",
    label: "신호·우선권",
    question: "당시 신호나 우선권 상황",
  },
  {
    key: "collisionLocation",
    serverKey: "collision_location",
    label: "충돌 부위",
    question: "각 차량의 어느 부위가 충돌했는지",
  },
];

const ACCIDENT_CONSULTATION_TYPES = new Set([
  "fault_ratio",
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
    accidentType: "",
    documentDispositionType: "",
    issuingAuthority: "",
    responseDeadline: "",
    attachmentAvailable: "",
    fineQuestion: "",
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
  const typeLabel = consultationRequestTypeLabel(normalizedIntake.consultationType);
  if (typeLabel) {
    sections.push(`[상담 유형]\n${typeLabel}`);
  }

  const accidentTypeLabel = consultationTypeLabel(normalizedIntake.accidentType);
  if (normalizedIntake.consultationType === "fault_ratio" && accidentTypeLabel) {
    sections.push(`[사고 유형]\n${accidentTypeLabel}`);
  }

  const fineLines = FINE_NOTICE_FIELDS.flatMap((field) =>
    normalizedIntake[field.key] ? [`- ${field.label}: ${normalizedIntake[field.key]}`] : []
  );
  if (normalizedIntake.consultationType === "fine_notice" && fineLines.length) {
    sections.push(`[과태료 기본정보]\n${fineLines.join("\n")}`);
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

export function buildConsultationMessagePair({ freeText = "", intake } = {}) {
  const displayText = normalizeText(freeText);
  const requestText = buildStructuredConsultationMessage({ freeText, intake });
  return { displayText: displayText || requestText, requestText };
}

export function buildConsultationRequestContext({ intake } = {}) {
  const normalizedIntake = normalizeConsultationIntake(intake);
  const context = {
    consultation_type: normalizedIntake.consultationType,
    facts: Object.fromEntries(
      CONSULTATION_FACT_FIELDS.flatMap(({ key, serverKey }) =>
        normalizedIntake[key] ? [[serverKey, normalizedIntake[key]]] : []
      )
    ),
  };
  if (normalizedIntake.consultationType === "fine_notice") {
    context.fine_notice_slots = Object.fromEntries(
      FINE_NOTICE_FIELDS.flatMap(({ key, serverKey }) =>
        normalizedIntake[key] ? [[serverKey, normalizedIntake[key]]] : []
      )
    );
  }
  return context;
}

function shouldCollectAccidentFacts(intake) {
  return (
    ACCIDENT_CONSULTATION_TYPES.has(intake.consultationType) ||
    CONSULTATION_FACT_FIELDS.some((field) => intake[field.key]) ||
    Boolean(intake.confirmedFacts || intake.userClaims || intake.missingDetails)
  );
}

function consultationTypeLabel(value) {
  const match = [...CONSULTATION_TYPE_OPTIONS, ...ACCIDENT_TYPE_OPTIONS].find(
    (option) => option.value === value
  );
  return match ? match.label : "";
}

function consultationRequestTypeLabel(value) {
  if (value === "fine_notice") {
    return "고지서 상담";
  }
  return consultationTypeLabel(value);
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
