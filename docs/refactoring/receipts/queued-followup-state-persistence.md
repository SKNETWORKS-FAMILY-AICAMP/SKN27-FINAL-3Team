# Queued follow-up state persistence receipt

## Base

- Base branch: `origin/dev`
- Base SHA: `198efeba3cabacc3a977cfcaf2f8d7e06fd47104`
- Working branch: `fix/queued-followup-state-persistence`

## Git

- Worktree: `E:\\dev\\project\\SKN27-FINAL-3Team-followup-fix`
- Branch: `fix/queued-followup-state-persistence`
- Verified application head: `131b075b0b1c134b15a62868af1f4b395f17f453`
- Commits:
  - `137a8aa fix: persist queued follow-up state atomically`
  - `131b075 docs: record queued follow-up state fix`
- Draft PR: [#400](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/pull/400)

## Root-cause evidence

- Production route: `POST /api/chat/messages/` in `chatbot.views.submit_chat_message`.
- Queued persistence boundary: `chatbot.repositories.enqueue_analysis_job_work`.
- The queued response carries server-owned `job_payload.chat_response.pending_questions`.
- Before the change, that transaction preserved confirmed OCR state only; it did
  not store `chat_session_followup_state.v1` for a queued pending question.

## RED / GREEN evidence

| Check | Command | Exit code | Result |
|---|---|---:|---|
| RED | `python backend/manage.py test chatbot.test_queued_followup_state_persistence --verbosity 2` | 1 | `KeyError: 'chat_followup_state'` after the real queued fine-notice confirmation flow. |
| GREEN | `python backend/manage.py test chatbot.test_queued_followup_state_persistence --verbosity 2` | 0 | 5 tests passed. |
| Diff whitespace | `git diff --check` | 0 | No whitespace errors. |

The local Python invocation used the installed Python 3.13 executable because
`python` was not available on the local shell PATH; the Django command and test
arguments above are unchanged.

## Mutation sensitivity

Only the expected `response_deadline` assertion in
`test_queued_fine_notice_pending_question_is_persisted_for_next_turn` was
temporarily changed to `mutated_response_deadline`.

| Check | Command | Exit code | Result |
|---|---|---:|---|
| Mutated assertion | `python backend/manage.py test chatbot.test_queued_followup_state_persistence.QueuedFollowupStatePersistenceTests.test_queued_fine_notice_pending_question_is_persisted_for_next_turn --verbosity 1` | 1 | Expected list mismatch. |
| Assertion restored | `python backend/manage.py test chatbot.test_queued_followup_state_persistence --verbosity 2` | 0 | 5 tests passed. |

No production code was altered for the mutation check.

## CI gate

`production-gate.yml` adds a separate blocking step:

```text
Queued follow-up state regression
python backend/manage.py test chatbot.test_queued_followup_state_persistence --verbosity 1
```

The step has `timeout-minutes: 5` and no `continue-on-error`. It is independent
of the existing Phase 0 core regression step and does not add a broad full-suite
test run.

## Changed files

| Path | Type | Symbol / step | Purpose | Test coverage |
|---|---|---|---|---|
| `backend/chatbot/repositories.py` | production | `enqueue_analysis_job_work` | Atomically store a server-owned queued follow-up snapshot. | New 5-test regression module. |
| `backend/chatbot/test_queued_followup_state_persistence.py` | test | `QueuedFollowupStatePersistenceTests` | Characterize queue persistence, next-answer binding, forged input, no-wipe, and rollback. | 5 tests. |
| `.github/workflows/production-gate.yml` | CI | `Queued follow-up state regression` | Make the regression blocking. | GitHub Actions Run `31307095521`. |
| `docs/bugs/2026-08-09-queued-followup-state-persistence.md` | documentation | root-cause record | Record the runtime boundary and deliberate non-goals. | Review artifact. |
| this receipt | documentation | evidence | Record local and remote evidence. | Review artifact. |

## Transaction consistency

- Queue and snapshot atomicity: the snapshot assignment is inside the existing
  `transaction.atomic()` block that writes `ChatSession`, `AnalysisJob`, and
  `AgentWorkItem`.
- Rollback evidence: `test_queue_failure_does_not_commit_new_followup_snapshot`
  creates a real conflicting work-item ID. The repository raises its normal
  binding `ValueError`; the new job and follow-up snapshot are absent afterward,
  while the prior session metadata and intent remain unchanged.
- Duplicate message behavior: unchanged. The queue path continues to use its
  existing `ChatMessage.update_or_create(message_id=...)` boundary.
- Idempotency: unchanged. Existing analysis-job idempotency handling remains in
  `enqueue_analysis_job_work`; this change does not add a new job or message
  path.

## Security

- Client pending fields: the snapshot is built from
  `job_payload.chat_response.pending_questions`; the forged client-field test
  proves the client value is absent from persisted state.
- Raw OCR and private URI: the snapshot test asserts neither `raw_ocr` nor
  `storage_uri` is written by this path.
- Credentials: no credential value, secret, or token field was added.
- Ownership: existing session-owner validation is unchanged and remains before
  the transaction's metadata write.

## API and data model changes

- API: none.
- Model: none.
- Migration: none.
- Follow-up contract: existing `chat_session_followup_state.v1` only; no new
  metadata contract version was introduced.

## Remote CI evidence

| Workflow | Run ID | Job / step | Result |
|---|---:|---|---|
| `production-gate` | `31307095521` | `offline-verification` / `Queued follow-up state regression` | PASS |
| `production-gate` | `31307095521` | frontend build, Terraform validation, Docker build and import smoke | PASS |
| `regression-signal` | `31307095525` | workflow | PASS |

The production-gate run validated application head
`131b075b0b1c134b15a62868af1f4b395f17f453`.

## Remaining risks

- P0: none found in this fix boundary.
- P1: Docker Compose service integration remains outside this PR's focused
  regression gate.
- P2: Report lifecycle behavior is deliberately out of scope.

## Rollback

- Revert application commit: `git revert 137a8aa`.
- Revert documentation/CI record if needed: `git revert 131b075`.
- Database rollback: none; no schema or migration changed.
- Verify after a revert: run
  `python backend/manage.py test chatbot.test_queued_followup_state_persistence --verbosity 2`.

## Scope check

- No model or migration changed.
- No API contract or endpoint changed.
- No agent, supervisor, OCR, RAG, vision, frontend, Docker, dependency,
  Terraform, deployment, or report-generation change is included.
- The fix does not trust client `pending_questions`; it stores only server
  response questions and preserves existing state when no valid server question
  is present.

## P2 characterization follow-up

### Review adjudication

- Original review: `FAIL` due to mixed baseline findings.
- Corrected PR judgment: `PASS_WITH_CONDITIONS`.
- Corrected merge: `ALLOWED_AFTER_P2_FIX`.
- PR-introduced P0: none.
- PR-introduced P1: none.

### Added assertions

| Test | Added verification | Database boundary | Result |
|---|---|---|---|
| `test_successful_pending_enqueue_persists_job_work_item_and_message_once` | API response IDs resolve to exactly one queued job, work item, and message with one shared session/owner binding. | `ChatSession`, `AnalysisJob`, `AgentWorkItem`, `ChatMessage` | PASS |
| `test_queue_failure_does_not_commit_new_followup_snapshot` | A real work-item binding collision leaves no new job, work item, message, or event and preserves the existing binding and session state. | `ChatSession`, `AnalysisJob`, `AgentWorkItem`, `ChatMessage`, `AnalysisJobEvent` | PASS |
| `test_idempotent_pending_enqueue_reuses_job_work_item_message_and_snapshot` | The existing repository re-enqueue contract reuses one job, work item, message, event, and unchanged pending snapshot. | `ChatSession`, `AnalysisJob`, `AgentWorkItem`, `ChatMessage` | PASS |

### Success enqueue invariants

- `AnalysisJob` has the response job ID, current session, current owner, and
  `queued` status.
- `AgentWorkItem` has the response work-item ID, belongs to that job, and is
  `queued`.
- `ChatMessage` has the response message ID, belongs to the same session, and
  is the job's message.
- The stored snapshot routing intent and pending questions equal the queued
  job's routing intent and persisted pending questions.
- The target job, work item, message, and job-to-work-item binding each have a
  count of exactly one.

### Rollback invariants

- The conflicting work item remains bound to its original queued job.
- The new job, work item, message, and analysis-job event do not exist after
  the binding `ValueError`.
- Existing session metadata, `chat_followup_state`, and `current_intent` are
  unchanged; the new pending field is absent.
- Session-scoped message, job, work-item, and existing-event counts are
  unchanged.

### Replay invariants

- Replay contract: supported repository-level re-enqueue with the same
  server-owned job and message IDs; no new replay API or production behavior
  was added.
- Job, work-item, and message counts remain one; the queued job retains one
  queue event.
- The persisted snapshot, pending-question order, session auth marker, and
  `current_intent` remain unchanged after replay.
- Result: PASS.

### Sensitivity

| Test | Temporary mutation | Exit code | Restore result |
|---|---|---:|---|
| Successful enqueue | Expected job count `1` changed to `2`. | 1 | Restored; 7-test module passed. |
| Rollback | New-message absence assertion inverted. | 1 | Restored; 7-test module passed. |
| Replay | Expected work-item count `1` changed to `2`. | 1 | Restored; 7-test module passed. |

### Local verification

The local shell has no `python` or `ruff` command on `PATH`; equivalent
commands used the installed Python 3.13 executable and `python -m ruff`.

| Check | Exit code | Result |
|---|---:|---|
| queued follow-up characterization module | 0 | 7 passed |
| analysis-job queue module | 0 | 34 passed |
| related attachment/OCR/consultation/hardening modules | 0 | 95 passed |
| follow-up/fine-notice/orchestration service tests | 0 | 81 passed |
| production contract/artifact/API tests | 0 | 53 passed |
| Django system check | 0 | no issues |
| OpenAPI and frontend route drift checks | 0 | current |
| Ruff `E9,F63,F7,F82` | 0 | all checks passed |
| frontend production build | 0 | built successfully |
| full offline pytest | 1 | known `cv2` (3) and `pypdf` (1) collection baseline |
| full Django chatbot suite on Windows | 1 | 419 tests; one EICAR fixture `OSError: [Errno 22]` at quarantine source read |

### Baseline exclusions

The following remain separate from PR #400 and were not changed here:

- `cv2` collection baseline.
- `pypdf` collection baseline.
- Windows EICAR portability. The failing path is the existing upload and
  object-storage boundary, not the queued follow-up change. Canonical Ubuntu
  CI completed the Django chatbot suite successfully.

### Verified behavior commit

- Verified behavior commit: `90c55bd90db4e068250a7db6bea1ae594dc04611`
  (`test: strengthen queued follow-up persistence invariants`).

### CI evidence

| Workflow | Run ID | Commit | Result |
|---|---:|---|---|
| `production-gate` / `offline-verification` | `31312325571` | `90c55bd90db4e068250a7db6bea1ae594dc04611` | PASS, including the blocking queued follow-up regression and Docker import smoke. |
| `regression-signal` | `31312325570` | `90c55bd90db4e068250a7db6bea1ae594dc04611` | Workflow PASS; full offline pytest command Exit 2 under `continue-on-error`, Django chatbot suite 419 tests `OK`. |

### Final PR Head authority

The final PR head is authoritative in GitHub PR metadata. The receipt records
the verified behavior commit and CI run separately to avoid self-referential
documentation commits.
