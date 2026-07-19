# Supervisor server-authoritative execution handoff

## Goal

For public chat and analysis-job requests, only the server-generated Supervisor
plan and its matching agent input package may control agent execution. A client
must not select a node, inject a slot value, or mark an upstream dependency as
complete.

## Observed gaps

- Chat workers receive a Supervisor handoff, but analysis-job workers can be
  queued from the raw request without that server handoff.
- Nested `agent_input.node_code` currently has precedence over a plan step's
  top-level `node_code`.
- Public `slot_state` and `upstream_results` can reach runtime input.
- Restoring an older queued work item does not independently re-apply the
  public-input boundary, and cannot distinguish a raw stored upstream value
  from a trusted server checkpoint.

## Design

Create `app/services/supervisor_execution_input_service.py`. It is a pure
transformation module with declarative public and worker-only field policies.

1. `sanitize_public_supervisor_request(payload)` removes public execution
   controls before fingerprinting, planning, queueing, or worker persistence:
   `agent_input`, `node_code`, `slot_state`, `upstream_results`, plan metadata,
   adapter/mode controls, reporting controls, and forged context handoff keys.
   Conversational search hints remain available to the Supervisor planner.
2. `build_trusted_worker_execution_payload(request_payload, chat_response)`
   takes the sanitized request and server-generated session/message/attachments
   and Supervisor state, then builds a worker payload with a server handoff,
   fresh `upstream_results`, and server-owned execution mode. Worker-only
   sanitation additionally removes direct query/retrieval controls. A legacy
   retry can receive upstream state only as repository-supplied rows rebuilt
   from `AgentResult` records for the same job and current plan.
3. `bind_supervisor_plan_step_payload(payload, step, upstream_results)` binds a
   plan step to the matching ready Supervisor package. The package snapshot and
   slot state are passed to the agent runtime; only runtime-generated upstream
   results are retained.

A ready handoff accepts the existing mock/fallback contracts and the real LLM
`supervisor_conversation.v1` contract. A matching package is executable only
when it has `agent_input_schema.v1`, the requested ready node, and a payload
with a string user-text field (`user_text` or legacy `raw_user_text`), list
attachments, and mapping slot state. An incomplete package is fail-closed.
The worker preflights that rule before creating a paid-dispatch reservation, and
repeats it at each runtime step.

`submit_chat_message` and `analysis_jobs` use the same sanitizer and builder.
`execute_agent_plan` binds every planned step through the shared service and
top-level plan `node_code` wins over a nested legacy field. Work-item payload
restoration applies the sanitizer as defence in depth. The separately
server-built reporting handoff is preserved as an internal path.

## Non-goals

- No new Agent, LLM provider, database migration, OpenAPI promotion, or report
  business-rule change.
- No request-specific routing hard-coded in views; field ownership is declared
  once in the service policy.

## Verification

- Unit tests prove two-stage control stripping, server handoff construction,
  LLM v1 compatibility, malformed-package fail-close, and matching package
  slot binding.
- Agent runtime regression proves a client nested node, client slot, and fake
  upstream result cannot override a one-step plan.
- Public Django E2E proves chat -> queue -> worker -> result uses server
  handoff/package state and owner-only result access; it also proves a malformed
  package creates neither an adapter call nor paid-dispatch reservation.
- Queue regression tests prove a non-Supervisor work item resumes only from
  persisted `AgentResult` rows, not a stored public `upstream_results` value.
- #224 / PR #225 remains the existing reverse-follow-up persistence contract.
