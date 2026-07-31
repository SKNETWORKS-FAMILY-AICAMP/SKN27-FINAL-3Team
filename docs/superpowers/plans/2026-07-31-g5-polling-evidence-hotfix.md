# G5 Polling Semantics and E2E Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement HFX-017 and HFX-018 so polling exposes truthful semantic progress, safely resumes from persisted jobs, and produces a validated privacy-safe evidence bundle contract for the later deployed E2Es.

**Architecture:** Add a pure Python semantic-progress projector and integrate it into both analysis query paths. Extract frontend progress mapping and polling into small JavaScript modules so the React shell renders server state without inventing success. Add a separate pure Python evidence-bundle builder/validator that reuses the existing PII sanitizer and does not perform deployment or screenshot capture.

**Tech Stack:** Python 3, pytest, Django test client, React 19, Node test runner, Vite.

## Global Constraints

- Work on `feat-pilot-safety-hotfix` at G4 checkpoint `fe80bc93`.
- Use `docs/superpowers/specs/2026-07-31-g5-polling-evidence-design.md`.
- Write and run every behavior test RED before editing production code.
- Semantic statuses are exactly `queued`, `running`, `partial`, `failed`, `needs_input`, and `success`.
- Worker `success` alone never means semantic `success`.
- Polling exhaustion and transport failure preserve the latest known server result.
- Retry means read-only polling continuation unless an existing server/domain contract explicitly permits a retry.
- Do not add a requeue endpoint or replay paid Agent calls.
- Do not change models, migrations, queue leases, retry backoff, or worker loops.
- Do not deploy, merge, push, or execute production E2Es.
- Stage, commit, and push remain user-owned.

---

### Task 1: Add the server-owned semantic progress projector

**Files:**
- Create: `app/services/analysis_progress_service.py`
- Create: `test/test_analysis_progress_service.py`

**Interfaces:**
- Produces `ANALYSIS_SEMANTIC_STATUSES: frozenset[str]`.
- Produces `build_analysis_progress(job: Mapping[str, Any], *, composed_result: Mapping[str, Any] | None = None) -> dict[str, Any]`.
- Produces `analysis_progress.v1` with `semantic_status`, `terminal`, `retryable`, `next_action`, `user_message`, `job_id`, and `correlation_id`.

- [x] **Step 1: Write RED status-precedence tests**

  Add literal cases proving:

  ```python
  assert build_analysis_progress(
      {
          "job_id": "job_queued",
          "status": "queued",
          "work_item": {"work_item_id": "awork_job_queued", "status": "queued"},
      }
  ) == {
      "contract_version": "analysis_progress.v1",
      "semantic_status": "queued",
      "terminal": False,
      "retryable": True,
      "next_action": "continue_polling",
      "user_message": "분석 요청이 대기 중입니다. 순서가 되면 자동으로 진행됩니다.",
      "job_id": "job_queued",
      "correlation_id": "awork_job_queued",
  }
  ```

  Add independent tests for:

  - `running` and work-item `retrying` → semantic `running`;
  - pending questions, fact conflicts, and confirmation attachment states →
    `needs_input` after the job is terminal;
  - canonical `failed` → `failed`;
  - canonical `partial`, partial Agent result, or limitations → `partial`;
  - canonical `success` plus a real assistant answer/card/structured result/report
    link → `success`;
  - work-item `success` without a user result → `partial`;
  - unknown status → fail-closed `failed`, `retryable=False`;
  - malformed identifiers are omitted rather than copied.

- [x] **Step 2: Run Task 1 RED**

  ```powershell
  python -m pytest test/test_analysis_progress_service.py -q
  ```

  Expected: collection error because `analysis_progress_service` does not exist.

