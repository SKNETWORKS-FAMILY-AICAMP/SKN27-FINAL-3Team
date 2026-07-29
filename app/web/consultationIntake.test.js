import test from "node:test";
import assert from "node:assert/strict";

import {
  buildStructuredConsultationMessage,
  createEmptyConsultationIntake,
  hasConsultationIntakeData,
  listConsultationIntakeMissingFields,
} from "./consultationIntake.js";

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
  intake.violationDate = "2026-07-29";
  intake.violationLocation = "서울시 강남구";
  intake.violationType = "신호 위반";
  intake.fineQuestion = "이의신청이 가능한가요?";

  const message = buildStructuredConsultationMessage({ intake });

  assert.match(message, /2026-07-29/);
  assert.match(message, /서울시 강남구/);
  assert.match(message, /신호 위반/);
  assert.match(message, /이의신청이 가능한가요/);
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
      violationDate: "2026-07-29",
      violationLocation: "서울시 강남구",
      violationType: "신호 위반",
      fineQuestion: "이의신청이 가능한가요?",
    }),
    []
  );
});
