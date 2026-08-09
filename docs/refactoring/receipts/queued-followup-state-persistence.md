# Queued follow-up state persistence receipt

## Base

- Base branch: `origin/dev`
- Base SHA: `198efeba3cabacc3a977cfcaf2f8d7e06fd47104`
- Working branch: `fix/queued-followup-state-persistence`

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

## Scope check

- No model or migration changed.
- No API contract or endpoint changed.
- No agent, supervisor, OCR, RAG, vision, frontend, Docker, dependency,
  Terraform, deployment, or report-generation change is included.
- The fix does not trust client `pending_questions`; it stores only server
  response questions and preserves existing state when no valid server question
  is present.
