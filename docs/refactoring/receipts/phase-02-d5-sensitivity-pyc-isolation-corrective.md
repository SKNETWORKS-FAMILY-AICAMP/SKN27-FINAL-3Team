# Phase 2-D5 sensitivity PYC isolation corrective

## Authority

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Base branch: `dev`
- Base SHA: `5b86f4a357b6c156d3c9e92845f62f038cede4ee`
- Corrective branch: `fix/phase-02-d5-sensitivity-pyc-isolation`
- RED Head: `8d0fee3ab06747a442b6473fe65b5a10985e94dc`
- GREEN Head: `d1042f33181dafc7064ca4ff5aba0ffd7dfc2309`

This receipt does not self-reference its own Docs commit SHA; that Head is
recorded externally after this commit is created.

## Trigger

The related D13 PR is #417 at
`2306bd909ad48ba5ec766a3251f871cd0772add2`. Its historical D5 evidence had
baseline exit `0`, an empty mutation result, and a generic unexpected-pass
error. The relevant historical references are production-gate `33820851126`
and D5 artifact `9918251513`.

## Confirmed Root Cause

`TIMESTAMP_PYC_EQUAL_SIZE_COLLISION` is confirmed.

- `list_view_application_bypass` and `detail_view_application_bypass` both
  mutate `backend/chatbot/views.py` by `+90` bytes.
- The two mutated `views.py` files therefore both have size `135180`.
- Their timestamp-mode `.pyc` headers have flags `0`, with the same stored
  timestamp and source size.
- A shared cache allowed the second mutation to reuse stale bytecode and
  escape with exit `0`.
- An empty unique cache made the same mutation fail by direct `AssertionError`.
- Reversing list/detail order reproduced the symmetric escape.
- Django pre-import and mutation-anchor instability were excluded.

## Corrective

Each D5 mutation subprocess now receives a newly-created, empty,
repository-external `PYTHONPYCACHEPREFIX`. The runner copies `os.environ`,
passes the child-specific environment through `_run`, and deletes the prefix
when the mutation completes. It does not delete source-tree `__pycache__`,
sleep, alter mtimes, or use `-B`/`PYTHONDONTWRITEBYTECODE` as a corrective.

Mutation execution is now sequential. A successful `MutationOutcome` is
appended immediately. A failing mutation preserves the completed outcomes and
records the exact mutation identity, exit code, bounded output tail, and a
qualified error such as `detail_view_application_bypass: mutation unexpectedly
passed`. The artifact keeps `contract_version` at
`phase_02_d5_sensitivity.v1` and records
`pycache_strategy=per_mutation_unique_prefix`.

## RED and GREEN

RED commit `8d0fee3ab06747a442b6473fe65b5a10985e94dc` changed only
`test/test_phase_02_d5_sensitivity_runner.py`.

- `test_each_d5_mutation_uses_a_unique_empty_pycache_prefix` directly failed
  by `AssertionError` because the old runner provided no child environment.
- `test_d5_failure_evidence_preserves_completed_and_failed_mutation` directly
  failed by `AssertionError` because the tuple generator discarded the first
  completed mutation and the failed mutation identity.

GREEN commit `d1042f33181dafc7064ca4ff5aba0ffd7dfc2309` changed only
`scripts/refactoring/verify_phase_02_d5_report_read_queries_test_sensitivity.py`.
It provides the per-mutation unique-prefix and sequential-evidence corrective
without changing any of the five target names, target order, mutation anchors,
or detector IDs.

## Verification

- D5 runner contract: `5 passed`.
- Authoritative D5 boundary:
  `chatbot.test_phase_02_report_read_queries_use_case` plus
  `chatbot.test_report_api_contract`: `18 tests, OK`.
- Five consecutive full runner executions: baseline `0`, exact five mutations
  in order, `25/25` nonzero direct `AssertionError` outcomes, all five
  `completed_mutations`, no `failed_mutation`, and clean worktree/diff after
  each run.
- The historical pair ran list/detail and detail/list three times each:
  `12/12` direct `AssertionError` outcomes, twelve distinct launch-time empty
  pycache prefixes, and all prefixes removed after completion.
- D12-through-current Phase 2 application-boundary selection: `145 tests, OK`.
- `backend/manage.py check`, `ruff --select E9,F63,F7,F82 .`, and the D5
  runner `F401` check passed.

## Scope

Before this receipt, the Base-to-GREEN diff contained only the D5 runner and
its runner test. Production, application/view/repository/service, workflow,
OpenAPI, frontend, model/migration/dependency, and D13 changes are `0`.

## D13 Dependency

PR #417 remains OPEN, Draft, unmerged, and unmodified by this corrective. It
is blocked until this corrective is independently reviewed and merged to
`dev`, then #417 is synchronized, receives fresh successful CI and D13
artifact evidence, and receives its D13 Receipt Delta Independent Review.

## Deferred

`CROSS_RUNNER_PYC_ISOLATION_AUDIT` is deferred. This change intentionally uses
D5-local helpers rather than introducing a generic sensitivity framework.

## Current Status

```text
P1_D5_SENSITIVITY_PYC_COLLISION:
REMEDIATED_PENDING_INDEPENDENT_REVIEW

P1_D5_SENSITIVITY_FAILURE_EVIDENCE_LOSS:
REMEDIATED_PENDING_INDEPENDENT_REVIEW

Merge:
NOT_PERFORMED

Independent Review:
NOT_PERFORMED; SELF-APPROVAL PROHIBITED

NEXT_STEP:
PHASE_2_D5_SENSITIVITY_CORRECTIVE_INDEPENDENT_REVIEW
```
