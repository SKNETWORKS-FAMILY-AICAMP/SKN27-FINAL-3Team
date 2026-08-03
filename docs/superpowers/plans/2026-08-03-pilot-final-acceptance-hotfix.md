# Pilot Final Acceptance Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix only the four confirmed pilot defects, produce one final `dev` SHA, and verify the complete production journey in external Chrome.

**Architecture:** Keep message transport, case-readiness, report truthfulness, and public law projection as four independent change units on one branch. Each unit adds a focused regression test before the minimal implementation, preserves existing API and persistence contracts, and ends in its own commit. Deployment and browser acceptance occur only after every local suite and the production build pass for the combined branch.

**Tech Stack:** React 19, JavaScript ES modules, Node test runner, Vite 7, Python 3, pytest, Django test runner, existing Case API and Supervisor service boundaries.

## Global Constraints

- Base all implementation on the latest `origin/dev` and keep branch name `feat-pilot-final-acceptance-hotfix`.
- Modify only the four approved defect areas; do not add consultation types, report types, OCR fields, routes, pages, jobs, APIs, providers, or persistence fields.
- Do not modify `ai/**`, `etl/**`, database models, migrations, AWS pipeline definitions, deployment scripts, infrastructure, Case API contracts, report API contracts, OCR providers, or legal retrieval engines.
- Do not change the backend material-evidence policy, Supervisor reducer, or Supervisor AI engine.
- Keep automatic attachment, OCR-confirmation, and classification-confirmation messages distinct from manual composer answers.
- Do not expose raw exceptions, request payloads, OCR text, storage URIs, internal identifiers, tokens, cookies, or personal information.
- Preserve the user-owned untracked validation reports and `docs/tech-validation-reports/evidence/`; do not stage, edit, or delete them.
- Use red-green-refactor for every production change and keep the four fixes in separate commits.
- Deploy only the final merged `dev` SHA after Source and Build succeed for that exact SHA.

## File Responsibility Map

- `app/web/consultationIntake.js`: pure structured-message, pending-question, and transport-text selection.
- `app/web/consultationIntake.test.js`: manual follow-up, initial request, restored pending question, and automatic service-message transport contracts.
- `app/web/FrontendAppShell.jsx`: connect the pure selectors to the existing chat submission, case error, and report rendering boundaries without changing APIs.
- `app/web/caseReadyWorkflow.js`: build evidence-backed Case API payloads and fixed public workflow-error messages.
- `app/web/caseReadyWorkflow.test.js`: evidence-source eligibility, restored attachment, error mapping, and Case API sequencing contracts.
- `app/web/reportWorkbenchState.js`: decide whether a temporary reporting payload has visible report content.
- `app/web/reportWorkbenchState.test.js`: empty, meaningful temporary, and authoritative persisted-report state contracts.
- `app/services/public_law_projection_service.py`: remove malformed table fragments from optional public law summaries while retaining verified labels.
- `test/test_public_law_projection_service.py`: public projection allowlist and malformed-pipe regression.
- `test/test_supervisor_control_service.py`: final fine-notice answer remains readable after public projection.

---

### Task 1: Manual Follow-up Transport Without Structured Labels

**Files:**
- Modify: `app/web/consultationIntake.js:166-174`
- Modify: `app/web/consultationIntake.test.js:1-38`
- Modify: `app/web/FrontendAppShell.jsx:32-41, 947, 1392-1532`

**Interfaces:**
- Consumes: `displayText` and `requestText` from `buildConsultationMessagePair`, normalized top-level pending questions, `supervisor_state.next_questions`, and a submission kind of `manual` or `service`.
- Produces: `hasPendingConsultationQuestion({ pendingQuestions, supervisorQuestions }) -> boolean` and `selectConsultationTransportText({ displayText, requestText, hasPendingQuestion, submissionKind }) -> string`.

- [ ] **Step 1: Add failing pure-function tests**

Add these imports and tests to `app/web/consultationIntake.test.js`:

