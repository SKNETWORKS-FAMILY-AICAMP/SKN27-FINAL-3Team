# #229 Supervisor server-authoritative handoff plan

## Guardrails

- The user performs all Git stage, commit, push, PR, merge, and deletion work.
- Keep the implementation modular and configuration/policy-driven; do not add
  view-local node routing or test-only production branches.
- Do not change the Agent's legal/business role, provider, API surface, or DB.

## Files in scope

| File | Change |
| --- | --- |
| `app/services/supervisor_execution_input_service.py` | New pure public-input sanitation, worker payload builder, and package binding service |
| `backend/chatbot/views.py` | Use the shared sanitizer/builder in chat and analysis public entrypoints |
| `app/services/agent_node_service.py` | Bind server package per plan step and make plan node authoritative |
| `backend/chatbot/repositories.py` | Sanitize restored public work payload, rebuild non-Supervisor checkpoints from DB result rows, and preflight handoff before paid dispatch |
| `test/test_supervisor_execution_input_service.py` | New pure service tests |
| `test/test_agent_execution_service.py` | Node/slot/upstream override regression |
| `backend/chatbot/test_production_hardening.py` | Both public entrypoints produce trusted execution payloads |
| `backend/chatbot/test_analysis_job_queue.py` | Public queue -> worker -> result E2E |
| `docs/ops/project-readiness-master-checklist.md` | Record #224/#226 complete and #229 in progress |

## Tasks

- [x] Write failing tests for public-control stripping and package binding.
- [x] Implement the shared input service and wire both public entrypoints.
- [x] Write failing Agent runtime regression, then implement plan node/slot and
  runtime-upstream precedence.
- [x] Add queue restoration defence in depth and public Django E2E.
- [ ] Run changed-file, unintended-file, tests, lint/type, direct feature,
  security/privacy, hard-coding/modularity, and plan-vs-actual gates.

## Required evidence before PR handoff

1. No public payload retains `agent_input`, `node_code`, `slot_state`,
   `upstream_results`, plan, adapter, reporting, or forged handoff controls.
2. A queued chat and analysis request contain server-generated Supervisor
   handoff/package state.
3. A plan step's node and package slot state reach the adapter even if the
   original request supplied conflicting values.
4. Only runtime-generated upstream results are used for plan dependencies.
5. The public owner can retrieve the finished result; no new route or
   authorization bypass is introduced.
6. A malformed ready package is rejected before a paid-dispatch reservation or
   adapter invocation, while normal LLM `supervisor_conversation.v1` handoffs
   remain executable.
7. A legacy/non-Supervisor retry can resume only from `AgentResult` rows owned
   by the current job, never from stored request JSON.
