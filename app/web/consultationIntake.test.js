import test from "node:test";
import assert from "node:assert/strict";
import * as consultationIntakeModule from "./consultationIntake.js";

import {
  CONSULTATION_TYPE_OPTIONS,
  buildStructuredConsultationMessage,
  createEmptyConsultationIntake,
  hasConsultationIntakeData,
  listConsultationIntakeMissingFields,
} from "./consultationIntake.js";

test("keeps structured context in the request but shows only the user's free text", () => {
  assert.equal(typeof consultationIntakeModule.buildConsultationMessagePair, "function");
  assert.deepEqual(
    consultationIntakeModule.buildConsultationMessagePair({
      freeText: "안녕하십니까 혹시 과실비율 측정은 어떻게 진행되는지요",
      intake: { consultationType: "general" },
    }),
    {
      displayText: "안녕하십니까 혹시 과실비율 측정은 어떻게 진행되는지요",
      requestText:
        "[상담 유형]\n일반 상담\n\n[자유 입력]\n안녕하십니까 혹시 과실비율 측정은 어떻게 진행되는지요",
    }
  );
});

test("builds a bounded fault-ratio request context with canonical fact keys", () => {
  assert.equal(typeof consultationIntakeModule.buildConsultationRequestContext, "function");
  assert.deepEqual(
    consultationIntakeModule.buildConsultationRequestContext({
      intake: {
        consultationType: "fault_ratio",
        roadLayout: "신호등 없는 사거리",
        vehicleActions: "저는 직진, 상대는 우측 진입",
        signalPriority: "표지 없음",
        collisionLocation: "제 우측 앞범퍼와 상대 좌측 앞범퍼",
      },
    }),
    {
      consultation_type: "fault_ratio",
      facts: {
        road_layout: "신호등 없는 사거리",
        vehicle_actions: "저는 직진, 상대는 우측 진입",
        signal_priority: "표지 없음",
        collision_location: "제 우측 앞범퍼와 상대 좌측 앞범퍼",
      },
    }
  );
});

test("builds the approved fine-notice slot request context", () => {
  assert.deepEqual(
    consultationIntakeModule.FINE_NOTICE_FIELDS.map(({ key, serverKey }) => [key, serverKey]),
    [
      ["documentDispositionType", "document_disposition_type"],
      ["issuingAuthority", "issuing_authority"],
      ["responseDeadline", "response_deadline"],
      ["attachmentAvailable", "attachment_available"],
    ]
  );
  assert.deepEqual(
    consultationIntakeModule.buildConsultationRequestContext({
      intake: {
        consultationType: "fine_notice",
        documentDispositionType: "과태료 사전통지서",
        issuingAuthority: "가상시청",
        responseDeadline: "2026-08-07",
        attachmentAvailable: "yes",
      },
    }),
    {
      consultation_type: "fine_notice",
      facts: {},
      fine_notice_slots: {
        document_disposition_type: "과태료 사전통지서",
        issuing_authority: "가상시청",
        response_deadline: "2026-08-07",
        attachment_available: "yes",
      },
    }
  );
});

test("does not turn arbitrary intake fields into server facts", () => {
  assert.deepEqual(
    consultationIntakeModule.buildConsultationRequestContext({
      intake: { consultationType: "general", confirmedFacts: "임의 텍스트" },
    }),
    { consultation_type: "general", facts: {} }
  );
});

test("supports general consultation without extra structured fields", () => {
  assert.ok(
    CONSULTATION_TYPE_OPTIONS.some(
      (option) => option.value === "general" && option.label === "일반 상담"
    )
  );
  assert.equal(
    buildStructuredConsultationMessage({
      freeText: "비보호 좌회전 관련 판례를 알려줘.",
      intake: { consultationType: "general" },
    }),
    "[상담 유형]\n일반 상담\n\n[자유 입력]\n비보호 좌회전 관련 판례를 알려줘."
  );
  assert.deepEqual(listConsultationIntakeMissingFields({ consultationType: "general" }), []);
});

test("returns plain free text when structured intake is empty", () => {
  assert.equal(
    buildStructuredConsultationMessage({
      freeText: "보험사에서 과실비율을 8:2라고 합니다.",
      intake: createEmptyConsultationIntake(),
    }),
    "보험사에서 과실비율을 8:2라고 합니다."
  );
  assert.equal(hasConsultationIntakeData(createEmptyConsultationIntake()), false);
});

test("builds a structured message with fact and claim sections", () => {
  const message = buildStructuredConsultationMessage({
    freeText: "블랙박스는 오늘 저녁에 올릴 수 있어요.",
    intake: {
      consultationType: "intersection",
      roadLayout: "신호 없는 사거리",
      vehicleActions: "저는 직진, 상대는 우측 골목에서 진입",
      signalPriority: "신호등은 없고 저는 대로였습니다.",
      collisionLocation: "제 차량 운전석 앞범퍼와 상대 조수석 뒤쪽",
      confirmedFacts: "사고 시각은 오후 7시 20분입니다.",
      userClaims: "상대방은 제가 속도를 냈다고 주장합니다.",
      missingDetails: "목격자 연락처는 아직 못 받았습니다.",
    },
  });

  assert.match(message, /\[상담 유형\]\n교차로 사고/);
  assert.match(message, /- 도로 형태: 신호 없는 사거리/);
  assert.match(message, /- 사고 시각은 오후 7시 20분입니다\./);
  assert.match(message, /\[사용자 주장\]/);
  assert.match(message, /\[추가 확인이 필요한 점\]/);
  assert.match(message, /\[자유 입력\]\n블랙박스는 오늘 저녁에 올릴 수 있어요\./);
});

test("lists only unresolved accident facts as missing", () => {
  const missing = listConsultationIntakeMissingFields({
    consultationType: "rear_end",
    roadLayout: "편도 3차선 도로",
    vehicleActions: "",
    signalPriority: "",
    collisionLocation: "제 차량 후면",
  });

  assert.deepEqual(
    missing.map((item) => item.key),
    ["vehicleActions", "signalPriority"]
  );
  assert.deepEqual(
    listConsultationIntakeMissingFields({
      consultationType: "fine_notice",
      confirmedFacts: "",
      userClaims: "",
    }),
    []
  );
});

test("builds fine notice details without requesting accident facts", () => {
  const intake = createEmptyConsultationIntake();
  intake.consultationType = "fine_notice";
  intake.documentDispositionType = "과태료 사전통지서";
  intake.issuingAuthority = "가상시청";
  intake.responseDeadline = "2026-08-07";
  intake.attachmentAvailable = "yes";

  const message = buildStructuredConsultationMessage({ intake });

  assert.match(message, /- 문서명·처분 유형: 과태료 사전통지서/);
  assert.match(message, /- 발급기관: 가상시청/);
  assert.match(message, /- 제출 기한: 2026-08-07/);
  assert.match(message, /- 첨부 가능 여부: yes/);
  assert.doesNotMatch(message, /상담 질문/);
  assert.deepEqual(listConsultationIntakeMissingFields(intake), []);
});

test("requests detailed accident facts only for fault ratio", () => {
  assert.deepEqual(
    listConsultationIntakeMissingFields({
      consultationType: "fault_ratio",
    }).map((item) => item.key),
    ["roadLayout", "vehicleActions", "signalPriority", "collisionLocation"]
  );
  assert.deepEqual(
    listConsultationIntakeMissingFields({
      consultationType: "fine_notice",
      documentDispositionType: "과태료 사전통지서",
      issuingAuthority: "가상시청",
      responseDeadline: "2026-08-07",
      attachmentAvailable: "yes",
    }),
    []
  );
});
