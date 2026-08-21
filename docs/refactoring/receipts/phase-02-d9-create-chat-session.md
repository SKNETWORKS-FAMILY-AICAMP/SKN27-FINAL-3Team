# Phase 2-D9 CreateChatSession receipt

## Authority

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Base: `893c0c56b9e05b65340e08ed3c8abb40a08c5696`
- Branch: `refactor/phase-02-d9-create-chat-session-use-case`
- RED Head: `ee40edbc368347f0724d6e9b1f4ce7bb297781ea`
- GREEN Head: `ff5d7cc1f03e13756b2e95700328f3d10b73e6e5`
- Verification / final runtime Head: `839447db4ad330ad9cbf913c3a7cc64dac33969c`
- PR: `PENDING_DRAFT_CREATION`

This receipt does not include its own commit SHA to avoid a self-reference commit loop.

## RED chronology

- RED was test-only: `backend/chatbot/test_phase_02_create_chat_session_use_case.py`.
- Command: `python backend/manage.py test chatbot.test_phase_02_create_chat_session_use_case --verbosity 1`
- Draft, identity spoofing, guest, history, history failure, invalid JSON, and no-persistence characterizations passed.
- The only RED failure was the new seam assertion:
  `AssertionError: Expected 'execute_create_chat_session' to have been called once. Called 0 times.`
- `RED_HEAD` is an ancestor of `GREEN_HEAD`.
- Classification: `INDEPENDENTLY_PROVABLE`.

## Implementation

- Route: `POST /api/chat/sessions/`
- View: `create_chat_session`
- Application: `app/application/chat/create_session.py`
- Use Case: `CreateChatSession`
- `CreateChatSessionCommand` receives normalized `identity_payload`, transport-derived history actor/source, and the existing best-effort history recorder.
- `execute_create_chat_session` derives the trusted subject, calls existing `create_session`, composes `chat_session_created`, records history, and returns `CreateChatSessionResult`.
- The View retains `_json_body`, `_payload_with_request_identity`, `_request_identity_error_response`, command construction, and `_json_response` only.

## Public contract

- Documented operation: `issueChatSessionDraft`
- Request body: optional
- Schema: `ChatSessionCreateRequest`, `contract_status="shadow"`
- Success: `200`
- Draft DTO: `contract_version`, `session_id`, `user_id`, `status`, `created_at`
- Initial status: `draft`
- Invalid JSON reaches the existing `{}` normalization; authenticated requests retain draft issuance.
- Authenticated users receive the verified user as `user_id`.
- Valid credentialed guests receive `user_id=None`; forged body user selection is ignored.
- Invalid guest credential or forged guest pairing retains `401`.
- `app/web/apiClient.js` and `app/web/FrontendAppShell.jsx` remain unchanged consumers for initial start, guest recovery, and new consultation creation.

### Existing transport observation

`ChatSessionCreateRequest` remains auth-optional, but current `JwtAuthMiddleware` returns `401 auth_required` for a request with neither a Bearer token nor a guest credential. D9 preserves this existing effective HTTP behavior and does not alter middleware alignment.

## Security

- `_payload_with_request_identity` neutralizes client-owned `user_id`, `owner_id`, `guest_id`, `subject_id`, `subject_type`, and `auth_session_id`.
- `CreateChatSession` uses `access_subject_from_payload` over trusted `auth_context` only.
- Authenticated user A remains authoritative when the body supplies B values.
- Valid guest requests cannot choose a user through body fields.
- No client-owned owner authority or P0 spoofing leakage was introduced.

## State and persistence

- `create_session` still issues only a draft DTO with `ses_` prefix.
- D9 does not create a persistent `ChatSession` row.
- The focused suite verifies ChatSession row count is unchanged by draft issuance.
- No transaction or rollback architecture was introduced.

## History

- Event: `chat_session_created`
- Actor and subject: trusted identity-derived actor and generated session ID.
- Metadata: `{"session_status": "draft"}`
- The injected recorder remains `partial(_record_history_safely, request)`.
- `DatabaseError` and `OSError` history failures keep the valid `200` draft response.

## Sensitivity

Runner: `scripts/refactoring/verify_phase_02_d9_create_chat_session_test_sensitivity.py`

| Mutation | Direct detection | Result |
| --- | --- | --- |
| `view_application_bypass` | executor-call HTTP test | `AssertionError` |
| `trusted_identity_bypass` | forged identity characterization | `AssertionError` |
| `draft_initialization_bypass` | exact draft response characterization | `AssertionError` |
| `history_event_bypass` | trusted history event assertion | `AssertionError` |
| `history_failure_semantics_bypass` | history failure `200` characterization | `AssertionError` |

Baseline exit code was `0`; all five mutations had nonzero exit code and `failure_kind="assertion"`. Source restoration and working-tree preservation were `true`.

## Verification

- D9 focused: `9 tests, OK`
- D9 + chat-session contract + guest boundary: `28 tests, OK`
- B1–D8 plus D9 Application boundaries: `102 tests, OK`
- API/OpenAPI/sensitivity runner pytest selection: `58 passed`
- Django system check: passed
- OpenAPI and frontend route catalog drift checks: passed
- Ruff static and D9 F401 import gates: passed
- Deployment artifacts and frontend Explicit Mock surface: `19 passed`
- Frontend node suite: `155 passed`
- Frontend production build: passed
- `git diff --check`: passed before this receipt change

### Windows observation

`python backend/manage.py test chatbot --verbosity 1` ran `557 tests` and retained `20 errors`: existing `pymupdf._extra` DLL loading and attachment classification adapter portability groups. No D9-specific failure group was observed.

### Docker and production DB

- Local Docker D1/D2: `NOT_EXECUTED` — Docker Desktop Linux daemon pipe was unavailable.
- Production DB audit: `NOT_EXECUTED`.

## CI

The final source Head, runtime checkout SHA, `production-gate`, `offline-verification`, `compose-integration`, `regression-signal`, and `phase-02-d9-sensitivity-evidence` artifact will be recorded after this receipt is pushed. This receipt deliberately does not create a post-CI self-reference commit.

## Deferred

- `FileReadQueries`
- `AnalysisReadQueries`
- guest-session issue
- refresh
- logout
- `auth/me`
- Phase 3 provider, storage, queue/worker, renderer, retry/refund, and transaction architecture work
- `RESUME_GUEST_TRANSPORT_VIEW_CONTRACT_ALIGNMENT`
- `MYPAGE_PUBLIC_PROJECTION_HARDENING_REQUIRED`
- Windows portability debt

`ESTIMATED_REMAINING_PHASE_2_SLICES=7`