- [x] **Step 3: Implement the minimal projector**

  Implement fixed safe-copy mappings:

  ```python
  _SEMANTIC_PRESENTATION = {
      "queued": (
          False,
          True,
          "continue_polling",
          "분석 요청이 대기 중입니다. 순서가 되면 자동으로 진행됩니다.",
      ),
      "running": (
          False,
          True,
          "continue_polling",
          "분석이 진행 중입니다. 확인된 결과는 완료되는 대로 표시됩니다.",
      ),
      "needs_input": (
          True,
          False,
          "provide_requested_input",
          "분석을 계속하려면 표시된 확인 항목에 답해 주세요.",
      ),
      "partial": (
          True,
          False,
          "review_partial_result",
          "확인된 결과만 표시했습니다. 한계와 추가 확인 사항을 검토해 주세요.",
      ),
      "failed": (
          True,
          False,
          "review_failure_guidance",
          "분석을 완료하지 못했습니다. 표시된 다음 행동을 확인해 주세요.",
      ),
      "success": (
          True,
          False,
          "review_result",
          "분석이 완료되었습니다.",
      ),
  }
  ```

  Override `partial` or `failed` retryability only when the persisted work item
  or an attachment workflow explicitly contains `retryable=True`.
  Accept diagnostic identifiers only when they match
  `^[A-Za-z][A-Za-z0-9_-]{2,63}$`.

- [x] **Step 4: Run Task 1 GREEN**

  ```powershell
  python -m pytest test/test_analysis_progress_service.py -q
  ```

  Expected: all Task 1 tests pass.

---

### Task 2: Integrate progress into public result/detail and verify restart continuity

**Files:**
- Modify: `app/services/analysis_job_query_service.py`
- Modify: `test/test_analysis_job_query_service.py`
- Modify: `backend/chatbot/test_supervisor_reporting_pipeline.py`

**Interfaces:**
- Adds `analysis_progress: analysis_progress.v1` to pending and completed
  analysis results and analysis job details.
- Reuses persisted `job_id` and latest `work_item.work_item_id`.
- Does not expose raw progress cache or worker payload fields.

- [x] **Step 1: Write query RED tests**

  Extend literal public payload tests to assert:

  - queued and running results carry non-terminal semantic progress;
  - terminal result status remains canonical while semantic state differentiates
    `partial`, `failed`, `needs_input`, and `success`;
  - work-item success without a composed user result is semantic `partial`;
  - job detail and result expose the identical `job_id` and `correlation_id`;
  - raw worker payload, exception, private trace, and storage URI are absent.

- [x] **Step 2: Write Django restart-continuity RED test**

  In `test_supervisor_reporting_pipeline.py`:

  1. create or queue a real persisted async analysis job;
  2. ensure its `AnalysisJob` and `AgentWorkItem` rows remain present;
  3. delete the transient progress-cache key or patch cache read to return
     `None`;
  4. call `/api/analysis/results/<job_id>/` with the existing authenticated or
     guest owner;
  5. assert HTTP 202, the same `job_id`, the persisted
     `correlation_id=work_item_id`, and semantic `queued` or `running`.

  This catches a regression where the result endpoint depends solely on
  transient cache state.

- [x] **Step 3: Run Task 2 RED**

  ```powershell
  python -m pytest test/test_analysis_job_query_service.py -q
  python backend/manage.py test chatbot.test_supervisor_reporting_pipeline --verbosity 1
  ```

  Expected: new assertions fail because `analysis_progress` is absent.

- [x] **Step 4: Integrate the projector**

  Import `build_analysis_progress`. Add the contract to:

  - the queued/running result payload;
  - the terminal composed result after canonical status is restored;
  - `_project_analysis_job_detail`.

  Build progress only from the canonical job record and the already projected
  composed result. Do not copy arbitrary `analysis_progress` supplied by
  storage or client input.

- [x] **Step 5: Run Task 2 GREEN**

  ```powershell
  python -m pytest test/test_analysis_progress_service.py test/test_analysis_job_query_service.py -q
  python backend/manage.py test chatbot.test_supervisor_reporting_pipeline --verbosity 1
  ```

  Expected: zero failures.

---

### Task 3: Add frontend semantic progress and bounded polling contracts

**Files:**
- Create: `app/web/analysisProgressUi.js`
- Create: `app/web/analysisProgressUi.test.js`
- Create: `app/web/workerPolling.js`
- Create: `app/web/workerPolling.test.js`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `test/test_consultation_v2_contract.py`
- Modify: `test/test_ui_v3_frontend_contract.py`

**Interfaces:**
- Produces `buildAnalysisProgressUi(value) -> object | null`.
- Produces:

  ```javascript
  pollWorkerResult({
    initialResult,
    loadResult,
    wait,
    maxAttempts,
    onDiagnostic,
    onUpdate,
  }) -> Promise<object>
  ```

- The React shell supplies `api.getAnalysisResult`, identity, wait function, and
  diagnostic logger.

