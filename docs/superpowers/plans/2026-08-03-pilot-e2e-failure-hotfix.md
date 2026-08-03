# Pilot E2E Failure Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove F-01 through F-05 and B-01 from the 2026-08-03 pilot browser report and prove the connected production journey.

**Architecture:** Preserve raw agent results as private data while introducing node-specific public projections. Reconcile current and stored routing before merging domain state, branch attachment workflow by purpose, and make authentication persistence and worker polling observable and recoverable.

**Tech Stack:** Python 3, Django, pytest, React 19, Node test runner, Vite 7, JSON policy.

## Global Constraints

- Raw OCR, storage URI, credentials, tokens, provider output, and private traces never enter public API responses or logs.
- Existing attachment safety scanning and confirmation gates remain fail-closed.
- Each production change follows a witnessed red test, minimal green implementation, and focused regression run.
- Completion requires production browser evidence, not automatic tests alone.

---

### Task 1: Fine-notice attachment availability normalization

**Files:**
- Modify: `test/test_supervisor_input_normalization_service.py`
- Modify: `test/test_chat_orchestration_service.py`
- Modify: `app/config/supervisor_input_normalization_policy.v1.json`

**Interfaces:**
- Consumes: `normalize_supervisor_input(user_text, source_message_id)`.
- Produces: an auto-applied `attachment_available=yes` candidate for the observed browser phrase.

- [ ] Add a failing normalization test for `고지서 첨부가 가능합니다` plus negative and uncertain guards.
- [ ] Run the exact test and verify the positive case fails because the candidate is absent.
- [ ] Add only the required deterministic aliases to the policy.
- [ ] Run normalization and orchestration tests and verify no repeated attachment question.
- [ ] Commit the isolated normalization fix.

### Task 2: Safe public agent result contract

**Files:**
- Modify: `test/test_analysis_job_query_service.py`
- Modify: `app/services/analysis_job_query_service.py`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/web/caseReadyWorkflow.js`
- Modify: `app/web/trafficAccidentOcrPresentation.test.js`
- Modify: `app/web/caseReadyWorkflow.test.js`
- Modify: `test/test_frontend_auth_session_contract.py`

**Interfaces:**
- Produces: `public_results.contract_version == "public_agent_results.v1"` with node-specific allowlisted objects.
- Preserves: absence of top-level raw `structured_results` and `agent_results`.

- [ ] Add failing completed/detail response tests for safe classification, fine-notice OCR, traffic OCR, and appeal fields.
- [ ] Assert private nested values and raw `structured_results` remain absent.
- [ ] Run the focused query-service tests and verify expected missing `public_results` failures.
- [ ] Implement per-node projectors and add them to completed and detail payloads.
- [ ] Migrate frontend and CaseReady consumers to `public_results`.
- [ ] Run Python public-contract tests, Node presentation tests, and Vite build.
- [ ] Commit the isolated public contract fix.

### Task 3: Specialized traffic-accident OCR workflow

**Files:**
- Modify: `test/test_attachment_workflow_service.py`
- Modify: `app/services/attachment_workflow_service.py`
- Modify: `test/test_analysis_job_query_service.py`

**Interfaces:**
- Consumes: attachment purpose and `traffic_accident_confirmation_ocr` result.
- Produces: existing workflow states without requiring generic classification.

- [ ] Add failing tests for running, success, partial, and failed specialized OCR.
- [ ] Verify the current implementation incorrectly returns `classification_running`.
- [ ] Branch by purpose and derive state from specialized OCR result and active node.
- [ ] Run workflow and query-service tests including private-field assertions.
- [ ] Commit the isolated workflow fix.

### Task 4: Follow-up topic switch and polling recovery

**Files:**
- Modify: `test/test_chat_session_followup_service.py`
- Modify: `test/test_chat_orchestration_service.py`
- Modify: `backend/chatbot/views.py`
- Modify: `app/services/chat_session_followup_service.py`
- Modify: `app/services/chat_orchestration_service.py`
- Modify: `app/web/workerPolling.js` and its tests.

**Interfaces:**
- Produces: forced/current/continuation routing resolution and a topic-switch merge policy.
- Produces: recoverable polling exhaustion with retained job identity.

- [ ] Add failing tests for accident-to-law topic switch and short accident-answer continuation.
- [ ] Add a failing test proving incompatible pending questions and facts are removed on switch.
- [ ] Implement route-source separation and compatible-state merge.
- [ ] Add a failing polling test that requires job identity and a status-check action after exhaustion.
- [ ] Implement the minimal recoverable polling outcome without extending the fixed delay.
- [ ] Run routing, follow-up, polling, and source-contract tests.
- [ ] Commit the isolated routing/polling fix.

### Task 5: Authentication persistence and restore diagnostics

**Files:**
- Modify: `app/web/authSession.test.js`
- Modify: `app/web/authSession.js`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `test/test_frontend_auth_session_contract.py`

**Interfaces:**
- Produces: a persistence result containing booleans and a reason code, never token values.
- Preserves: stored session on transient verification failures and guest/chat lineage on 401/403.

- [ ] Add failing tests for storage exception, incomplete read-back, complete tuple, transient auth/me, and 401/403.
- [ ] Implement boolean storage writes and authenticated tuple read-back.
- [ ] Surface restore stages and retry state in the shell without treating unverified identity as authenticated.
- [ ] Run auth Node tests and frontend source-contract tests.
- [ ] Commit the isolated authentication fix.

### Task 6: Regression, deployment, and connected browser E2E

**Files:**
- Update: `docs/tech-validation-reports/2026-08-03-pilot-browser-manual-e2e-scenario-report.md`

**Interfaces:**
- Consumes: all prior hotfix commits.
- Produces: deployment revision and evidence for every report item.

- [ ] Run all focused Python modules changed by Tasks 1-5.
- [ ] Run all frontend Node tests and `npm run build` from `app/web`.
- [ ] Run full `python -m pytest -q --timeout=30`.
- [ ] Integrate the current `origin/dev`, rerun affected tests, and publish through the repository workflow.
- [ ] Confirm deployed backend, worker, and frontend image tags match the hotfix revision.
- [ ] Repeat J01, J02, J03, J04, J06, and J08 in the browser until each expected result is observed.
- [ ] Complete OCR/Vision, fact confirmation, CaseReady, persisted report, appeal draft, and reload retrieval.
- [ ] Record exact evidence and mark the goal complete only when no report failure or blocker remains.
