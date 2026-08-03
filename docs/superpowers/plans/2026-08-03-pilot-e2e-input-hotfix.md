# Pilot E2E Input Hotfix Implementation Plan

> **For Codex:** Execute this plan sequentially with test-driven development. Do not include OCR or authentication changes in this hotfix.

**Goal:** Make the production browser E2E fine-notice and accident sentences populate the existing Supervisor input contracts without repeated questions or lost follow-up slots.

**Architecture:** Keep the frontend consultation selector as routing metadata, normalize only domain facts expressed by the user, project the newly supported facts into the existing fine-notice and accident contracts, and persist fine-notice slots through the existing server-authoritative follow-up snapshot.

**Tech Stack:** React/Node tests, Python service layer, pytest, JSON normalization policy.

---

### Task 1: Stop the consultation label from creating a fine-type conflict

**Files:**
- Modify: `app/web/consultationIntake.js`
- Test: `app/web/consultationIntake.test.js`

1. Add a failing test proving the `fine_notice` category does not inject both `과태료` and `범칙금` into the request text.
2. Use a neutral request label while leaving the visible option label unchanged.
3. Run the focused Node test.

### Task 2: Normalize the verified fine-notice and accident phrases

**Files:**
- Modify: `app/config/supervisor_input_normalization_policy.v1.json`
- Modify: `app/services/supervisor_input_normalization_service.py`
- Modify: `app/services/supervisor_input_projection_service.py`
- Modify: `docs/policies/supervisor-input-normalization/*.md`
- Test: `test/test_supervisor_input_normalization_service.py`
- Test: `test/test_supervisor_input_projection_service.py`

1. Add failing tests for `서울특별시`, spaced `의견제출 기한`, attachment availability, lane change, and front-bumper/side-door collision facts.
2. Add only the rules and projections required by those verified E2E phrases.
3. Run the focused Python tests.

### Task 3: Preserve fine-notice intake slots across follow-up turns

**Files:**
- Modify: `app/services/chat_session_followup_service.py`
- Test: `test/test_chat_session_followup_service.py`

1. Add a failing test for snapshot and restore of server-produced fine-notice slots.
2. Merge persisted slots with server state taking precedence.
3. Run the focused Python test.

### Task 4: Verify the bounded hotfix

**Files:**
- No additional production files.

1. Run all focused tests and the relevant orchestration/frontend contract tests.
2. Run the complete local regression suite and production frontend build.
3. After deployment, repeat the same browser sentences before moving to the OCR hotfix.