- [x] **Step 1: Write mapper RED tests**

  Assert all six statuses yield distinct labels/messages and preserve only:

  - `semanticStatus`
  - `terminal`
  - `retryable`
  - `nextAction`
  - `message`
  - `jobId`
  - `correlationId`

  Unknown versions/statuses and malformed identifiers return `null` or omit the
  identifier. No public message contains either identifier.

- [x] **Step 2: Write polling RED tests**

  Use real async functions with injected in-memory responses:

  - queued → running → success returns the success response;
  - `needs_input`, `partial`, and `failed` stop immediately;
  - exhausting two attempts returns the last running response with
    `polling_exhausted=True`, safe delayed message, and retryable state;
  - a thrown transport error returns the last server response with
    `polling_interrupted=True` and does not copy the raw exception;
  - diagnostics receive job and correlation IDs;
  - `onUpdate` receives queued → running → terminal transitions and final
    interrupted/exhausted notices;
  - no result path produces “상담 내용을 접수했습니다.”

- [x] **Step 3: Run frontend RED**

  ```powershell
  node --test app/web/analysisProgressUi.test.js app/web/workerPolling.test.js
  ```

  Expected: modules do not exist.

- [x] **Step 4: Implement the mapper and polling helper**

  The helper:

  1. reads `initialResult.analysis_progress`;
  2. calls `loadResult()` only for semantic `queued` or `running`;
  3. merges each public server result over the latest result;
  4. stops on any terminal semantic status;
  5. publishes the initial, intermediate, and final result through `onUpdate`;
  6. on budget exhaustion or transport interruption, attaches a safe local
     `polling_notice` object without changing the server semantic state;
  7. never includes the raw error in its returned object.

- [x] **Step 5: Integrate the React shell**

  Replace the inline polling loop with `pollWorkerResult`. Use
  `analysis_progress.user_message` or the safe `polling_notice.message` for
  assistant/status presentation. Remove the generic accepted fallback from the
  worker-result path. Bind `onUpdate` to `setAnalysisResponse` so queued and
  running transitions are visible before polling terminates.

  Render a compact status element with semantic label and retry availability.
  Log only safe diagnostic fields:

  ```javascript
  {
    semanticStatus,
    jobId,
    correlationId,
    pollingExhausted,
    pollingInterrupted,
  }
  ```

- [x] **Step 6: Align source-contract tests**

  Replace source-text assumptions about the inline loop with module import and
  consumer-boundary assertions. Keep guest polling and auth identity behavior
  unchanged.

- [x] **Step 7: Run Task 3 GREEN**

  ```powershell
  node --test app/web/analysisProgressUi.test.js app/web/workerPolling.test.js
  python -m pytest test/test_consultation_v2_contract.py test/test_ui_v3_frontend_contract.py -q
  ```

  Expected: zero failures.

---

### Task 4: Add the privacy-safe E2E evidence bundle contract

**Files:**
- Create: `app/services/e2e_evidence_bundle_service.py`
- Create: `test/test_e2e_evidence_bundle_service.py`

**Interfaces:**
- Produces `build_e2e_evidence_bundle(payload: Mapping[str, Any]) -> dict[str, Any]`.
- Produces `validate_e2e_evidence_bundle(payload: Mapping[str, Any]) -> list[str]`.
- Produces contract `pilot_e2e_evidence.v1`.
- Reuses `sanitize_pii` from `app.security.pii_masking`.

- [x] **Step 1: Write complete-bundle RED test**

  Use one literal synthetic bundle with:

  - a 40-character lowercase release SHA;
  - frontend/backend `sha256:` digests with 64 lowercase hex characters;
  - `ID-04-authenticated`;
  - exact input;
  - ISO-8601 execution time;
  - relative screenshot artifact filename;
  - integer HTTP status and public response;
  - routing intent, node list, semantic status, job/correlation identifiers;
  - sanitized log records.

  Assert the built result has exactly the approved public fields and validation
  returns `[]`.

- [x] **Step 2: Write RED validation and privacy tests**

  Add independent cases for:

  - every required field missing;
  - malformed SHA, digest, timestamp, HTTP status, semantic status, and ID;
  - absolute Windows path, local path, storage URI, and signed URL screenshot
    reference;
  - resident number, phone number, access token, password, authorization header,
    raw OCR field, and signed URL in input/response/logs;
  - validation error codes never echo rejected values.

