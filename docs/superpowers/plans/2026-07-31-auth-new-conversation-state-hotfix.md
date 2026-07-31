# HFX-012 Authentication Recovery and New Conversation State Plan

> **Execution rule:** Implement every behavior test-first. Observe each focused test fail for the intended reason before editing production code.

**Goal:** Make reload authentication server-verified, prevent authenticated users from falling back into guest bootstrap, and make “new conversation” switch to a newly issued server session only after every conversation-owned UI state can be reset together.

**Baseline:** `feat-pilot-safety-hotfix` at `9db7ccb50f5d9961597bb551846cbfc677723db6`

**Architecture:** Treat local storage only as a recovery hint. During startup, keep guest bootstrap closed while the stored app JWT is checked against `/api/auth/me/`. Proactively refresh a still-valid token in its refresh window, then verify the returned identity. On an authentication failure, remove only the invalid authenticated identity while preserving the signed guest/session recovery context and all visible conversation data. For a new conversation, use the existing canonical `POST /api/chat/sessions/` contract and commit the new session ID plus a complete conversation-state reset only after the server call succeeds.

**Approved scope:** G2/HFX-012 only. Reuse the existing Django authentication and chat-session contracts. Do not change OAuth provider policy, ownership authorization, attachment/OCR processing, report generation, Worker behavior, deployment configuration, or production E2E behavior in this phase unless a new RED regression proves a contract defect.

## Task 1: Recover stored authentication through the server

**Files**

- Modify: `app/web/authSession.test.js`
- Modify: `app/web/authSession.js`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `test/test_frontend_auth_session_contract.py`

**Contract**

- A stored app JWT is not considered authenticated until `/auth/me` confirms the same user and auth session.
- A still-valid token inside the five-minute refresh window is refreshed before `/auth/me`.
- A token outside the refresh window goes directly to `/auth/me`.
- An expired, invalid, or revoked authenticated identity becomes `reauth_required`; it is never converted into a different guest identity.
- Signed guest credentials and the current chat session ID survive authenticated-token recovery failure.
- Authentication validation failure does not clear chat, attachment, OCR, or current analysis state.

- [x] Add RED Node tests for direct `/auth/me` recovery, proactive refresh plus `/auth/me`, refresh failure, and auth-session mismatch.
- [x] Add a RED source-contract test proving startup calls `api.getCurrentAuthSubject` and does not initialize authenticated UI state directly from unverified local storage.
- [x] Run:

  ```powershell
  node --test app/web/authSession.test.js
  python -m pytest test/test_frontend_auth_session_contract.py -q
  ```

  Expected RED: no recovery helper, no startup `/auth/me` effect, and local storage immediately sets `authSessionId`.

- [x] Implement a pure `recoverStoredAuthSession` helper that returns explicit `authenticated`, `reauth_required`, `verification_unavailable`, or `not_applicable` results.
- [x] Validate that `/auth/me` returns `auth_state=authenticated`, an authenticated subject, and the expected `auth_session_id`.
- [x] Refresh only while the locally decoded expiry is at or inside the existing early-refresh window; remember that the current server contract requires the old token to still be valid.
- [x] Initialize authenticated React state as empty while recovery is `checking`, then populate it only from the verified result.
- [x] On authentication rejection, clear the invalid app JWT/profile but re-persist the existing signed guest credential and chat session binding; on transient verification failure, preserve storage and keep privileged actions closed.
- [x] Re-run focused tests and confirm GREEN.

## Task 2: Close guest bootstrap while authenticated or validating

**Files**

- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `test/test_frontend_auth_session_contract.py`

**Contract**

- `bootstrapGuestSession` is unreachable while startup auth validation is pending.
- An authenticated user with an existing session reuses that session without a guest bootstrap request.
- An authenticated user without a chat session obtains one from `POST /api/chat/sessions/`.
- Direct attachment and follow-up paths use the same guarded session-ensuring function.

