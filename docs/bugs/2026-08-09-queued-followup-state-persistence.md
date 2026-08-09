# Queued follow-up state is not persisted

## Symptom

A user can upload and confirm a fine-notice document. The canonical
`POST /api/chat/messages/` response is queued and contains server-generated
`pending_questions`, but the next short answer has no persisted field context.

## Root cause

`chatbot.views.submit_chat_message` sends queued responses to
`chatbot.repositories.enqueue_analysis_job_work`. Before this change that
repository method stored the queue job and work item but did not create the
`chat_session_followup_state.v1` snapshot that synchronous follow-up responses
create through `persist_chat_followup_state`.

The client request is not an authority for pending questions. The queued
response's `job_payload.chat_response` is the server-owned boundary.

## Fix boundary

Within the existing `enqueue_analysis_job_work` transaction, the repository now:

- creates a follow-up snapshot only when the server response has at least one
  pending question with a non-empty `field`;
- builds it with `build_chat_followup_snapshot` from the persisted request and
  server response;
- updates `ChatSession.current_intent` from the server response only in that
  case; and
- leaves an existing follow-up state unchanged when a queued response has no
  valid pending question.

The snapshot write is in the same transaction as `ChatSession`, `AnalysisJob`,
and `AgentWorkItem`; a work-item binding conflict rolls all of those new writes
back. Existing confirmed-OCR merge behavior is retained before this conditional
snapshot replacement.

## Deliberately unchanged

- API request and response contracts, models, and migrations;
- agent, supervisor, OCR, RAG, vision, frontend, and deployment behavior;
- Docker and dependency definitions; and
- report-generation behavior.

## Regression boundary

`backend/chatbot/test_queued_followup_state_persistence.py` drives the real
authenticated upload, local file scan, classification worker, classification
confirmation, and queued chat API path. Only the external classification leaf
is deterministic. It also verifies a client-supplied forged pending question is
not persisted, a later short answer fills only the server-persisted field, and
a real queue work-item collision does not commit the new snapshot.
