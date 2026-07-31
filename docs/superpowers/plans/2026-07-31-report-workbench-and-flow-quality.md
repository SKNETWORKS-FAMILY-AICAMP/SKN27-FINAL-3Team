# 리포트 작업대 상시 진입과 사용자 흐름 품질 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 리포트 작업대를 상시 진입 가능하게 만들고, 리포트가 없는 사용자가 현재 단계·부족 자료·다음 행동을 확인하게 하며, 전체 사용자 흐름의 E2E·에이전트·품질 핫픽스를 추적한다.

**Architecture:** 순수 프런트엔드 상태 모듈이 공개 가능한 상담 상태를 다섯 작업대 상태로 정규화한다. `FrontendAppShell`은 그 상태를 `ReportingScreen`에 전달하고, 기존 저장·문서·로그인 API 계약은 유지한다. 기술 체크리스트는 배포 전 결정적 통합 검증과 배포 후 실제 연동 스모크를 분리해 기록한다.

**Tech Stack:** React 19, Vite 7, Node test runner, Python pytest, Django HTTP E2E, Markdown.

## Global Constraints

- 일반 법령 질문을 리포트 생성으로 전환하지 않는다.
- 리포트 저장·DOCX 다운로드·Google 로그인·신원 노출 확인의 기존 정책을 바꾸지 않는다.
- 빈 작업대에는 공개 가능한 상태 필드만 표시하고 OCR 원문·내부 실행 payload·저장소 URI·식별 정보는 표시하지 않는다.
- 외부 OCR/Vision/LLM 유료 실연동은 별도 승인 전 실행하지 않는다.

---

### Task 1: 작업대 상태 모델과 단위 테스트

**Files:**

- Create: `app/web/reportWorkbenchState.js`
- Create: `app/web/reportWorkbenchState.test.js`

**Interfaces:**

- Produces: `deriveReportWorkbenchState({ hasReport, hasSavedReports, canGenerateReport, reportingPayload, supervisorState })`.
- Returns: `{ kind, stageLabel, title, description, missingItems, ctaLabel }` where `kind` is one of `available`, `persisting`, `needs_information`, `not_reportable`, `not_started`.

- [ ] **Step 1: Write failing Node tests**

```js
test('describes unresolved supervisor facts as a workbench action', () => {
  const state = deriveReportWorkbenchState({
    hasReport: false,
    hasSavedReports: false,
    canGenerateReport: true,
    reportingPayload: null,
    supervisorState: {
      stage: 'follow_up_required',
      missing_fields: ['충돌 부위'],
      next_questions: ['양쪽 차량의 충돌 부위를 알려주세요.'],
    },
  });
  assert.equal(state.kind, 'needs_information');
  assert.deepEqual(state.missingItems, ['충돌 부위']);
  assert.equal(state.ctaLabel, 'AI 상담으로 이동');
});
```

- [ ] **Step 2: Run the new test and verify RED**

Run: `node --test reportWorkbenchState.test.js`

Expected: FAIL because the state module does not exist.

- [ ] **Step 3: Implement the smallest state mapper**

Implement only the five documented states. De-duplicate and trim missing fields/questions, retain at most three items, and return Korean copy from the mapper so the presentation component remains declarative.

- [ ] **Step 4: Run Node tests and existing frontend tests**

Run: `node --test reportWorkbenchState.test.js *.test.js`

Expected: PASS.

### Task 2: 좌측 메뉴와 빈 작업대 화면

**Files:**

- Modify: `app/web/FrontendAppShell.jsx:2023-2053`
- Modify: `app/web/FrontendAppShell.jsx:1757-1778,4301-4679`
- Modify: `app/web/styles.css`
- Create: `test/test_report_workbench_frontend_contract.py`

**Interfaces:**

- Consumes: `deriveReportWorkbenchState` and the existing `ReportingScreen` props.
- Produces: always reachable `reporting` rail item and `ReportWorkbenchEmptyState` for a workspace without a report.

- [ ] **Step 1: Write a failing static UI contract test**

Assert that `RAIL_ITEMS` contains `{ id: "reporting", label: "리포트 작업대" }`, `ReportingScreen` receives `canGenerateReport`, and `ReportWorkbenchEmptyState` is rendered when `hasReport` is false.

- [ ] **Step 2: Run the focused pytest and verify RED**

Run: `python -m pytest -q test/test_report_workbench_frontend_contract.py`

Expected: FAIL because no rail item or empty-state component exists.

- [ ] **Step 3: Add the rail item and empty-state component**

Import the state mapper, pass `canGenerateReport={hasReportGenerationNode(supervisorState)}` from the shell, and render a status card with the state label, user-safe missing items, and `onOpenChat`. Preserve the existing report canvas and inspector when `hasReport` is true.

- [ ] **Step 4: Add focused responsive styles**

Add styles only for `.report-workbench-empty`, its status badge, missing-item list, and action area. Reuse existing button, panel, tag, and responsive breakpoints.

- [ ] **Step 5: Run targeted tests and production build**

Run:

```powershell
python -m pytest -q test/test_report_workbench_frontend_contract.py test/test_consultation_v2_contract.py test/test_frontend_report_api_contract.py
node --test reportWorkbenchState.test.js *.test.js
npm run build
```

Expected: PASS.

### Task 3: 핫픽스·E2E·품질 체크리스트

**Files:**

- Create: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-checklist.md`
- Modify: `docs/superpowers/specs/2026-07-31-report-workbench-and-flow-quality-design.md`

**Interfaces:**

- Consumes: scenario results, agent evidence, source commit, and issue IDs.
- Produces: `HFX-*` records with issue type, priority, exact reproduction, expected/actual behavior, owner, fix evidence, and retest state.

- [ ] **Step 1: Record confirmed current issues and Excel mappings**

Create records for the report workbench discoverability defect and the four existing Excel rows. Mark unexecuted E2E and provider flows as `검증 대기`, not complete.

- [ ] **Step 2: Add the full user-flow matrix**

Cover home/navigation, guest session, fine notice text/OCR/appeal, fault facts/Vision, general law, report readiness/empty state, login/save/mypage, ownership, errors, and recovery.

- [ ] **Step 3: Add agent and quality acceptance criteria**

For every flow, record required agent nodes, safe evidence, expected quality signals, failure classification, and whether live provider spend is required.

### Task 4: 결정적 통합과 배포 후 재검증

**Files:**

- Modify: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-checklist.md`
- Modify: `docs/tech-validation-reports/2026-07-31-pilot-post-deploy-e2e-retest-report.md` when a deployment exists

- [ ] **Step 1: Run deterministic Django E2E suites**

Run the existing canonical, guest-login ownership, supervisor reporting, report API, attachment handoff, and agent node test modules with external providers replaced by fixtures.

- [ ] **Step 2: Run browser smoke in the deployed Pilot**

Use only synthetic information. Capture only safe request status, UI state, generated report ID, and visible status; never store authorization codes, OCR text, uploads, or user personal data in Markdown.

- [ ] **Step 3: Request explicit approval before paid OCR/Vision/LLM scenarios**

If full real-provider runs are required, state the exact scenarios and expected cost-bearing services before submitting data.

- [ ] **Step 4: Update each HFX item with evidence**

Set `완료` only when the relevant test/build and user-visible retest both pass. Otherwise preserve `원인 확인`, `수정 대기`, or `재검증 필요`.