```js
import {
  CONSULTATION_TYPE_OPTIONS,
  buildStructuredConsultationMessage,
  createEmptyConsultationIntake,
  hasConsultationIntakeData,
  hasPendingConsultationQuestion,
  listConsultationIntakeMissingFields,
  selectConsultationTransportText,
} from "./consultationIntake.js";

test("uses plain display text only for a manual pending-question answer", () => {
  const pair = consultationIntakeModule.buildConsultationMessagePair({
    freeText: "2차로 회전교차로",
    intake: { consultationType: "fault_ratio", accidentType: "intersection" },
  });

  assert.equal(
    selectConsultationTransportText({
      ...pair,
      hasPendingQuestion: true,
      submissionKind: "manual",
    }),
    "2차로 회전교차로",
  );
  assert.doesNotMatch(
    selectConsultationTransportText({
      ...pair,
      hasPendingQuestion: true,
      submissionKind: "manual",
    }),
    /\[상담 유형\]|\[사고 유형\]|\[자유 입력\]/,
  );
});

test("keeps structured transport for initial and automatic service messages", () => {
  const pair = consultationIntakeModule.buildConsultationMessagePair({
    freeText: "첨부한 자료를 확인해 주세요.",
    intake: { consultationType: "fault_ratio", accidentType: "intersection" },
  });

  assert.equal(
    selectConsultationTransportText({
      ...pair,
      hasPendingQuestion: false,
      submissionKind: "manual",
    }),
    pair.requestText,
  );
  assert.equal(
    selectConsultationTransportText({
      ...pair,
      hasPendingQuestion: true,
      submissionKind: "service",
    }),
    pair.requestText,
  );
});

test("detects pending questions from live and restored response shapes", () => {
  assert.equal(
    hasPendingConsultationQuestion({
      pendingQuestions: [{ field: "road_layout" }],
      supervisorQuestions: [],
    }),
    true,
  );
  assert.equal(
    hasPendingConsultationQuestion({
      pendingQuestions: [],
      supervisorQuestions: [{ field: "vehicle_actions" }],
    }),
    true,
  );
  assert.equal(
    hasPendingConsultationQuestion({ pendingQuestions: [], supervisorQuestions: [] }),
    false,
  );
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
node --test app/web/consultationIntake.test.js
```

Expected: FAIL because `hasPendingConsultationQuestion` and `selectConsultationTransportText` are not exported.

- [ ] **Step 3: Implement the two pure selectors**

Add after `buildConsultationMessagePair` in `app/web/consultationIntake.js`:

```js
export function hasPendingConsultationQuestion({
  pendingQuestions = [],
  supervisorQuestions = [],
} = {}) {
  return [pendingQuestions, supervisorQuestions].some(
    (questions) => Array.isArray(questions) && questions.length > 0,
  );
}

export function selectConsultationTransportText({
  displayText = "",
  requestText = "",
  hasPendingQuestion = false,
  submissionKind = "manual",
} = {}) {
  const display = normalizeText(displayText);
  const request = normalizeText(requestText);
  if (submissionKind === "manual" && hasPendingQuestion && display) {
    return display;
  }
  return request || display;
}
```

- [ ] **Step 4: Wire manual and service submissions explicitly**

Import both selectors in `app/web/FrontendAppShell.jsx`. Add `submissionKind = "manual"` to the `submitServiceMessage` parameter object. Pass `submissionKind: "service"` from attachment scan completion, OCR confirmation, and attachment-classification confirmation.

Inside `submitServiceMessage`, compute one transport value and use it for both server fields:

```js
const hasPendingQuestion = hasPendingConsultationQuestion({
  pendingQuestions: responsePresentation?.pendingQuestions,
  supervisorQuestions: supervisorState?.next_questions,
});
const transportText = selectConsultationTransportText({
  displayText,
  requestText: composedQuestion,
  hasPendingQuestion,
  submissionKind,
});
```

Replace only the current-turn server values:

```js
const requestConversationHistory = [
  ...conversationHistory.slice(0, -1),
  { role: "user", content: transportText },
];
```

In the existing `chatPayload` object, change exactly `user_text: composedQuestion` to `user_text: transportText` and retain `conversation_history: requestConversationHistory`. Do not add or remove any other payload property.

Do not change `displayText`, `consultation_type`, `facts`, `fine_notice_slots`, authentication, guest recovery, or attachment payload construction.

- [ ] **Step 5: Run focused and adjacent regressions**

Run:

```powershell
node --test app/web/consultationIntake.test.js app/web/attachmentScanWorkflow.test.js app/web/chatResponsePresentation.test.js
python -m pytest test/test_chat_orchestration_service.py test/test_chat_session_followup_service.py -q
```

Expected: all tests PASS; initial structured requests retain their sections and manual pending answers contain no structured labels.

- [ ] **Step 6: Commit Task 1 only**

