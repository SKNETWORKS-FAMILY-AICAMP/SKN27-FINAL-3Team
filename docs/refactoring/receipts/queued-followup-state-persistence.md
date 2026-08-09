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
