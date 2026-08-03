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