```powershell
git add -- app/web/consultationIntake.js app/web/consultationIntake.test.js app/web/FrontendAppShell.jsx
git diff --cached --check
git commit -m "fix: keep follow-up facts free of intake labels"
```

---

### Task 2: Evidence-Backed Case-Ready Gate and Public Error

**Files:**
- Modify: `app/web/caseReadyWorkflow.js:52-118`
- Modify: `app/web/caseReadyWorkflow.test.js:12-178, 435-493`
- Modify: `app/web/FrontendAppShell.jsx:1297-1372`

**Interfaces:**
- Consumes: current React attachments, public restored `analysisResponse.attachments`, accepted target-document OCR evidence, existing Case API error objects with `error.code`.
- Produces: `buildCaseReadyViewModel(analysisResponse = {}, registeredAttachments = []) -> object` with `eligible === true` only when `confirmationPayload.sources` is non-empty, plus `caseReadyWorkflowErrorMessage(error) -> string`.

- [ ] **Step 1: Add failing evidence-gate and error-message tests**

Import `caseReadyWorkflowErrorMessage` and add these tests to `app/web/caseReadyWorkflow.test.js`:

```js
test("requires material evidence before offering case analysis", () => {
  const withoutEvidence = buildCaseReadyViewModel(completeResponse());
  const scanningEvidence = buildCaseReadyViewModel(completeResponse(), [
    { attachment_id: "att_scanning", status: "scanning", scan_status: "scanning" },
  ]);

  assert.equal(withoutEvidence.eligible, false);
  assert.deepEqual(withoutEvidence.confirmationPayload.sources, []);
  assert.equal(scanningEvidence.eligible, false);
});

test("accepts a restored clean attachment without a new attachment API call", () => {
  const response = completeResponse();
  response.attachments = [
    {
      attachment_id: "att_restored_clean",
      purpose: "traffic_accident_confirmation",
      scan_status: "clean",
    },
  ];

  const model = buildCaseReadyViewModel(response, []);

  assert.equal(model.eligible, true);
  assert.deepEqual(model.confirmationPayload.sources, [
    { source_type: "official_document", source_ref: "att_restored_clean" },
  ]);
});

test("maps fact readiness rejection to fixed safe public copy", () => {
  assert.equal(
    caseReadyWorkflowErrorMessage({ code: "fact_readiness_not_met" }),
    "첨부 자료의 안전 검사를 완료한 뒤 사건 분석을 다시 시도해 주세요.",
  );
  assert.equal(
    caseReadyWorkflowErrorMessage(new Error("private backend detail")),
    "사건 분석 리포트를 완료하지 못했습니다. 입력과 자료 상태를 확인해 주세요.",
  );
});
```

Replace successful test setup calls that currently use `buildCaseReadyViewModel(completeResponse())` with this helper:

```js
function eligibleModel() {
  return buildCaseReadyViewModel(completeResponse(), [
    { attachment_id: "att_case_ready", status: "ready", scan_status: "clean" },
  ]);
}
```

Use `eligibleModel()` only in tests that are meant to reach Case API calls or show the case-start action. Keep explicit ineligible tests source-free.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
node --test app/web/caseReadyWorkflow.test.js
```

Expected: FAIL because source-free `case_ready` is still eligible, restored clean attachments are ignored, and the error helper is missing.

- [ ] **Step 3: Build and deduplicate sources before eligibility**

In `buildCaseReadyViewModel`, build current and restored ready IDs separately:

```js
const readyAttachmentIds = (Array.isArray(registeredAttachments) ? registeredAttachments : [])
  .filter((item) => (
    item
    && typeof item === "object"
    && item.status === "ready"
    && nonEmpty(item.attachment_id)
  ))
  .map((item) => String(item.attachment_id).trim());

const restoredReadyAttachmentIds = (
  Array.isArray(analysisResponse?.attachments) ? analysisResponse.attachments : []
)
  .filter((item) => (
    item
    && typeof item === "object"
    && item.scan_status === "clean"
    && nonEmpty(item.attachment_id)
  ))
  .map((item) => String(item.attachment_id).trim());
