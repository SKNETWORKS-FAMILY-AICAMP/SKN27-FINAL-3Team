# Report Account Workspace Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show every report owned by the authenticated user across chat sessions and automatically prepare a reviewable objection draft after OCR confirmation without keyword gates.

**Architecture:** Keep report detail and download session binding unchanged, but make the report list an owner-scoped authenticated query. Treat confirmed fine-notice OCR as sufficient to plan a draft; incomplete facts produce a partial draft, while integrity, ownership, scan, and official-download safety gates remain intact.

**Tech Stack:** React 19, native Node test runner, Django, pytest, Vite

## Global Constraints

- Preserve authenticated `owner_id` isolation for every persisted report.
- Do not expose persistence-only report metadata.
- Generate a reviewable draft after confirmed fine-notice OCR without requiring document/action keywords.
- Keep current report detail, confirmation, and download authorization unchanged.
- Keep official DOCX download blocked when the appeal eligibility gate is blocked.

---

### Task 1: Owner-scoped report list

**Files:**
- Modify: `app/web/apiClient.js`
- Modify: `app/web/FrontendAppShell.jsx`
- Test: `app/web/apiClient.test.js`
- Test: `backend/chatbot/test_report_api_contract.py`

**Interfaces:**
- Consumes: authenticated frontend identity headers
- Produces: `listReports({ identity }) -> ReportListResponse`

- [x] Write a failing frontend test asserting `GET /api/reports/` has no `session_id` query.
- [x] Write a backend regression test asserting one owner sees reports from two owned sessions but not another owner.
- [x] Run both tests and confirm the frontend test fails for the current session-scoped URL.
- [x] Remove the list-only session query and stop passing the active session to `listReports`.
- [x] Run both tests and confirm they pass.

### Task 2: Relaxed OCR-to-draft planning

**Files:**
- Modify: `app/services/chat_orchestration_service.py`
- Modify: `app/web/FrontendAppShell.jsx`
- Test: `test/test_chat_orchestration_service.py`
- Test: `test/test_frontend_report_api_contract.py`

**Interfaces:**
- Consumes: confirmed fine-notice OCR payload
- Produces: an analysis plan containing `objection_report_generation`

- [x] Change the synthetic fine-notice regression test to require report planning without report keywords, complete OCR fields, or pre-confirmed user facts; confirm it fails.
- [x] Make confirmed OCR sufficient for fine-notice report planning and remove the pre-plan user-facts hold.
- [x] Relabel the OCR confirmation action so automatic draft preparation is explicit to the user.
- [x] Run the focused orchestration and frontend contract tests and confirm they pass.

### Task 3: Reviewable partial drafts and truthful empty state

**Files:**
- Modify: `app/services/report_document_card_service.py`
- Modify: `ai/agents/objection_report_generation/agent.py`
- Modify: `app/web/reportWorkbenchState.js`
- Test: `test/test_report_document_card_service.py`
- Test: `app/web/reportWorkbenchState.test.js`

**Interfaces:**
- Consumes: report availability and Supervisor stage
- Produces: actionable `not_reportable` workbench copy

- [x] Change the blocked-appeal card test to require a copyable partial draft; confirm it fails.
- [x] Keep copy actions and draft cards available while the appeal gate continues to block official download.
- [x] Change the existing workbench test to require an `아직 생성되지 않았습니다` state and OCR draft guidance; confirm it fails.
- [x] Update the state copy without altering available, loading, or temporary report behavior.
- [x] Run the focused frontend tests.
- [x] Run Django chatbot tests, the complete Python suite, all frontend Node tests, Vite build, and `git diff --check`.
- [ ] Deploy the verified SHA and run the authenticated browser flow: open the report menu, select a prior report, start a new fine-notice flow, confirm OCR, verify automatic draft generation, and download DOCX when eligible.

### Task 4: Separate current-session, saved-list, and selected-report state

**Files:**
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/web/newConversationState.js`
- Test: `app/web/newConversationState.test.js`
- Test: `app/web/reportWorkbenchState.test.js`
- Test: `test/test_frontend_auth_session_contract.py`

**Interfaces:**
- Consumes: active chat `sessionId`, resume manifest session report, owner-scoped report summaries
- Produces: independent `currentSessionReport`, `savedReportList`, and `selectedSavedReport` state

- [ ] Add failing tests requiring three independent report states and requiring new-conversation reset to preserve the account list.
- [ ] Add a failing auth-restore contract test requiring an owner-scoped list request after resume hydration.
- [ ] Replace the two overloaded report states with the three explicit states and an active-report projection.
- [ ] Make `loadReports` update the account list, hydrate only a matching current-session report, and never auto-select another session's latest report.
- [ ] Make explicit list selection update `selectedSavedReport`; reset only conversation-owned report state on new conversation.
- [ ] Run the focused frontend tests and contract tests.

### Task 5: Persist the structured OCR draft-generation request

**Files:**
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/services/chat_session_followup_service.py`
- Modify: `backend/chatbot/views.py`
- Modify: `backend/chatbot/repositories.py`
- Test: `backend/chatbot/test_chat_session_followup_ocr_confirmation.py`
- Test: `backend/chatbot/test_attachment_classification_confirmation_flow.py`
- Test: `test/test_frontend_auth_session_contract.py`

**Interfaces:**
- Consumes: `report_generation_requested: true` and `report_generation_action.v1`
- Produces: server-normalized action in `chat_followup_state` and `AnalysisJob.metadata`

- [ ] Add failing frontend contract coverage for the boolean and the `generate_objection_draft` action.
- [ ] Add failing service tests proving valid confirmed-OCR actions persist and topic switches or stale attachments do not restore them.
- [ ] Add a failing Django E2E assertion for both ChatSession and AnalysisJob persistence.
- [ ] Normalize and restore the narrow action at the server follow-up boundary; remove previous-message keyword reconstruction.
- [ ] Persist the same normalized request in queued analysis metadata without granting public execution authority.
- [ ] Run focused service, E2E, and frontend contract tests.

### Task 6: Distinguish saved-only report workspaces and verify

**Files:**
- Modify: `app/web/reportWorkbenchState.js`
- Modify: `app/web/FrontendAppShell.jsx`
- Test: `app/web/reportWorkbenchState.test.js`

**Interfaces:**
- Consumes: current-session report presence, explicit saved-report selection, and owner-scoped saved-list presence
- Produces: `saved_reports_only` workbench state

- [ ] Add a failing test for “현재 상담 리포트 없음 + 내 저장 리포트 있음”.
- [ ] Add the `saved_reports_only` state and pass the separate state flags from the shell.
- [ ] Run all frontend Node tests, the complete Python test suite, Django chatbot tests, Vite build, and `git diff --check`.
- [ ] After deployment, verify login restore, saved-only workspace, prior-report selection, OCR action persistence, automatic draft generation, and eligible DOCX download in the browser.
