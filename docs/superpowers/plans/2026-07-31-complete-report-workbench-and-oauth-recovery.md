# Complete Report Workbench and OAuth Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the report workbench load and display real saved or in-session reports end-to-end, and make Google login failures actionable without weakening OAuth boundaries.

**Architecture:** Reuse the existing report list/detail API and `ReportingScreen`; add one route-level loader that hydrates the active report from the canonical detail DTO. Preserve guest restrictions in the backend, but make the UI distinguish public in-session preview, authenticated persisted report, loading, and auth-required states. Keep OAuth code exchange unchanged, expose only safe failure categories, and document the required Console/runtime equality check.

**Tech Stack:** React/Vite, browser `node:test`, Django REST endpoints, Django test client.

## Global Constraints

- Do not send OpenAI, OCR, Vision, or Google authorization-code requests in automated tests.
- Never place OAuth codes, secrets, user identifiers, raw OCR text, or private URLs in UI diagnostics, tests, or logs.
- `GET /api/reports/` and `GET /api/reports/{report_id}/` remain authenticated-only; the frontend must not emulate a saved report for a guest.
- Preserve document confirmation and appeal gates before any DOCX action.

---

### Task 1: Route-level report hydration

**Files:**
- Modify: `app/web/FrontendAppShell.jsx`
- Test: `app/web/reportWorkbenchState.test.js`
- Test: `test/test_report_workbench_frontend_contract.py`

**Interfaces:**
- Consumes: `api.listReports({ sessionId, identity })`, `api.getReportDetail({ reportId, sessionId, identity })`
- Produces: `openReportingWorkspace(): Promise<void>` and `loadReports({ hydrateLatest: boolean }): Promise<{ reports: object[] } | null>`

- [ ] **Step 1: Write the failing tests**

```js
test("requires persisted detail before describing a saved report as available", () => {
  const state = deriveReportWorkbenchState({
    hasReport: false,
    hasSavedReports: true,
    savedReportDetailLoaded: false,
  });
  assert.equal(state.kind, "loading_saved_report");
});
```

```python
def test_reporting_route_hydrates_latest_saved_report_before_rendering():
    source = FRONTEND_SHELL.read_text(encoding="utf-8")
    assert "loadReports({ hydrateLatest: true })" in source
    assert "api.getReportDetail" in source
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test app/web/reportWorkbenchState.test.js` and `python -m pytest -q test/test_report_workbench_frontend_contract.py`

Expected: failure because `loading_saved_report` and route hydration do not exist.

- [ ] **Step 3: Write minimal implementation**

Add a loading state to `deriveReportWorkbenchState`. Change the reporting route entry to call the loader when authenticated; after list success, fetch the selected report detail before assigning it to `currentReport`. Keep raw list summaries in `reportList` only.

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test app/web/reportWorkbenchState.test.js` and `python -m pytest -q test/test_report_workbench_frontend_contract.py`

Expected: PASS.

### Task 2: Complete workbench states and actions

**Files:**
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/web/styles.css`
- Test: `app/web/reportWorkbenchState.test.js`
- Test: `test/test_report_workbench_frontend_contract.py`

**Interfaces:**
- Consumes: public `reporting_payload`, persisted report detail, `supervisor_state`
- Produces: visible loading, public temporary-preview, auth-required, no-report, and persisted-report states

- [ ] **Step 1: Write the failing tests**

```js
test("labels an in-session payload as a temporary report when it is not persisted", () => {
  const state = deriveReportWorkbenchState({
    reportingPayload: { report_type: "fault_ratio_analysis", sections: [] },
    hasReport: true,
    isAuthenticated: false,
    isPersistedReport: false,
  });
  assert.equal(state.kind, "temporary_preview");
  assert.match(state.description, /로그인/);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test app/web/reportWorkbenchState.test.js`

Expected: failure because the temporary preview state is not distinguished.

- [ ] **Step 3: Write minimal implementation**

Render an explicit “임시 리포트” status with factual limitations for guest preview. Render a non-ambiguous authenticated loading state while detail is fetched. Keep the existing preview, grounds, missing-evidence, save, and DOCX controls for hydrated reports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test app/web/reportWorkbenchState.test.js` and `npm.cmd run build --prefix app/web`

Expected: PASS and production build succeeds.

### Task 3: OAuth failure boundary and post-login return

**Files:**
- Modify: `app/web/authSession.js`
- Modify: `app/web/authSession.test.js`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `docs/ops/production-env.md`
- Test: `test/test_google_oauth_code_contract.py`

**Interfaces:**
- Consumes: Google popup error type, backend canonical OAuth response, current `window.location.origin`
- Produces: safe `googleLoginFailureMessage(error)` categories and post-login `loadReports({ hydrateLatest: true })`

- [ ] **Step 1: Write the failing tests**

```js
test("keeps popup callback failure distinct from a user-closed popup", () => {
  assert.match(
    googleLoginFailureMessage(new Error("popup_closed")),
    /다시 시도/
  );
});
```

```python
def test_google_code_login_rejects_client_and_origin_mismatch_before_exchange(monkeypatch):
    _configure_google(monkeypatch)
    exchange_calls = []
    monkeypatch.setattr(
        google_auth_service,
        "_google_token_response_from_code",
        lambda *args, **kwargs: exchange_calls.append(args),
    )
    payload = _valid_payload()
    payload["client_id"] = "other-client.apps.googleusercontent.com"
    status, response = google_auth_service.create_google_code_login(
        payload,
        request_headers=_valid_headers(),
    )
    assert status == 401
    assert response["error"]["auth"]["reason"] == "google_client_id_mismatch"
    assert exchange_calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test app/web/authSession.test.js` and `python -m pytest -q test/test_google_oauth_code_contract.py`

Expected: frontend copy test fails; backend contract remains green as a boundary regression guard.

- [ ] **Step 3: Write minimal implementation**

Improve the safe public popup failure copy, preserve the raw error only in the local catch path, and after successful login invoke report hydration if the requested next route is `reporting`. Document exact Google Console / runtime equality checks without recording a client secret.

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test app/web/authSession.test.js` and `python -m pytest -q test/test_google_oauth_code_contract.py`

Expected: PASS.

### Task 4: End-to-end verification and handoff

**Files:**
- Modify: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-checklist.md`
- Test: `backend/chatbot/test_canonical_user_flow_e2e.py`
- Test: `backend/chatbot/test_guest_login_session_ownership_e2e.py`

- [ ] **Step 1: Run deterministic report/auth integration tests**

Run: `python backend/manage.py test chatbot.test_canonical_user_flow_e2e chatbot.test_guest_login_session_ownership_e2e chatbot.test_supervisor_reporting_pipeline`

Expected: canonical worker report, guest-to-user promotion, report list/detail ownership, document confirmation and download gates all pass.

- [ ] **Step 2: Run frontend and build verification**

Run: `node --test *.test.js`, `python -m pytest -q test/test_report_workbench_frontend_contract.py test/test_google_oauth_code_contract.py`, and `npm.cmd run build --prefix app/web`.

Expected: all pass.

- [ ] **Step 3: Deploy and browser retest**

Verify in the deployed site: workbench menu, empty state, authenticated saved-report hydration, report detail, save/DOCX gate, and Google login. Do not submit a provider-backed consultation or upload a file without separate cost authorization. If Google login fails, record whether the provider popup reports redirect mismatch, popup termination, or backend exchange failure.

- [ ] **Step 4: Update evidence**

Record exact pass/fail boundaries in the hotfix checklist. Do not mark provider/OCR/Vision/LLM flows passed without their independent live evidence.
