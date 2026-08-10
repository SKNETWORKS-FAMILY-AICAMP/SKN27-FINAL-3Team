# Phase 0-B Baseline Gates Receipt

## Current authority

- Approved initial base: `198efeba3cabacc3a977cfcaf2f8d7e06fd47104`
- Current PR branch: `refactor/phase-00-baseline-gates` (PR #399)
- C verified-behavior commit: `1ed561ab1a9b2de9b0d043d0ec9e0b27890e598e`
- G verified-behavior commit: `2f41fff12a36d6108d9b928e796a9b2f3ffaad3d`
- P2 stale-OCR characterization commit: `7e0b003`
- P2 CI/evidence-contract commit: `868cefc`

The final P2 PR head and its newest `production-gate` run are authoritative
in PR metadata. This receipt is not amended by a docs-only commit merely to
self-reference that later run.

## P2 review adjudication

The P2 delta closes the independently identified non-production gaps:

1. C now characterizes replacement attachment B without reusing A's
   attachment-bound OCR confirmation.
2. C/G doubles are labelled at their actual service, pipeline, or
   provider-call boundary, and their internal contracts are blocking.
3. Compose success evidence no longer records a failure marker; cleanup
   success and cleanup failure are distinguishable receipts.
4. The Phase 0 authority documents contain one current status and A–G matrix.
5. C/G assertion sensitivity is reproducible without changing tracked tests.

## C/G characterization boundary

C/G characterization keeps HTTP, routing, planning, queue, worker,
persistence, authorization, confirmation, rendering, and download boundaries
real. Classification and retrieval dependencies are deterministic
service/pipeline-level doubles whose internal contracts are protected by a
separate blocking service-contract selector.

- C uses `classify_document_bytes` as a service-level double, `_call_gpt` at
  the OCR provider-call boundary, and `search_legal_rag` as a service-level
  double.
- G uses `run_unified_pgvector_pipeline` as a pipeline-level double and
  `search_legal_rag` as a service-level double.
- Neither flow patches orchestration, queue, worker, report persistence,
  authorization, or download code. Neither inserts `AgentResult`,
  `RetrievalEvent`, `AnalysisDisplayResult`, or `Report` directly.

The C stale-OCR characterization creates OCR-confirmed attachment A, uploads
and scans replacement B in the same session, and uses the normal message API
without an OCR confirmation. It asserts a real B job/work-item/message binding
and count of one each, no `law_ground_search` result or retrieval event for B,
no A confirmation field or A storage URI in B's response, and a fresh B
classification path. The existing foreign-owner test remains separate from
the stale classification confirmation test.

## Local P2 evidence

| Command | Exit code | Result |
|---|---:|---|
| `python backend/manage.py test chatbot.test_phase_00_ocr_law_flow --verbosity 2` | 0 | PASS: 5 tests, including replacement-A/B stale OCR characterization |
| `python -m pytest -q --timeout=30 test/test_attachment_document_classification_adapter.py test/test_legal_rag_service.py etl/fault_cases/src/agents/text_ml_case_search/tests/test_pgvector_unified_retriever.py` | 0 | PASS: 33 tests |
| `python -m pytest -q test/test_phase_00_sensitivity_runner.py` | 0 | PASS: 3 tests |
| `python scripts/refactoring/verify_phase_00_test_sensitivity.py` | 0 | PASS: C/G originals exit 0; temporary mutants exit 1 by `AssertionError`; working tree unchanged |
| `bash -n scripts/refactoring/run_phase_00_compose_gate.sh` | 0 | PASS |
| `git diff --check` | 0 | PASS before each P2 commit |

The sensitivity receipt uses contract version `phase_00_sensitivity.v1` and
contains only `contract_version`, `status`, `working_tree_unchanged`, and C/G
original/mutant exit and failure-kind fields. It records no private payload.

## Blocking CI contract

`production-gate.yml` contains these blocking P2 steps with no
`continue-on-error`:

1. `Phase 0 deterministic service-contract gate` immediately after
   `Contract and artifact gate`.
2. `Phase 0 core user-flow characterization gate`, including C and G.
3. `Phase 0 sensitivity negative controls`, with the
   `phase-00-sensitivity-evidence` artifact retained for 14 days.
4. `Phase 0 Compose integration gate`, with the
   `phase-00-compose-evidence` artifact retained for 14 days.

## Docker evidence

| Scope | Result | Evidence |
|---|---|---|
| D1 image build/import smoke | PASS | `production-gate` Run `30861528733`, Job `91844345278`, Docker build/import step success on the approved-base-equivalent tree |
| D2 Compose integration | PASS | historical C/G `production-gate` Run `31317365628`, compose Job `93255063276`; `phase-00-compose-evidence` artifact reported `status=pass` |

For the P2-corrected Compose receipt, a successful current-head artifact must
have `last-step.txt` equal to `compose-final`, `cleanup.txt` containing
`cleanup_success`, and no `failed-step.txt`. On a gate failure the failed step
is retained; on teardown failure `failed-step.txt` is `cleanup`.

## Known debt and unverified boundaries

- `PREEXISTING_BASELINE_DEBT`: full-collection cv2/pypdf collection debt and
  the Windows EICAR portability observation. Neither is introduced by PR #399
  or treated as a C/G pass.
- Paid or external providers and operating AWS are outside the deterministic
  Phase 0 gate.
- The next current-head CI run must verify the new Compose evidence semantics
  and upload the new sensitivity receipt. A CI or runtime failure is recorded
  as a baseline blocker; it is not repaired by this Phase 0 P2 scope.