- [x] **Step 3: Run Task 4 RED**

  ```powershell
  python -m pytest test/test_e2e_evidence_bundle_service.py -q
  ```

  Expected: collection error because the service does not exist.

- [x] **Step 4: Implement builder and validator**

  Apply an explicit top-level and nested allowlist. Sanitize text/data with
  `sanitize_pii`, then recursively reject URI/path/credential-shaped values.
  Return stable error codes such as:

  - `missing:release.sha`
  - `invalid:release.frontend_image_digest`
  - `unsafe:browser_evidence.input_response_screenshot`
  - `unsafe:http.public_response`
  - `unsafe:sanitized_logs`

  Never include the rejected source value in an error.

- [x] **Step 5: Run Task 4 GREEN**

  ```powershell
  python -m pytest test/test_e2e_evidence_bundle_service.py -q
  ```

  Expected: all Task 4 tests pass.

---

### Task 5: G5 integration regression and master checklist evidence

**Files:**
- Modify: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md`
- Verify every G5 production, test, plan, and spec file.

**Interfaces:**
- Produces local G5 gate `GREEN`, `RED`, or `BLOCKED`.
- Records exact commands, pass counts, warnings, and remaining G6/G8/G9 work.

- [x] **Step 1: Run focused G5 tests**

  ```powershell
  python -m pytest test/test_analysis_progress_service.py test/test_analysis_job_query_service.py test/test_e2e_evidence_bundle_service.py test/test_consultation_v2_contract.py test/test_ui_v3_frontend_contract.py -q
  node --test app/web/analysisProgressUi.test.js app/web/workerPolling.test.js
  python backend/manage.py test chatbot.test_supervisor_reporting_pipeline --verbosity 1
  ```

- [x] **Step 2: Run adjacent safety/auth/attachment tests**

  ```powershell
  python -m pytest test/test_chat_input_privacy.py test/test_privacy_boundaries.py test/test_chat_orchestration_service.py test/test_attachment_workflow_service.py test/test_frontend_auth_session_contract.py -q
  node --test app/web/authSession.test.js app/web/attachmentWorkflowUi.test.js app/web/newConversationState.test.js
  ```

- [x] **Step 3: Run full local verification**

  ```powershell
  python -m pytest -q
  ```

  ```powershell
  node --test appealDecisionUi.test.js analysisProgressUi.test.js attachmentWorkflowUi.test.js authSession.test.js caseReports.test.js chatPrivacyUi.test.js consultationIntake.test.js consultationLayout.test.js guestConversationPolicy.test.js newConversationState.test.js reportWorkbenchState.test.js workerPolling.test.js
  ```

  Run the Node command from `app/web`.

  ```powershell
  npm run build
  ```

  Run the build from `app/web`.

- [x] **Step 4: Run diff and scope review**

  ```powershell
  git diff --check
  git status --short --branch
  git diff --stat
  ```

  Confirm:

  - no model or migration files;
  - no generated `dist` files;
  - no retry/requeue endpoint or paid-call replay;
  - no raw OCR, signed URL, private path, credential, or PII in public output;
  - no G6 deployment or G8/G9 production execution.

- [x] **Step 5: Update the master checklist**

  Mark only G5/HFX-017/HFX-018 local contract items with passing evidence.
  Keep real release SHA/image digest, screenshots, deployed logs, recapture IDs,
  and 13 live E2Es open for G8/G9.

- [x] **Step 6: Present user-owned Git handoff**

  Report changed files, exact counts, warning classification, residual risks,
  and recommended commit:

  ```text
  fix: preserve semantic polling and e2e evidence contracts
  ```

  Do not stage, commit, push, merge, deploy, or create a PR.

## G5 Exit Criteria

- Worker success and semantic task success are demonstrably separate.
- Every approved semantic status has a server contract and UI presentation.
- Polling exhaustion and transport errors preserve the latest result.
- Retryability is truthful and does not trigger paid work.
- Persisted jobs remain pollable without transient progress cache.
- Developer diagnostics carry safe job/correlation references.
- Evidence bundles require all approved HFX-018 fields and reject unsafe data.
- Focused, adjacent, and full tests plus Vite build and diff checks are GREEN.
- Production evidence capture and all 13 E2Es remain open for G8/G9.
