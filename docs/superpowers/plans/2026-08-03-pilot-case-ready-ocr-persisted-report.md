# Pilot Case-Ready, OCR, Persisted Report Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect an explicitly approved case_ready consultation to the existing Case APIs, persisted report, and objection draft, then validate the four provided OCR documents in the deployed production build.

**Architecture:** Add a pure frontend workflow module that converts consultation_state.v2 into existing Case API payloads and runs create-confirm-start in order. Keep authentication and React state in FrontendAppShell, reuse existing worker polling and report APIs, and add a separate safe presentation adapter for the existing traffic-accident OCR result. Backend engines, data models, routing, and deployment infrastructure remain unchanged.

**Tech Stack:** React/Vite, JavaScript ES modules, Node test runner, Python/Django contract tests, existing Case v2 APIs, existing OpenAI Vision OCR agents, in-app production browser verification.

## Global Constraints

- Start from the latest origin/dev, not the previous hotfix branch.
- Do not modify ai/**, etl/**, backend/chatbot/case_repository.py, backend/chatbot/repositories.py, models, migrations, deploy/**, infra/**, or buildspec files.
- Do not create a case, fact version, or analysis job before the user clicks 로그인 후 사건 생성·분석 시작.
- Use only existing Case, analysis result, report detail, document confirmation, and download APIs.
- A final report requires both a persisted report_id and report detail containing content.reporting_payload.
- Do not commit the four source documents. Fixtures contain filenames and non-sensitive expectations only.
- Actual OpenAI Vision OCR is approved for the four provided files and necessary same-file diagnostic retries.
- Never store or print raw OCR text or unmasked personal fields in tests or reports.
- Keep accident documents and fine-notice documents in separate scenarios.
- Do not move to the next hotfix until deployed-browser acceptance passes.

---

### Task 1: Case-ready payload boundary

**Files:**
- Create: app/web/caseReadyWorkflow.js
- Create: app/web/caseReadyWorkflow.test.js

**Interfaces:**
- Consumes: analysisResponse, registeredAttachments, existing API client, authenticated identity.
- Produces: buildCaseReadyViewModel(response, attachments), runCaseReadyWorkflow(options), initialCaseAnalysisResult(startResponse).
- runCaseReadyWorkflow returns caseId, factVersionId, jobId, workItemId, and startResponse.

- [ ] **Step 1: Write the failing view-model test**

~~~js
test("builds Case API payloads from four confirmed facts", () => {
  const model = buildCaseReadyViewModel({
    status: "case_ready",
    session_id: "ses_case_ready",
    consultation_state: {
      v2: {
        schema_version: "consultation_state.v2",
        risk_gate: { level: "standard" },
        next_action: "confirm_facts"
      },
      fact_state: {
        facts: {
          road_layout: { value: "four_way_intersection", confirmed: true },
          vehicle_actions: { value: "ego_straight_other_left_turn", confirmed: true },
          signal_priority: { value: "ego_green", confirmed: true },
          collision_location: { value: "front_left", confirmed: true }
        },
        conflicts: []
      }
    }
  }, [{ attachment_id: "att_accident", status: "ready" }]);

  assert.equal(model.eligible, true);
  assert.deepEqual(model.confirmationPayload.facts, {
    road_layout: "four_way_intersection",
    vehicle_actions: "ego_straight_other_left_turn",
    signal_priority: "ego_green",
    collision_location: "front_left"
  });
  assert.deepEqual(model.confirmationPayload.sources, [
    { source_type: "official_document", source_ref: "att_accident" }
  ]);
});
~~~

Use this table-driven negative test so every ineligible path is explicit.

~~~js
for (const [name, mutate] of [
  ["non-case-ready", (value) => { value.status = "needs_input"; }],
  ["unconfirmed fact", (value) => {
    value.consultation_state.fact_state.facts.road_layout.confirmed = false;
  }],
  ["conflict", (value) => {
    value.consultation_state.fact_state.conflicts = [{ field: "road_layout" }];
  }],
  ["high risk", (value) => {
    value.consultation_state.v2.risk_gate.level = "high_risk";
  }]
]) {
  test(`rejects ${name}`, () => {
    const candidate = structuredClone(completeResponse);
    mutate(candidate);
    assert.equal(buildCaseReadyViewModel(candidate).eligible, false);
  });
}
~~~

- [ ] **Step 2: Run the test and confirm RED**

~~~powershell
node --test app/web/caseReadyWorkflow.test.js
~~~

Expected: module-not-found failure.

- [ ] **Step 3: Implement the minimal view model**

Export CASE_READY_FACTS with road_layout, vehicle_actions, signal_priority, and collision_location plus Korean labels. buildCaseReadyViewModel must:

- read consultation_state.v2 and consultation_state.fact_state;
- require status case_ready, standard risk, zero conflicts, and four confirmed non-empty values;
- create casePayload with session_id, title 교통사고 과실 상담, case_type accident_fault, consultation_state, and empty location;
- create confirmationPayload with facts, ready attachment sources, conflicts, and empty user_edit_history;
- avoid copying OCR raw text or storage_uri.

- [ ] **Step 4: Write the failing orchestration test**

~~~js
test("runs create, confirm, and start in order", async () => {
  const calls = [];
  const api = {
    createConsultationCase: async () => {
      calls.push("create");
      return { case: { case_id: "case_1" } };
    },
    confirmConsultationCaseFacts: async () => {
      calls.push("confirm");
      return { fact_version: { fact_version_id: "fact_1" } };
    },
    startConsultationCaseAnalysis: async () => {
      calls.push("start");
      return {
        job: { job_id: "job_1", status: "queued" },
        work_item: { work_item_id: "work_1", status: "queued" }
      };
    }
  };

  const result = await runCaseReadyWorkflow({
    api,
    identity: { authToken: "token" },
    model: completeModel,
    onStep: () => {}
  });

  assert.deepEqual(calls, ["create", "confirm", "start"]);
  assert.equal(result.jobId, "job_1");
});
~~~

Use the same fake API with create rejecting, then confirm rejecting, and assert the calls arrays are ["create"] and ["create", "confirm"]. For an ineligible model assert runCaseReadyWorkflow rejects with case_ready_required and calls remains empty.

- [ ] **Step 5: Implement orchestration**

runCaseReadyWorkflow must emit creating_case, confirming_facts, and starting_analysis through onStep; call the three existing API methods; validate case_id, fact_version_id, and job_id after each response; and return only identifiers plus startResponse. initialCaseAnalysisResult must convert the queued start response into the existing analysis_progress.v1 shape for pollWorkerResult.

- [ ] **Step 6: Run focused tests**

~~~powershell
node --test app/web/caseReadyWorkflow.test.js
~~~

Expected: PASS.

- [x] **Step 7: Commit**

~~~powershell
git add -- app/web/caseReadyWorkflow.js app/web/caseReadyWorkflow.test.js
git commit -m "feat: add explicit case ready workflow"
~~~

### Task 2: Persisted report polling

**Files:**
- Modify: app/web/caseReadyWorkflow.js
- Modify: app/web/caseReadyWorkflow.test.js

**Interfaces:**
- Consumes: pollWorkerResult, api.getAnalysisResult, api.getReportDetail.
- Produces: pollCaseReadyReport(options) returning workerResult and report.

- [ ] **Step 1: Write the failing persisted-report test**

~~~js
test("hydrates a persisted report after analysis success", async () => {
  const api = {
    getAnalysisResult: async () => ({
      result: {
        status: "success",
        analysis_progress: {
          semantic_status: "success",
          terminal: true,
          retryable: false,
          job_id: "job_1"
        },
        report_links: [{ report_id: "rep_1" }]
      }
    }),
    getReportDetail: async () => ({
      report: {
        report_id: "rep_1",
        content: {
          reporting_payload: { report_type: "fault_ratio_analysis" }
        }
      }
    })
  };

  const result = await pollCaseReadyReport({
    api,
    identity: { authToken: "token" },
    sessionId: "ses_case_ready",
    startResponse: {
      job: { job_id: "job_1", status: "queued" },
      work_item: { work_item_id: "work_1" }
    },
    wait: async () => {},
    maxAttempts: 2,
    onUpdate: () => {}
  });

  assert.equal(result.report.report_id, "rep_1");
});
~~~

Add these exact assertions after the success case.

~~~js
test("does not accept temporary reporting payload as a persisted report", async () => {
  const result = await pollCaseReadyReport({
    api: {
      getAnalysisResult: async () => ({
        result: {
          status: "success",
          analysis_progress: { semantic_status: "success", terminal: true },
          reporting_payload: { report_type: "fault_ratio_analysis" },
          report_links: []
        }
      }),
      getReportDetail: async () => {
        throw new Error("must not load detail without report_id");
      }
    },
    identity: {},
    sessionId: "ses_case_ready",
    startResponse: queuedStartResponse,
    wait: async () => {},
    maxAttempts: 1
  });
  assert.equal(result.report, null);
});
~~~

For the incomplete detail case return report_id rep_1 with content {}, then assert result.report is null.

- [ ] **Step 2: Run the test and confirm RED**

~~~powershell
node --test app/web/caseReadyWorkflow.test.js
~~~

Expected: missing export failure.

- [ ] **Step 3: Implement polling**

Import pollWorkerResult. Poll api.getAnalysisResult with the job ID, find report_id only in terminal report_links, call api.getReportDetail with the same session and identity, and return report only when both report.report_id and report.content.reporting_payload exist. Return report null for partial, failed, delayed, or incomplete responses.

- [ ] **Step 4: Run regression**

~~~powershell
node --test app/web/caseReadyWorkflow.test.js app/web/workerPolling.test.js
~~~

Expected: PASS.

- [x] **Step 5: Commit**

~~~powershell
git add -- app/web/caseReadyWorkflow.js app/web/caseReadyWorkflow.test.js
git commit -m "feat: hydrate persisted case reports"
~~~

### Task 3: Case-ready CTA and login recovery

**Files:**
- Create: app/web/CaseReadyPanel.js
- Create: app/web/CaseReadyPanel.test.js
- Modify: app/web/FrontendAppShell.jsx
- Modify: app/web/styles.css
- Modify: app/web/caseReadyWorkflow.js
- Modify: app/web/caseReadyWorkflow.test.js

**Interfaces:**
- Consumes: Task 1 and 2 exports, loginAndBindCurrentSession, registeredAttachments, identity, report setters.
- Produces: startCaseReadyAnalysis and CaseReadyPanel.

- [ ] **Step 1: Write failing user-action state tests**

Add buildCaseReadyActionUi({ model, progress, authenticated }) and render CaseReadyPanel with react-dom/server. Test behavior, not source text.

~~~js
test("offers one explicit start action only for an eligible idle case", () => {
  const ui = buildCaseReadyActionUi({
    model: completeModel,
    progress: { step: "idle", error: "" },
    authenticated: false
  });
  assert.equal(ui.visible, true);
  assert.equal(ui.buttonLabel, "로그인 후 사건 생성·분석 시작");
  assert.equal(ui.disabled, false);
  assert.equal(ui.facts.length, 4);
});

test("disables the action while a server mutation is active", () => {
  for (const step of [
    "creating_case", "confirming_facts", "starting_analysis", "polling", "loading_report"
  ]) {
    const ui = buildCaseReadyActionUi({
      model: completeModel,
      progress: { step, error: "" },
      authenticated: true
    });
    assert.equal(ui.buttonLabel, "사건 생성·분석 시작");
    assert.equal(ui.disabled, true);
  }
});
~~~

- [ ] **Step 2: Run tests and confirm RED**

~~~powershell
node --test app/web/caseReadyWorkflow.test.js
node --test app/web/CaseReadyPanel.test.js
~~~

Expected: new assertions fail.

- [ ] **Step 3: Add state and explicit handler**

Add caseReadyProgress with step idle and empty error. Derive caseReadyModel from analysisResponse and registeredAttachments. startCaseReadyAnalysis must:

1. return unless the model is eligible and idle or failed;
2. set pendingAuthAction type case_ready_analysis;
3. call loginAndBindCurrentSession only when unauthenticated;
4. rebuild the model with the bound session ID;
5. run create-confirm-start;
6. poll using existing delays and attempts;
7. set analysisResponse during polling;
8. require a persisted report;
9. set currentReport and route reporting;
10. catch without logging raw error or document content and show a fixed user-safe message.

The handler uses this control shape:

~~~js
async function startCaseReadyAnalysis() {
  if (!caseReadyModel.eligible || !["idle", "failed"].includes(caseReadyProgress.step)) return;
  let requestIdentity = identity;
  let activeSessionId = sessionId;
  try {
    if (!authSessionId) {
      setPendingAuthAction({ type: "case_ready_analysis" });
      const loginState = await loginAndBindCurrentSession({
        source: "case_ready_analysis",
        nextRoute: "chatbot"
      });
      requestIdentity = loginState.identity;
      activeSessionId = loginState.sessionId;
    }
    const model = buildCaseReadyViewModel(
      { ...analysisResponse, session_id: activeSessionId },
      registeredAttachments
    );
    const started = await runCaseReadyWorkflow({
      api,
      identity: requestIdentity,
      model,
      onStep: (step) => setCaseReadyProgress({ step, error: "" })
    });
    setCaseReadyProgress({ step: "polling", error: "" });
    const completed = await pollCaseReadyReport({
      api,
      identity: requestIdentity,
      sessionId: activeSessionId,
      startResponse: started.startResponse,
      wait: () => new Promise((resolve) => window.setTimeout(resolve, WORKER_POLL_DELAY_MS)),
      maxAttempts: WORKER_POLL_ATTEMPTS,
      onUpdate: setAnalysisResponse
    });
    if (!completed.report) throw new Error("persisted_report_missing");
    setCurrentReport(completed.report);
    setCaseReadyProgress({ step: "ready", error: "" });
    setPendingAuthAction(null);
    setActiveRoute("reporting");
  } catch {
    setCaseReadyProgress({
      step: "failed",
      error: "사건 분석 리포트를 완료하지 못했습니다. 현재 단계에서 다시 시도해 주세요."
    });
    setPendingAuthAction(null);
  }
}
~~~

- [ ] **Step 4: Render CaseReadyPanel**

Render only when caseReadyModel.eligible is true. Show four labels and values, one CTA, progress text, and retry after failed. Disable the CTA during creating_case, confirming_facts, starting_analysis, polling, and loading_report. Guest copy is 로그인 후 사건 생성·분석 시작; authenticated copy is 사건 생성·분석 시작.

- [ ] **Step 5: Add scoped styles**

Add case-ready-panel, case-ready-facts, case-ready-fact, case-ready-actions, and case-ready-progress. Keep 44px minimum button height. At max-width 860px use one column and prevent horizontal overflow.

- [ ] **Step 6: Run focused tests**

~~~powershell
node --test app/web/caseReadyWorkflow.test.js app/web/CaseReadyPanel.test.js app/web/workerPolling.test.js
npm run build
~~~

Run npm from app/web. Expected: tests and production build PASS. React rendering and click behavior are verified as real behavior in Task 7, not by grepping JSX source.

- [x] **Step 7: Commit**

~~~powershell
git add -- app/web/CaseReadyPanel.js app/web/CaseReadyPanel.test.js app/web/FrontendAppShell.jsx app/web/styles.css app/web/caseReadyWorkflow.js app/web/caseReadyWorkflow.test.js
git commit -m "feat: connect case ready consultation to reports"
~~~

### Task 4: Traffic-accident OCR presentation

**Files:**
- Create: app/web/trafficAccidentOcrPresentation.js
- Create: app/web/trafficAccidentOcrPresentation.test.js
- Create: app/web/TrafficAccidentOcrPanel.js
- Create: app/web/TrafficAccidentOcrPanel.test.js
- Modify: app/web/FrontendAppShell.jsx
- Modify: app/web/styles.css

**Interfaces:**
- Consumes: analysisResponse.structured_results.traffic_accident_confirmation_ocr.
- Produces: buildTrafficAccidentOcrUi({ structuredResult, semanticStatus, nextActions }) and TrafficAccidentOcrPanel.

- [x] **Step 1: Write failing safe-field tests**

Use the actual public OCR contract and allow only accident_datetime, accident_location, accident_type.value, accident_cause, damage.raw_text, and accident_description. Test partial, failed, and absent results. Assert the UI model contains only attachment_id from evidence and never storage_uri, raw_text_redacted, or arbitrary sensitive fields.

~~~js
test("keeps only allow-listed masked accident OCR fields", () => {
  const ui = buildTrafficAccidentOcrUi({
    semanticStatus: "partial",
    structuredResult: {
      extracted_fields: {
        accident_datetime: "2022-11-18 14:10",
        accident_location: "경기도 안산시",
        accident_type: { value: "차대차" },
        accident_cause: "신호 또는 지시 위반",
        resident_registration_number: "must-not-appear"
      },
      missing_fields: ["damage_summary"],
      privacy: { masking_applied: true },
      ocr_evidence: [{
        attachment_id: "att_accident",
        storage_uri: "s3://must-not-appear"
      }]
    },
    nextActions: ["누락 필드를 확인해 주세요."]
  });
  assert.equal(ui.status, "partial");
  assert.equal(ui.maskingApplied, true);
  assert.equal(ui.attachmentId, "att_accident");
  assert.equal(JSON.stringify(ui).includes("must-not-appear"), false);
});
~~~

- [x] **Step 2: Run the test and confirm RED**

~~~powershell
cd app/web
node --test trafficAccidentOcrPresentation.test.js
~~~

Expected: module-not-found failure.

- [x] **Step 3: Implement the presentation adapter**

Read semanticStatus, structuredResult.extracted_fields, document_check, quality.image_quality, privacy.masking_applied, ocr_evidence[0].attachment_id, failure_reason, and nextActions only. Map values through fixed path readers and return null for an absent or non-object structured result.

~~~js
const OCR_FIELDS = [
  ["accident_datetime", "사고 일시", (fields) => fields.accident_datetime],
  ["accident_location", "사고 장소", (fields) => fields.accident_location],
  ["accident_type", "사고 유형", (fields) => fields.accident_type?.value],
  ["accident_cause", "사고 원인", (fields) => fields.accident_cause],
  ["damage", "피해 내용", (fields) => fields.damage?.raw_text],
  ["accident_description", "사고 내용", (fields) => fields.accident_description]
];

export function buildTrafficAccidentOcrUi(input) {
  const structured = input?.structuredResult;
  if (!structured || typeof structured !== "object") return null;
  const extracted = structured.extracted_fields || {};
  const evidence = Array.isArray(structured.ocr_evidence) ? structured.ocr_evidence : [];
  return {
    status: input.semanticStatus || "completed",
    fields: OCR_FIELDS.map(([field, label, read]) => ({ field, label, value: read(extracted) ?? null })),
    maskingApplied: structured?.privacy?.masking_applied === true,
    attachmentId: evidence[0]?.attachment_id || "",
    nextActions: Array.isArray(input.nextActions) ? input.nextActions : []
  };
}
~~~

- [x] **Step 4: Render the OCR panel**

Write React server-render tests first, then render after attachment workflow state and before CaseReadyPanel. Distinguish completed, partial, and failed; show 개인정보 마스킹 적용 when true and the safe attachment ID; never show storage URI or arbitrary raw text. The existing final case fact confirmation remains the user confirmation gate, so do not add a backend endpoint.

- [x] **Step 5: Add responsive styles and build verification**

Add responsive styles using the existing chat palette. The adapter tests verify the displayed data contract; Task 7 verifies the rendered panel and statuses in the real deployed browser.

- [x] **Step 6: Run focused tests**

~~~powershell
node --test trafficAccidentOcrPresentation.test.js TrafficAccidentOcrPanel.test.js
npm run build
~~~

Run npm from app/web. Expected: test and production build PASS.

- [x] **Step 7: Commit**

~~~powershell
git add -- app/web/trafficAccidentOcrPresentation.js app/web/trafficAccidentOcrPresentation.test.js app/web/TrafficAccidentOcrPanel.js app/web/TrafficAccidentOcrPanel.test.js app/web/FrontendAppShell.jsx app/web/styles.css
git commit -m "feat: present accident document OCR safely"
~~~

### Task 5: Four-file sanitized OCR scenarios

**Files:**
- Create: test/fixtures/pilot_ocr_scenarios.json
- Create: test/test_pilot_ocr_scenarios.py

**Interfaces:**
- Consumes: source filenames only.
- Produces: scenario IDs OCR-A-01, OCR-A-02, OCR-F-01, and OCR-F-02 with non-sensitive expectations.

- [x] **Step 1: Write the failing manifest contract test**

Assert the exact four IDs and filenames, no absolute_path or expected_raw_text, no sensitive field names, separate purposes, allowed statuses, and PDF stages 사전통지 and 1차 고지서.

~~~python
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pilot_ocr_manifest_contains_only_approved_sanitized_scenarios() -> None:
    path = ROOT / "test" / "fixtures" / "pilot_ocr_scenarios.json"
    scenarios = json.loads(path.read_text(encoding="utf-8"))["scenarios"]
    assert [item["id"] for item in scenarios] == [
        "OCR-A-01", "OCR-A-02", "OCR-F-01", "OCR-F-02"
    ]
    serialized = json.dumps(scenarios, ensure_ascii=False)
    for forbidden in (
        "absolute_path", "expected_raw_text", "resident_registration_number",
        "driver_license_number", "phone_number", "home_address", "storage_uri"
    ):
        assert forbidden not in serialized
    assert scenarios[2]["expected_notice_stage"] == "사전통지"
    assert scenarios[3]["expected_notice_stage"] == "1차 고지서"
~~~

- [x] **Step 2: Run the test and confirm RED**

~~~powershell
python -m pytest test/test_pilot_ocr_scenarios.py -q
~~~

Expected: fixture-not-found failure.

- [x] **Step 3: Create the manifest**

Use these exact scenario contracts:

- OCR-A-01: 22-11-18-_.png, traffic_accident_confirmation, allowed success or partial, safe accident fields required.
- OCR-A-02: 15-07-18-.jpg, traffic_accident_confirmation, allowed partial or failed, complete-page reupload required.
- OCR-F-01: form2_별지154_위반사실통지및과태료사전통지서.pdf, fine_notice, stage 사전통지, allowed success or partial.
- OCR-F-02: form3_별지152_과태료납부고지서원부_운전자.pdf, fine_notice, stage 1차 고지서, allowed success or partial.

~~~json
{
  "contract_version": "pilot_ocr_scenarios.v1",
  "scenarios": [
    {
      "id": "OCR-A-01",
      "filename": "22-11-18-_.png",
      "purpose": "traffic_accident_confirmation",
      "expected_classification": "traffic_accident_confirmation",
      "allowed_statuses": ["success", "partial"],
      "required_safe_fields": [
        "accident_datetime", "accident_location", "accident_type", "accident_cause"
      ]
    },
    {
      "id": "OCR-A-02",
      "filename": "15-07-18-.jpg",
      "purpose": "traffic_accident_confirmation",
      "expected_classification": "traffic_accident_confirmation",
      "allowed_statuses": ["partial", "failed"],
      "required_next_action": "reupload_complete_page"
    },
    {
      "id": "OCR-F-01",
      "filename": "form2_별지154_위반사실통지및과태료사전통지서.pdf",
      "purpose": "fine_notice",
      "expected_classification": "fine_notice",
      "expected_notice_stage": "사전통지",
      "allowed_statuses": ["success", "partial"]
    },
    {
      "id": "OCR-F-02",
      "filename": "form3_별지152_과태료납부고지서원부_운전자.pdf",
      "purpose": "fine_notice",
      "expected_classification": "fine_notice",
      "expected_notice_stage": "1차 고지서",
      "allowed_statuses": ["success", "partial"]
    }
  ]
}
~~~

- [x] **Step 4: Run the test**

~~~powershell
python -m pytest test/test_pilot_ocr_scenarios.py -q
~~~

Expected: PASS.

- [x] **Step 5: Commit**

~~~powershell
git add -- test/fixtures/pilot_ocr_scenarios.json test/test_pilot_ocr_scenarios.py
git commit -m "test: define pilot OCR acceptance scenarios"
~~~

### Task 6: Regression and production build

**Files:**
- Modify only previously listed in-scope files if a regression reveals an in-scope defect.

- [x] **Step 1: Run focused frontend tests**

~~~powershell
node --test app/web/caseReadyWorkflow.test.js app/web/trafficAccidentOcrPresentation.test.js app/web/workerPolling.test.js app/web/consultationLayout.test.js app/web/caseReports.test.js
~~~

Expected: PASS.

- [x] **Step 2: Run existing Case API tests**

~~~powershell
python backend/manage.py test chatbot.test_consultation_v2.ConsultationCaseApiTests --verbosity 2
~~~

Expected: PASS, including create-confirm-start ordering and no automatic Worker at case_ready.

- [x] **Step 3: Run focused root contracts**

~~~powershell
python -m pytest test/test_frontend_case_api_contract.py test/test_pilot_ocr_scenarios.py test/test_traffic_accident_ocr_runtime.py test/test_fine_notice_ocr.py test/test_ocr_privacy_contract.py -q
~~~

Expected: PASS without a paid provider call because automated tests mock provider functions.

- [x] **Step 4: Run all frontend tests and build**

~~~powershell
node --test app/web/*.test.js
npm run build
~~~

Run npm from app/web. Expected: all tests and Vite build pass.

- [x] **Step 5: Run full Python and Django regression**

~~~powershell
python -m pytest -q
python backend/manage.py test chatbot --verbosity 1
~~~

Expected: PASS with no new warning category.

- [x] **Step 6: Verify scope**

~~~powershell
git diff --check
git status --short
git diff --name-only origin/dev...HEAD
~~~

Expected: no excluded engine, migration, deployment, infrastructure, or raw source document paths. Preserve the unrelated untracked validation report.

### Task 7: Deployed-build browser acceptance

**Files:**
- Input: C:/Users/Playdata/Downloads/과태료 고지서 과실비율 확인서.zip
- Create after validation: docs/tech-validation-reports/2026-08-03-pilot-case-ready-ocr-browser-acceptance.md

**Interfaces:**
- Consumes: deployed final SHA at https://skn27-traffic-pilot.duckdns.org/ and only the four approved files.
- Produces: PASS or FAIL for every scenario and the full persisted-report chain.

- [ ] **Step 1: Confirm the deployed SHA**

Record the final SHA and verify the deployed build is that SHA. Do not validate a superseded execution.

- [ ] **Step 2: Run OCR-A-01**

In a fresh accident consultation upload 22-11-18-_.png as traffic_accident_confirmation. Verify ready/clean scan, correct classification, success or partial OCR, safe fields, masking, and no raw sensitive field or storage URI.

- [ ] **Step 3: Complete the case chain**

Enter the four core facts, reach case_ready, click the explicit CTA, and verify in order: case ID, fact version ID, job ID, terminal result, persisted report ID, report detail content.reporting_payload, and traffic-accident objection draft entry. The report must not remain an all-empty temporary preview.

- [ ] **Step 4: Run OCR-A-02 separately**

Upload 15-07-18-.jpg in a new consultation. Accept only partial or failed with missing fields and complete-page reupload guidance. Fabricated success is FAIL.

- [ ] **Step 5: Run OCR-F-01 and OCR-F-02 separately**

Use a new consultation per PDF. Verify fine_notice classification, stages 사전통지 and 1차 고지서, editable OCR confirmation before follow-up, safe fields, and existing objection flow.

- [ ] **Step 6: Inspect diagnostics**

Require zero console errors, zero failed API calls on the accepted path, zero server mutation before CTA, and no raw OCR text in diagnostics.

- [ ] **Step 7: Write the acceptance report**

Record only deployed SHA, URL, timestamp, scenario ID, terminal statuses, masked identifiers, privacy-safe screenshots, and PASS or exact failed step. Never include raw OCR text or personal fields.

- [ ] **Step 8: Apply the pass gate**

If any scenario fails, add the smallest in-scope failing test, fix, rebuild, redeploy, and rerun the failed scenario plus OCR-A-01 full-chain regression. Move to the next hotfix only after all four scenarios and the persisted-report chain pass.