- [x] Add RED source-contract assertions for a validation-pending guard, an authenticated branch, and removal of direct guest bootstrap calls from attachment/follow-up paths.
- [x] Add `createChatSession` to the frontend API client for the existing canonical endpoint.
- [x] Refactor `ensureGuestSession` into an identity-aware session gate without changing the guest two-step credential bootstrap contract.
- [x] Replace direct guest bootstrap call sites with the guarded session gate.
- [x] Remove local session-ID fallbacks at message/attachment call sites and abort the request when the guarded gate returns no server session.
- [x] Re-run the frontend auth/session contract suite.

## Task 3: Make new conversation activation atomic

**Files**

- Create: `app/web/newConversationState.js`
- Create: `app/web/newConversationState.test.js`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `test/test_frontend_auth_session_contract.py`

**Contract**

- “New conversation” first requests a server-issued session ID using the current verified identity.
- A missing or unchanged session ID is rejected and the old conversation remains visible.
- Server failure changes only the status message; it does not partially clear the current conversation.
- Success preserves authenticated user, app JWT, guest credential lineage, and Google profile.
- Success clears question, submitted question, chat messages, intake, analysis, current/listed report state, report errors/actions, selected/registered attachments, upload input, OCR fields/pending confirmation, pending auth action, save prompt/decision, detailed-report quota flag, appeal acknowledgement, My Page/history snapshots, and relevant loading flags.
- The new session binding is persisted only after successful issuance.

- [x] Add RED Node tests for distinct session acceptance, missing/unchanged session rejection, and fresh reset values on every call.
- [x] Replace the old source-contract assertion (`setSessionId("")`) with assertions for server issuance, success-only reset, attachment/OCR cleanup, identity preservation, and session persistence.
- [x] Run:

  ```powershell
  node --test app/web/newConversationState.test.js
  python -m pytest test/test_frontend_auth_session_contract.py -q
  ```

  Expected RED: the helper does not exist and `startNewConversation` clears only a subset of state without issuing a server session.

- [x] Implement pure session-response validation and reset-state construction.
- [x] Make `startNewConversation` asynchronous and apply setters only after session issuance succeeds.
- [x] Persist the new session with the current verified auth/guest identity.
- [x] Keep the previous session and state untouched on failure.
- [x] Re-run focused tests and confirm GREEN.

## Task 4: Verify backend ownership contracts remain intact

**Files**

- Modify only if RED proves necessary: `backend/chatbot/test_security_hardening.py`
- Modify only if RED proves necessary: `backend/chatbot/test_guest_credential_boundary.py`
- Modify only if RED proves necessary: `backend/chatbot/test_report_api_contract.py`

- [x] Run the existing auth lifecycle, guest credential, chat session, and report ownership tests.
- [x] Confirm another user cannot open the previous user’s session/report.
- [x] Confirm guest → Google login continues to bind the same conversation.
- [x] Confirm valid-token refresh and subsequent `/auth/me` preserve the same user.
- [x] Do not modify backend production code when the existing contracts pass.

## Task 5: G2 regression, build, and evidence update

**Files**

- Modify: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md`
- Modify only for observed evidence: `docs/tech-validation-reports/2026-07-31-e2e-cross-analysis-final-hotfix-report.md`

- [x] Run all frontend Node tests:

  ```powershell
  node --test app/web/*.test.js
  ```

- [x] Run the focused Python/Django auth and ownership suites.
- [x] Run the broader P0 regression modules already used at the G1 gate.
- [x] Run:

  ```powershell
  npm run build
  git diff --check
  git status --short
  ```

- [x] Record exact command results, test counts, build version, and remaining production-only validation in the master checklist.
- [x] Mark G2 complete only when ID 5 can proceed past authentication locally, lifecycle contracts pass, ownership remains isolated, and the UI hotfix integration review has no unresolved conflict.
- [x] Leave production redeploy and all 13 deployed E2Es under G8/G9; do not claim them from local G2 evidence.

## Execution checkpoint

The user has already selected in-session execution after the P0 safety-boundary commit. Execute Tasks 1–5 sequentially with RED/GREEN checkpoints and stop before any commit, push, merge, build deployment, or production E2E action that remains user-owned or belongs to a later gate.