```

Merge these IDs with the existing accepted OCR IDs, build `sources`, and calculate `eligible` afterward with `sources.length > 0` added to the existing conditions. Do not change source type, Case payload shape, fact values, conflicts, or OCR storage filtering.

- [ ] **Step 4: Add the fixed public error mapper and use it in the shell**

Add to `app/web/caseReadyWorkflow.js`:

```js
export function caseReadyWorkflowErrorMessage(error) {
  if (error?.code === "fact_readiness_not_met") {
    return "첨부 자료의 안전 검사를 완료한 뒤 사건 분석을 다시 시도해 주세요.";
  }
  return "사건 분석 리포트를 완료하지 못했습니다. 입력과 자료 상태를 확인해 주세요.";
}
```

Import it in `FrontendAppShell.jsx`, change `catch {` to `catch (error) {`, compute `const publicMessage = caseReadyWorkflowErrorMessage(error)`, and use that fixed value for the progress error and status message. Do not render `error.message`, `error.payload`, or `error.details`.

- [ ] **Step 5: Run focused and contract regressions**

Run:

```powershell
node --test app/web/caseReadyWorkflow.test.js app/web/attachmentScanWorkflow.test.js
python -m pytest test/test_consultation_v2_contract.py test/test_chat_orchestration_service.py -q
python backend/manage.py test chatbot.test_consultation_v2 -v 1
```

Expected: all tests PASS; evidence-free UI is ineligible while the unchanged backend Case contract continues to pass.

- [ ] **Step 6: Commit Task 2 only**

```powershell
git add -- app/web/caseReadyWorkflow.js app/web/caseReadyWorkflow.test.js app/web/FrontendAppShell.jsx
git diff --cached --check
git commit -m "fix: require ready evidence before case analysis"
```

---

### Task 3: Truthful Temporary and Persisted Report States

**Files:**
- Modify: `app/web/reportWorkbenchState.js:1-112`
- Modify: `app/web/reportWorkbenchState.test.js:1-139`
- Modify: `app/web/FrontendAppShell.jsx:44-47, 418-425, 5154-5185, 5821-5832`

**Interfaces:**
- Consumes: a possible live `reporting_payload`, `supervisor_state`, and an already-hydrated persisted report with `report_id` plus `content.reporting_payload`.
- Produces: `hasMeaningfulReportingPayload(value) -> boolean`; live payloads require a summary, section, or document card, while persisted report detail remains authoritative.

- [ ] **Step 1: Add failing meaningful-payload tests and correct the old skeletal expectation**

Update the import and add these cases to `app/web/reportWorkbenchState.test.js`:

```js
import {
  compactUniqueStrings,
  deriveReportWorkbenchState,
  hasMeaningfulReportingPayload,
} from "./reportWorkbenchState.js";

test("rejects empty and skeletal temporary reporting payloads", () => {
  assert.equal(hasMeaningfulReportingPayload(null), false);
  assert.equal(hasMeaningfulReportingPayload({}), false);
  assert.equal(
    hasMeaningfulReportingPayload({ report_type: "general", sections: [] }),
    false,
  );
  assert.equal(hasMeaningfulReportingPayload({ summary: "   " }), false);
});

test("accepts temporary payloads with visible report content", () => {
  assert.equal(hasMeaningfulReportingPayload({ summary: "사고 분석 요약" }), true);
  assert.equal(
    hasMeaningfulReportingPayload({ sections: [{ title: "사고 개요", items: ["직진 중 충돌"] }] }),
    true,
  );
  assert.equal(
    hasMeaningfulReportingPayload({ document_cards: [{ type: "objection_draft" }] }),
    true,
  );
});

test("does not turn a skeletal live payload into an active report canvas", () => {
  const state = deriveReportWorkbenchState({
    hasReport: true,
    hasSavedReports: false,
    canGenerateReport: false,
    isPersistedReport: false,
    reportingPayload: { report_type: "general", sections: [] },
    supervisorState: {
      stage: "agent_execution_ready",
      missing_fields: [],
      next_questions: [],
    },
  });

  assert.equal(state.kind, "not_reportable");
});
```

Change the existing temporary-preview fixture from an empty `sections` array to a visible section:

```js
reportingPayload: {
  report_type: "fault_ratio_analysis",
  sections: [{ title: "사고 개요", items: ["확인된 사고 사실"] }],
},
```

Keep the persisted-report test with `report_id` so the existing authoritative contract stays covered.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
node --test app/web/reportWorkbenchState.test.js
```

Expected: FAIL because `hasMeaningfulReportingPayload` is not exported and the skeletal payload is still treated as a preview.

- [ ] **Step 3: Implement the pure temporary-payload predicate**

Add near the top of `app/web/reportWorkbenchState.js`:

```js
export function hasMeaningfulReportingPayload(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const hasSummary = typeof value.summary === "string" && Boolean(value.summary.trim());
  const hasSections = Array.isArray(value.sections) && value.sections.length > 0;
  const hasDocumentCards =
    Array.isArray(value.document_cards) && value.document_cards.length > 0;
  return hasSummary || hasSections || hasDocumentCards;
}
```

In `deriveReportWorkbenchState`, calculate the effective state from the payload contract rather than trusting a caller's truthy flag:

```js
const hasMeaningfulPayload = hasMeaningfulReportingPayload(reportingPayload);
const effectiveHasReport = isPersistedReport || hasMeaningfulPayload;

if (hasSavedReports && !savedReportDetailLoaded && !hasMeaningfulPayload) {
  return {
    kind: "loading_saved_report",
    stageLabel: "저장 리포트 불러오는 중",
    title: "저장된 리포트를 작업대에 연결하고 있습니다.",
    description: "목록 요약이 아니라 리포트 본문과 근거를 확인한 뒤 표시합니다.",
    missingItems: [],
    ctaLabel: "목록 새로고침",
  };
}

if (hasMeaningfulPayload && !isPersistedReport) {
  return {
    kind: "temporary_preview",
    stageLabel: "임시 리포트 미리보기",
    title: "현재 상담의 분석 리포트를 검토할 수 있습니다.",
    description: isAuthenticated
      ? "저장 처리 후 내 사건과 작업대에서 다시 확인할 수 있습니다."
      : "현재 접속 중에는 검토할 수 있지만 저장과 제출용 문서는 Google 로그인 후 사용할 수 있습니다.",
    missingItems: [],
    ctaLabel: "AI 상담으로 이동",
  };
}

if (effectiveHasReport || hasSavedReports) {
  return {
    kind: "available",
    stageLabel: "리포트 확인 가능",
    title: "리포트가 준비되었습니다.",
    description: "리포트 미리보기와 저장·다운로드 작업을 계속할 수 있습니다.",
    missingItems: [],
    ctaLabel: "AI 상담으로 이동",
  };
}
```

Replace the three existing conditions and return blocks with the code above. Retain the `hasReport` parameter for call compatibility during this hotfix, but do not let it override an empty live payload. Do not apply the temporary predicate to reject an already-hydrated persisted report.

- [ ] **Step 4: Apply the predicate at both live and workbench boundaries**

Import `hasMeaningfulReportingPayload` beside `deriveReportWorkbenchState` in `FrontendAppShell.jsx`.

Update `isReportingPayloadReady` so the first guard is:

```js
if (!hasMeaningfulReportingPayload(reportingPayload)) {
  return false;
}
```

In `ReportingScreen`, preserve persisted detail and filter only the live fallback:

```js
const liveReportingPayload = hasMeaningfulReportingPayload(reportingPayload)
  ? reportingPayload
  : null;
const activeReportingPayload =
  currentReport?.content?.reporting_payload || liveReportingPayload;
const isPersistedReport = Boolean(
  currentReport?.report_id && currentReport?.content?.reporting_payload,
);
const hasReport = isPersistedReport || hasMeaningfulReportingPayload(activeReportingPayload);
```

Keep existing worker polling, report-list refresh, persisted detail loading, download, and document confirmation unchanged.

- [ ] **Step 5: Run report regressions and frontend contract checks**

Run:

```powershell
node --test app/web/reportWorkbenchState.test.js app/web/chatResponsePresentation.test.js app/web/SafeMarkdown.test.js
python -m pytest test/test_report_workbench_frontend_contract.py test/test_service_scope_frontend_contract.py -q
```

Expected: all tests PASS; empty live payloads use an existing truthful empty/not-reportable state and persisted detail remains available.

- [ ] **Step 6: Commit Task 3 only**

```powershell
git add -- app/web/reportWorkbenchState.js app/web/reportWorkbenchState.test.js app/web/FrontendAppShell.jsx
git diff --cached --check
git commit -m "fix: hide skeletal report previews"
```

---

### Task 4: Remove Malformed Law Table Fragments at the Public Boundary

**Files:**
- Modify: `app/services/public_law_projection_service.py:10-61`
- Modify: `test/test_public_law_projection_service.py:1-83`
- Modify: `test/test_supervisor_control_service.py:319-413`

**Interfaces:**
- Consumes: optional verified-law `summary` text after law retrieval and before public answer construction.
- Produces: the existing public law item shape with `law_name` and `article` retained and malformed table-like `summary` omitted.

- [ ] **Step 1: Add a failing public projection regression**

Add to `test/test_public_law_projection_service.py`:

```python
def test_public_law_projection_omits_malformed_pipe_table_summary() -> None:
    public = project_public_law_items(
        {
            "matched_laws": [
                {
                    "law_name": "도로교통법 시행령",
                    "article": "별표10",
                    "summary": "| | 3) 이륜자동차등: 6만원 |\n| | | |",
                    "source_reference": "law:verified:appendix-10",
                }
            ]
        }
    )

    assert public == [{"law_name": "도로교통법 시행령", "article": "별표10"}]
    assert "|" not in repr(public)
```

- [ ] **Step 2: Add a failing final-answer regression**

Add to `test/test_supervisor_control_service.py`:

```python
def test_fine_notice_procedure_drops_malformed_pipe_summary_from_answer() -> None:
    merged = merge_final_response(
        {
            "law_ground_search": {
                "status": "success",
                "summary": "검증된 법령 근거를 확인했습니다.",
                "structured_result": {
                    "matched_laws": [
                        {
                            "law_name": "도로교통법 시행령",
                            "article": "별표10",
                            "summary": "| | 3) 이륜자동차등: 6만원 |\n| | | |",
                            "source_reference": "law:verified:appendix-10",
                        }
                    ]
                },
                "evidence": [{"source_reference": "law:verified:appendix-10"}],
                "limitations": [],
            },
            "agent_result_validation": {
                "status": "success",
                "structured_result": {
                    "merge_ready": True,
                    "report_ready": False,
                    "accepted_results": ["law_ground_search"],
                    "rejected_results": [],
                    "missing_fields": [],
                    "limitations": [],
                },
            },
        },
        routing_intent="fine_notice_procedure",
        user_text="과태료 의견제출 절차를 알려줘.",
    )

    answer = merged["assistant_message"]["answer"]
    assert "도로교통법 시행령 별표10" in answer
    assert "|" not in answer
    assert "이륜자동차등: 6만원" not in answer
```

- [ ] **Step 3: Run both tests and verify RED**

Run:

```powershell
python -m pytest test/test_public_law_projection_service.py test/test_supervisor_control_service.py -k "pipe or practical_guidance" -q
```

Expected: the new pipe cases FAIL because the optional summary is still projected and rendered.

- [ ] **Step 4: Implement the narrow table-fragment detector**

Add this helper to `app/services/public_law_projection_service.py`:

```python
def _contains_pipe_table_fragment(value: str) -> bool:
    for line in value.splitlines() or [value]:
        stripped = line.strip()
        if line.count("|") < 2:
            continue
        if stripped.startswith("|") or stripped.endswith("|"):
            return True
        if re.search(r"\|\s*\|", line):
            return True
    return False
```

Add one condition to the existing summary allowlist:

```python
and not _contains_pipe_table_fragment(summary)
```

Do not change law retrieval, source verification, `SafeMarkdown`, raw-provision filtering, PII detection, length limits, or the three-item public cap.

- [ ] **Step 5: Run law, Supervisor, and Markdown regressions**

Run:

```powershell
python -m pytest test/test_public_law_projection_service.py test/test_supervisor_control_service.py -q
node --test app/web/SafeMarkdown.test.js
```

Expected: all tests PASS; normal prose law summaries remain visible and valid Markdown tables in other assistant messages still render.

- [ ] **Step 6: Commit Task 4 only**

```powershell
git add -- app/services/public_law_projection_service.py test/test_public_law_projection_service.py test/test_supervisor_control_service.py
git diff --cached --check
git commit -m "fix: omit malformed law table summaries"
```

---

### Task 5: Combined Local Regression, Production Build, and Scope Audit

**Files:**
- Verify: all files changed by Tasks 1-4
- Do not modify: user-owned untracked validation reports or evidence directories

**Interfaces:**
- Consumes: the four isolated implementation commits.
- Produces: one locally verified branch whose combined diff is limited to the approved code and tests.

- [ ] **Step 1: Verify the branch still contains the latest `origin/dev`**

Run:

```powershell
git fetch origin --prune
git merge-base --is-ancestor origin/dev HEAD
git status --short --branch --untracked-files=no
```

Expected: `git merge-base` exits `0`; the branch is not behind `origin/dev`; no tracked implementation changes remain unstaged. If `origin/dev` advanced and is not an ancestor, stop before rewriting history and realign the branch with the newly fetched `dev` using the repository's normal PR workflow.

- [ ] **Step 2: Run all frontend Node tests**

Run from the repository root:

```powershell
Set-Location app/web
node --test
Set-Location ../..
```

Expected: every discovered `*.test.js` test PASS with zero failures.

- [ ] **Step 3: Build the frontend production bundle**

Run:

```powershell
Set-Location app/web
npm run build
Set-Location ../..
```

Expected: Vite exits `0` and writes the normal production bundle without unresolved imports or JSX errors.

- [ ] **Step 4: Run focused connected Python regressions**

Run:

```powershell
python -m pytest test/test_public_law_projection_service.py test/test_supervisor_control_service.py test/test_chat_orchestration_service.py test/test_chat_session_followup_service.py test/test_consultation_v2_contract.py test/test_report_workbench_frontend_contract.py test/test_service_scope_frontend_contract.py -q
```

Expected: all tests PASS; no external LLM or OCR provider call is made by these offline tests.

- [ ] **Step 5: Run full pytest and Django chatbot regression**

Run:

```powershell
python -m pytest -q --timeout=30
python backend/manage.py test chatbot -v 1
```

Expected: both commands exit `0`. Existing skip markers remain skips; new failures, collection errors, or timeouts block publishing.

- [ ] **Step 6: Audit whitespace and excluded paths**

Run:

```powershell
git diff --check origin/dev...HEAD
git diff --name-status origin/dev...HEAD
git diff --name-only origin/dev...HEAD | Select-String -Pattern '^(ai/|etl/|backend/chatbot/models.py|backend/chatbot/migrations/|scripts/|buildspec|\.github/)'
```

Expected: `git diff --check` has no output, the name-status list contains only the approved docs/code/tests, and the excluded-path search has no matches.

- [ ] **Step 7: Review each isolated fix commit**

Run:

```powershell
git log --oneline --decorate origin/dev..HEAD
git diff --stat origin/dev...HEAD
```

Expected: the four implementation commits remain separately reviewable after the documentation commits; no unrelated refactor, dependency, asset, lockfile, API contract, or deployment change appears.

---

### Task 6: Final SHA Publication, Deployment, and External-Chrome Acceptance

**Files:**
- Read only: `docs/tech-validation-reports/2026-08-03-pilot-browser-manual-e2e-scenario-report.md`
- External input: `C:\Users\Playdata\Downloads\과태료 고지서 과실비율 확인서.zip`
- Do not copy: OCR originals, raw OCR output, cookies, tokens, storage paths, or screenshots containing personal information into the repository

**Interfaces:**
- Consumes: the locally verified branch and its merged final `dev` SHA.
- Produces: a production acceptance result for follow-up facts, OCR, evidence-backed case analysis, persisted report, objection draft, report truthfulness, law rendering, and authentication restore.

- [ ] **Step 1: Publish the verified branch and create a PR to `dev`**

Run:

```powershell
git status --short --branch --untracked-files=no
git push -u origin feat-pilot-final-acceptance-hotfix
```

Create one PR targeting `dev`. The PR description must list only the four approved fixes and the local verification commands from Task 5. Do not include the user-owned untracked validation artifacts.

- [ ] **Step 2: Require the PR checks and merge result before deployment**

Confirm all required checks pass, merge the PR to `dev`, then run:

```powershell
git fetch origin --prune
$releaseSha = git rev-parse origin/dev
$releaseSha
git log -1 --oneline origin/dev
```

Expected: `$releaseSha` is the merge result that contains all four implementation commits. Record this exact value in the task handoff; do not approve a build for an earlier or later SHA.

- [ ] **Step 3: Approve only the exact final SHA in AWS**

In the existing AWS pipeline:

1. Confirm Source resolved `$releaseSha`.
2. Confirm Build succeeded for `$releaseSha`.
3. Confirm no newer `dev` commit superseded the run.
4. Manually approve only that run.
5. Wait for deployment completion and health checks.

Do not edit `Release-PilotApp-FromPipeline.sh`, buildspec files, pipeline definitions, evidence permissions, or infrastructure as part of this plan.

- [ ] **Step 4: Prepare the four approved OCR inputs outside the repository**

Use a temporary directory and preserve the archive:

```powershell
$ocrE2eDir = Join-Path ([System.IO.Path]::GetTempPath()) ("pilot-final-acceptance-ocr-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Path $ocrE2eDir
Expand-Archive -LiteralPath "C:\Users\Playdata\Downloads\과태료 고지서 과실비율 확인서.zip" -DestinationPath $ocrE2eDir
Get-ChildItem -LiteralPath $ocrE2eDir -File | Select-Object Name,Length
```

Expected files and purposes:

- `form2_별지154_위반사실통지및과태료사전통지서.pdf`: 사전통지서 OCR 및 의견제출 흐름.
- `form3_별지152_과태료납부고지서원부_운전자.pdf`: 납부고지 단계 구분.
- `15-07-18-.jpg`: 사고 자료/현장 사진.
- `22-11-18-_.png`: 교통사고 사실확인원.

- [ ] **Step 5: Verify follow-up transport and law rendering in external Chrome**

Open `https://skn27-traffic-pilot.duckdns.org/` in external Chrome with a fresh session.

1. Select 사고 과실비율 and submit an initial structured accident question.
2. Answer a pending road-layout question with `2차로 회전교차로`.
3. Continue the remaining vehicle-action, signal-priority, and collision-location questions.
4. Confirm the visible and server-returned fact cards never contain `[상담 유형]`, `[사고 유형]`, or `[자유 입력]`.
5. Start a separate fresh 과태료 consultation and ask for the objection procedure.
6. Confirm the answer contains readable law/article labels and contains no broken raw `|` table fragments.

Pass condition: facts accumulate without repeated structured labels, normal prose remains readable, accepted requests show no failed API call, and the browser console has no error.

- [ ] **Step 6: Run each OCR document in a fresh scenario**

For each of the four files, start a fresh consultation and use only its approved purpose mapping. Confirm:

1. Upload registration succeeds.
2. Safety scan progresses from uploaded/scanning to `status: ready` and `scan_status: clean`.
3. OCR or image analysis starts automatically only after the clean state.
4. A target-document result is shown without raw OCR text, storage URI, token, or personal identifier exposure.
5. Rejected or non-target documents do not unlock case analysis or draft generation.

Pass condition: each file reaches its allowed result without cross-session attachment leakage or a stuck `scan=not_started` state.

- [ ] **Step 7: Run the complete persisted-report and objection-draft journey**

Use the accident scenario with the approved fact-confirmation document:

1. Confirm all four core facts.
2. Confirm `사건 생성·분석 시작` is hidden before ready evidence and appears after clean or accepted OCR evidence.
3. Authenticate with Google when prompted and continue the same consultation.
4. Start `case_ready → case creation → fact confirmation → analysis job`.
5. Wait for worker completion and confirm a real `report_id` is loaded from report detail.
6. Confirm the report contains a non-empty summary, sections, or document cards and does not show `확인된 자료 없음` as if it were an active report.
7. Confirm the objection-draft card appears only when the report contract provides it.
8. Refresh or reopen the authenticated session and confirm the saved report detail can be restored.

Pass condition: the connected journey reaches a persisted report and objection draft, with zero accepted-path API failures and zero browser-console errors.

- [ ] **Step 8: Verify truthful empty-report behavior**

In a fresh general legal-guidance session:

1. Submit a question that does not include a report-generation node.
2. Open the report workbench.
3. Confirm an empty or skeletal payload does not render `작성 중`, a fake report count, or `확인된 자료 없음` report metadata.
4. Confirm the existing `절차 안내 완료`, `상담·자료 보완 필요`, or `상담 시작 전` state is shown according to Supervisor state.

Pass condition: waiting without a job does not transform the empty workbench into a report.

- [ ] **Step 9: Apply the failure-specific retry rule**

If any production step fails:

1. Record the exact failing scenario, final SHA, visible public state, public API status/code, and console error without recording secrets or raw OCR.
2. Add one automated test that reproduces only that failure.
3. Apply the smallest change within the four approved files and constraints.
4. Rerun the focused test, Task 5 full regression, production build, and the complete connected journey.
5. Merge the corrective commit to `dev`, capture the new final SHA, and approve only the build for that new SHA.

Do not batch unrelated observations into the retry commit and do not modify backend engines, API contracts, deployment scripts, or infrastructure without a new explicit user decision.

- [ ] **Step 10: Report final acceptance**

Return one concise acceptance record containing:

- deployed final `dev` SHA;
- local Node, Vite, pytest, and Django results;
- four OCR file outcomes by filename and approved purpose;
- follow-up fact, law rendering, evidence gate, persisted report, objection draft, and authentication restore results;
- any failed step and its corrective SHA;
- final PASS or FAIL decision.

Do not commit raw OCR, personal information, authentication material, private storage references, or browser network payloads as evidence.
