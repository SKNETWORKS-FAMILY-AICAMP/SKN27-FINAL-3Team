# Phase 0-B Baseline Gates Receipt

## Base and scope

- Base: `198efeba3cabacc3a977cfcaf2f8d7e06fd47104`
- Working branch: `refactor/phase-00-baseline-gates`
- Permitted changes: refactoring documentation, tests, Compose gate scripts, and `production-gate.yml` only.
- No production runtime module, Dockerfile, root Compose file, dependency metadata, migration, or API contract is changed.

## Local deterministic evidence

| Command | Result |
|---|---|
| `python backend/manage.py test chatbot.test_phase_00_core_user_flows chatbot.test_file_quarantine.FileQuarantinePipelineTests.test_multipart_registration_writes_only_to_quarantine chatbot.test_consultation_v2.ConsultationCaseApiTests.test_fact_confirmation_precedes_real_worker_queue --verbosity 1` | PASS: 5 tests |
| `python -m pytest test/test_phase_00_compose_probe.py -q` | PASS: 6 tests |
| `bash -n scripts/refactoring/run_phase_00_compose_gate.sh` | PASS |
| `git diff --check` | PASS |

The test runner initially rejected two incorrectly transcribed existing class names. Those selectors were corrected to the code-defined `ConsultationCaseApiTests`; this was not an application baseline failure.

## Docker evidence boundary

| Scope | Result | Evidence |
|---|---|---|
| D1 image build/import | PASS | Existing `production-gate` Run 30861528733, Job 91844345278; equivalent approved-base tree |
| D2 Compose integration | PENDING_CI | new blocking `compose-integration` job invokes `scripts/refactoring/run_phase_00_compose_gate.sh` and uploads `tmp/phase-00-compose-evidence/` |

Local D2 was not invoked because the local Docker daemon is unavailable. This is an environment limitation, not a passing result and not an application baseline failure.

## Unverified boundaries

- D2 service integration awaits the first GitHub Actions execution.
- External provider calls and operating AWS infrastructure are deliberately outside the provider-free Phase 0 gate.
- C's persisted OCR-to-law-search path and G's generated-report-to-confirmation path have only supporting existing tests; their missing production characterization coverage is recorded in the verification matrix and must not be represented as a pass.
