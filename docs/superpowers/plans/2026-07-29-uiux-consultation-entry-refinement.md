# UI/UX Consultation Entry Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로그인 후 상담 이동을 복구하고, 중복 CTA와 색상 문제를 정리하며, 과태료·과실비율 유형별 입력만 조건부로 표시한다.

**Architecture:** 기존 `FrontendAppShell.jsx`의 라우팅과 첨부·전송 흐름을 재사용한다. 입력 데이터의 생성·정규화·메시지 조립은 기존 `consultationIntake.js`에 유지하고 화면은 선택된 상위 유형에 따라 필요한 필드만 렌더링한다.

**Tech Stack:** React, CSS, Node.js built-in test runner, Python pytest source-contract tests

## Global Constraints

- `dev` 최신 상태에서 작업한다.
- Vision 파일과 백엔드 API 계약은 변경하지 않는다.
- 기존 로그인, 게스트 세션, 첨부파일, 상담 전송 연결을 재사용한다.
- 신규 의존성을 추가하지 않는다.

---

### Task 1: 상담 이동과 중복 CTA 수정

**Files:**
- Modify: `app/web/FrontendAppShell.jsx`
- Test: `test/test_ui_v3_frontend_contract.py`

**Interfaces:**
- Consumes: 기존 `ensureGuestSession(nextRoute)` 함수
- Produces: 로그인·게스트 상태 모두에서 재사용되는 상담 진입 핸들러

- [ ] **Step 1: 실패하는 화면 계약 테스트 작성**

`test_ui_v3_frontend_contract.py`에 상담 버튼이 기존 세션을 재사용하고 사고 가이드에 상담 CTA가 하나만 존재하는지 검증한다.

```python
assert 'onOpenChat={() => ensureGuestSession("chatbot")}' in source
guide_source = source[source.index("function GuideScreen"):source.index("function EntryScreenWheelLegacy")]
assert guide_source.count("AI 상담 시작") == 1
assert "사고 접수하기" not in guide_source
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest test/test_ui_v3_frontend_contract.py -q`
Expected: 기존 `bootstrapGuestSession` 직접 호출과 중복 버튼 때문에 FAIL

- [ ] **Step 3: 최소 구현**

상단·메인·가이드가 `ensureGuestSession("chatbot")`을 사용하도록 공통 콜백을 전달하고, 가이드의 `사고 접수하기` 버튼만 제거한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest test/test_ui_v3_frontend_contract.py -q`
Expected: PASS

### Task 2: 과태료·과실비율 입력 모델 분리

**Files:**
- Modify: `app/web/consultationIntake.js`
- Modify: `app/web/consultationIntake.test.js`

**Interfaces:**
- Produces: `consultationType` 값 `fine_notice | fault_ratio`
- Produces: 과태료 필드 `violationDate`, `violationLocation`, `violationType`, `fineQuestion`
- Produces: 과실비율 필드 `accidentType`, 기존 사고 사실 필드와 주장 필드

- [ ] **Step 1: 실패하는 입력 모델 테스트 작성**

```javascript
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
  assert.deepEqual(listConsultationIntakeMissingFields(intake), []);
});

test("requests detailed accident facts only for fault ratio", () => {
  assert.deepEqual(
    listConsultationIntakeMissingFields({ consultationType: "fault_ratio" }).map((item) => item.key),
    ["roadLayout", "vehicleActions", "signalPriority", "collisionLocation"]
  );
});
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `node --test app/web/consultationIntake.test.js`
Expected: 신규 유형과 필드가 없어 FAIL

- [ ] **Step 3: 최소 구현**

기존 정규화와 메시지 조립 함수에 상위 유형과 과태료 필드만 추가하고, 사고 사실 누락 검사는 `fault_ratio`에서만 수행한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `node --test app/web/consultationIntake.test.js`
Expected: PASS

### Task 3: 유형별 조건부 화면과 색상 수정

