# Mypage Case Report Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each case in My Page open its own saved report and present the existing report data in the approved card-based detail layout.

**Architecture:** Keep the existing case, report, authentication, download, and routing APIs. Add one small pure helper for associating reports with cases, pass the existing report list into `MyPageScreen`, and restyle the existing `ReportingScreen` content without creating a parallel report route.

**Tech Stack:** React 19, Vite 7, native CSS, Node.js built-in test runner

## Global Constraints

- Do not add an API, dependency, sample report value, or external video.
- Reuse `openReportDetail()`, `ReportingScreen`, `currentReport`, `reportingPayload`, `analysisCards`, and `supervisorExecution`.
- Preserve login, upload, chat, save, DOCX download, and top-navigation behavior.
- Missing values display `확인된 자료 없음`.

---

### Task 1: Associate Saved Reports with Cases

**Files:**
- Create: `app/web/caseReports.js`
- Create: `app/web/caseReports.test.js`

**Interfaces:**
- Consumes: case objects and report objects returned by existing APIs
- Produces: `reportsForCase(caseItem, reports)` returning matching reports without duplicates

- [ ] **Step 1: Write the failing test**

```js
import test from "node:test";
import assert from "node:assert/strict";
import { reportsForCase } from "./caseReports.js";

test("returns only reports linked to the selected case", () => {
  const reports = [
    { report_id: "R-1", metadata: { case_id: "C-1" } },
    { report_id: "R-2", metadata: { case_id: "C-2" } },
  ];
  assert.deepEqual(reportsForCase({ case_id: "C-1", latest_report_id: "R-1" }, reports), [reports[0]]);
  assert.deepEqual(reportsForCase({ case_id: "C-2" }, reports), [reports[1]]);
});

test("returns no report when the case has no report link", () => {
  assert.deepEqual(reportsForCase({ case_id: "C-3" }, [{ report_id: "R-1" }]), []);
});
```

- [ ] **Step 2: Run the test and verify failure**

Run: `node --test app/web/caseReports.test.js`

Expected: FAIL because `caseReports.js` does not exist.

- [ ] **Step 3: Implement the pure matcher**

```js
export function reportsForCase(item = {}, reports = []) {
  const caseId = item.case_id || item.job_id || "";
  const directIds = new Set([item.latest_report_id, item.report_id].filter(Boolean));
  return reports.filter((report) => {
    const reportCaseId = report.case_id || report.metadata?.case_id || "";
    return directIds.has(report.report_id) || Boolean(caseId && reportCaseId === caseId);
  });
}
```

- [ ] **Step 4: Run the test and verify pass**

Run: `node --test app/web/caseReports.test.js`

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/web/caseReports.js app/web/caseReports.test.js
git commit -m "test: cover case report association"
```

### Task 2: Add Case-Level Report Actions to My Page

**Files:**
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/web/styles.css`

**Interfaces:**
- Consumes: `reportsForCase()`, `effectiveReportList`, `openReportDetail()`, `openSavedCase()`
- Produces: `리포트 자세히 보기` or `리포트 생성 필요` and `AI 상담 이어가기` per case

- [ ] **Step 1: Import the matcher and pass report props**

Add:

```js
import { reportsForCase } from "./caseReports.js";
```

Pass `reports={effectiveReportList}` and an `onOpenReport` callback to `MyPageScreen`. The callback must await `openReportDetail(report)` and then call `setActiveRoute("reporting")`.

- [ ] **Step 2: Render the correct action for each selected case**

Inside `MyPageScreen`, derive:

```js
const selectedCaseReports = reportsForCase(selectedCase, reports);
```

Render one `리포트 자세히 보기` button for each matched report. When the array is empty, render `리포트 생성 필요` and reuse `onOpenCase(selectedCase)` for `AI 상담 이어가기`.

- [ ] **Step 3: Add minimal responsive styles**

Add styles for `.case-report-actions`, `.case-report-action`, and `.case-report-empty` using existing `--brand`, `--line`, `--muted`, and `.button` tokens.

- [ ] **Step 4: Run checks**

Run:

```bash
node --test app/web/caseReports.test.js
docker compose run --rm frontend npm run build
```

Expected: tests pass and Vite build exits 0.

- [ ] **Step 5: Commit**

```bash
git add app/web/FrontendAppShell.jsx app/web/styles.css
git commit -m "feat: open reports from mypage cases"
```

### Task 3: Apply the Card-Based Report Detail Layout

**Files:**
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/web/styles.css`

**Interfaces:**
- Consumes: existing `activeReportingPayload`, `sections`, `analysisCards`, `nodeResults`, `currentReport`
- Produces: the approved report header, ratio, facts, references, and vision cards inside `ReportingScreen`

- [ ] **Step 1: Reorder existing report content**

Keep the existing report list and actions. In the report detail canvas, display:

```text
사건 메타데이터
AI 추정 과실비율 + 한계 안내
사고 정황 요약
관련 법령·유사 사례·판단 근거
영상 분석 결과·주요 시점
저장·DOCX 작업
```

Use current payload values only. Every empty section renders `확인된 자료 없음`.

- [ ] **Step 2: Reuse existing evidence values**

Use `groupReportSections(sections)`, `analysisCards`, and `nodeResults`; do not copy values from `message.txt`. Show a native `<video controls>` only when the current report provides a playable URL. Otherwise render the missing-data message.

- [ ] **Step 3: Add layout styles**

Add `.case-report-detail`, `.case-report-ratio`, `.case-report-grid`, `.case-report-facts`, `.case-report-references`, and `.case-report-vision`. Use the existing navy palette and collapse two columns to one below 860px.

- [ ] **Step 4: Verify preserved actions**

Confirm the existing save, report selection, login, copy, and DOCX buttons still call their original callbacks.

- [ ] **Step 5: Run checks**

Run:

```bash
node --test app/web/caseReports.test.js
docker compose run --rm frontend npm run build
```

Expected: tests pass and Vite build exits 0.

- [ ] **Step 6: Commit**

```bash
git add app/web/FrontendAppShell.jsx app/web/styles.css
git commit -m "feat: restyle case report detail"
```

### Task 4: Browser Verification

**Files:**
- No source changes expected

**Interfaces:**
- Consumes: running frontend and backend
- Produces: verified user flow without FR, push, or merge

- [ ] **Step 1: Start the isolated stack**

Run: `docker compose up -d --build`

- [ ] **Step 2: Verify case flows**

Check:

1. Two cases with different reports open different report IDs.
2. A case without a report shows `리포트 생성 필요`.
3. `AI 상담 이어가기` opens the existing saved consultation.
4. Report detail contains the approved five content groups.
5. Existing save and DOCX actions remain available.

- [ ] **Step 3: Re-run final checks**

Run:

```bash
git diff --check
git status --short
node --test app/web/caseReports.test.js
docker compose run --rm frontend npm run build
```

Expected: no whitespace errors, only intentional files changed, tests pass, and build exits 0.
